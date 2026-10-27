"""백엔드별 Circuit Breaker (closed → open → half_open → closed).

연결 실패/5xx/OOM 류만 실패로 센다. 큐 대기로 생긴 timeout 이나 4xx(모델 없음 등)는
백엔드 장애가 아니므로 세지 않는다 — 부하 때문에 회로가 열려 전 기능이 막히는 것을 막는다.
half-open 탐침이 성공/실패 어느 쪽으로도 보고되지 않고 끝나면(읽기 timeout, 대기 거부, 취소) 탐침을 반납하고,
보고가 끝내 없으면 probe_timeout_s 뒤 새 탐침을 허용한다 — 탐침 1건이 회로를 영구히 붙잡지 않게(2026-10-28 리뷰).
"""
from __future__ import annotations

import os
import threading
import time
from typing import Dict


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class CircuitBreaker:
    def __init__(self, name: str, *, threshold: int | None = None, window_s: float | None = None,
                 cooldown_s: float | None = None) -> None:
        self.name = name
        self.threshold = int(threshold if threshold is not None else _f("AI_GW_BREAKER_THRESHOLD", 5))
        self.window_s = float(window_s if window_s is not None else _f("AI_GW_BREAKER_WINDOW_S", 30))
        self.cooldown_s = float(cooldown_s if cooldown_s is not None else _f("AI_GW_BREAKER_COOLDOWN_S", 10))
        self._lock = threading.Lock()
        self._fails: list[float] = []
        self._opened_at = 0.0
        self._half_open_probe = False
        self._probe_at = 0.0
        self.probe_timeout_s = _f("AI_GW_BREAKER_PROBE_TIMEOUT_S", 30)
        self.state = "closed"
        self.open_count = 0

    def allow(self) -> bool:
        with self._lock:
            if self.state == "closed":
                return True
            now = time.monotonic()
            if self.state == "open" and now - self._opened_at >= self.cooldown_s:
                self.state = "half_open"
                self._half_open_probe = False
            if self.state == "half_open" and (not self._half_open_probe
                                               or now - self._probe_at >= self.probe_timeout_s):
                self._half_open_probe = True     # 탐침 요청 1건만 통과
                self._probe_at = now
                return True
            return False

    def release_probe(self) -> None:
        """탐침이 결과 없이 끝났다(대기 거부·읽기 timeout·취소) → 다음 요청이 탐침이 될 수 있게 반납."""
        with self._lock:
            if self.state == "half_open":
                self._half_open_probe = False

    def record_success(self) -> None:
        with self._lock:
            self._fails.clear()
            self.state = "closed"
            self._half_open_probe = False

    def record_failure(self) -> None:
        with self._lock:
            now = time.monotonic()
            if self.state == "half_open":
                self._trip(now)
                return
            self._fails = [t for t in self._fails if now - t <= self.window_s]
            self._fails.append(now)
            if len(self._fails) >= self.threshold:
                self._trip(now)

    def _trip(self, now: float) -> None:
        self.state = "open"
        self._opened_at = now
        self._half_open_probe = False
        self._fails.clear()
        self.open_count += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self.state, "recentFailures": len(self._fails), "openCount": self.open_count}


_breakers: Dict[str, CircuitBreaker] = {}
_reg_lock = threading.Lock()


def breaker(name: str) -> CircuitBreaker:
    with _reg_lock:
        b = _breakers.get(name)
        if b is None:
            b = _breakers[name] = CircuitBreaker(name)
        return b


def snapshot_all() -> dict:
    with _reg_lock:
        items = list(_breakers.items())
    return {k: v.snapshot() for k, v in items}


def reset_all() -> None:
    with _reg_lock:
        _breakers.clear()
