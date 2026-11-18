"""Vision 동시성 게이트 (프로세스 전역, 단일 uvicorn 워커 기준).

요청 한 건은 두 단계를 거치고, 단계마다 슬롯이 따로 있다.
  admit()       요청 전체: 같은 requestId 진행 중·최근 성공(TTL) → 409, 그룹당 in-flight ≤ max_per_group → 429
  gpu_slot()    VLM 화면 판독만: running ≤ max_concurrency(기본 1), waiting ≤ max_queue(초과 429),
                대기 > queue_timeout → 503. 판독이 끝나면 즉시 반환해 OpenAI 호출 동안 GPU 를 잡지 않는다.
  answer_slot() OpenAI 최종 답변: 동시 ≤ answer_max_concurrency, 대기 > answer_queue_timeout → 503.
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


class _Slots:
    """설정 크기의 세마포어 + 대기/실행 카운터. 크기 변경(테스트 포함)은 유휴 상태에서만 반영한다."""

    def __init__(self) -> None:
        self._sem: asyncio.Semaphore | None = None
        self._size = 0
        self.running = 0
        self.waiting = 0
        self.max_running_seen = 0
        self.max_waiting_seen = 0

    def semaphore(self, size: int) -> asyncio.Semaphore:
        if self._sem is None or (self._size != size and self.running == 0 and self.waiting == 0):
            self._sem = asyncio.Semaphore(size)
            self._size = size
        return self._sem

    @asynccontextmanager
    async def hold(self, size: int, timeout: float, on_timeout) -> AsyncIterator[float]:
        sem = self.semaphore(size)
        t0 = time.monotonic()
        acquired = False
        self.waiting += 1
        self.max_waiting_seen = max(self.max_waiting_seen, self.waiting)
        try:
            try:
                await asyncio.wait_for(sem.acquire(), timeout=max(0.01, timeout))
                acquired = True
            except asyncio.TimeoutError:
                raise on_timeout() from None
            finally:
                self.waiting -= 1
            self.running += 1
            self.max_running_seen = max(self.max_running_seen, self.running)
            try:
                yield (time.monotonic() - t0) * 1000.0
            finally:
                self.running -= 1
        finally:
            if acquired:
                sem.release()


class VisionGate:
    def __init__(self) -> None:
        self._gpu = _Slots()
        self._answer = _Slots()
        self._inflight_ids: set[str] = set()
        self._group_inflight: dict[str, int] = {}
        self._completed: OrderedDict[str, float] = OrderedDict()
        self.draining = False

    # 기존 계약(테스트·health)의 이름: GPU 판독 단계 카운터
    @property
    def running(self) -> int:
        return self._gpu.running

    @property
    def waiting(self) -> int:
        return self._gpu.waiting

    @property
    def max_running_seen(self) -> int:
        return self._gpu.max_running_seen

    @property
    def max_waiting_seen(self) -> int:
        return self._gpu.max_waiting_seen

    @property
    def answer_running(self) -> int:
        return self._answer.running

    @property
    def answer_waiting(self) -> int:
        return self._answer.waiting

    @property
    def inflight(self) -> int:
        return len(self._inflight_ids)

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
            "running": self._gpu.running,
            "waiting": self._gpu.waiting,
            "maxRunningSeen": self._gpu.max_running_seen,
            "maxWaitingSeen": self._gpu.max_waiting_seen,
            "answerRunning": self._answer.running,
            "answerWaiting": self._answer.waiting,
            "maxAnswerRunningSeen": self._answer.max_running_seen,
            "inflight": len(self._inflight_ids),
            "draining": self.draining,
        }

    @asynccontextmanager
    async def admit(self, request_id: str, group_id: str, settings: VisionSettings) -> AsyncIterator[None]:
        """요청 전체(판독+답변) 입장. 어떤 경로로 끝나도 id·그룹 카운터를 되돌린다."""
        if self.draining:
            raise vision_error("VISION_SHUTTING_DOWN", "서버가 종료 중입니다.", retry_after=5)
        self._prune_completed(settings.duplicate_ttl_s)
        if request_id in self._inflight_ids or request_id in self._completed:
            raise vision_error("VISION_DUPLICATE_REQUEST", "이미 처리 중이거나 처리된 requestId 입니다.")
        if self._group_inflight.get(group_id, 0) >= settings.max_per_group:
            raise vision_error("VISION_GROUP_LIMIT", "그룹의 동시 AI 분석 요청 한도를 초과했습니다.", retry_after=5)
        self._inflight_ids.add(request_id)
        self._group_inflight[group_id] = self._group_inflight.get(group_id, 0) + 1
        try:
            yield
        finally:
            self._inflight_ids.discard(request_id)
            left = self._group_inflight.get(group_id, 1) - 1
            if left <= 0:
                self._group_inflight.pop(group_id, None)
            else:
                self._group_inflight[group_id] = left

    @asynccontextmanager
    async def gpu_slot(self, settings: VisionSettings, timeout: float | None = None) -> AsyncIterator[float]:
        """VLM 판독 슬롯 → yield(대기ms)."""
        if self._gpu.running >= settings.max_concurrency and self._gpu.waiting >= settings.max_queue:
            raise vision_error("VISION_QUEUE_FULL", "AI 분석 대기열이 가득 찼습니다.", retry_after=10)
        t = settings.queue_timeout_s if timeout is None else min(settings.queue_timeout_s, timeout)
        async with self._gpu.hold(settings.max_concurrency, t, lambda: vision_error(
                "VISION_QUEUE_TIMEOUT", "AI 분석 대기 시간이 초과되었습니다.", retry_after=10)) as waited:
            if self.draining:
                raise vision_error("VISION_SHUTTING_DOWN", "서버가 종료 중입니다.", retry_after=5)
            yield waited

    @asynccontextmanager
    async def answer_slot(self, settings: VisionSettings, timeout: float | None = None) -> AsyncIterator[float]:
        """OpenAI 최종 답변 슬롯 → yield(대기ms). GPU 와 무관하다."""
        t = settings.answer_queue_timeout_s if timeout is None else min(settings.answer_queue_timeout_s, timeout)
        async with self._answer.hold(settings.answer_max_concurrency, t, lambda: vision_error(
                "VISION_ANSWER_QUEUE_TIMEOUT", "AI 답변 대기 시간이 초과되었습니다.", retry_after=10)) as waited:
            yield waited


gate = VisionGate()
