"""
상황극(simulation) 전용 실행 핸들러 (SSE / 동기).

세션 1턴: 진행 Agent 가 상황 + 선택지를 만든다.
2턴 이후: 심화 검증 → 피드백 코치 → 진행(결과 + 다음 장면 + 선택지) 3역할이 모두 발화한다.
장면은 세션에 고정되어 매 턴 새로 만들지 않는다. 실패해도 일반 Q&A 로 폴백하지 않는다.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Generator, List, Optional

from app.schemas.multi_chat_schema import AgentProfile, MultiChatRequest
from app.services import learning_session as LS
from app.services import simulation_session_engine as SE

logger = logging.getLogger(__name__)

MODE = "simulation"


def _roles(agents: List[AgentProfile]) -> Dict[str, AgentProfile]:
    """방의 에이전트 프로필을 보존한 채 3역할을 매핑한다(부족하면 재사용)."""
    live = [a for a in (agents or []) if a is not None]
    if not live:
        live = [AgentProfile(agentId=f"sim-{i}", id=f"sim-{i}", name=n)
                for i, n in enumerate(("진행자", "검증자", "코치"), start=1)]
    return {
        SE.HOST: live[0],
        SE.CHALLENGER: live[1 % len(live)],
        SE.COACH: live[2 % len(live)],
    }


def _identity(agent: AgentProfile) -> Dict[str, Any]:
    try:
        from app.services.multi_agent_service import _agent_identity_payload
        return _agent_identity_payload(agent)
    except Exception:  # pragma: no cover
        return {}


def _current_message(request: MultiChatRequest) -> str:
    from app.services.memory_recall_service import strip_memory_block
    return strip_memory_block(getattr(request, "message", "") or "").strip()


def _selected_choice_text(request: MultiChatRequest, message: str,
                          session_choices=None) -> str:
    """선택지를 고른 경우 그 라벨을 사용자의 답으로 쓴다(없으면 자유 입력).

    프론트가 selectedChoice 를 보내지 않고 사용자가 '2번'처럼만 답해도
    세션에 저장된 선택지 문구로 되돌려 준다(그래야 검증/피드백이 실제 선택을 본다).
    """
    choice = getattr(request, "selectedChoice", None)
    if isinstance(choice, dict):
        label = choice.get("label") or choice.get("text") or choice.get("action")
        if label:
            return f"{label} ({message})" if message else str(label)
    if session_choices:
        label = SE.resolve_choice_reference(message, session_choices)
        if label:
            return f"{label} ({message})"
    return message


def _agent_id(agent: AgentProfile, fallback: str) -> Any:
    return getattr(agent, "agentId", None) or getattr(agent, "id", None) or fallback


def run_simulation_mode_stream(
    request: MultiChatRequest,
    agents: List[AgentProfile],
    llm=None,
) -> Generator[Dict[str, Any], None, None]:
    message = _current_message(request)
    echo = getattr(request, "simulationState", None)
    key, session, is_new = LS.resolve_active_session(request, MODE, message, echo=echo)
    stype, difficulty, choice_count = SE.resolve_config(request)
    choice_count = SE.effective_choice_count(request, choice_count)
    role_map = _roles(agents)
    _prev_choices = (session.data.get("choices") if session is not None else None) or []
    user_answer = _selected_choice_text(request, message, _prev_choices)

    if is_new:
        session = LS.LearningSession(
            session_id=LS.new_session_id(MODE), mode=MODE, topic=message,
            state=SE.SCENE_SETUP, turn_index=0,
            data={"scenarioType": stype, "difficulty": difficulty, "choiceCount": choice_count,
                  "roles": {r: getattr(a, "name", "") for r, a in role_map.items()}},
        )
    else:
        # 설정은 세션 시작 시점 값을 유지한다(턴마다 장면 규칙이 바뀌지 않게).
        stype = session.data.get("scenarioType", stype)
        difficulty = session.data.get("difficulty", difficulty)
        choice_count = int(session.data.get("choiceCount", choice_count))

    logger.info("[SIMULATION] request mode=simulation session_id=%s state=%s turn=%d new_session=%s "
                "type=%s difficulty=%s choices=%d", session.session_id, session.state,
                session.turn_index, is_new, stype, difficulty, choice_count)

    yield {
        "event": "turn_start",
        "data": {"type": "turn_start", "mode": MODE, "learningMode": MODE, "phase": "SIMULATION",
                 "visible": True, "message": "상황을 준비하고 있습니다...",
                 "sessionId": session.session_id, "turnIndex": session.turn_index,
                 "scenarioType": stype, "difficulty": difficulty, "choiceCount": choice_count,
                 "responderAgentIds": [str(_agent_id(a, r)) for r, a in role_map.items()]},
    }

    speeches: List[SE.SimSpeech] = []
    try:
        if is_new:
            # 1턴부터 설명문이 아니라 '대사'다. 주 질문자 → 심화 검증자 → 답변 코치 세 인물이
            # 모두 실제로 모델 호출을 받고, 뒤 인물은 앞 인물의 대사를 입력으로 읽는다.
            host = SE.generate_scene_setup(session.topic, stype, difficulty, choice_count,
                                           getattr(role_map[SE.HOST], "name", "진행자"), llm=llm)
            speeches.append(host)
            session.data.update({
                "scenario": host.structured.get("sceneBrief", ""),
                "userRole": host.structured.get("userRole", ""),
                "goal": host.structured.get("goal", ""),
                "prompt": host.structured.get("line", ""),
                "choices": host.choices,
            })
            challenger = SE.generate_opening_challenge(
                session.data, host.structured.get("line", ""), stype, difficulty,
                getattr(role_map[SE.CHALLENGER], "name", "검증자"), llm=llm)
            speeches.append(challenger)
            coach = SE.generate_answer_brief(
                session.data, host.structured.get("line", ""),
                challenger.structured.get("line", ""),
                getattr(role_map[SE.COACH], "name", "코치"), llm=llm)
            speeches.append(coach)
        else:
            data = session.data
            host = SE.generate_follow_up(data, user_answer, stype, difficulty, choice_count,
                                         getattr(role_map[SE.HOST], "name", "진행자"), llm=llm)
            speeches.append(host)
            speeches.append(SE.generate_challenge(
                data, user_answer, stype, difficulty,
                getattr(role_map[SE.CHALLENGER], "name", "검증자"), llm=llm,
                host_line=host.structured.get("line", "")))
            speeches.append(SE.generate_feedback(
                data, user_answer, difficulty,
                getattr(role_map[SE.COACH], "name", "코치"), llm=llm))
            data["prompt"] = host.structured.get("line", "")
            data["choices"] = host.choices
    except SE.SimulationStageError as exc:
        logger.error("[SIMULATION] 역할 단계 실패 role=%s issues=%s", exc.role, exc.issues)
        yield {
            "event": "error",
            "data": {"type": "error", "mode": MODE, "phase": "ERROR", "visible": True,
                     "status": "error", "code": "SIMULATION_STAGE_FAILED",
                     "failedRole": exc.role, "issues": exc.issues,
                     "message": "상황극 진행 중 한 역할의 응답을 만들지 못했습니다. 잠시 후 다시 시도해 주세요."},
        }
        return
    except Exception as exc:  # pragma: no cover - 방어
        logger.exception("[SIMULATION] 실행 실패: %s", type(exc).__name__)
        yield {
            "event": "error",
            "data": {"type": "error", "mode": MODE, "phase": "ERROR", "visible": True,
                     "status": "error", "code": "SIMULATION_FAILED", "reason": type(exc).__name__,
                     "message": "상황극 진행 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."},
        }
        return

    issues = SE.validate_turn(speeches, choice_count, is_new, user_answer)
    session.state = next((sp.stage_type for sp in speeches if sp.role == SE.HOST),
                         speeches[-1].stage_type)
    session.turn_index += 1
    LS.save(key, session)

    answers: List[Dict[str, Any]] = []
    stages: List[Dict[str, Any]] = []
    for order, sp in enumerate(speeches, start=1):
        agent = role_map[sp.role]
        aid = _agent_id(agent, f"sim-{sp.role.lower()}")
        ident = _identity(agent)
        yield {
            "event": "agent_start",
            "data": {"type": "agent_start", "mode": MODE, "phase": "SIMULATION", "visible": True,
                     "agentId": aid, "agentName": getattr(agent, "name", sp.agent_name),
                     "agentIndex": order, "stageType": sp.stage_type,
                     "simulationRole": sp.role, **ident},
        }
        data = {
            "type": "agent_answer", "mode": MODE, "learningMode": MODE, "phase": "SIMULATION",
            "visible": True, "status": "SUCCESS",
            "agentId": aid, "agentName": getattr(agent, "name", sp.agent_name), "agentIndex": order,
            "answer": sp.text, "content": sp.text,
            "displayOrder": order, "sequence": order, "round": session.turn_index,
            "stageType": sp.stage_type, "stageTitle": sp.stage_title,
            "simulationRole": sp.role, "roleLabel": SE.ROLE_LABEL[sp.role],
            "choices": sp.choices, "sessionId": session.session_id,
            **ident,
        }
        yield {"event": "agent_answer", "data": data}
        answers.append({k: v for k, v in data.items() if k != "type"})
        stages.append({
            "stageType": sp.stage_type, "stageTitle": sp.stage_title,
            "role": SE.ROLE_LABEL[sp.role], "agentIndex": order,
            "agentName": getattr(agent, "name", sp.agent_name),
            "content": sp.text, "choices": sp.choices,
            "userRole": session.data.get("userRole"),
        })

    complete = {
        "type": "all_complete", "mode": MODE, "learningMode": MODE,
        "status": "COMPLETED", "phase": "ALL_COMPLETE", "visible": True,
        "answers": answers, "messages": answers,
        "suppressAgentFill": True,
        "simulationStages": stages,
        "simulationState": session.to_payload(),
        "sessionId": session.session_id, "turnIndex": session.turn_index,
        "scenarioType": stype, "difficulty": difficulty, "choiceCount": choice_count,
        "choices": SE.scene_choices(speeches),
        "simulationValidation": {"passed": not issues, "issues": issues},
    }
    logger.info("[SIMULATION] done session_id=%s state=%s turn=%d roles=%s issues=%s",
                session.session_id, session.state, session.turn_index,
                [sp.role for sp in speeches], issues[:4])
    yield {"event": "all_complete", "data": complete}


def run_simulation_mode_sync(request: MultiChatRequest, agents: List[AgentProfile], llm=None) -> Dict[str, Any]:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result: Dict[str, Any] = {}
    for ev in run_simulation_mode_stream(request, agents, llm=llm):
        if ev["event"] in ("all_complete", "error"):
            result = dict(ev["data"])
    if result.get("type") == "error":
        return {"success": False, "mode": MODE, "learningMode": MODE, "status": "FAILED",
                "answers": [], "messages": [], "code": result.get("code"),
                "failedRole": result.get("failedRole"), "message": result.get("message")}
    result.pop("type", None)
    for m in result.get("messages", []):
        m.setdefault("senderType", "AGENT")
        m.setdefault("createdAt", now)
    result.update({"success": True, "mode": MODE, "learningMode": MODE,
                   "groupId": getattr(request, "groupId", None),
                   "roomId": getattr(request, "roomId", None),
                   "agentRoomId": getattr(request, "agentRoomId", None),
                   "status": "COMPLETED", "question": _current_message(request)})
    return result
