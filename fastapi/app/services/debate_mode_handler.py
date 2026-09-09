"""
DEBATE 전용 실행 핸들러 (SSE 스트림 / 동기 JSON).

★ 이 핸들러는 기본 모드(per-agent 1회 호출) 경로를 절대 재사용하지 않는다.
   debate_engine.run_debate 가 두 에이전트를 실제로 번갈아 호출하고,
   상대의 실제 발언 원문을 다음 호출의 입력으로 넘긴다.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import Any, Dict, Generator, List, Optional

from app.schemas.multi_chat_schema import AgentProfile, MultiChatRequest
from app.services import debate_engine as DE

logger = logging.getLogger(__name__)


def _speech_gap_seconds() -> float:
    """발언 사이 최소 간격(초). 토론은 LLM 호출 자체가 시차를 만들어 기본 0."""
    try:
        return max(0.0, float(os.getenv("DEBATE_MIN_SPEECH_GAP_SECONDS", "0")))
    except (TypeError, ValueError):
        return 0.0


def _identity(agent: Optional[AgentProfile]) -> Dict[str, Any]:
    if agent is None:
        return {}
    try:
        from app.services.multi_agent_service import _agent_identity_payload
        return _agent_identity_payload(agent)
    except Exception:  # pragma: no cover - 방어
        return {}


def _agent_index_map(agents: List[AgentProfile]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for idx, a in enumerate(agents or [], start=1):
        slot = getattr(a, "agentSlot", None)
        aid = getattr(a, "agentId", None) or getattr(a, "id", None)
        out[str(aid)] = int(slot) if isinstance(slot, int) and slot >= 1 else idx
    return out


def run_debate_mode_stream(
    request: MultiChatRequest,
    agents: List[AgentProfile],
    llm=None,
) -> Generator[Dict[str, Any], None, None]:
    """
    토론 SSE 제너레이터.

    turn_start → phase_progress(단계) → agent_start/agent_answer(발언마다) → all_complete
    발언은 생성되는 즉시 흘려보낸다(전체 토론이 끝날 때까지 기다리지 않는다).
    """
    topic = DE.extract_topic(request)
    strength = DE.resolve_strength(request)
    rounds = DE.rebuttal_rounds(strength)
    # 선택된 에이전트 전원이 참여한다(앞의 2명만 쓰면 나머지는 화면에 등장하지 못한다).
    participants = DE.select_debate_participants(agents)
    index_of = _agent_index_map(agents)
    identity_of = {str(DE._agent_id(a)): _identity(a) for a in participants}

    logger.info("[DEBATE] stream 시작 mode=debate debate_strength=%s rounds=%d selected=%d participants=%d",
                strength, rounds, len(agents or []), len(participants))

    yield {
        "event": "turn_start",
        "data": {
            "type": "turn_start",
            "mode": "debate",
            "learningMode": "debate",
            "phase": "DEBATE_SETUP",
            "visible": True,
            "message": "두 에이전트가 이 질문을 안건으로 토론을 시작합니다...",
            "topic": topic,
            "debateStrength": strength,
            "rebuttalRounds": rounds,
            "expectedAgentCount": len(participants),
            "responderAgentIds": [str(DE._agent_id(a)) for a in participants],
        },
    }

    # run_debate 는 콜백 기반(동기)이라, 스레드에서 돌리고 큐로 이벤트를 흘린다.
    q: "queue.Queue[Any]" = queue.Queue()
    _DONE = object()
    box: Dict[str, Any] = {}

    def on_speech(speech: DE.Speech) -> None:
        q.put(("speech", speech))

    def on_stage(key: str, title: str) -> None:
        q.put(("stage", (key, title)))

    def worker() -> None:
        try:
            box["transcript"] = DE.run_debate(request, agents, llm=llm,
                                              on_speech=on_speech, on_stage=on_stage)
        except DE.DebateAgentFailure as exc:
            # 한 명이 실패했다고 남은 한 명으로 일반 답변을 만들어 성공 처리하지 않는다.
            logger.error("[DEBATE] 참여자 발언 실패 agent=%s stage=%s issues=%s",
                         exc.agent_name, exc.stage, exc.issues)
            box["agent_failure"] = exc
        except Exception as exc:  # pragma: no cover - 방어
            logger.exception("[DEBATE] 실행 실패: %s", type(exc).__name__)
            box["error"] = exc
        finally:
            q.put(_DONE)

    th = threading.Thread(target=worker, name="debate-engine", daemon=True)
    th.start()

    order = 0
    gap = _speech_gap_seconds()
    answers: List[Dict[str, Any]] = []

    while True:
        item = q.get()
        if item is _DONE:
            break
        kind, payload = item
        if kind == "stage":
            key, title = payload
            yield {
                "event": "phase_progress",
                "data": {"type": "phase_progress", "mode": "debate", "phase": "DEBATE",
                         "stageKey": key, "stageTitle": title, "visible": True,
                         "debateStrength": strength, "rebuttalRounds": rounds},
            }
            continue

        speech: DE.Speech = payload
        order += 1
        is_consensus = speech.slot == DE.CONSENSUS_SLOT
        ident = {} if is_consensus else identity_of.get(str(speech.agent_id), {})
        agent_index = 0 if is_consensus else index_of.get(
            str(speech.agent_id), (DE.SLOT_LETTERS.index(speech.slot) + 1)
            if speech.slot in DE.SLOT_LETTERS else 1)

        yield {
            "event": "agent_start",
            "data": {"type": "agent_start", "agentId": speech.agent_id, "agentName": speech.agent_name,
                     "agentIndex": agent_index, "mode": "debate", "phase": "DEBATE",
                     "stageType": speech.stage_type, "stageTitle": speech.stage_title,
                     "speechType": speech.speech_type, "debateRound": speech.round_no,
                     "visible": True, **ident},
        }
        data = DE.speech_answer(speech, order, ident)
        data.update({"type": "agent_answer", "agentIndex": agent_index,
                     "phase": "DEBATE", "visible": True, "learningMode": "debate",
                     "consensus": is_consensus})
        yield {"event": "agent_answer", "data": data}
        answers.append({k: v for k, v in data.items() if k != "type"})
        if gap:
            time.sleep(gap)

    th.join(timeout=1.0)
    transcript: Optional[DE.DebateTranscript] = box.get("transcript")

    if transcript is None:
        failure = box.get("agent_failure")
        if failure is not None:
            yield {
                "event": "error",
                "data": {"type": "error", "mode": "debate", "learningMode": "debate",
                         "phase": "ERROR", "visible": True, "status": "error",
                         "code": "DEBATE_AGENT_FAILURE",
                         "failedAgentId": failure.agent_id, "failedAgentName": failure.agent_name,
                         "failedStage": failure.stage, "issues": failure.issues,
                         "expectedAgentCount": len(participants),
                         "message": (f"{failure.agent_name} 이(가) 토론 발언을 만들지 못했습니다. "
                                     "한 명만으로 토론을 진행하지 않습니다. 잠시 후 다시 시도해 주세요.")},
            }
            return
        yield {
            "event": "error",
            "data": {"type": "error", "mode": "debate", "phase": "ERROR", "visible": True,
                     "status": "error", "code": "DEBATE_FAILED",
                     "reason": type(box.get("error")).__name__ if box.get("error") else "UNKNOWN",
                     "message": "토론 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."},
        }
        return

    payload = DE.transcript_payload(transcript)
    logger.info("[DEBATE] stream 종료 speeches=%d validation_passed=%s issues=%s",
                len(transcript.speeches), payload["debateValidation"]["passed"],
                payload["debateValidation"]["issues"][:6])

    complete = {
        "type": "all_complete",
        "mode": "debate",
        "learningMode": "debate",
        "answers": answers,
        "messages": answers,
        "status": "COMPLETED",
        "phase": "ALL_COMPLETE",
        "visible": True,
        # 토론 참여자는 2명이다. 선택된 에이전트 N명을 채우는 compat 보강을 끈다.
        "suppressAgentFill": True,
    }
    complete.update(payload)
    yield {"event": "all_complete", "data": complete}


def run_debate_mode_sync(request: MultiChatRequest, agents: List[AgentProfile], llm=None) -> Dict[str, Any]:
    """비스트림 /api/ai/multi-chat 용. 스트림과 동일한 엔진/검증을 쓴다."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result: Dict[str, Any] = {}
    answers: List[Dict[str, Any]] = []
    for ev in run_debate_mode_stream(request, agents, llm=llm):
        if ev["event"] == "agent_answer":
            answers.append({k: v for k, v in ev["data"].items() if k != "type"})
        elif ev["event"] == "all_complete":
            result = dict(ev["data"])
        elif ev["event"] == "error":
            result = dict(ev["data"])

    if result.get("type") == "error":
        return {"success": False, "mode": "debate", "learningMode": "debate",
                "status": "FAILED", "answers": [], "messages": [],
                "code": result.get("code"), "message": result.get("message"),
                "failedAgentName": result.get("failedAgentName"),
                "failedStage": result.get("failedStage")}

    messages = [
        {"senderType": "AGENT", "agentId": a.get("agentId"), "agentName": a.get("agentName"),
         "role": "debater", "mode": "debate", "round": a.get("debateRound") or 0,
         "sequence": a.get("displayOrder"), "content": a.get("answer"),
         "speechType": a.get("speechType"), "stageType": a.get("stageType"),
         "createdAt": now, "groupId": request.groupId, "roomId": request.roomId}
        for a in answers
    ]
    result.pop("type", None)
    result.update({
        "success": True, "mode": "debate", "learningMode": "debate",
        "groupId": request.groupId, "roomId": request.roomId, "agentRoomId": request.agentRoomId,
        "status": "COMPLETED", "question": DE.extract_topic(request),
        "answers": answers, "messages": messages,
    })
    return result
