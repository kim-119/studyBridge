"""요청 런타임 컨텍스트(contextvar).

compat 의 async 제너레이터가 set 하면 asyncio.to_thread 가 컨텍스트를 복사하므로
동기 파이프라인/모드 엔진 어디서든 같은 cancel token·budget·trace 에 접근한다.
"""
from __future__ import annotations

import contextvars
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.studymate.budget import TurnBudget
from app.studymate.cancellation import CancelToken

_CTX: contextvars.ContextVar[Optional["RequestRuntime"]] = contextvars.ContextVar("studymate_runtime", default=None)


@dataclass
class RequestRuntime:
    request_id: str
    turn_id: str
    cancel: CancelToken = field(default_factory=CancelToken)
    budget: Optional[TurnBudget] = None
    llm_calls: List[Dict[str, Any]] = field(default_factory=list)
    traces: List[Dict[str, Any]] = field(default_factory=list)
    degraded_notes: List[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_llm(self, task: str, res: Any) -> None:
        with self._lock:
            self.llm_calls.append({
                "task": task, "promptEvalCount": getattr(res, "prompt_eval_count", None),
                "evalCount": getattr(res, "eval_count", None), "totalMs": getattr(res, "total_ms", None),
                "ttftMs": getattr(res, "ttft_ms", None), "numCtx": getattr(res, "num_ctx", None),
                "contextSaturated": getattr(res, "context_saturated", False),
            })

    def add_trace(self, trace_dict: Dict[str, Any]) -> None:
        with self._lock:
            self.traces.append(trace_dict)

    def note(self, text: str) -> None:
        with self._lock:
            if text not in self.degraded_notes:
                self.degraded_notes.append(text)


def new_runtime(request_id: Optional[str] = None, turn_id: Optional[str] = None) -> RequestRuntime:
    return RequestRuntime(request_id=request_id or f"req_{uuid.uuid4().hex[:12]}",
                          turn_id=turn_id or f"turn_{uuid.uuid4().hex[:16]}")


def set_current(rt: Optional[RequestRuntime]):
    return _CTX.set(rt)


def reset(token) -> None:
    try:
        _CTX.reset(token)
    except Exception:  # 다른 컨텍스트에서 reset 하면 ValueError — 무해
        _CTX.set(None)


def current() -> Optional[RequestRuntime]:
    return _CTX.get()
