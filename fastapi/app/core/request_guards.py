"""라우터 단위 요청 가드: 본문 크기 제한(본문을 읽기 전에), 토큰버킷 rate limit, 멱등 캐시.

본문 제한은 FastAPI 가 dependency 보다 먼저 body 를 읽기 때문에 dependency 로는 막을 수 없다 →
APIRoute 하위 클래스(limited_route_class)로 receive 를 감싸 Content-Length/스트리밍 바이트를 센다.
전역 미들웨어를 추가하지 않으므로 다른 운영 라우트에는 영향이 없다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional, Tuple

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute


class _BodyTooLarge(Exception):
    pass


def limited_route_class(max_bytes: int):
    class LimitedBodyRoute(APIRoute):
        def get_route_handler(self) -> Callable:
            original = super().get_route_handler()

            async def handler(request: Request):
                if request.method in ("POST", "PUT", "PATCH"):
                    cl = request.headers.get("content-length")
                    try:
                        if cl is not None and int(cl) > max_bytes:
                            return _too_large(max_bytes)
                    except ValueError:
                        return JSONResponse(status_code=400, content={"detail": {"errorCode": "BAD_CONTENT_LENGTH"}})
                    receive = request._receive
                    seen = {"n": 0}

                    async def limited_receive():
                        msg = await receive()
                        if msg.get("type") == "http.request":
                            seen["n"] += len(msg.get("body") or b"")
                            if seen["n"] > max_bytes:
                                raise _BodyTooLarge()
                        return msg

                    request._receive = limited_receive
                try:
                    return await original(request)
                except _BodyTooLarge:
                    return _too_large(max_bytes)

            return handler

    return LimitedBodyRoute


def _too_large(max_bytes: int) -> JSONResponse:
    return JSONResponse(status_code=413, content={"detail": {"errorCode": "PAYLOAD_TOO_LARGE", "maxBytes": max_bytes}})


class RateLimiter:
    """프로세스 내 토큰버킷. key 별 capacity 개, 초당 refill 개 회복."""

    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        self.capacity, self.refill = capacity, refill_per_sec
        self._b: Dict[str, Tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._b.get(key, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill)
            if tokens < 1.0:
                self._b[key] = (tokens, now)
                return False
            self._b[key] = (tokens - 1.0, now)
            if len(self._b) > 10000:
                self._b.pop(next(iter(self._b)))
            return True

    def check(self, key: str) -> None:
        if not self.allow(key):
            raise HTTPException(status_code=429, detail={"errorCode": "RATE_LIMITED"}, headers={"Retry-After": "5"})

    def reset(self) -> None:
        with self._lock:
            self._b.clear()


class IdempotencyCache:
    """requestId → (본문 해시, 응답). 같은 id + 같은 본문 = 재생, 같은 id + 다른 본문 = 409."""

    def __init__(self, max_items: int = 2048, ttl_seconds: float = 600) -> None:
        self.max_items, self.ttl = max_items, ttl_seconds
        self._d: "OrderedDict[str, Tuple[float, str, Any]]" = OrderedDict()
        self._inflight: Dict[str, asyncio.Event] = {}
        self._lock = threading.Lock()

    @staticmethod
    def body_hash(payload: Any) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

    def lookup(self, request_id: str, body_hash: str) -> Optional[Any]:
        now = time.time()
        with self._lock:
            hit = self._d.get(request_id)
            if hit is None or now - hit[0] > self.ttl:
                self._d.pop(request_id, None)
                return None
            if hit[1] != body_hash:
                raise HTTPException(status_code=409, detail={"errorCode": "IDEMPOTENCY_CONFLICT"})
            return hit[2]

    def store(self, request_id: str, body_hash: str, response: Any) -> None:
        with self._lock:
            self._d[request_id] = (time.time(), body_hash, response)
            self._d.move_to_end(request_id)
            while len(self._d) > self.max_items:
                self._d.popitem(last=False)

    def reset(self) -> None:
        with self._lock:
            self._d.clear()
