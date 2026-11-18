"""OpenAI 토큰/비용 예산.

일 단위(KST) 토큰 상한을 넘으면 새 OpenAI 호출을 거부한다 → 호출부의 기존 fallback(Ollama/문구)으로
넘어간다. 카운터는 Redis 가 있으면 INCRBY(멀티워커/재시작에도 유지), 없거나 실패하면 프로세스 로컬.
Redis 는 EC2 터널 경유라 짧은 timeout 으로만 쓰고, 실패해도 요청 경로를 막지 않는다(fail-open to local).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
_KST = timezone(timedelta(hours=9))

# USD per 1M tokens (input, output). 2026-10 기준 공개 단가 — env 로 덮어쓴다.
_PRICE = {"gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.00)}


def _today() -> str:
    return datetime.now(_KST).strftime("%Y%m%d")


class TokenBudget:
    def __init__(self) -> None:
        self.daily_cap = int(os.getenv("AI_GW_OPENAI_DAILY_TOKEN_CAP", "0") or 0)   # 0 = 상한 없음(관측만)
        self._lock = threading.Lock()
        self._day = _today()
        self.used = 0
        self.calls = 0
        self.denied = 0
        self.cost_usd = 0.0
        self._redis = None
        self._redis_checked = 0.0

    def _r(self):
        if os.getenv("AI_GW_BUDGET_REDIS", "false").strip().lower() not in ("1", "true", "yes"):
            return None
        now = time.monotonic()
        if self._redis is None and now - self._redis_checked > 60:
            self._redis_checked = now
            try:
                import redis  # type: ignore
                url = os.getenv("REDIS_URL", "")
                if url:
                    self._redis = redis.Redis.from_url(url, socket_timeout=0.2, socket_connect_timeout=0.2)
                    self._redis.ping()
            except Exception as e:  # noqa: BLE001
                logger.info("[AI_GW] budget redis unavailable → local counter (%s)", type(e).__name__)
                self._redis = None
        return self._redis

    def _roll(self) -> None:
        d = _today()
        if d != self._day:
            self._day, self.used, self.calls, self.denied, self.cost_usd = d, 0, 0, 0, 0.0

    def _shared_used(self) -> int:
        r = self._r()
        if r is None:
            return self.used
        try:
            v = r.get(f"ai_gw:openai_tokens:{self._day}")
            return int(v or 0)
        except Exception:  # noqa: BLE001
            self._redis = None
            return self.used

    def allow(self, estimated_tokens: int = 0) -> bool:
        with self._lock:
            self._roll()
            if self.daily_cap <= 0:
                return True
            if self._shared_used() + max(0, estimated_tokens) > self.daily_cap:
                self.denied += 1
                return False
            return True

    def record(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        total = max(0, int(prompt_tokens or 0)) + max(0, int(completion_tokens or 0))
        pin, pout = _PRICE.get(model, _PRICE["gpt-4o-mini"])
        with self._lock:
            self._roll()
            self.used += total
            self.calls += 1
            self.cost_usd += (prompt_tokens or 0) / 1e6 * pin + (completion_tokens or 0) / 1e6 * pout
        r = self._r()
        if r is not None:
            try:
                key = f"ai_gw:openai_tokens:{self._day}"
                r.incrby(key, total)
                r.expire(key, 3 * 86400)
            except Exception:  # noqa: BLE001
                self._redis = None

    def snapshot(self) -> dict:
        with self._lock:
            self._roll()
            return {"day": self._day, "dailyCap": self.daily_cap, "usedTokens": self.used, "calls": self.calls,
                    "denied": self.denied, "estCostUsd": round(self.cost_usd, 4),
                    "shared": self._redis is not None}


budget = TokenBudget()
