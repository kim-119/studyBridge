"""
소크라테스 전용 실행 핸들러 (SSE / 동기).

기본 모드(per-agent 1회 호출)를 재사용하지 않는다. 세션 상태를 읽어
ASSESS/ASK → EVALUATE → HINT|DEEPEN → VERIFY → SUMMARY 중 '이번 턴'만 생성한다.
실패해도 basic 으로 폴백하지 않는다(모드 전용 오류를 낸다).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Generator, List, Optional

from app.schemas.multi_chat_schema import AgentProfile, MultiChatRequest
from app.services import learning_session as LS
from app.services import socratic_session_engine as SE

logger = logging.getLogger(__name__)

MODE = "socratic"

# 내부 상태 → 기존 프론트 socraticSteps stageType (새 UI 계약을 만들지 않는다).
_STAGE_TYPE = {
    SE.ASK: "DIAGNOSIS",
    SE.HINT: "HINT",
    SE.DEEPEN: "APPLICATION",
    SE.VERIFY: "SELF_EXPLANATION",
    SE.SUMMARY: "SUMMARY",
}
_STAGE_TITLE = {
    "DIAGNOSIS": "생각 확인 질문",
    "HINT": "힌트와 다시 생각하기",
    "APPLICATION": "적용/심화 질문",
    "SELF_EXPLANATION": "네 말로 정리하기",
    "SUMMARY": "정리",
}


def _tutor(agents: List[AgentProfile]) -> AgentProfile:
    if agents:
        return agents[0]
    return AgentProfile(agentId="socratic-tutor", id="socratic-tutor", name="러닝메이트")


def _identity(agent: AgentProfile) -> Dict[str, Any]:
    try:
        from app.services.multi_agent_service import _agent_identity_payload
        return _agent_identity_payload(agent)
    except Exception:  # pragma: no cover
        return {}


def _current_message(request: MultiChatRequest) -> str:
    """주입된 [이전 대화 기억] 블록을 제외한 '현재 질문 원문'만 쓴다."""
    from app.services.memory_recall_service import strip_memory_block
    return strip_memory_block(getattr(request, "message", "") or "").strip()


def run_socratic_mode_stream(
    request: MultiChatRequest,
    agents: List[AgentProfile],
    llm=None,
) -> Generator[Dict[str, Any], None, None]:
    message = _current_message(request)
    echo = getattr(request, "socraticState", None)
    key, session, is_new = LS.resolve_active_session(request, MODE, message, echo=echo)
    intensity, hint_style = SE.resolve_config(request)
    tutor = _tutor(agents)
    identity = _identity(tutor)
    agent_id = getattr(tutor, "agentId", None) or getattr(tutor, "id", None) or "socratic-tutor"
    agent_name = getattr(tutor, "name", None) or "러닝메이트"

    if is_new:
        session = LS.LearningSession(
            session_id=LS.new_session_id(MODE), mode=MODE, topic=message, state=SE.ASSESS,
            turn_index=0,
            data={"intensity": intensity, "hintStyle": hint_style, "hintLevel": 0,
                  "consecutiveFail": 0, "transcript": [], "expectedIdea": "", "pendingSummary": False},
        )
    session.data.setdefault("transcript", [])
    session.data["intensity"] = intensity
    session.data["hintStyle"] = hint_style

    logger.info("[SOCRATIC] request mode=socratic session_id=%s state=%s turn=%d new_session=%s "
                "intensity=%s hint_style=%s", session.session_id, session.state, session.turn_index,
                is_new, intensity, hint_style)

    yield {
        "event": "turn_start",
        "data": {"type": "turn_start", "mode": MODE, "learningMode": MODE,
                 "phase": "SOCRATIC", "visible": True,
                 "message": "질문을 준비하고 있습니다...",
                 "sessionId": session.session_id, "socraticState": session.state,
                 "turnIndex": session.turn_index,
                 "questionIntensity": intensity, "hintPolicy": hint_style,
                 "responderAgentIds": [str(agent_id)]},
    }

    try:
        if is_new:
            turn, issues = SE.generate_first_turn(session.topic, intensity, hint_style, agent_name, llm=llm)
            if turn is None:
                raise RuntimeError("first_turn_generation_failed")
            session.data["expectedIdea"] = turn.structured.get("expectedIdea", "")
            session.data["answerKeywords"] = turn.structured.get("answerKeywords", [])
            session.data["transcript"] = [{"role": "user", "text": message},
                                          {"role": "mate", "text": turn.text}]
            session.data["questions"] = [turn.question] if turn.question else []
        else:
            data = session.data
            transcript = list(data.get("transcript") or [])
            transcript.append({"role": "user", "text": message})
            wrap_up = bool(data.get("pendingSummary")) or session.turn_index + 1 >= SE.MAX_TURNS \
                or session.state == SE.VERIFY
            if wrap_up:
                turn, issues = SE.generate_summary(session.topic, transcript,
                                                   data.get("expectedIdea", ""), llm=llm)
            else:
                turn, issues = SE.generate_followup(
                    session.topic, message, transcript, intensity, hint_style,
                    int(data.get("hintLevel") or 0), int(data.get("consecutiveFail") or 0),
                    data.get("expectedIdea", ""), llm=llm,
                    answer_keywords=data.get("answerKeywords"),
                    previous_questions=data.get("questions") or [])
            if turn is None:
                raise RuntimeError("followup_generation_failed")

            if turn.assessment in (SE.WRONG, SE.UNKNOWN):
                data["consecutiveFail"] = int(data.get("consecutiveFail") or 0) + 1
                data["hintLevel"] = int(data.get("hintLevel") or 0) + 1
            elif turn.assessment in (SE.CORRECT, SE.PARTIAL):
                data["consecutiveFail"] = 0
                if turn.state == SE.DEEPEN and session.state == SE.DEEPEN:
                    data["pendingSummary"] = True
            transcript.append({"role": "mate", "text": turn.text})
            data["transcript"] = transcript[-12:]
            if turn.question:
                data["questions"] = ((data.get("questions") or []) + [turn.question])[-4:]
    except Exception as exc:
        logger.exception("[SOCRATIC] 턴 생성 실패: %s", type(exc).__name__)
        yield {
            "event": "error",
            "data": {"type": "error", "mode": MODE, "phase": "ERROR", "visible": True,
                     "status": "error", "code": "SOCRATIC_TURN_FAILED",
                     "reason": type(exc).__name__,
                     "message": "소크라테스 진행 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."},
        }
        return

    session.state = turn.state
    session.turn_index += 1
    LS.save(key, session)

    stage_type = _STAGE_TYPE.get(turn.state, "DIAGNOSIS")
    step = {
        "stageType": stage_type,
        "stageTitle": _STAGE_TITLE.get(stage_type, "질문"),
        "role": "질문자",
        "agentIndex": 1,
        "agentId": agent_id,
        "agentName": agent_name,
        "question": turn.question,
        "hint": turn.hint,
        "content": turn.text,
        "directAnswerSuppressed": turn.state != SE.SUMMARY,
    }

    yield {
        "event": "agent_start",
        "data": {"type": "agent_start", "mode": MODE, "phase": "SOCRATIC", "visible": True,
                 "agentId": agent_id, "agentName": agent_name, "agentIndex": 1,
                 "stageType": stage_type, "socraticState": turn.state, **identity},
    }
    answer = {
        "type": "agent_answer", "mode": MODE, "learningMode": MODE, "phase": "SOCRATIC",
        "visible": True, "status": "SUCCESS",
        "agentId": agent_id, "agentName": agent_name, "agentIndex": 1,
        "answer": turn.text, "content": turn.text,
        "displayOrder": 1, "sequence": 1, "round": session.turn_index,
        "stageType": stage_type, "stageTitle": step["stageTitle"],
        "socraticState": turn.state, "assessment": turn.assessment,
        "hintLevel": turn.hint_level, "sessionId": session.session_id,
        **identity,
    }
    yield {"event": "agent_answer", "data": answer}

    complete = {
        "type": "all_complete", "mode": MODE, "learningMode": MODE,
        "status": "COMPLETED", "phase": "ALL_COMPLETE", "visible": True,
        "answers": [{k: v for k, v in answer.items() if k != "type"}],
        "messages": [{k: v for k, v in answer.items() if k != "type"}],
        "suppressAgentFill": True,             # 한 턴에 한 명만 말한다(질문 1개 계약)
        "socraticSteps": [step],
        "socraticState": session.to_payload(),
        "sessionId": session.session_id,
        "turnIndex": session.turn_index,
        "questionIntensity": intensity,
        "hintPolicy": hint_style,
        "socraticValidation": {"passed": not issues, "issues": issues},
    }
    logger.info("[SOCRATIC] done session_id=%s state=%s turn=%d assessment=%s issues=%s",
                session.session_id, session.state, session.turn_index, turn.assessment, issues[:4])
    yield {"event": "all_complete", "data": complete}


def run_socratic_mode_sync(request: MultiChatRequest, agents: List[AgentProfile], llm=None) -> Dict[str, Any]:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result: Dict[str, Any] = {}
    for ev in run_socratic_mode_stream(request, agents, llm=llm):
        if ev["event"] in ("all_complete", "error"):
            result = dict(ev["data"])
    if result.get("type") == "error":
        return {"success": False, "mode": MODE, "learningMode": MODE, "status": "FAILED",
                "answers": [], "messages": [], "code": result.get("code"),
                "message": result.get("message")}
    result.pop("type", None)
    for m in result.get("messages", []):
        m.setdefault("senderType", "AGENT")
        m.setdefault("createdAt", now)
        m.setdefault("groupId", getattr(request, "groupId", None))
        m.setdefault("roomId", getattr(request, "roomId", None))
    result.update({"success": True, "mode": MODE, "learningMode": MODE,
                   "groupId": getattr(request, "groupId", None),
                   "roomId": getattr(request, "roomId", None),
                   "agentRoomId": getattr(request, "agentRoomId", None),
                   "status": "COMPLETED", "question": _current_message(request)})
    return result
