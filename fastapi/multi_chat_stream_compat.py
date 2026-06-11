import asyncio
import json
import os
import time
import uuid

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/ai", tags=["ai-stream-compat"])

_STREAM_SENTINEL = object()


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data or {}, ensure_ascii=False)}\n\n"


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
                    last_agent_index = data.get("agentIndex", last_agent_index)
                    last_agent_name = data.get("agentName", last_agent_name)

                yield _sse(event, data)

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
