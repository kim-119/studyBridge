import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger("studybridge.multi_chat_stream_compat")

router = APIRouter(prefix="/api/ai", tags=["ai-stream-compat"])

_STREAM_SENTINEL = object()


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data or {}, ensure_ascii=False)}\n\n"


PERSONALITY_LABEL_MAP = {
    "친절": "friendly", "친절형": "friendly", "친근함": "friendly",
    "비판": "critical", "비판형": "critical", "솔직함": "critical",
    "논리": "logical", "논리형": "logical", "전문적": "logical",
    "창의": "creative", "창의형": "creative", "독특함": "creative",
    "간결": "concise", "간결형": "concise", "효율적": "concise",
    "츤데레": "coach", "코치": "coach", "냉소적": "coach",
}

KNOWLEDGE_LABEL_MAP = {
    "입문": "beginner", "초급": "beginner", "학사": "undergraduate", "학부": "undergraduate",
    "석사": "master", "박사": "phd", "전문가": "expert",
}


def _resolve_label(value: Any, mapping: Dict[str, str], default: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    lower = raw.lower()
    for label, key in mapping.items():
        if raw == label or lower == label.lower() or label.replace(" ", "") in raw.replace(" ", ""):
            return key
    return lower.replace(" ", "_")


def _normalize_stream_agent(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    raw = raw or {}
    personality_raw = raw.get("personality") or raw.get("persona") or raw.get("type") or raw.get("personalityLabel") or raw.get("personality_label")
    knowledge_raw = raw.get("knowledgeLevel") or raw.get("knowledge_level") or raw.get("level") or raw.get("knowledgeLevelLabel") or raw.get("knowledge_level_label")
    personality = _resolve_label(personality_raw, PERSONALITY_LABEL_MAP, os.getenv("AI_DEFAULT_PERSONALITY", "friendly"))
    knowledge = _resolve_label(knowledge_raw, KNOWLEDGE_LABEL_MAP, os.getenv("AI_DEFAULT_KNOWLEDGE_LEVEL", "undergraduate"))
    return {
        "agentId": raw.get("agentId") or raw.get("agent_id") or raw.get("id") or f"agent-{index + 1}",
        "agentName": raw.get("name") or raw.get("agentName") or raw.get("agent_name") or raw.get("displayName") or f"에이전트 {index + 1}",
        "personality": personality,
        "personalityLabel": raw.get("personalityLabel") or raw.get("personality_label") or os.getenv("AI_DEFAULT_PERSONALITY_LABEL", "친절형"),
        "knowledgeLevel": knowledge,
        "knowledgeLevelLabel": raw.get("knowledgeLevelLabel") or raw.get("knowledge_level_label") or os.getenv("AI_DEFAULT_KNOWLEDGE_LEVEL_LABEL", "학사"),
        "role": raw.get("role") or raw.get("agentRole") or raw.get("agent_role") or os.getenv("AI_DEFAULT_AGENT_ROLE", "학습 지원"),
    }


def _stream_agent_maps(payload: Dict[str, Any]):
    agents = [_normalize_stream_agent(a, idx) for idx, a in enumerate(payload.get("agents") or [])]
    by_id = {str(a.get("agentId")): a for a in agents if a.get("agentId") is not None}
    by_name = {str(a.get("agentName")): a for a in agents if a.get("agentName")}
    return agents, by_id, by_name


def _find_stream_agent(data: Dict[str, Any], by_id: Dict[str, Dict[str, Any]], by_name: Dict[str, Dict[str, Any]], index: int) -> Dict[str, Any]:
    agent = by_id.get(str(data.get("agentId"))) if data.get("agentId") is not None else None
    if not agent:
        agent = by_name.get(str(data.get("agentName") or data.get("name") or ""))
    if agent:
        return agent
    return _normalize_stream_agent(data, index - 1)


def _message_from_stream_answer(data: Dict[str, Any], agent: Dict[str, Any], mode: str, sequence: int, group_id: Any, room_id: Any) -> Dict[str, Any]:
    content = data.get("content") or data.get("answer") or data.get("feedback") or ""
    return {
        "senderType": "AGENT",
        "agentId": data.get("agentId") or agent.get("agentId"),
        "agentName": data.get("agentName") or agent.get("agentName"),
        "personality": data.get("personality") or agent.get("personality"),
        "personalityLabel": data.get("personalityLabel") or agent.get("personalityLabel"),
        "knowledgeLevel": data.get("knowledgeLevel") or agent.get("knowledgeLevel"),
        "knowledgeLevelLabel": data.get("knowledgeLevelLabel") or agent.get("knowledgeLevelLabel"),
        "role": data.get("role") or agent.get("role"),
        "mode": mode,
        "round": data.get("round") or 1,
        "sequence": data.get("sequence") or data.get("displayOrder") or sequence,
        "content": content,
        "createdAt": data.get("createdAt") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "groupId": group_id,
        "roomId": room_id,
    }


def _enrich_stream_event(data: Dict[str, Any], by_id: Dict[str, Dict[str, Any]], by_name: Dict[str, Dict[str, Any]], mode: str) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return data
    agent = _find_stream_agent(data, by_id, by_name, int(data.get("agentIndex") or data.get("sequence") or 1))
    data.setdefault("agentId", agent.get("agentId"))
    data.setdefault("agentName", agent.get("agentName"))
    data.setdefault("personality", agent.get("personality"))
    data.setdefault("personalityLabel", agent.get("personalityLabel"))
    data.setdefault("knowledgeLevel", agent.get("knowledgeLevel"))
    data.setdefault("knowledgeLevelLabel", agent.get("knowledgeLevelLabel"))
    data.setdefault("role", agent.get("role"))
    data.setdefault("mode", mode)
    return data


def _messages_from_complete_payload(data: Dict[str, Any], payload: Dict[str, Any], by_id: Dict[str, Dict[str, Any]], by_name: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    mode = str(payload.get("mode") or payload.get("learningMode") or data.get("mode") or "default").lower()
    group_id = payload.get("groupId") if payload.get("groupId") is not None else payload.get("group_id")
    room_id = payload.get("roomId") if payload.get("roomId") is not None else payload.get("room_id")
    messages = []
    answers = data.get("answers") or []
    for idx, answer in enumerate(answers, start=1):
        if not isinstance(answer, dict):
            continue
        agent = _find_stream_agent(answer, by_id, by_name, idx)
        messages.append(_message_from_stream_answer(answer, agent, mode, idx, group_id, room_id))
    return messages


# ── selectedAgents 보존 guard ────────────────────────────────────────────────
# 모드 무관 공통: selectedAgentCount=N이면 agent_answer가 N개 미만일 때 누락 에이전트의
# agent_answer SSE를 백엔드에서 실제로 보강 emit한다(프론트 fake 아님). simulation에서
# NPC 1명이 selected 교수 N명을 대체하던 버그(agent_answer=0) 방어. content는 mode/agent
# role 기반 fallback으로 채워 빈 content/누락이 없도록 한다.
# ── 필러는 '정상 AI 답변'이 아니라 '실행 누락 표시'다 ────────────────────────
# 과거엔 모드별로 그럴듯한 문장("{agentName} 관점에서 핵심을 정리하면…")을 합성했는데,
# 그 결과 (a) 실제 LLM 실행 실패가 정상 답변처럼 위장되고, (b) 의도적 partial route
# (정리 요청 WRAP / 기억 회상 / direct reply)에서 교수 2~3명이 똑같은 문장을 내뱉었다.
# 의도적 partial 은 handler 가 suppressAgentFill=True 로 알리고, 그 외의 누락은
# 여기서 degraded 카드로 '드러내야' 한다(조용한 성공 위장 금지).
_MISSING_ANSWER_TEXT = (
    "{agentName}의 답변을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요."
)


def _fallback_content(mode: str, agent_name: str) -> str:
    return _MISSING_ANSWER_TEXT.format(agentName=agent_name or "이 에이전트")


def _synth_agent_answer(agent: Dict[str, Any], index: int, mode: str) -> Dict[str, Any]:
    content = _fallback_content(mode, agent.get("agentName"))
    return {
        "type": "agent_answer",
        "agentId": agent.get("agentId"),            # _normalize_stream_agent가 항상 채움(null 금지)
        "agentIndex": index + 1,
        "agentName": agent.get("agentName"),
        "personality": agent.get("personality"),
        "personalityLabel": agent.get("personalityLabel"),
        "knowledgeLevel": agent.get("knowledgeLevel"),
        "knowledgeLevelLabel": agent.get("knowledgeLevelLabel"),
        "role": agent.get("role"),
        "mode": mode,
        "round": 1,
        "sequence": index + 1,
        "content": content,
        "answer": content,
        "synthesized": True,
        # 성공 위장 금지: 이 카드는 실패 표시다.
        "degraded": True,
        "status": "FAILED",
        "code": "AGENT_ANSWER_MISSING",
    }


def _reject_unknown_target(payload: Dict[str, Any]):
    """targetAgentId 가 있는데 agents 에서 해석되지 않으면 422 JSONResponse, 아니면 None.
    대상 없음/blank 는 기존 전체 협업 모드이므로 통과. 그 외 검증 오류는 기존 스트림 경로에 맡긴다."""
    target_id = str(payload.get("targetAgentId") or payload.get("target_agent_id") or "").strip()
    if not target_id:
        return None
    try:
        from app.schemas.multi_chat_schema import MultiChatRequest
        from app.services.multi_agent_service import UnknownTargetAgentError, _filter_agents, _get_agents
        req = MultiChatRequest(**payload)
        resolved = _filter_agents(_get_agents(req), req.targetAgentId)
        logger.info("[AGENT-RESOLVE] compat targetAgentId=%s → %s", target_id,
                    [(a.agentId, a.name, getattr(a, "agentSlot", None)) for a in resolved])
        return None
    except UnknownTargetAgentError as e:
        logger.warning("[AGENT-RESOLVE] compat targetAgentId=%s 거절: %s", target_id, e)
        return JSONResponse(status_code=422, content={"detail": {
            "code": "TARGET_AGENT_NOT_FOUND",
            "targetAgentId": e.target_id,
            "availableAgentIds": e.available,
            "message": "지정한 교수(targetAgentId)가 이 방의 에이전트 목록에 없습니다.",
        }})
    except Exception as exc:  # 스키마 오류 등은 기존 스트림 경로에서 처리
        logger.warning("[AGENT-RESOLVE] compat 사전 검증 건너뜀: %s", type(exc).__name__)
        return None


def _reject_unknown_mode(payload: Dict[str, Any]):
    """알 수 없는 mode/learningMode 는 basic 으로 조용히 폴백하지 않고 422 로 거절한다.
    (mode 자체가 없는 legacy 요청은 basic 으로 통과.)"""
    from app.services import mode_router
    try:
        resolved = mode_router.resolve_mode(payload.get("mode"), payload.get("learningMode") or payload.get("learning_mode"))
        logger.info("[MODE-ROUTER] compat mode=%r learningMode=%r → %s",
                    payload.get("mode"), payload.get("learningMode"), resolved)
        return None
    except mode_router.UnsupportedModeError as exc:
        logger.warning("[MODE-ROUTER] compat 거절: %s", exc)
        return JSONResponse(status_code=422, content={"detail": mode_router.error_detail(exc)})
    except Exception as exc:  # pragma: no cover - 라우터 장애가 스트림을 막지 않게
        logger.warning("[MODE-ROUTER] compat 검증 건너뜀: %s", type(exc).__name__)
        return None


@router.post("/multi-chat/stream")
async def multi_chat_stream_compat(request: Request):
    """
    운영 hotfix_main 학습메이트 SSE 라우터(v2).

    1) 스트림(200)을 열기 전에 JSON/스키마/message/mode/targetAgentId 를 검증해 422 로 거절한다.
    2) 요청 런타임(requestId·turnId·CancelToken·TurnBudget)을 만들고 절단 감시 태스크를 붙인다.
    3) 도메인 제너레이터(multi_agent_service.build_stream_generator) 이벤트를
       identity 정규화 → 타입드 계약/순서/짝/dedup 시퀀서 → SSE 직렬화로 내보낸다.
    구현: app/studymate/stream_runtime.py (non-stream /api/ai/multi-chat 도 같은 경로를 쓴다).
    """
    from app.studymate import stream_runtime as SR

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=422, content={"detail": {
            "code": "INVALID_JSON", "message": "요청 본문이 올바른 JSON 이 아닙니다."}})
    chat_request, rejected = SR.validate_before_open(payload)
    if rejected is not None:
        logger.warning("[SSE-VALIDATE] rejected before open code=%s",
                       (json.loads(rejected.body).get("detail") or {}).get("code"))
        return rejected
    request_id = (request.headers.get("x-request-id") or (payload.get("requestId") if isinstance(payload, dict) else None)
                  or f"req_{uuid.uuid4().hex[:12]}")
    rt = SR.new_runtime_for(chat_request, str(request_id)[:64])
    logger.info("[SSE-OPEN] request=%s turn=%s mode=%s agents=%d target=%s budget=%s",
                rt.request_id, rt.turn_id, SR.resolved_mode(chat_request), len(chat_request.agents or []),
                chat_request.targetAgentId, rt.budget.snapshot() if rt.budget else None)
    return StreamingResponse(
        SR.stream_turn(request, chat_request, rt),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-Id": rt.request_id,
        },
    )


@router.post("/predict-study-time")
async def predict_study_time_compat(request: Request):
    payload = await request.json()
    port = os.getenv("FASTAPI_PORT", "8000")
    url = f"http://127.0.0.1:{port}/api/ai/predict/study-time"

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload)

    try:
        return response.json()
    except Exception:
        return {"status": response.status_code, "body": response.text}
