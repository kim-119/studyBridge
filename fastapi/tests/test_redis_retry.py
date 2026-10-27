"""Redis 1회 실패 후 영구 비활성화 회귀 테스트(외부 I/O 없음 — redis 클라이언트를 가짜로 바꾼다).

2026-10-28: ai07 Redis 터널이 20일 동안 끊겨 있던 사이 FastAPI 가 기동되면서 대화 기억/청크 캐시가 영구 비활성화됐다.
터널을 복구해도 프로세스 재시작 전까지 돌아오지 않던 문제를 막는다.
"""
from __future__ import annotations

import asyncio
import time

import pytest


class _AsyncFake:
    def __init__(self, state):
        self.state = state

    async def ping(self):
        self.state["pings"] += 1
        if self.state["down"]:
            raise ConnectionError("tunnel down")
        return True


class _SyncFake:
    def __init__(self, state):
        self.state = state

    def ping(self):
        self.state["pings"] += 1
        if self.state["down"]:
            raise ConnectionError("tunnel down")
        return True


def test_multi_chat_memory_reconnects_after_cooldown(monkeypatch):
    import redis.asyncio as redis_async
    from app.services import multi_chat_redis_memory as m
    state = {"down": True, "pings": 0}
    monkeypatch.setattr(redis_async, "from_url", lambda *a, **k: _AsyncFake(state))
    monkeypatch.setattr(m, "MEMORY_ENABLED", True)
    monkeypatch.setattr(m, "_redis", None)
    monkeypatch.setattr(m, "_redis_tried", False)
    monkeypatch.setattr(m, "_redis_retry_at", 0.0)
    monkeypatch.setattr(m, "_RETRY_SECONDS", 0.1)

    async def scenario():
        assert await m._get_redis() is None                  # 터널 끊김
        assert await m._get_redis() is None                  # 쿨다운 중에는 재시도하지 않는다
        assert state["pings"] == 1
        state["down"] = False                                # 터널 복구
        await asyncio.sleep(0.12)
        client = await m._get_redis()
        assert client is not None and state["pings"] == 2    # 재시작 없이 복구
        assert await m._get_redis() is client                # 이후 재사용
    asyncio.run(scenario())


def test_chunk_cache_reconnects_after_cooldown(monkeypatch):
    import redis
    from app.services import chunk_cache as cc
    state = {"down": True, "pings": 0}
    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(lambda *a, **k: _SyncFake(state)))
    monkeypatch.setattr(cc, "CACHE_BACKEND", "redis")
    monkeypatch.setattr(cc, "_redis_client", None)
    monkeypatch.setattr(cc, "_redis_tried", False)
    monkeypatch.setattr(cc, "_redis_retry_at", 0.0)
    monkeypatch.setenv("REDIS_RETRY_SECONDS", "0.1")
    assert cc._get_redis() is None
    assert cc._get_redis() is None and state["pings"] == 1
    state["down"] = False
    time.sleep(0.12)
    client = cc._get_redis()
    assert client is not None and cc._get_redis() is client and state["pings"] == 2
