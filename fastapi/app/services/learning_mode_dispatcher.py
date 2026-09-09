"""
학습 모드 디스패처 — 모드별 전용 파이프라인 진입점.

책임 3가지만 한다.
  1) 세션 판정: 지금이 '새 세션 첫 입력'인가, 진행 중 세션의 답변인가.
  2) LearningIntentGuard: 새 세션 첫 입력이 학습 목적이 아니면 모델을 부르지 않고 거절.
  3) 모드 전용 핸들러로 위임. 실패해도 다른 모드로 폴백하지 않는다.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Generator, List

from app.schemas.multi_chat_schema import AgentProfile, MultiChatRequest
from app.services import learning_intent_guard as GUARD
from app.services import learning_session as LS

logger = logging.getLogger(__name__)

DEDICATED_MODES = ("debate", "socratic", "simulation")

_STATE_ECHO_ATTR = {
    "socratic": "socraticState",
    "simulation": "simulationState",
    "debate": "debateState",
}


def _current_message(request: MultiChatRequest) -> str:
    from app.services.memory_recall_service import strip_memory_block
    return strip_memory_block(getattr(request, "message", "") or "").strip()


def _handler(mode: str):
    if mode == "debate":
        from app.services.debate_mode_handler import run_debate_mode_stream
        return run_debate_mode_stream, "debate_engine"
    if mode == "socratic":
        from app.services.socratic_mode_handler import run_socratic_mode_stream
        return run_socratic_mode_stream, "socratic_session_engine"
    if mode == "simulation":
        from app.services.simulation_mode_handler import run_simulation_mode_stream
        return run_simulation_mode_stream, "simulation_session_engine"
    raise ValueError(f"전용 핸들러가 없는 모드: {mode}")


def guard_block_events(mode: str, decision: GUARD.IntentDecision,
                       agents: List[AgentProfile]) -> List[Dict[str, Any]]:
    """모델 호출 없이 내보내는 거절 이벤트(기존 SSE 계약 유지)."""
    payload = GUARD.block_payload(mode, decision)
    agent = agents[0] if agents else None
    agent_id = (getattr(agent, "agentId", None) or getattr(agent, "id", None)) if agent else f"{mode}-guard"
    agent_name = getattr(agent, "name", None) if agent else "학습 도우미"
    answer = {
        "type": "agent_answer", "mode": mode, "learningMode": mode, "phase": "GUARD",
        "visible": True, "status": "BLOCKED", "code": payload["code"],
        "agentId": agent_id, "agentName": agent_name or "학습 도우미", "agentIndex": 1,
        "answer": payload["message"], "content": payload["message"],
        "displayOrder": 1, "sequence": 1,
    }
    return [
        {"event": "turn_start", "data": {"type": "turn_start", "mode": mode, "learningMode": mode,
                                         "phase": "GUARD", "visible": True,
                                         "message": payload["message"], "code": payload["code"]}},
        {"event": "agent_answer", "data": answer},
        {"event": "all_complete", "data": {
            "type": "all_complete", "mode": mode, "learningMode": mode, "phase": "ALL_COMPLETE",
            "visible": True, "status": "BLOCKED", "code": payload["code"], "blocked": True,
            "reason": decision.reason, "message": payload["message"],
            "answers": [{k: v for k, v in answer.items() if k != "type"}],
            "messages": [{k: v for k, v in answer.items() if k != "type"}],
            "suppressAgentFill": True,
        }},
    ]


def evaluate_gate(request: MultiChatRequest, mode: str):
    """(is_new_session, session_id, decision) 판정. decision 은 가드를 탄 경우만 값이 있다."""
    message = _current_message(request)
    echo = getattr(request, _STATE_ECHO_ATTR.get(mode, ""), None)
    key, session, is_new = LS.resolve_active_session(request, mode, message, echo=echo)

    # 진행 중 세션이라도 '답변이 아닌 잡담'이 들어오면 그 세션을 이어가지 않는다.
    #  (짧은 답 '모르겠어'/'2번'/'왜?'는 여기서 제외 — 절대 재판정하지 않는다.)
    if session is not None and not LS.matches_answer_pattern(message):
        det = GUARD.classify_deterministic(message, mode)
        if det is not None and not det.is_learning:
            logger.info("[SESSION] 진행 중 세션에 비학습 입력 → 세션 종료 mode=%s session_id=%s reason=%s",
                        mode, session.session_id, det.reason)
            LS.end(key)
            session, is_new = None, True

    session_id = session.session_id if session is not None else None
    decision = None
    if GUARD.should_guard(mode, is_new):
        decision = GUARD.classify_learning_intent(message, mode)
    return is_new, session_id, decision


def run_learning_mode_stream(
    request: MultiChatRequest,
    agents: List[AgentProfile],
    mode: str,
    requested_mode: str = "",
) -> Generator[Dict[str, Any], None, None]:
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    is_new, session_id, decision = evaluate_gate(request, mode)
    handler, pipeline = _handler(mode)

    if decision is not None and not decision.is_learning:
        logger.info("[MODE-DISPATCH] request_id=%s requested_mode=%s resolved_mode=%s session_id=%s "
                    "pipeline=%s fallback_used=false blocked=%s reason=%s",
                    request_id, requested_mode or mode, mode, session_id or "-",
                    "learning_intent_guard", GUARD.NON_LEARNING_CODE, decision.reason)
        for ev in guard_block_events(mode, decision, agents):
            yield ev
        return

    logger.info("[MODE-DISPATCH] request_id=%s requested_mode=%s resolved_mode=%s session_id=%s "
                "pipeline=%s fallback_used=false new_session=%s agents=%d",
                request_id, requested_mode or mode, mode, session_id or "-", pipeline, is_new, len(agents or []))
    # 전용 핸들러가 실패하면 error 이벤트로 끝난다. 절대 basic 파이프라인으로 넘기지 않는다.
    yield from handler(request, agents)


def run_learning_mode_sync(request: MultiChatRequest, agents: List[AgentProfile], mode: str) -> Dict[str, Any]:
    """비스트림 경로. 스트림과 동일한 게이트/핸들러를 쓴다(계약 일치)."""
    result: Dict[str, Any] = {}
    answers: List[Dict[str, Any]] = []
    for ev in run_learning_mode_stream(request, agents, mode):
        if ev["event"] == "agent_answer":
            answers.append({k: v for k, v in ev["data"].items() if k != "type"})
        elif ev["event"] in ("all_complete", "error"):
            result = dict(ev["data"])
    result.pop("type", None)
    if result.get("code") in (GUARD.NON_LEARNING_CODE,):
        result.update({"success": True, "status": "BLOCKED"})
    elif result.get("status") == "error":
        result.update({"success": False, "status": "FAILED"})
    else:
        result.setdefault("success", True)
        result.setdefault("status", "COMPLETED")
    result.setdefault("answers", answers)
    result.setdefault("messages", answers)
    result.update({"mode": mode, "learningMode": mode,
                   "groupId": getattr(request, "groupId", None),
                   "roomId": getattr(request, "roomId", None),
                   "agentRoomId": getattr(request, "agentRoomId", None)})
    return result
