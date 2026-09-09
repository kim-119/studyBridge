"""
소크라테스 전용 실행 핸들러 (SSE / 동기).

기본 모드(per-agent 1회 호출)를 재사용하지 않는다. 세션 상태를 읽어 '이번 사이클'만 생성한다.
실패해도 basic 으로 폴백하지 않는다(모드 전용 오류를 낸다).

★ 한 사이클 = 선택된 에이전트 '전원'이 기능적 역할을 나눠 한 번씩 발화한다.
   (개념 유도 → 다른 관점/반례 → 논리 검증). 뒤 순서 에이전트는 앞 발언을 실제로 읽는다.
   agents[0] 한 명만 쓰던 구조는 제거됐다.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Generator, List

from app.schemas.multi_chat_schema import AgentProfile, MultiChatRequest
from app.services import learning_session as LS
from app.services import socratic_multi_agent as MA
from app.services import socratic_session_engine as SE

logger = logging.getLogger(__name__)

MODE = "socratic"

_SUMMARY_STAGE_TYPE = "SUMMARY"
_SUMMARY_STAGE_TITLE = "정리"


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


def _agent_slot(agent: AgentProfile, fallback: int) -> int:
    slot = getattr(agent, "agentSlot", None)
    return int(slot) if isinstance(slot, int) and slot >= 1 else fallback


def _answer_event(sp: MA.AgentSpeech, agent: AgentProfile, session, order: int,
                  stage_type: str, stage_title: str) -> Dict[str, Any]:
    return {
        "type": "agent_answer", "mode": MODE, "learningMode": MODE, "phase": "SOCRATIC",
        "visible": True, "status": "SUCCESS",
        "agentId": sp.agent_id, "agentName": sp.agent_name,
        "agentIndex": _agent_slot(agent, order),
        "answer": sp.text, "content": sp.text,
        "displayOrder": order, "sequence": order, "round": session.turn_index + 1,
        "stageType": stage_type, "stageTitle": stage_title,
        "socraticRole": sp.role, "roleLabel": MA.ROLE_LABEL.get(sp.role, sp.role),
        "question": sp.question, "assessment": sp.assessment,
        "socraticState": session.state, "sessionId": session.session_id,
        **_identity(agent),
    }


def run_socratic_mode_stream(
    request: MultiChatRequest,
    agents: List[AgentProfile],
    llm=None,
) -> Generator[Dict[str, Any], None, None]:
    message = _current_message(request)
    echo = getattr(request, "socraticState", None)
    key, session, is_new = LS.resolve_active_session(request, MODE, message, echo=echo)
    intensity, hint_style = SE.resolve_config(request)
    roles = MA.assign_roles(agents)
    expected_count = len(roles)

    if is_new:
        session = LS.LearningSession(
            session_id=LS.new_session_id(MODE), mode=MODE, topic=message, state=SE.ASSESS,
            turn_index=0,
            data={"intensity": intensity, "hintStyle": hint_style, "transcript": [],
                  "expectedIdea": "", "answerKeywords": [], "questions": []},
        )
    session.data.setdefault("transcript", [])
    session.data.setdefault("questions", [])
    session.data["intensity"] = intensity
    session.data["hintStyle"] = hint_style

    logger.info("[SOCRATIC] request mode=socratic session_id=%s state=%s turn=%d new_session=%s "
                "intensity=%s hint_style=%s selected_agents=%d roles=%s",
                session.session_id, session.state, session.turn_index, is_new, intensity,
                hint_style, expected_count, [r for _, r in roles])

    yield {
        "event": "turn_start",
        "data": {"type": "turn_start", "mode": MODE, "learningMode": MODE,
                 "phase": "SOCRATIC", "visible": True,
                 "message": "질문을 준비하고 있습니다...",
                 "sessionId": session.session_id, "socraticState": session.state,
                 "turnIndex": session.turn_index,
                 "questionIntensity": intensity, "hintPolicy": hint_style,
                 "expectedAgentCount": expected_count,
                 "responderAgentIds": [str(MA._agent_id(a, f"socratic-{i}"))
                                       for i, (a, _) in enumerate(roles, start=1)]},
    }

    transcript = list(session.data.get("transcript") or [])
    # 마무리 조건은 기존 계약을 유지한다: VERIFY 상태 / 예약된 정리 / 최대 턴 도달.
    wrap_up = (not is_new) and (
        session.state == SE.VERIFY
        or bool(session.data.get("pendingSummary"))
        or session.turn_index + 1 >= SE.MAX_TURNS
    )

    try:
        if is_new:
            idea, keywords = MA.derive_expected_idea(session.topic, llm=llm)
            session.data["expectedIdea"] = idea
            session.data["answerKeywords"] = keywords
            transcript = [{"role": "user", "text": message}]
        else:
            transcript.append({"role": "user", "text": message})

        if wrap_up:
            speeches = []
        else:
            speeches = MA.run_cycle(
                topic=session.topic, user_message=message, roles=roles,
                transcript=transcript, intensity=intensity, hint_style=hint_style,
                is_first_cycle=is_new, expected_idea=session.data.get("expectedIdea", ""),
                keywords=session.data.get("answerKeywords") or None,
                used_questions=list(session.data.get("questions") or []), llm=llm)
    except Exception as exc:
        logger.exception("[SOCRATIC] 사이클 생성 실패: %s", type(exc).__name__)
        yield {
            "event": "error",
            "data": {"type": "error", "mode": MODE, "phase": "ERROR", "visible": True,
                     "status": "error", "code": "SOCRATIC_TURN_FAILED",
                     "reason": type(exc).__name__,
                     "message": "소크라테스 진행 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."},
        }
        return

    answers: List[Dict[str, Any]] = []
    steps: List[Dict[str, Any]] = []
    issues: List[str] = []

    if wrap_up:
        session.data["pendingSummary"] = False
        # 마지막 사이클: 정리는 마지막 순서 에이전트가 맡는다(새 사회자를 만들지 않는다).
        agent, role = roles[-1]
        try:
            turn, s_issues = SE.generate_summary(session.topic, transcript,
                                                 session.data.get("expectedIdea", ""), llm=llm)
        except Exception as exc:
            logger.exception("[SOCRATIC] 정리 생성 실패: %s", type(exc).__name__)
            turn, s_issues = None, ["summary_failed"]
        if turn is None:
            yield {
                "event": "error",
                "data": {"type": "error", "mode": MODE, "phase": "ERROR", "visible": True,
                         "status": "error", "code": "SOCRATIC_TURN_FAILED",
                         "reason": "summary_failed",
                         "message": "소크라테스 정리 생성에 실패했습니다. 잠시 후 다시 시도해 주세요."},
            }
            return
        issues = s_issues
        sp = MA.AgentSpeech(role=role, agent_id=MA._agent_id(agent, "socratic-1"),
                            agent_name=MA._agent_name(agent, len(roles)),
                            agent_index=len(roles), text=turn.text, question=turn.question)
        speeches = [sp]
        session.state = SE.SUMMARY
        transcript.append({"role": "mate", "name": sp.agent_name, "text": sp.text})
        yield {"event": "agent_start",
               "data": {"type": "agent_start", "mode": MODE, "phase": "SOCRATIC", "visible": True,
                        "agentId": sp.agent_id, "agentName": sp.agent_name,
                        "agentIndex": _agent_slot(agent, 1), "stageType": _SUMMARY_STAGE_TYPE,
                        "socraticState": SE.SUMMARY, **_identity(agent)}}
        data = _answer_event(sp, agent, session, 1, _SUMMARY_STAGE_TYPE, _SUMMARY_STAGE_TITLE)
        yield {"event": "agent_answer", "data": data}
        answers.append({k: v for k, v in data.items() if k != "type"})
        steps.append({"stageType": _SUMMARY_STAGE_TYPE, "stageTitle": _SUMMARY_STAGE_TITLE,
                      "role": MA.ROLE_LABEL.get(role, role), "agentIndex": _agent_slot(agent, 1),
                      "agentId": sp.agent_id, "agentName": sp.agent_name,
                      "question": sp.question, "content": sp.text,
                      "directAnswerSuppressed": False})
    else:
        issues = MA.validate_cycle(speeches, expected_count)
        session.state = SE.ASK if is_new else SE.DEEPEN
        # 사이클 첫 발언자의 평가가 correct 면 다음 턴에 정리로 넘어간다(기존 상태 흐름 유지).
        lead_assessment = speeches[0].assessment if speeches else ""
        if lead_assessment == SE.CORRECT:
            session.data["pendingSummary"] = True
        elif lead_assessment in (SE.WRONG, SE.UNKNOWN):
            session.data["hintLevel"] = int(session.data.get("hintLevel") or 0) + 1
        for order, sp in enumerate(speeches, start=1):
            agent = roles[order - 1][0]
            stage_type = MA.ROLE_STAGE_TYPE.get(sp.role, "DIAGNOSIS")
            stage_title = MA.ROLE_STAGE_TITLE.get(sp.role, "질문")
            yield {"event": "agent_start",
                   "data": {"type": "agent_start", "mode": MODE, "phase": "SOCRATIC", "visible": True,
                            "agentId": sp.agent_id, "agentName": sp.agent_name,
                            "agentIndex": _agent_slot(agent, order), "stageType": stage_type,
                            "socraticRole": sp.role, "socraticState": session.state,
                            **_identity(agent)}}
            data = _answer_event(sp, agent, session, order, stage_type, stage_title)
            yield {"event": "agent_answer", "data": data}
            answers.append({k: v for k, v in data.items() if k != "type"})
            steps.append({"stageType": stage_type, "stageTitle": stage_title,
                          "role": MA.ROLE_LABEL.get(sp.role, sp.role),
                          "agentIndex": _agent_slot(agent, order),
                          "agentId": sp.agent_id, "agentName": sp.agent_name,
                          "question": sp.question, "content": sp.text,
                          "directAnswerSuppressed": True})
            transcript.append({"role": "mate", "name": sp.agent_name, "text": sp.text})

    session.data["transcript"] = transcript[-16:]
    session.data["questions"] = ([q for q in (session.data.get("questions") or [])]
                                 + [sp.question for sp in speeches if sp.question])[-8:]
    session.turn_index += 1
    LS.save(key, session)

    complete = {
        "type": "all_complete", "mode": MODE, "learningMode": MODE,
        "status": "COMPLETED", "phase": "ALL_COMPLETE", "visible": True,
        "answers": answers, "messages": answers,
        # 선택된 에이전트가 이미 전원 발화했으므로 compat 필러가 끼어들 필요가 없다.
        "suppressAgentFill": True,
        "socraticSteps": steps,
        "socraticState": session.to_payload(),
        "sessionId": session.session_id,
        "turnIndex": session.turn_index,
        "questionIntensity": intensity,
        "hintPolicy": hint_style,
        "expectedAgentCount": expected_count,
        "socraticRoles": [{"agentId": MA._agent_id(a, f"socratic-{i}"),
                           "agentName": MA._agent_name(a, i),
                           "role": r, "roleLabel": MA.ROLE_LABEL.get(r, r)}
                          for i, (a, r) in enumerate(roles, start=1)],
        "socraticValidation": {"passed": not issues, "issues": issues},
    }
    logger.info("[SOCRATIC] done session_id=%s state=%s turn=%d speakers=%s issues=%s",
                session.session_id, session.state, session.turn_index,
                [sp.agent_name for sp in speeches], issues[:4])
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
