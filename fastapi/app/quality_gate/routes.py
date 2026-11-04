"""POST /api/ai/quality/evaluate — 내부 인증 전용 품질 평가 API (response-quality.v1).

- 내부 Bearer 필수(fail-closed). 브라우저 직접 호출 대상 아님(Spring → ai07).
- 기능 플래그 AI_QUALITY_EVALUATE_API_ENABLED (기본 false → 503 FEATURE_DISABLED).
- 본문 상한 = 계약 상한(문자)에서 유도한 바이트(아래 MAX_BODY_BYTES), rate limit, 동시 평가 상한(세마포어),
  requestId 멱등(같은 본문 재생/다른 본문 409), 평가 timeout → 200 VALIDATION_ERROR. 로그에는 질문/답변/근거 원문을 남기지 않는다.

오류 응답 계약(Spring QualityEvaluatorClient 는 HTTP 상태로만 분류한다 — 본문은 진단용, 원문 미포함):
  200 response-quality.v1 출력       — 평가 완료(APPROVED/REJECTED) 또는 평가 불가(VALIDATION_ERROR, success=false → Spring UNAVAILABLE)
  401/403 (인증 의존성·미들웨어)     — EVALUATOR_AUTH_FAILED, 재시도 무의미
  409 IDEMPOTENCY_CONFLICT/_IN_PROGRESS — 같은 requestId 에 다른 본문/처리 중
  413 PAYLOAD_TOO_LARGE, 422 CONTRACT_VALIDATION_FAILED — EVALUATOR_INPUT_REJECTED, 재시도 무의미(retryable=false)
  429 EVALUATOR_BUSY / RATE_LIMITED   — Retry-After 포함, retryable=true
  503 FEATURE_DISABLED                — 기능 꺼짐(retryable=false)
라우트가 직접 만드는 오류 본문은 {"success": false, "errorCode", "retryable"} 로 통일한다.
"""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from fastapi import HTTPException

from app.contracts.jtypes import ContractJsonError, loads_contract
from app.contracts.response_quality_v1 import (MAX_EVIDENCE_CHARS, MAX_EVIDENCE_ITEMS, MAX_OUTPUT_CHARS, QualityInput,
                                               output_to_dict)
from app.core.request_guards import IdempotencyCache, RateLimiter, limited_route_class
from app.core.security import verify_internal_token

logger = logging.getLogger(__name__)

# R5-9: 계약 상한은 '문자(코드포인트)' 기준(proposedOutput 6만, originalRequest 8천, 근거 32×8천). 계약 안의 입력이 바이트
# 상한에 걸려 413 이 나지 않도록, 코드포인트당 최악 6바이트(\uXXXX 이스케이프)로 환산하고 구조·제약 필드 여유 64KiB 를 더한다.
# = 6 × (60000 + 8000 + 256000) + 65536 = 2,009,536 바이트. Spring 사전 차단(MAX_REQUEST_BYTES)도 같은 값을 써야 한다.
CONTRACT_MAX_BODY_BYTES = 6 * (MAX_OUTPUT_CHARS + 8000 + MAX_EVIDENCE_ITEMS * MAX_EVIDENCE_CHARS) + 64 * 1024


def _max_body_bytes() -> int:
    try:
        v = int(os.getenv("AI_QUALITY_EVAL_MAX_BODY_BYTES", str(CONTRACT_MAX_BODY_BYTES)))
    except ValueError:
        return CONTRACT_MAX_BODY_BYTES
    return max(256 * 1024, min(v, 8 * 1024 * 1024))


MAX_BODY_BYTES = _max_body_bytes()
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


def _err(status: int, code: str, *, retryable: bool = False, retry_after: int | None = None, **extra) -> JSONResponse:
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
    return JSONResponse(status_code=status, content={"success": False, "errorCode": code, "retryable": retryable, **extra},
                        headers=headers)


def _http_err(e: HTTPException) -> JSONResponse:
    d = e.detail if isinstance(e.detail, dict) else {}
    code = str(d.get("errorCode") or "HTTP_" + str(e.status_code))
    ra = (e.headers or {}).get("Retry-After")
    return _err(e.status_code, code, retryable=e.status_code in (409, 429) and code != "IDEMPOTENCY_CONFLICT",
                retry_after=int(ra) if ra and str(ra).isdigit() else None)


@router.post("/api/ai/quality/evaluate", summary="AI 생성물 품질 평가(response-quality.v1, 내부 전용)")
async def evaluate_endpoint(request: Request, x_caller_id: str | None = Header(default=None, alias="X-Caller-Id")):
    if not api_enabled():
        return _err(503, "FEATURE_DISABLED")
    # 호출자는 모두 같은 내부 키를 쓰므로 X-Caller-Id(자기 주장)로 버킷을 나누지 않는다 → 전역 버킷.
    try:
        RATE.check("evaluate")
    except HTTPException as e:
        return _http_err(e)
    # 원시 바이트를 EC2 Jackson STRICT 와 같은 규칙으로 해석한다(NaN/중복 키/뒤따르는 토큰 거부, 암묵 변환 금지).
    try:
        body = loads_contract(await request.body())
    except ContractJsonError:
        return _err(422, "CONTRACT_VALIDATION_FAILED", errors=[{"loc": ["body"], "type": "json_invalid"}])
    try:
        inp = QualityInput.model_validate(body)
    except ValidationError as e:
        # 입력 원문을 되돌려주지 않는다(필드 위치/타입만).
        return _err(422, "CONTRACT_VALIDATION_FAILED",
                    errors=[{"loc": list(x.get("loc", ())), "type": x.get("type")} for x in e.errors()[:20]])
    bh = IDEMPOTENCY.body_hash(body)
    try:
        cached = IDEMPOTENCY.lookup(inp.requestId, bh)
    except HTTPException as e:
        return _http_err(e)
    if cached is not None:
        return JSONResponse(status_code=200, content=cached, headers={"Idempotent-Replay": "true"})

    sem = _semaphore()
    try:
        await asyncio.wait_for(sem.acquire(), timeout=float(os.getenv("AI_QUALITY_EVAL_QUEUE_WAIT_SECONDS", "2")))
    except asyncio.TimeoutError:
        IDEMPOTENCY.release(inp.requestId)
        return _err(429, "EVALUATOR_BUSY", retryable=True, retry_after=1)
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
