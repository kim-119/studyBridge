"""POST /api/ai/planner/adaptive · GET /api/ai/planner/adaptive/health (Spring → ai07 내부 호출).

경로 근거: 기존 /api/ai/planner/* (assist·expand·roadmap·analyze·analyze-semantic) 와 같은 플래너 AI 묶음이고
충돌하는 경로가 없다. 기존 /api/ai/plan-recommendation 은 PDF 체크리스트 기반 별도 기능이라 유지한다.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import time
from collections import Counter
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.adaptive_planner import config, service
from app.adaptive_planner.errors import AdaptiveError
from app.adaptive_planner.schema import parse_request

logger = logging.getLogger("studybridge.adaptive_planner")
router = APIRouter(tags=["adaptive-planner"])


class _Admission:
    """단일 워커 이벤트 루프 안에서만 쓰므로 잠금이 필요 없다."""

    def __init__(self) -> None:
        self.total = 0
        self.per_user: Counter = Counter()

    def enter(self, user_key: str, rt: config.RuntimeSettings) -> None:
        if self.per_user[user_key] >= rt.max_inflight_per_user:
            raise AdaptiveError("ADAPTIVE_TOO_MANY_REQUESTS", "같은 사용자의 추천 요청이 이미 처리 중입니다.", retry_after=3)
        if self.total >= rt.max_inflight:
            raise AdaptiveError("ADAPTIVE_OVERLOADED", "추천 요청이 많아 잠시 후 다시 시도해 주세요.", retry_after=5)
        self.total += 1
        self.per_user[user_key] += 1

    def leave(self, user_key: str) -> None:
        self.total -= 1
        self.per_user[user_key] -= 1
        if self.per_user[user_key] <= 0:
            del self.per_user[user_key]


admission = _Admission()


def _check_auth(request: Request, rt: config.RuntimeSettings) -> None:
    """Spring↔FastAPI 내부 계약(Authorization: Bearer AI_SERVER_API_KEY), fail-closed."""
    key = os.getenv("AI_SERVER_API_KEY") or ""
    if not key:
        if rt.allow_unauthenticated:
            return
        raise AdaptiveError("ADAPTIVE_AUTH_NOT_CONFIGURED", "AI 서버 내부 인증이 설정되지 않았습니다.")
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), key.encode()):
        raise AdaptiveError("ADAPTIVE_UNAUTHORIZED", "AI 서버 인증에 실패했습니다.")


async def _read_body_limited(request: Request, limit: int) -> bytes:
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > limit:
                raise AdaptiveError("ADAPTIVE_BODY_TOO_LARGE", f"요청 바디는 최대 {limit} 바이트입니다.")
        except ValueError:
            raise AdaptiveError("ADAPTIVE_INVALID_JSON", "Content-Length 가 올바르지 않습니다.") from None
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > limit:
            raise AdaptiveError("ADAPTIVE_BODY_TOO_LARGE", f"요청 바디는 최대 {limit} 바이트입니다.")
    return bytes(buf)


def _error(err: AdaptiveError, request_id: Optional[str]) -> JSONResponse:
    headers = {"Retry-After": str(err.retry_after)} if err.retry_after else None
    body = {"code": err.code, "message": err.message, "retryable": err.retryable, "requestId": request_id}
    if err.field:
        body["field"] = err.field
    return JSONResponse(status_code=err.status, content={"error": body}, headers=headers)


async def _watch_disconnect(request: Request) -> None:
    while not await request.is_disconnected():
        await asyncio.sleep(0.5)


@router.post("/api/ai/planner/adaptive", summary="적응형 학습 엔진(ROADMAP_COACH 현재 단계 코칭 / MANUAL_NEXT 다음 학습)")
async def adaptive(request: Request) -> JSONResponse:
    from app.studymate.cancellation import CancelledByClient, CancelToken

    t0 = time.monotonic()
    rt = config.runtime()
    request_id: Optional[str] = request.headers.get("x-request-id")
    admitted: Optional[str] = None
    try:
        if not rt.enabled:
            raise AdaptiveError("ADAPTIVE_DISABLED", "적응형 학습 엔진이 비활성화되어 있습니다.")
        _check_auth(request, rt)
        raw = await _read_body_limited(request, config.limits().max_body_bytes)
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise AdaptiveError("ADAPTIVE_INVALID_JSON", "요청 바디가 올바른 JSON 이 아닙니다.") from None
        if isinstance(payload, dict) and isinstance(payload.get("requestId"), str):
            request_id = payload["requestId"][:64]
        req = parse_request(payload, request.headers.get("x-request-id"))
        request_id = req.request_id
        admission.enter(req.user_key, rt)
        admitted = req.user_key

        cancel = CancelToken()
        deadline = time.time() + max(2.0, rt.request_timeout_s - 2.0)
        work = asyncio.ensure_future(run_in_threadpool(service.run, req, rt, cancel, deadline))
        watch = asyncio.ensure_future(_watch_disconnect(request))
        try:
            done, _ = await asyncio.wait({work, watch}, timeout=rt.request_timeout_s,
                                         return_when=asyncio.FIRST_COMPLETED)
        finally:
            watch.cancel()
        if work in done:
            return JSONResponse(work.result())
        if watch in done:
            cancel.cancel("client_disconnected")
            raise AdaptiveError("ADAPTIVE_CLIENT_CANCELLED", "클라이언트가 요청을 취소했습니다.")
        # 전체 예산 초과(LLM 이 마감을 넘김) → LLM 을 끊고 규칙 결과로 응답한다. 규칙 계산은 수 ms 다.
        cancel.cancel("request_timeout")
        out = await run_in_threadpool(service.run, req, rt, None, None, forced_fallback="REQUEST_TIMEOUT")
        return JSONResponse(out)
    except AdaptiveError as e:
        if e.status >= 500 or e.status == 429:
            logger.warning("[ADAPTIVE] reject requestId=%s code=%s", request_id, e.code)
        else:
            logger.info("[ADAPTIVE] reject requestId=%s code=%s field=%s", request_id, e.code, e.field)
        return _error(e, request_id)
    except CancelledByClient:
        return _error(AdaptiveError("ADAPTIVE_CLIENT_CANCELLED", "클라이언트가 요청을 취소했습니다."), request_id)
    except Exception as e:  # noqa: BLE001 — 예외 메시지(입력 포함 가능)는 남기지 않는다.
        logger.error("[ADAPTIVE] internal error type=%s requestId=%s elapsedMs=%d", type(e).__name__, request_id,
                     int((time.monotonic() - t0) * 1000))
        return _error(AdaptiveError("ADAPTIVE_INTERNAL_ERROR", "추천을 처리하지 못했습니다."), request_id)
    finally:
        if admitted is not None:
            admission.leave(admitted)


@router.get("/api/ai/planner/adaptive/health")
async def adaptive_health() -> JSONResponse:
    rt = config.runtime()
    return JSONResponse({"enabled": rt.enabled, "llmEnabled": rt.llm_enabled,
                         "authConfigured": bool(os.getenv("AI_SERVER_API_KEY")),
                         "contractVersion": config.CONTRACT_VERSION, "allowedMinutes": list(config.ALLOWED_MINUTES),
                         "inflight": admission.total, "metrics": service.metrics.snapshot()})
