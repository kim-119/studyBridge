import asyncio
import json
import os
import time
import uuid
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

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


@router.post("/multi-chat/stream")
async def multi_chat_stream_compat(request: Request):
    """
    운영 hotfix_main 전용 호환 SSE 라우터.

    기존 구현은 /api/ai/multi-chat 동기 JSON을 끝까지 기다린 뒤
    agent_complete/all_complete를 한꺼번에 보내서 UI가 '우르르' 표시됐다.

    이 구현은 정식 multi_agent_service.build_stream_generator를 직접 사용해서
    turn_start → agent_start → heartbeat → agent_answer/error → all_complete 순서로 즉시 전송한다.
    """
    payload = await request.json()

    async def event_generator():
        route_request_id = f"compat_{uuid.uuid4().hex[:12]}"
        heartbeat_s = max(5.0, float(os.getenv("AI_STREAM_HEARTBEAT_SECONDS", "10")))
        started = time.time()
        last_agent_index = None
        last_agent_name = None

        try:
            from app.schemas.multi_chat_schema import MultiChatRequest
            from app.services.multi_agent_service import build_stream_generator

            mode = str(payload.get("mode") or payload.get("learningMode") or "default").lower()
            _, agent_by_id, agent_by_name = _stream_agent_maps(payload)
            chat_request = MultiChatRequest(**payload)
            gen = build_stream_generator(chat_request)

            while True:
                task = asyncio.create_task(asyncio.to_thread(next, gen, _STREAM_SENTINEL))

                while True:
                    done, _ = await asyncio.wait({task}, timeout=heartbeat_s)
                    if done:
                        item = task.result()
                        break

                    yield _sse("heartbeat", {
                        "type": "heartbeat",
                        "requestId": route_request_id,
                        "agentIndex": last_agent_index,
                        "agentName": last_agent_name,
                        "elapsedMs": int((time.time() - started) * 1000),
                        "message": "답변 생성 중입니다.",
                    })

                if item is _STREAM_SENTINEL:
                    break

                event = item.get("event") or "message"
                data = item.get("data") or {}

                if isinstance(data, dict):
                    if event in {"agent_answer", "agent_message", "agent_start", "agent_error"}:
                        data = _enrich_stream_event(data, agent_by_id, agent_by_name, mode)
                    if event == "all_complete":
                        data.setdefault("success", True)
                        data.setdefault("groupId", payload.get("groupId") or payload.get("group_id"))
                        data.setdefault("roomId", payload.get("roomId") or payload.get("room_id"))
                        data.setdefault("agentRoomId", payload.get("agentRoomId") or payload.get("agent_room_id"))
                        data["mode"] = mode
                        data["messages"] = _messages_from_complete_payload(data, payload, agent_by_id, agent_by_name)
                    last_agent_index = data.get("agentIndex", last_agent_index)
                    last_agent_name = data.get("agentName", last_agent_name)

                yield _sse(event, data)
                if event == "all_complete":
                    yield _sse("done", data)

        except Exception as exc:
            yield _sse("error", {
                "message": "AI 스트리밍 중 오류가 발생했습니다.",
                "detail": str(exc),
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
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
