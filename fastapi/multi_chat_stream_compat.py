import json
import os
import httpx

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/ai", tags=["ai-stream-compat"])


@router.post("/multi-chat/stream")
async def multi_chat_stream_compat(request: Request):
    payload = await request.json()

    async def event_generator():
        yield "event: start\ndata: {}\n\n"

        try:
            port = os.getenv("FASTAPI_PORT", "8000")
            url = f"http://127.0.0.1:{port}/api/ai/multi-chat"

            async with httpx.AsyncClient(timeout=900.0) as client:
                response = await client.post(url, json=payload)

            if response.status_code >= 400:
                yield "event: error\ndata: " + json.dumps({
                    "status": response.status_code,
                    "body": response.text
                }, ensure_ascii=False) + "\n\n"
                return

            try:
                result = response.json()
            except Exception:
                result = {"content": response.text}

            candidates = []
            if isinstance(result, dict):
                for key in ["answers", "responses", "agentResponses", "agent_responses", "results", "agents"]:
                    value = result.get(key)
                    if isinstance(value, list):
                        candidates = value
                        break

            if candidates:
                for item in candidates:
                    yield "event: agent_complete\ndata: " + json.dumps(item, ensure_ascii=False) + "\n\n"
            else:
                yield "event: agent_complete\ndata: " + json.dumps(result, ensure_ascii=False) + "\n\n"

            yield "event: all_complete\ndata: " + json.dumps(result, ensure_ascii=False) + "\n\n"

        except Exception as exc:
            yield "event: error\ndata: " + json.dumps({
                "message": str(exc)
            }, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
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
