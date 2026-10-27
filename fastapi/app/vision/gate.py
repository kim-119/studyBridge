"""Vision 추론 동시성 게이트 (프로세스 전역, 단일 uvicorn 워커 기준).

받아들이는 요청 수와 GPU 에서 실제로 동시에 돌리는 추론 수를 분리한다.
  * running  ≤ max_concurrency   (기본 1: 16GB 단일 GPU 에서 qwen3:14b 와 공유)
  * waiting  ≤ max_queue         (초과 → 429 VISION_QUEUE_FULL)
  * 그룹당 in-flight ≤ max_per_group (초과 → 429 VISION_GROUP_LIMIT)
  * 대기 시간 > queue_timeout    (→ 503 VISION_QUEUE_TIMEOUT)
  * 같은 requestId 가 진행 중이거나 최근 성공(TTL) → 409 VISION_DUPLICATE_REQUEST
"""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.vision.config import VisionSettings
from app.vision.errors import vision_error

_DUP_MAX_ENTRIES = 10_000


class VisionGate:
    def __init__(self) -> None:
        self._sem: asyncio.Semaphore | None = None
        self._sem_size = 0
        self.running = 0
        self.waiting = 0
        self.max_waiting_seen = 0
        self.max_running_seen = 0
        self._inflight_ids: set[str] = set()
        self._group_inflight: dict[str, int] = {}
        self._completed: OrderedDict[str, float] = OrderedDict()
        self.draining = False

    def _semaphore(self, size: int) -> asyncio.Semaphore:
        # 설정 변경(테스트 포함) 시 유휴 상태에서만 재생성
        if self._sem is None or (self._sem_size != size and self.running == 0 and self.waiting == 0):
            self._sem = asyncio.Semaphore(size)
            self._sem_size = size
        return self._sem

    def _prune_completed(self, ttl: float) -> None:
        now = time.monotonic()
        while self._completed:
            rid, ts = next(iter(self._completed.items()))
            if now - ts <= ttl and len(self._completed) <= _DUP_MAX_ENTRIES:
                break
            self._completed.popitem(last=False)

    def mark_completed(self, request_id: str, settings: VisionSettings) -> None:
        if settings.duplicate_ttl_s <= 0:
            return
        self._completed[request_id] = time.monotonic()
        self._completed.move_to_end(request_id)
        self._prune_completed(settings.duplicate_ttl_s)

    def snapshot(self) -> dict:
        return {
            "running": self.running,
            "waiting": self.waiting,
            "maxRunningSeen": self.max_running_seen,
            "maxWaitingSeen": self.max_waiting_seen,
            "draining": self.draining,
        }

    @asynccontextmanager
    async def admit(self, request_id: str, group_id: str, settings: VisionSettings) -> AsyncIterator[float]:
        """입장 → 슬롯 획득까지 대기 → yield(대기ms). 어떤 경로로 끝나도 카운터를 되돌린다."""
        if self.draining:
            raise vision_error("VISION_SHUTTING_DOWN", "서버가 종료 중입니다.", retry_after=5)
        self._prune_completed(settings.duplicate_ttl_s)
        if request_id in self._inflight_ids or request_id in self._completed:
            raise vision_error("VISION_DUPLICATE_REQUEST", "이미 처리 중이거나 처리된 requestId 입니다.")
        if self._group_inflight.get(group_id, 0) >= settings.max_per_group:
            raise vision_error("VISION_GROUP_LIMIT", "그룹의 동시 AI 분석 요청 한도를 초과했습니다.", retry_after=5)
        sem = self._semaphore(settings.max_concurrency)
        if self.running >= settings.max_concurrency and self.waiting >= settings.max_queue:
            raise vision_error("VISION_QUEUE_FULL", "AI 분석 대기열이 가득 찼습니다.", retry_after=10)

        self._inflight_ids.add(request_id)
        self._group_inflight[group_id] = self._group_inflight.get(group_id, 0) + 1
        t0 = time.monotonic()
        acquired = False
        self.waiting += 1
        self.max_waiting_seen = max(self.max_waiting_seen, self.waiting)
        try:
            try:
                await asyncio.wait_for(sem.acquire(), timeout=settings.queue_timeout_s)
                acquired = True
            except asyncio.TimeoutError:
                raise vision_error("VISION_QUEUE_TIMEOUT", "AI 분석 대기 시간이 초과되었습니다.", retry_after=10) from None
            finally:
                self.waiting -= 1
            if self.draining:
                raise vision_error("VISION_SHUTTING_DOWN", "서버가 종료 중입니다.", retry_after=5)
            self.running += 1
            self.max_running_seen = max(self.max_running_seen, self.running)
            try:
                yield (time.monotonic() - t0) * 1000.0
            finally:
                self.running -= 1
        finally:
            if acquired:
                sem.release()
            self._inflight_ids.discard(request_id)
            left = self._group_inflight.get(group_id, 1) - 1
            if left <= 0:
                self._group_inflight.pop(group_id, None)
            else:
                self._group_inflight[group_id] = left


gate = VisionGate()
