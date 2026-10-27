"""요청 단위 컨텍스트(작업 유형 + 공정성 키).

middleware 가 HTTP 요청 진입 시 설정하고, 내부 LLM 호출은 contextvars 로 상속받는다.
asyncio.to_thread / Starlette threadpool 은 contextvars 를 복사하므로 동기 호출부에서도 보인다.
멀티에이전트처럼 논리 요청 1개가 내부 호출 N개를 만드는 경우에도 같은 클래스/사용자로 묶인다.
"""
from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor as _TPE
from contextlib import contextmanager
from typing import Iterator, Optional

from app.ai_gateway.policy import WorkloadClass

_wclass: contextvars.ContextVar[Optional[WorkloadClass]] = contextvars.ContextVar("ai_gw_wclass", default=None)
_fair_key: contextvars.ContextVar[str] = contextvars.ContextVar("ai_gw_fair_key", default="anon")
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("ai_gw_request_id", default="")
_group_key: contextvars.ContextVar[str] = contextvars.ContextVar("ai_gw_group_key", default="")


def current_class(default: WorkloadClass = WorkloadClass.INTERACTIVE_CHAT) -> WorkloadClass:
    return _wclass.get() or default


def current_fair_key() -> str:
    return _fair_key.get()


def current_request_id() -> str:
    return _request_id.get()


def current_group_key() -> str:
    """그룹 단위 공정성 키. 그룹 식별자가 없으면 사용자 키(개인 사용자는 자기 자신이 한 그룹)."""
    return _group_key.get() or _fair_key.get()


def set_context(wclass: Optional[WorkloadClass], fair_key: Optional[str] = None,
                request_id: Optional[str] = None, group_key: Optional[str] = None) -> tuple:
    tokens = (_wclass.set(wclass),
              _fair_key.set(fair_key or "anon"),
              _request_id.set(request_id or ""),
              _group_key.set(group_key or ""))
    return tokens


def reset_context(tokens: tuple) -> None:
    for var, tok in zip((_wclass, _fair_key, _request_id, _group_key), tokens):
        try:
            var.reset(tok)
        except ValueError:
            pass


@contextmanager
def workload(wclass: WorkloadClass, fair_key: Optional[str] = None) -> Iterator[None]:
    """코드에서 명시적으로 작업 유형을 지정할 때(백그라운드 작업 등)."""
    tokens = set_context(wclass, fair_key or _fair_key.get(), _request_id.get(), _group_key.get())
    try:
        yield
    finally:
        reset_context(tokens)


def bind(fn, wclass: Optional[WorkloadClass] = None):
    """현재 게이트웨이 컨텍스트(작업 유형/공정성 키)를 다른 스레드에서 실행될 fn 에 묶는다.

    concurrent.futures.ThreadPoolExecutor 는 contextvars 를 복사하지 않아(asyncio.to_thread 와 다름) 멀티에이전트
    병렬 단계의 LLM 호출이 INTERACTIVE_CHAT/anon 으로 분류됐다(2026-10-28 리뷰 재현). 게이트웨이 변수 4개만 넘기고
    다른 contextvars 는 건드리지 않는다(기존 동작 보존).
    """
    snap = (wclass or _wclass.get(), _fair_key.get(), _request_id.get(), _group_key.get())

    def run(*a, **k):
        tokens = set_context(*snap)
        try:
            return fn(*a, **k)
        finally:
            reset_context(tokens)
    return run


class ContextThreadPoolExecutor(_TPE):
    """submit/map 시점의 게이트웨이 컨텍스트를 작업 스레드로 전달하는 ThreadPoolExecutor(그 외 동작 동일)."""

    def __init__(self, *args, wclass: Optional[WorkloadClass] = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._ai_gw_wclass = wclass

    def submit(self, fn, /, *args, **kwargs):
        return super().submit(bind(fn, self._ai_gw_wclass), *args, **kwargs)
