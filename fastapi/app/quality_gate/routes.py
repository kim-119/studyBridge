"""POST /api/ai/quality/evaluate — 내부 인증 전용 품질 평가 API (response-quality.v1).

- 내부 Bearer 필수(fail-closed). 브라우저 직접 호출 대상 아님(Spring → ai07).
- 기능 플래그 AI_QUALITY_EVALUATE_API_ENABLED (기본 false → 503 FEATURE_DISABLED).
- 본문 256KB 제한, 호출자별 rate limit, 동시 평가 상한(세마포어), requestId 멱등(같은 본문 재생/다른 본문 409),
  평가 timeout → VALIDATION_ERROR. 로그에는 질문/답변/근거 원문을 남기지 않는다.
"""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.contracts.response_quality_v1 import QualityInput, output_to_dict
from app.core.request_guards import IdempotencyCache, RateLimiter, limited_route_class
from app.core.security import verify_internal_token

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 256 * 1024
router = APIRouter(tags=["Quality Gate"], dependencies=[Depends(verify_internal_token)],
                   route_class=limited_route_class(MAX_BODY_BYTES))

RATE = RateLimiter(capacity=int(os.getenv("AI_QUALITY_EVAL_RATE_BURST", "60")),
                   refill_per_sec=float(os.getenv("AI_QUALITY_EVAL_RATE_PER_SEC", "2")))
IDEMPOTENCY = IdempotencyCache()
_sem = {"s": None, "n": 0}


def _semaphore() -> asyncio.Semaphore:
    n = max(1, int(os.getenv("AI_QUALITY_EVAL_MAX_CONCURRENCY", "2")))
    if _sem["s"] is None or _sem["n"] != n:
        _sem["s"], _sem["n"] = asyncio.Semaphore(n), n
    return _sem["s"]


def api_enabled() -> bool:
    return (os.getenv("AI_QUALITY_EVALUATE_API_ENABLED") or "false").strip().lower() in ("1", "true", "yes", "on")


def _err(status: int, code: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"success": False, "errorCode": code, **extra})


@router.post("/api/ai/quality/evaluate", summary="AI 생성물 품질 평가(response-quality.v1, 내부 전용)")
async def evaluate_endpoint(body: dict, x_caller_id: str | None = Header(default=None, alias="X-Caller-Id")):
    if not api_enabled():
        return _err(503, "FEATURE_DISABLED")
    # 호출자는 모두 같은 내부 키를 쓰므로 X-Caller-Id(자기 주장)로 버킷을 나누지 않는다 → 전역 버킷.
    RATE.check("evaluate")
    try:
        inp = QualityInput.model_validate(body)
    except ValidationError as e:
        # 입력 원문을 되돌려주지 않는다(필드 위치/타입만).
        return _err(422, "CONTRACT_VALIDATION_FAILED",
                    errors=[{"loc": list(x.get("loc", ())), "type": x.get("type")} for x in e.errors()[:20]])
    bh = IDEMPOTENCY.body_hash(body)
    cached = IDEMPOTENCY.lookup(inp.requestId, bh)
    if cached is not None:
        return JSONResponse(status_code=200, content=cached, headers={"Idempotent-Replay": "true"})

    sem = _semaphore()
    try:
        await asyncio.wait_for(sem.acquire(), timeout=float(os.getenv("AI_QUALITY_EVAL_QUEUE_WAIT_SECONDS", "2")))
    except asyncio.TimeoutError:
        IDEMPOTENCY.release(inp.requestId)
        return _err(429, "EVALUATOR_BUSY")
    try:
        from app.quality_gate.evaluator import evaluate
        from app.quality_gate.judge import get_judge
        out = await evaluate(inp, judge=get_judge())
    except BaseException:
        IDEMPOTENCY.release(inp.requestId)
        raise
    finally:
        sem.release()
    payload = output_to_dict(out)
    IDEMPOTENCY.store(inp.requestId, bh, payload)
    return JSONResponse(status_code=200, content=payload)
