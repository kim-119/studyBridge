"""
Fetch Streaming(NDJSON) endpoint — 기존 SSE와 완전히 별개의 "우회도로".

추가 endpoint (모두 media_type=application/x-ndjson):
  POST /api/ai/agents/chat/fetch-stream
  POST /api/group-study/ai/fetch-stream
  POST /api/materials/{material_id}/ai/fetch-stream
  POST /api/materials/{material_id}/roadmap/ai/fetch-stream
  POST /api/ai/tasks/fetch-stream

설계:
  - text/event-stream / "data:" 접두어를 절대 쓰지 않는다(SSE와 혼합 금지).
  - 스트림 본체 로직은 ai_fetch_stream_service에 있고, 여기서는 요청 파싱 + StreamingResponse만 담당.
  - AI_FETCH_STREAM_ENABLED=false면 503으로 비활성(기존 SSE 경로엔 영향 없음).
  - 동기 generator를 StreamingResponse에 넘기면 Starlette가 threadpool에서 순회 → event loop 비차단.
"""
import logging
from typing import Any, Dict, Iterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.services import ai_fetch_stream_service as svc

logger = logging.getLogger("studybridge.fetch_stream")
router = APIRouter(tags=["AI Fetch Streaming (NDJSON)"])

_NDJSON_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # nginx 버퍼링 비활성 → chunk 즉시 전달
}
_MEDIA = "application/x-ndjson"


def _disabled_response() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"type": "error", "message": "Fetch streaming is disabled (AI_FETCH_STREAM_ENABLED=false)."},
    )


async def _payload(request: Request) -> Dict[str, Any]:
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {"message": str(body)}
    except Exception:
        return {}


def _stream(gen: Iterator[bytes]) -> StreamingResponse:
    return StreamingResponse(gen, media_type=_MEDIA, headers=_NDJSON_HEADERS)


# ── 1) 멀티에이전트 AI 채팅 ───────────────────────────────────────────────────
@router.post("/api/ai/agents/chat/fetch-stream", summary="멀티에이전트 채팅 (NDJSON 스트리밍)")
async def agents_chat_fetch_stream(request: Request):
    if not svc.is_fetch_stream_enabled():
        return _disabled_response()
    payload = await _payload(request)
    return _stream(svc.agent_chat_stream(payload))


# ── 2) 그룹스터디 AI ──────────────────────────────────────────────────────────
@router.post("/api/group-study/ai/fetch-stream", summary="그룹스터디 AI (NDJSON 스트리밍)")
async def group_study_fetch_stream(request: Request):
    if not svc.is_fetch_stream_enabled():
        return _disabled_response()
    payload = await _payload(request)
    return _stream(svc.group_study_stream(payload))


# ── 3) 자료보관함 AI 채팅 ─────────────────────────────────────────────────────
@router.post("/api/materials/{material_id}/ai/fetch-stream", summary="자료보관함 RAG 채팅 (NDJSON 스트리밍)")
async def material_chat_fetch_stream(material_id: int, request: Request):
    if not svc.is_fetch_stream_enabled():
        return _disabled_response()
    payload = await _payload(request)
    return _stream(svc.material_chat_stream(material_id, payload))


# ── 4) 로드맵 AI 설명/채팅 ────────────────────────────────────────────────────
@router.post("/api/materials/{material_id}/roadmap/ai/fetch-stream", summary="로드맵 AI 설명/채팅 (NDJSON 스트리밍)")
async def roadmap_chat_fetch_stream(material_id: int, request: Request):
    if not svc.is_fetch_stream_enabled():
        return _disabled_response()
    payload = await _payload(request)
    return _stream(svc.roadmap_chat_stream(material_id, payload))


# ── 5) 통합 AI 작업 endpoint ──────────────────────────────────────────────────
@router.post("/api/ai/tasks/fetch-stream", summary="통합 AI 작업 (NDJSON 스트리밍)")
async def tasks_fetch_stream(request: Request):
    if not svc.is_fetch_stream_enabled():
        return _disabled_response()
    payload = await _payload(request)
    return _stream(svc.tasks_stream(payload))
