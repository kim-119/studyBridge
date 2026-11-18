"""POST /api/ai/vision/analyze — 화면공유 프레임 1장 + 질문 분석 (Spring → ai07 내부 호출).

처리: 입장(중복·그룹 한도) → GPU 슬롯에서 qwen3-vl 화면 판독(JSON) → 슬롯 반환 → 개인정보 마스킹 →
OpenAI 슬롯에서 최종 답변. 원본 이미지는 ai07 밖으로 나가지 않는다. 응답의 model 은 최종 답변 모델이다.

개인정보: 이미지·질문·판독 원문은 디스크/DB/로그에 남기지 않는다. 로그는 requestId·groupId·코드·
처리시간·이미지 크기·토큰 수 같은 최소 메타데이터만. Python GC 특성상 참조 해제가 즉시 물리 메모리 삭제를
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
from app.vision import answer as answer_mod
from app.vision.image_validation import decode_and_validate_image, parse_request
from app.vision.inference import model_id, run_extraction
from app.vision.redaction import mask_obj, mask_text

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
    body = {"code": err.code, "message": err.message, "retryable": err.retryable, "requestId": request_id}
    if err.stage:
        body["stage"] = err.stage
    return JSONResponse(status_code=err.status, content={"error": body}, headers=headers)


async def _watch_disconnect(request: Request) -> None:
    while not await request.is_disconnected():
        await asyncio.sleep(0.5)


async def _until_done_or_disconnect(request: Request, coro):
    """작업과 연결 끊김 감시를 함께 돌린다. 끊기면 작업을 취소하고 499 로 끝낸다(슬롯은 호출부 컨텍스트가 반환)."""
    work = asyncio.ensure_future(coro)
    watch = asyncio.create_task(_watch_disconnect(request))
    try:
        done, _ = await asyncio.wait({work, watch}, return_when=asyncio.FIRST_COMPLETED)
        if work not in done:
            work.cancel()
            raise vision_error("VISION_CLIENT_CANCELLED", "클라이언트가 요청을 취소했습니다.")
        return work.result()
    finally:
        watch.cancel()
        if not work.done():
            work.cancel()


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

        deadline = t0 + s.total_timeout_s
        async with gate.admit(req.request_id, req.group_id, s):
            # 1) VLM 화면 판독 — GPU 슬롯은 이 블록 안에서만 잡는다.
            async with gate.gpu_slot(s, timeout=deadline - time.monotonic()) as queue_ms:
                img = await run_in_threadpool(decode_and_validate_image, req.image_b64, req.mime, s)
                req.image_b64 = ""
                meta = {"w": img.width, "h": img.height, "bytes": img.source_bytes, "queueMs": int(queue_ms)}
                t_vis = time.monotonic()
                try:
                    extraction = await _until_done_or_disconnect(
                        request, run_extraction(img.jpeg_bytes, req.question, s, timeout=deadline - time.monotonic()))
                finally:
                    del img
                meta["visionMs"] = int((time.monotonic() - t_vis) * 1000)
            meta["screenType"], meta["legible"] = extraction["screenType"], extraction["legible"]
            # 2) 외부 전송 최소화: 판독 결과·질문만, 개인정보·비밀값 마스킹 후
            masked, n1 = mask_obj(extraction)
            question, n2 = mask_text(req.question)
            del extraction
            meta["masked"] = n1 + n2
            # 3) OpenAI 최종 답변 — GPU 와 무관한 별도 슬롯
            async with gate.answer_slot(s, timeout=deadline - time.monotonic()) as answer_wait_ms:
                meta["answerQueueMs"] = int(answer_wait_ms)
                answer, ameta = await _until_done_or_disconnect(
                    request, answer_mod.generate_answer(masked, question, s, timeout=deadline - time.monotonic()))
            meta.update(answerMs=ameta["answerMs"], promptTokens=ameta["promptTokens"],
                        completionTokens=ameta["completionTokens"], answerModel=ameta["answerModel"])
        gate.mark_completed(req.request_id, s)
        latency = int((time.monotonic() - t0) * 1000)
        return JSONResponse({
            "requestId": req.request_id,
            "answer": answer,
            "model": ameta["answerModel"],
            "latencyMs": latency,
            "queueWaitMs": meta["queueMs"] + meta["answerQueueMs"],
            "inferenceMs": meta["visionMs"] + meta["answerMs"],
            "visionModel": model_id(s),
            "answerModel": ameta["answerModel"],
            "answerProvider": ameta["answerProvider"],
            "visionLatencyMs": meta["visionMs"],
            "answerLatencyMs": meta["answerMs"],
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
            "[VISION] requestId=%s groupId=%s status=%s code=%s latencyMs=%s meta=%s visionModel=%s",
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
        "model": s.answer_model if s.answer_provider != "mock" else "mock-answer",
        "visionModel": model_id(s),
        "answerProvider": answer_mod.provider_id(s),
        "answerModel": s.answer_model if s.answer_provider != "mock" else "mock-answer",
        "externalLlmEnabled": s.external_llm_enabled,
        "answerMaxConcurrency": s.answer_max_concurrency,
        "answerBudget": answer_mod.budget.snapshot(s.answer_daily_token_cap),
        "maxConcurrency": s.max_concurrency,
        "maxQueue": s.max_queue,
        "maxPerGroup": s.max_per_group,
        "gate": gate.snapshot(),
    })
