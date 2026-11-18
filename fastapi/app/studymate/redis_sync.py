"""동기 Redis 클라이언트(파이프라인 스레드용) — 지수 백오프 재연결.

1회 실패로 영구 비활성화하지 않는다(2026-09-16 감사: multi_chat_redis_memory 의 _redis_tried 고정).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("studybridge.studymate.redis")

_CLIENT: Any = None
_LOCK = threading.Lock()
_FAILS = 0
_NEXT_TRY = 0.0
_MAX_BACKOFF = 120.0


def url() -> str:
    return os.getenv("MULTI_CHAT_REDIS_URL") or os.getenv("REDIS_URL") or "redis://127.0.0.1:16379/0"


def backoff_state() -> dict:
    return {"fails": _FAILS, "nextTryIn": max(0.0, round(_NEXT_TRY - time.time(), 1)), "connected": _CLIENT is not None}


def mark_failure(exc: Optional[BaseException] = None) -> None:
    global _CLIENT, _FAILS, _NEXT_TRY
    with _LOCK:
        _CLIENT = None
        _FAILS += 1
        delay = min(_MAX_BACKOFF, 1.0 * (2 ** min(_FAILS, 7)))
        _NEXT_TRY = time.time() + delay
    logger.warning("[REDIS] degraded fails=%d next_retry_in=%.0fs err=%s", _FAILS, delay,
                   type(exc).__name__ if exc else "-")


def enabled() -> bool:
    return (os.getenv("STUDYMATE_REDIS", "on") or "on").strip().lower() not in ("off", "0", "false", "no")


def client():
    global _CLIENT, _FAILS
    if not enabled():
        return None
    if _CLIENT is not None:
        return _CLIENT
    if time.time() < _NEXT_TRY:
        return None
    with _LOCK:
        if _CLIENT is not None:
            return _CLIENT
        try:
            import redis
            c = redis.Redis.from_url(url(), decode_responses=True, socket_connect_timeout=1.5, socket_timeout=1.5)
            c.ping()
            _CLIENT = c
            if _FAILS:
                logger.info("[REDIS] reconnected after %d failures", _FAILS)
            _FAILS = 0
            return _CLIENT
        except Exception as exc:  # noqa: BLE001 — 실패는 백오프로 기록
            err = exc
        else:  # pragma: no cover
            err = None
    mark_failure(err)
    return None
