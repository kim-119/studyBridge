"""학습메이트 전용 타입드 Ollama 게이트웨이.

기존 app.services.ollama_client.ask_ollama 는 연결실패/타임아웃/모델없음/빈응답을
'사람이 읽는 안내 문자열'로 반환했고, 호출부는 그것을 교수 답변으로 내보냈다
(운영 문구·모델명·예외 메시지가 사용자에게 노출 + 장애가 SUCCESS 로 집계).

이 모듈은 실패를 절대 텍스트로 돌려주지 않는다. 항상 LLMError 하위 예외를 던진다.
  LLM_UNAVAILABLE / LLM_TIMEOUT / LLM_MODEL_NOT_FOUND / LLM_EMPTY_RESPONSE /
  LLM_HTTP_ERROR / LLM_ABORTED
사용자에게 보일 문구는 USER_MESSAGES 의 중립 문장만 쓴다(모델명/URL/num_ctx 비노출).

스트리밍(stream=true)으로 호출하는 이유
  1) 청크마다 CancelToken·턴 데드라인을 확인해 연결을 닫을 수 있다(닫으면 Ollama 생성도 중단).
  2) prefix 검사 콜백(중복 가드)이 초반 토큰만 보고 생성을 조기 중단할 수 있다.
  3) TTFT 를 실측할 수 있다.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import requests

from app.studymate.cancellation import CancelToken, CancelledByClient

logger = logging.getLogger("studybridge.studymate.llm")


# ── 오류 계층 ─────────────────────────────────────────────────────────────────
class LLMError(RuntimeError):
    code = "LLM_ERROR"

    def __init__(self, detail: str = "", *, elapsed_ms: int = 0):
        super().__init__(detail or self.code)
        self.detail = detail          # 내부 로그 전용. 사용자 응답에 싣지 않는다.
        self.elapsed_ms = elapsed_ms


class LLMUnavailable(LLMError):
    code = "LLM_UNAVAILABLE"


class LLMTimeout(LLMError):
    code = "LLM_TIMEOUT"


class LLMModelNotFound(LLMError):
    code = "LLM_MODEL_NOT_FOUND"


class LLMEmptyResponse(LLMError):
    code = "LLM_EMPTY_RESPONSE"


class LLMHTTPError(LLMError):
    code = "LLM_HTTP_ERROR"


class LLMAborted(LLMError):
    """prefix 가드가 생성을 조기 중단했다(예: 앞 교수 문장 복제)."""
    code = "LLM_ABORTED"

    def __init__(self, detail: str = "", *, partial: str = "", elapsed_ms: int = 0):
        super().__init__(detail, elapsed_ms=elapsed_ms)
        self.partial = partial


USER_MESSAGES = {
    "LLM_UNAVAILABLE": "AI 모델 서버에 연결하지 못해 이 답변을 만들지 못했어요. 잠시 후 다시 시도해 주세요.",
    "LLM_TIMEOUT": "답변 생성이 제한 시간을 넘어 중단됐어요. 잠시 후 다시 시도해 주세요.",
    "LLM_MODEL_NOT_FOUND": "AI 모델을 사용할 수 없어 이 답변을 만들지 못했어요. 운영자에게 알려 주세요.",
    "LLM_EMPTY_RESPONSE": "AI가 빈 답변을 돌려줘 이 답변을 표시하지 못했어요. 다시 시도해 주세요.",
    "LLM_HTTP_ERROR": "AI 모델 호출 중 오류가 발생해 이 답변을 만들지 못했어요.",
    "LLM_ABORTED": "중복된 답변이 감지되어 생성을 중단했어요.",
    "TURN_TIMEOUT": "이번 턴의 시간 예산을 넘어 남은 답변 생성을 중단했어요.",
    "CLIENT_CANCELLED": "요청이 취소되었습니다.",
    "QUALITY_FAILED": "품질 기준을 통과하는 답변을 만들지 못했어요. 질문을 조금 바꿔 다시 시도해 주세요.",
    "AGENT_FAILED": "이 교수의 답변을 만들지 못했어요. 잠시 후 다시 시도해 주세요.",
}


def user_message_for(code: str) -> str:
    return USER_MESSAGES.get(code) or USER_MESSAGES["AGENT_FAILED"]


# ── 요청/결과 ─────────────────────────────────────────────────────────────────
@dataclass
class LLMRequest:
    system: str
    user: str
    model: str
    num_ctx: int
    num_predict: int
    temperature: float = 0.5
    top_p: float = 0.9
    top_k: Optional[int] = None
    repeat_penalty: Optional[float] = None
    seed: Optional[int] = None
    think: bool = False
    format: Optional[Any] = None       # JSON schema dict 또는 "json"
    timeout_s: float = 120.0
    keep_alive: Optional[str] = None
    task: str = "render"               # trace 용 라벨


@dataclass
class LLMResult:
    content: str
    thinking: str = ""
    model: str = ""
    num_ctx: int = 0
    prompt_eval_count: Optional[int] = None
    eval_count: Optional[int] = None
    done_reason: str = ""
    ttft_ms: Optional[int] = None
    total_ms: int = 0
    load_ms: Optional[int] = None
    prompt_eval_ms: Optional[int] = None
    eval_ms: Optional[int] = None
    thinking_enabled: bool = False
    context_saturated: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def tokens_per_sec(self) -> Optional[float]:
        if self.eval_count and self.eval_ms:
            return round(self.eval_count / (self.eval_ms / 1000.0), 2)
        return None


PrefixGuard = Callable[[str], Optional[str]]   # 누적 텍스트 → 중단 사유(None=계속)


def _base_url() -> str:
    return (os.getenv("STUDYMATE_OLLAMA_BASE_URL") or os.getenv("OLLAMA_BASE_URL")
            or "http://localhost:11434").rstrip("/")


# ── 테스트/장애주입 transport ─────────────────────────────────────────────────
# 단위 테스트는 set_transport 로 가짜 스트림을 주입한다. 운영에서는 None(실제 HTTP).
_TRANSPORT: Optional[Callable[[LLMRequest], Any]] = None


def set_transport(fn: Optional[Callable[[LLMRequest], Any]]) -> None:
    global _TRANSPORT
    _TRANSPORT = fn


def _fault_injection() -> str:
    """스테이징 전용 장애주입. STUDYMATE_ALLOW_FAULT_INJECTION=1 일 때만 의미가 있다."""
    if os.getenv("STUDYMATE_ALLOW_FAULT_INJECTION", "") != "1":
        return ""
    return (os.getenv("STUDYMATE_FAULT_INJECTION") or "").strip().lower()


def _payload(req: LLMRequest) -> Dict[str, Any]:
    options: Dict[str, Any] = {
        "temperature": float(req.temperature),
        "top_p": float(req.top_p),
        "num_ctx": int(req.num_ctx),
        "num_predict": int(req.num_predict),
    }
    if req.top_k is not None:
        options["top_k"] = int(req.top_k)
    if req.repeat_penalty is not None:
        options["repeat_penalty"] = float(req.repeat_penalty)
    if req.seed is not None:
        options["seed"] = int(req.seed)
    body: Dict[str, Any] = {
        "model": req.model,
        "messages": [
            {"role": "system", "content": req.system},
            {"role": "user", "content": req.user},
        ],
        "stream": True,
        "think": bool(req.think),       # 명시 전송: 생략하면 qwen3 는 thinking ON(실측)
        "options": options,
    }
    if req.format is not None:
        body["format"] = req.format
    ka = req.keep_alive if req.keep_alive is not None else (os.getenv("OLLAMA_KEEP_ALIVE") or "").strip()
    if ka:
        body["keep_alive"] = ka
    return body


def _ns_to_ms(v: Any) -> Optional[int]:
    try:
        return int(int(v) / 1_000_000)
    except (TypeError, ValueError):
        return None


def generate(
    req: LLMRequest,
    *,
    cancel: Optional[CancelToken] = None,
    deadline: Optional[float] = None,
    prefix_guard: Optional[PrefixGuard] = None,
    prefix_check_chars: int = 120,
) -> LLMResult:
    """Ollama /api/chat 스트리밍 호출. 실패는 항상 LLMError 하위 예외.

    deadline: time.time() 기준 절대 마감. timeout_s 보다 먼저 오면 그걸 쓴다.
    prefix_guard: 누적 content 가 prefix_check_chars 를 넘을 때마다 호출. 사유 문자열을
                  돌려주면 연결을 닫고 LLMAborted 를 던진다.
    """
    t0 = time.time()
    if cancel is not None:
        cancel.raise_if_cancelled()
    hard_deadline = t0 + max(1.0, float(req.timeout_s))
    if deadline is not None:
        hard_deadline = min(hard_deadline, deadline)
    if hard_deadline - t0 < 1.0:
        raise LLMTimeout("no budget left before call", elapsed_ms=0)

    fault = _fault_injection()
    if fault == "unavailable":
        raise LLMUnavailable("fault injection: unavailable")
    if fault == "model_missing":
        raise LLMModelNotFound("fault injection: model missing")

    body = _payload(req)
    content_parts: List[str] = []
    thinking_parts: List[str] = []
    final: Dict[str, Any] = {}
    ttft_ms: Optional[int] = None
    next_check = prefix_check_chars
    resp = None
    try:
        if _TRANSPORT is not None:
            chunks = _TRANSPORT(req)
        else:
            try:
                resp = requests.post(
                    f"{_base_url()}/api/chat", json=body, stream=True,
                    timeout=(3.0, max(1.0, min(60.0, hard_deadline - time.time()))),
                )
            except requests.ConnectionError as e:
                raise LLMUnavailable(f"connect: {type(e).__name__}", elapsed_ms=int((time.time() - t0) * 1000))
            except requests.Timeout as e:
                raise LLMTimeout(f"connect timeout: {type(e).__name__}", elapsed_ms=int((time.time() - t0) * 1000))
            if resp.status_code == 404:
                txt = ""
                try:
                    txt = resp.text[:200]
                finally:
                    resp.close()
                raise LLMModelNotFound(f"404 {txt}", elapsed_ms=int((time.time() - t0) * 1000))
            if resp.status_code >= 400:
                txt = resp.text[:200]
                resp.close()
                if "not found" in txt and "model" in txt:
                    raise LLMModelNotFound(f"{resp.status_code} {txt}")
                raise LLMHTTPError(f"{resp.status_code} {txt}", elapsed_ms=int((time.time() - t0) * 1000))
            chunks = (json.loads(line) for line in resp.iter_lines() if line)

        for chunk in chunks:
            now = time.time()
            if cancel is not None and cancel.cancelled:
                raise CancelledByClient(cancel.reason or "cancelled")
            if now > hard_deadline:
                raise LLMTimeout("deadline exceeded mid-stream", elapsed_ms=int((now - t0) * 1000))
            if isinstance(chunk, dict) and chunk.get("error"):
                err = str(chunk.get("error"))
                if "not found" in err and "model" in err:
                    raise LLMModelNotFound(err[:200])
                raise LLMHTTPError(err[:200])
            msg = (chunk or {}).get("message") or {}
            piece = msg.get("content") or ""
            th = msg.get("thinking") or ""
            if th:
                thinking_parts.append(th)
            if piece:
                if ttft_ms is None:
                    ttft_ms = int((now - t0) * 1000)
                content_parts.append(piece)
                if prefix_guard is not None:
                    acc_len = sum(len(p) for p in content_parts)
                    if acc_len >= next_check:
                        reason = prefix_guard("".join(content_parts))
                        if reason:
                            raise LLMAborted(reason, partial="".join(content_parts),
                                             elapsed_ms=int((now - t0) * 1000))
                        next_check = acc_len + prefix_check_chars
            if chunk.get("done"):
                final = chunk
                break
    except requests.exceptions.ChunkedEncodingError as e:
        raise LLMUnavailable(f"stream broken: {type(e).__name__}", elapsed_ms=int((time.time() - t0) * 1000))
    except requests.exceptions.ReadTimeout as e:
        raise LLMTimeout(f"read timeout: {type(e).__name__}", elapsed_ms=int((time.time() - t0) * 1000))
    except requests.ConnectionError as e:
        raise LLMUnavailable(f"connection: {type(e).__name__}", elapsed_ms=int((time.time() - t0) * 1000))
    finally:
        if resp is not None:
            resp.close()   # 조기 중단/취소 시 연결을 닫아 Ollama 생성도 멈춘다.

    content = "".join(content_parts).strip()
    thinking = "".join(thinking_parts)
    total_ms = int((time.time() - t0) * 1000)
    if fault == "empty":
        content = ""
    if fault == "timeout":
        raise LLMTimeout("fault injection: timeout", elapsed_ms=total_ms)
    if not content:
        raise LLMEmptyResponse(
            f"empty content done_reason={final.get('done_reason')} thinking_chars={len(thinking)}",
            elapsed_ms=total_ms)
    pec = final.get("prompt_eval_count")
    result = LLMResult(
        content=content, thinking=thinking, model=req.model, num_ctx=req.num_ctx,
        prompt_eval_count=pec, eval_count=final.get("eval_count"),
        done_reason=str(final.get("done_reason") or ""), ttft_ms=ttft_ms, total_ms=total_ms,
        load_ms=_ns_to_ms(final.get("load_duration")),
        prompt_eval_ms=_ns_to_ms(final.get("prompt_eval_duration")),
        eval_ms=_ns_to_ms(final.get("eval_duration")),
        thinking_enabled=bool(req.think),
        # prompt_eval_count 가 num_ctx 에 닿았다 = 입력이 잘렸을 가능성(2026-09-16 감사에서 4096==4096 실측).
        context_saturated=bool(pec and req.num_ctx and pec >= req.num_ctx - 8),
    )
    if result.context_saturated:
        logger.warning("[LLM] context saturated task=%s num_ctx=%s prompt_eval_count=%s — 입력 절단 의심",
                       req.task, req.num_ctx, pec)
    return result


def ask_text(system: str, user: str, *, task: str = "engine", max_tokens: Optional[int] = None,
             temperature: Optional[float] = None, level: Optional[str] = None,
             persona: Optional[str] = None, cancel: Optional[CancelToken] = None,
             deadline: Optional[float] = None, fmt: Optional[Any] = None) -> str:
    """모드 엔진(토론/소크라테스/상황극) 기존 `_llm(system, user, max_tokens, temperature)` 시그니처 대체.

    실패하면 예외(LLMError). 엔진은 이미 예외를 모드 전용 실패 이벤트로 바꾸는 경로를 갖고 있다.
    """
    from app.studymate import model_router
    from app.studymate import runtime_context

    ctx = runtime_context.current()
    cancel = cancel or (ctx.cancel if ctx else None)
    if deadline is None and ctx is not None and ctx.budget is not None:
        deadline = ctx.budget.deadline
    opts = model_router.resolve(task=task, level=level, persona=persona)
    req = LLMRequest(
        system=system, user=user, model=opts.model, num_ctx=opts.num_ctx,
        num_predict=int(max_tokens or opts.num_predict),
        temperature=float(opts.temperature if temperature is None else temperature),
        top_p=opts.top_p, seed=opts.seed, think=opts.think, format=fmt,
        timeout_s=opts.timeout_s, task=task,
    )
    res = generate(req, cancel=cancel, deadline=deadline)
    if ctx is not None:
        ctx.record_llm(task, res)
    return res.content
