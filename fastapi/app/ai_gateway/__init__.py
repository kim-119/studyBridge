"""StudyBridge AI Gateway — 모든 로컬 GPU 추론(Ollama :11434 텍스트 / :11435 비전)의 공통 입장 계층.

기능 플래그 AI_GATEWAY_ENABLED(기본 false). 꺼져 있으면 모든 진입점이 즉시 통과(기존 동작과 바이트 동일).

호출부 사용법(동기, 대부분의 호출부가 requests + to_thread):
    with gw.llm_slot(url=OLLAMA_BASE_URL, timeout=_timeout) as lease:
        payload = gw.normalize_ollama_payload(payload)
        resp = requests.post(...)
        lease and lease.backend_ok()

슬롯을 못 받으면 GatewayRejected 를 던진다 → 호출부는 기존 timeout/연결실패 경로로 매핑한다
(응답 계약 불변).
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Callable, Dict, Iterator, Optional
from urllib.parse import urlparse

from app.ai_gateway.breaker import breaker, reset_all as _reset_breakers, snapshot_all as breakers_snapshot
from app.ai_gateway.budget import budget
from app.ai_gateway.context import current_class, current_fair_key, current_group_key, workload
from app.ai_gateway.gpu_guard import GpuGuard
from app.ai_gateway.policy import WorkloadClass, all_policies, parse_class, policy_for
from app.ai_gateway.scheduler import GatewayRejected, Lease, Scheduler

logger = logging.getLogger(__name__)

TEXT = "ollama_text"
VISION = "ollama_vision"

__all__ = ["GatewayRejected", "Lease", "WorkloadClass", "enabled", "llm_slot", "async_llm_slot",
           "normalize_ollama_payload", "backend_for_url", "workload", "status", "get_scheduler",
           "openai_allowed", "record_openai_usage", "reset_for_tests"]


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def enabled() -> bool:
    return _flag("AI_GATEWAY_ENABLED", "false")


def _text_url() -> str:
    return (os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")


def _vision_url() -> str:
    return (os.getenv("VISION_OLLAMA_BASE_URL") or "http://127.0.0.1:11435").rstrip("/")


def _hostport(url: str):
    u = urlparse(url if "://" in url else f"http://{url}")
    host = (u.hostname or "").lower()
    if host in ("localhost", "0.0.0.0", "::1"):
        host = "127.0.0.1"
    return host, u.port or (443 if u.scheme == "https" else 80)


def backend_for_url(url: Optional[str]) -> str:
    if url and _hostport(url) == _hostport(_vision_url()):
        return VISION
    return TEXT


_sched: Optional[Scheduler] = None
_sched_lock = threading.Lock()


def _on_backend_result(backend: str, ok: bool) -> None:
    b = breaker(backend)
    b.record_success() if ok else b.record_failure()


def get_scheduler() -> Scheduler:
    global _sched
    with _sched_lock:
        if _sched is None:
            guard = GpuGuard()
            guard.register(TEXT, _text_url(), int(os.getenv("AI_GW_TEXT_FOOTPRINT_MIB", "10600")), protected=True)
            guard.register(VISION, _vision_url(), int(os.getenv("AI_GW_VISION_FOOTPRINT_MIB", "4800")))
            s = Scheduler(guard=guard, on_backend_result=_on_backend_result)
            # 텍스트 슬롯 = 시스템 Ollama 의 OLLAMA_NUM_PARALLEL(현재 1). 둘을 반드시 같이 바꾼다.
            s.configure_backend(TEXT, int(os.getenv("AI_GW_TEXT_SLOTS", "1")))
            s.configure_backend(VISION, int(os.getenv("AI_GW_VISION_SLOTS", "1")))
            # 첫 요청이 텔레메트리 첫 샘플 전에 판정되면 '불명'으로 비전이 거부된다(실측 1회) → 생성 시 바로 읽기 시작한다.
            # 이벤트 루프(비전 async 경로)에서 처음 불릴 수 있으므로 I/O 는 백그라운드 스레드에서 한다(리뷰 지적).
            # 첫 샘플 전 비전 신규 적재는 '불명'으로 보류됐다가 ticker 가 0.5초 안에 다시 판정한다.
            threading.Thread(target=lambda: guard.refresh(force=True), name="ai-gw-telemetry0", daemon=True).start()
            _sched = s
        return _sched


def reset_for_tests(scheduler: Optional[Scheduler] = None) -> None:
    global _sched
    with _sched_lock:
        if _sched is not None:
            _sched.stop()
        _sched = scheduler
    _reset_breakers()


def _resolve(wclass, backend: str) -> WorkloadClass:
    if wclass is not None:
        return parse_class(wclass)
    c = current_class()
    if backend == VISION and c not in (WorkloadClass.VISION, WorkloadClass.DOCUMENT_ANALYSIS):
        return WorkloadClass.VISION
    return c


def _check_breaker(backend: str, cls: WorkloadClass) -> None:
    if _flag("AI_GW_BREAKER", "true") and not breaker(backend).allow():
        raise GatewayRejected("CIRCUIT_OPEN", f"{backend} circuit open", retry_after=10, wclass=cls, backend=backend)


_internal_errors = 0


def _internal_error(where: str, e: BaseException) -> None:
    """게이트웨이 자체 결함은 추론 장애로 번지지 않게 fail-open(슬롯 없이 통과)한다."""
    global _internal_errors
    _internal_errors += 1
    logger.error("[AI_GW] internal error in %s (%s) — fail-open, request proceeds without slot",
                 where, type(e).__name__)


@contextmanager
def llm_slot(*, url: Optional[str] = None, backend: Optional[str] = None, wclass=None,
             timeout: Optional[float] = None, cancel_check: Optional[Callable[[], bool]] = None,
             fair_key: Optional[str] = None) -> Iterator[Optional[Lease]]:
    """동기 호출부용. 게이트웨이가 꺼져 있으면 None 을 yield 하고 아무것도 하지 않는다.

    GatewayRejected(대기열 포화/대기 초과/브레이커/취소/종료)만 호출부로 올라가고, 그 밖의 게이트웨이 내부
    예외는 fail-open 으로 처리한다(lease=None).
    """
    if not enabled():
        yield None
        return
    b = backend or backend_for_url(url)
    try:
        cls = _resolve(wclass, b)
        _check_breaker(b, cls)
    except GatewayRejected:
        raise
    except Exception as e:  # noqa: BLE001
        _internal_error("llm_slot", e)
        yield None
        return
    try:
        lease = get_scheduler().acquire_sync(b, cls, fair_key or current_fair_key(),
                                            timeout=timeout, cancel_check=cancel_check,
                                            group=current_group_key())
    except GatewayRejected:
        breaker(b).release_probe()
        raise
    except Exception as e:  # noqa: BLE001
        breaker(b).release_probe()
        _internal_error("llm_slot", e)
        yield None
        return
    try:
        with lease:
            yield lease
    finally:
        if not lease.reported:
            breaker(b).release_probe()


@asynccontextmanager
async def async_llm_slot(*, url: Optional[str] = None, backend: Optional[str] = None, wclass=None,
                         timeout: Optional[float] = None, fair_key: Optional[str] = None
                         ) -> AsyncIterator[Optional[Lease]]:
    if not enabled():
        yield None
        return
    b = backend or backend_for_url(url)
    try:
        cls = _resolve(wclass, b)
        _check_breaker(b, cls)
    except GatewayRejected:
        raise
    except Exception as e:  # noqa: BLE001
        _internal_error("async_llm_slot", e)
        yield None
        return
    try:
        lease = await get_scheduler().acquire_async(b, cls, fair_key or current_fair_key(), timeout=timeout,
                                                    group=current_group_key())
    except (GatewayRejected, asyncio.CancelledError):
        breaker(b).release_probe()
        raise
    except Exception as e:  # noqa: BLE001
        breaker(b).release_probe()
        _internal_error("async_llm_slot", e)
        yield None
        return
    try:
        with lease:
            yield lease
    finally:
        if not lease.reported:
            breaker(b).release_probe()


def _canonical_text_model() -> str:
    return (os.getenv("OLLAMA_MODEL") or "qwen3:14b").strip()


def normalize_ollama_payload(payload: Dict[str, Any], *, url: Optional[str] = None,
                             wclass=None) -> Dict[str, Any]:
    """재적재를 유발하는 옵션 편차를 없앤다(게이트웨이 켜졌을 때만, 원본 dict 를 직접 수정).

    * keep_alive 누락 → AI_GW_TEXT_KEEP_ALIVE(없으면 OLLAMA_KEEP_ALIVE). 누락 호출 1건이 상주 시간을
      Ollama 기본 5m 으로 되돌려 콜드 적재를 만든다(운영 .env 30m 인데 우회 호출부 4곳이 미전송).
    * num_ctx 가 표준값보다 작으면 표준값으로 올린다(낮추지는 않음 → 절단 위험 없음). 값이 다르면
      Ollama 러너가 재적재된다(실측 1.3~1.7s, 큰 쪽 적재 시 부분 CPU offload).
    * 클래스 max_tokens 가 설정돼 있으면 num_predict 상한 적용(기본 0 = 미적용).
    """
    if not enabled() or not _flag("AI_GW_NORMALIZE_OPTIONS", "true") or not isinstance(payload, dict):
        return payload
    b = backend_for_url(url) if url else TEXT
    if b != TEXT:
        return payload
    model = str(payload.get("model") or "")
    if model != _canonical_text_model():
        return payload
    ka = (os.getenv("AI_GW_TEXT_KEEP_ALIVE") or os.getenv("OLLAMA_KEEP_ALIVE") or "").strip()
    if ka and "keep_alive" not in payload:
        payload["keep_alive"] = ka
    opts = payload.setdefault("options", {})
    try:
        from app.services.ollama_client import _shared_num_ctx
        canon = int(_shared_num_ctx())
        cur = int(opts.get("num_ctx") or 0)
        if cur < canon:
            opts["num_ctx"] = canon
    except Exception:  # noqa: BLE001
        pass
    pol = policy_for(_resolve(wclass, b))
    if pol.max_tokens and int(opts.get("num_predict") or 0) > pol.max_tokens:
        opts["num_predict"] = pol.max_tokens
    return payload


# ── OpenAI ────────────────────────────────────────────────────────────────
def openai_allowed(estimated_tokens: int = 0) -> bool:
    """게이트웨이가 켜져 있으면 breaker + 일 토큰 예산을 확인한다."""
    if not enabled():
        return True
    if _flag("AI_GW_BREAKER", "true") and not breaker("openai").allow():
        return False
    return budget.allow(estimated_tokens)


def record_openai_usage(model: str, usage: Any, ok: bool = True) -> None:
    if not enabled():
        return
    _on_backend_result("openai", ok)
    if usage is None:
        return
    try:
        pt = getattr(usage, "prompt_tokens", None)
        ct = getattr(usage, "completion_tokens", None)
        if pt is None and isinstance(usage, dict):
            pt, ct = usage.get("prompt_tokens"), usage.get("completion_tokens")
        budget.record(model or "", int(pt or 0), int(ct or 0))
    except Exception:  # noqa: BLE001
        pass


def status() -> Dict[str, Any]:
    out: Dict[str, Any] = {"enabled": enabled(),
                           "policies": {c.value: p.__dict__ for c, p in all_policies().items()},
                           "breakers": breakers_snapshot(), "openaiBudget": budget.snapshot()}
    out["internalErrors"] = _internal_errors
    if enabled():
        s = get_scheduler()
        out["scheduler"] = s.snapshot()
        out["gpu"] = s.guard.snapshot() if s.guard is not None else None
    return out
