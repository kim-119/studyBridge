"""POST /api/ai/vision/analyze — 화면공유 프레임 1장 + 질문 분석 (Spring → ai07 내부 호출).

개인정보: 이미지·질문 원문은 디스크/DB/로그에 남기지 않는다. 로그는 requestId·groupId·코드·
처리시간·이미지 크기 같은 최소 메타데이터만. Python GC 특성상 참조 해제가 즉시 물리 메모리 삭제를
보장하지는 않는다.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.vision.config import VisionSettings, get_settings
from app.vision.errors import VisionError, vision_error
from app.vision.gate import gate
from app.vision.image_validation import decode_and_validate_image, parse_request
from app.vision.inference import model_id, run_inference

logger = logging.getLogger("studybridge.vision")


def _begin_drain() -> None:
    gate.draining = True


router = APIRouter(tags=["vision"], on_shutdown=[_begin_drain])


def _check_auth(request: Request, s: VisionSettings) -> None:
    """기존 Spring↔FastAPI 계약(Authorization: Bearer AI_SERVER_API_KEY)을 재사용하되 fail-closed."""
    key = os.getenv("AI_SERVER_API_KEY") or ""
    if not key:
        if s.allow_unauthenticated:
            return
        raise vision_error("VISION_AUTH_NOT_CONFIGURED", "AI 서버 내부 인증이 설정되지 않았습니다.")
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), key.encode()):
        raise vision_error("VISION_UNAUTHORIZED", "AI 서버 인증에 실패했습니다.")


async def _read_body_limited(request: Request, limit: int) -> bytes:
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > limit:
                raise vision_error("VISION_BODY_TOO_LARGE", f"요청 바디는 최대 {limit} 바이트입니다.")
        except ValueError:
            raise vision_error("VISION_INVALID_JSON", "Content-Length 가 올바르지 않습니다.") from None
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > limit:
            raise vision_error("VISION_BODY_TOO_LARGE", f"요청 바디는 최대 {limit} 바이트입니다.")
    return bytes(buf)


def _error_response(err: VisionError, request_id: str | None) -> JSONResponse:
    headers = {"Retry-After": str(err.retry_after)} if err.retry_after else None
    return JSONResponse(
        status_code=err.status,
        content={"error": {"code": err.code, "message": err.message, "retryable": err.retryable,
                           "requestId": request_id}},
        headers=headers,
    )


async def _watch_disconnect(request: Request) -> None:
    while not await request.is_disconnected():
        await asyncio.sleep(0.5)


@router.post("/api/ai/vision/analyze")
async def analyze(request: Request) -> JSONResponse:
    t0 = time.monotonic()
    s = get_settings()
    request_id: str | None = None
    group_id: str | None = None
    meta: dict = {}
    code = "OK"
    status = 200
    try:
        if not s.enabled:
            raise vision_error("VISION_DISABLED", "화면 분석 기능이 비활성화되어 있습니다.")
        _check_auth(request, s)
        raw = await _read_body_limited(request, s.max_body_bytes)
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise vision_error("VISION_INVALID_JSON", "요청 바디가 올바른 JSON 이 아닙니다.") from None
        finally:
            del raw
        req = parse_request(payload, s)
        del payload
        request_id, group_id = req.request_id, req.group_id

        async with gate.admit(req.request_id, req.group_id, s) as queue_ms:
            img = await run_in_threadpool(decode_and_validate_image, req.image_b64, req.mime, s)
            req.image_b64 = ""
            meta = {"w": img.width, "h": img.height, "bytes": img.source_bytes, "queueMs": int(queue_ms)}
            t_inf = time.monotonic()
            infer = asyncio.create_task(run_inference(img.jpeg_bytes, req.question, s))
            watch = asyncio.create_task(_watch_disconnect(request))
            try:
                done, _ = await asyncio.wait({infer, watch}, return_when=asyncio.FIRST_COMPLETED)
                if infer not in done:
                    infer.cancel()
                    raise vision_error("VISION_CLIENT_CANCELLED", "클라이언트가 요청을 취소했습니다.")
                answer = infer.result()
            finally:
                watch.cancel()
                if not infer.done():
                    infer.cancel()
                del img
            meta["inferMs"] = int((time.monotonic() - t_inf) * 1000)
        gate.mark_completed(req.request_id, s)
        latency = int((time.monotonic() - t0) * 1000)
        return JSONResponse({
            "requestId": req.request_id,
            "answer": answer,
            "model": model_id(s),
            "latencyMs": latency,
            "queueWaitMs": meta["queueMs"],
            "inferenceMs": meta["inferMs"],
        })
    except VisionError as e:
        code, status = e.code, e.status
        return _error_response(e, request_id)
    except asyncio.CancelledError:
        code, status = "VISION_CLIENT_CANCELLED", 499
        raise
    except Exception as e:  # noqa: BLE001 — 내부 오류도 구조화. 예외 메시지(입력 포함 가능)는 로깅하지 않는다.
        code, status = "VISION_INTERNAL_ERROR", 500
        logger.error("[VISION] internal error type=%s requestId=%s", type(e).__name__, request_id)
        return _error_response(vision_error("VISION_INTERNAL_ERROR", "내부 오류가 발생했습니다."), request_id)
    finally:
        logger.info(
            "[VISION] requestId=%s groupId=%s status=%s code=%s latencyMs=%s meta=%s model=%s",
            request_id, group_id, status, code, int((time.monotonic() - t0) * 1000), meta, model_id(s),
        )


@router.get("/api/ai/vision/health")
async def health(request: Request) -> JSONResponse:
    s = get_settings()
    try:
        _check_auth(request, s)
    except VisionError as e:
        return _error_response(e, None)
    return JSONResponse({
        "enabled": s.enabled,
        "backend": s.backend,
        "model": model_id(s),
        "maxConcurrency": s.max_concurrency,
        "maxQueue": s.max_queue,
        "maxPerGroup": s.max_per_group,
        "gate": gate.snapshot(),
    })
