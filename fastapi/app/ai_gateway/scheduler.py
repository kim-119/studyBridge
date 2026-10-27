"""GPU 슬롯 스케줄러 — 가중 공정 큐(stride) + 사용자 공정성 + backpressure + 취소.

Ollama(NUM_PARALLEL=1)는 도착 순서(FIFO)로만 처리하므로 긴 문서 생성이 실시간 채팅 앞을 막고,
한 사용자의 멀티에이전트 호출 묶음이 다른 사용자를 굶길 수 있다. 여기서는 슬롯 수(=Ollama 병렬도)
만큼만 백엔드로 내보내고, 나머지는 클래스별 대기열에서 다음 규칙으로 고른다.

  1) 자기 대기 한도의 aging_fraction(기본 0.5) 이상을 기다린 요청이 있으면 그중 마감이 가장 임박한 것
     (긴급도 = 대기시간/대기한도, EDF). 절대 시간 기준 aging 은 부하가 크면 긴 문서 작업이 전부 aged 가 되어
     FIFO 로 퇴화하고 짧은 대화형 호출이 한도를 넘긴다(2026-10-27 mock N=20 에서 멀티에이전트 5/5 실패 재현).
  2) 아니면 pass 값이 가장 작은 클래스(stride: 선택될 때마다 1/weight 증가)
  3) 클래스 안에서는 현재 점유 슬롯이 적은 사용자 → 먼저 온 순서

동기(스레드) 호출부와 async 호출부를 모두 지원한다. 상태는 threading.Lock 하나로 보호한다.
프로세스 로컬 상태다 — 운영은 uvicorn 단일 워커(systemd ExecStart 확인)라 충분하며,
멀티워커로 바꾸면 AI_GW_TEXT_SLOTS 를 워커 수로 나눠야 한다(보고서 '확장 전략' 참조).
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import os
import threading
import time
from collections import Counter, deque
from typing import Callable, Deque, Dict, List, Optional

from app.ai_gateway.policy import Policy, WorkloadClass, policy_for

logger = logging.getLogger(__name__)

_HTTP_STATUS = {"QUEUE_FULL": 429, "USER_LIMIT": 429, "QUEUE_TIMEOUT": 503, "CIRCUIT_OPEN": 503,
                "SHUTTING_DOWN": 503, "CANCELLED": 499, "BUDGET_EXCEEDED": 429}


class GatewayRejected(Exception):
    def __init__(self, code: str, message: str = "", *, retry_after: int = 5,
                 wclass: Optional[WorkloadClass] = None, backend: str = "") -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.wclass = wclass
        self.backend = backend

    @property
    def http_status(self) -> int:
        return _HTTP_STATUS.get(self.code, 503)


def _fenv(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class _Ticket:
    __slots__ = ("id", "backend", "wclass", "key", "policy", "enq", "granted", "done", "event",
                 "fut", "loop", "start", "limit", "group")

    def __init__(self, tid: int, backend: str, wclass: WorkloadClass, key: str, policy: Policy) -> None:
        self.id = tid
        self.backend = backend
        self.wclass = wclass
        self.key = key
        self.policy = policy
        self.enq = time.monotonic()
        self.granted = False
        self.done = False
        self.event: Optional[threading.Event] = None
        self.fut: Optional[asyncio.Future] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.start = 0.0
        self.limit = policy.queue_timeout_s     # acquire 시 호출부 timeout 으로 좁혀진다
        self.group = key                          # 그룹 공정성 키(없으면 사용자 키)


class Lease:
    """획득한 슬롯. release() 는 멱등이며 with 문으로도 쓸 수 있다."""

    def __init__(self, sched: "Scheduler", ticket: _Ticket, wait_ms: float) -> None:
        self._s = sched
        self._t = ticket
        self.wait_ms = wait_ms
        self.backend = ticket.backend
        self.wclass = ticket.wclass
        self.outcome = "ok"
        self.reported = False          # backend_ok/backend_fail 호출 여부(브레이커 탐침 반납 판단)

    def backend_ok(self) -> None:
        self.reported = True
        self._s.on_backend_result(self.backend, True)

    def backend_fail(self) -> None:
        self.reported = True
        self.outcome = "backend_error"
        self._s.on_backend_result(self.backend, False)

    def release(self) -> None:
        self._s._release(self._t, self.outcome)

    def __enter__(self) -> "Lease":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None and self.outcome == "ok":
            self.outcome = "error"
        self.release()


class _ClassStats:
    __slots__ = ("granted", "rejected_full", "rejected_timeout", "cancelled", "completed", "errors",
                 "wait_ms", "run_ms", "max_waiting")

    def __init__(self) -> None:
        self.granted = self.rejected_full = self.rejected_timeout = self.cancelled = 0
        self.completed = self.errors = self.max_waiting = 0
        self.wait_ms: Deque[float] = deque(maxlen=1024)
        self.run_ms: Deque[float] = deque(maxlen=1024)


def _limit(policy: Policy, timeout: Optional[float]) -> float:
    return policy.queue_timeout_s if timeout is None else min(policy.queue_timeout_s, max(0.05, float(timeout)))


def _pct(values, q: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    idx = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return round(s[idx], 1)


class Scheduler:
    def __init__(self, *, guard=None, on_backend_result: Optional[Callable[[str, bool], None]] = None) -> None:
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self.capacity: Dict[str, int] = {}
        self._waiting: Dict[str, List[_Ticket]] = {}
        self._inflight_backend: Counter = Counter()
        self._inflight_low: Counter = Counter()
        self._inflight_class: Counter = Counter()
        self._inflight_ck: Counter = Counter()     # (class, key)
        self._inflight_key: Counter = Counter()
        self._active: Dict[int, _Ticket] = {}
        # 공정성 카운터는 클래스 범위다. 전역으로 두면 같은 그룹의 비전/퀴즈가 실행 중일 때 그 그룹의 멀티에이전트가
        # 라운드로빈에서 밀리고, 다른 활동이 없는 사용자가 늘 이기는 역전이 생긴다(2026-10-27 실서비스형 mock 재현).
        self._last_grant: Dict[tuple, float] = {}      # (class, key) → 마지막 배정 시각
        self._inflight_cg: Counter = Counter()         # (class, group)
        self._last_grant_group: Dict[tuple, float] = {}  # (class, group) → 마지막 배정 시각
        self._pass: Dict[WorkloadClass, float] = {c: 0.0 for c in WorkloadClass}
        self._vt = 0.0
        self._stats: Dict[WorkloadClass, _ClassStats] = {c: _ClassStats() for c in WorkloadClass}
        self.guard = guard
        self._on_backend_result = on_backend_result
        self.draining = False
        self.aging_fraction = min(1.0, max(0.05, _fenv("AI_GW_AGING_FRACTION", 0.5)))
        self.reserved_interactive = int(_fenv("AI_GW_RESERVED_INTERACTIVE_SLOTS", 1))
        # 적응형 예약: 실시간 클래스 활동이 최근 hold_s 안에 있을 때만 마지막 슬롯을 남긴다(없으면 문서가 전부 사용).
        self.reserve_hold_s = _fenv("AI_GW_RESERVE_HOLD_S", 20.0)
        self._last_interactive: Dict[str, float] = {}
        self.max_queue_total = int(_fenv("AI_GW_MAX_QUEUE_TOTAL", 128))
        self.lease_max_s = _fenv("AI_GW_LEASE_MAX_S", 900.0)
        self.leaked_releases = 0
        self._ticker: Optional[threading.Thread] = None
        self._ticker_stop = threading.Event()
        if guard is not None:
            guard.on_change = self.kick

    # ── 설정 ─────────────────────────────────────────────────────────────
    def configure_backend(self, name: str, capacity: int) -> None:
        with self._lock:
            self.capacity[name] = max(1, int(capacity))
            self._waiting.setdefault(name, [])

    def on_backend_result(self, backend: str, ok: bool) -> None:
        if self._on_backend_result:
            try:
                self._on_backend_result(backend, ok)
            except Exception:  # noqa: BLE001
                pass

    # ── 선택 로직(lock 보유 상태에서만 호출) ─────────────────────────────────
    def _class_ok(self, t: _Ticket, cap: int) -> bool:
        if self._inflight_class[t.wclass] >= t.policy.max_concurrency:
            return False
        if t.policy.low_priority and cap >= 2 and self._interactive_active(t.backend):
            if self._inflight_low[t.backend] >= max(1, cap - self.reserved_interactive):
                return False
        return True

    def _interactive_active(self, backend: str) -> bool:
        if self._inflight_backend[backend] - self._inflight_low[backend] > 0:
            return True
        if any(not x.policy.low_priority for x in self._waiting.get(backend) or []):
            return True
        return time.monotonic() - self._last_interactive.get(backend, -1e9) < self.reserve_hold_s

    def _pick(self, backend: str) -> Optional[_Ticket]:
        q = self._waiting.get(backend) or []
        if not q:
            return None
        cap = self.capacity.get(backend, 1)
        cands = [t for t in q if self._class_ok(t, cap)]
        if not cands:
            return None
        strict = [t for t in cands if self._inflight_ck[(t.wclass, t.key)] < t.policy.per_user_inflight]
        pool = strict or cands          # 다른 대기자가 없으면 사용자 상한 초과 허용(work-conserving)
        now = time.monotonic()
        aged = [t for t in pool if (now - t.enq) >= self.aging_fraction * t.limit]
        if aged:
            return min(aged, key=lambda t: t.enq + t.limit)     # 마감(enq+limit)이 가장 이른 것
        best_cls = min({t.wclass for t in pool}, key=lambda c: self._pass[c])
        in_cls = [t for t in pool if t.wclass == best_cls]
        # 그룹 → 사용자 2단계 라운드로빈: 사용자가 많은 그룹이 개인/작은 그룹을 밀어내지 않게 그룹을 먼저 돌린다.
        c = best_cls
        return min(in_cls, key=lambda t: (self._inflight_cg[(c, t.group)], self._last_grant_group.get((c, t.group), 0.0),
                                          self._inflight_ck[(c, t.key)], self._last_grant.get((c, t.key), 0.0), t.enq))

    def _grant(self, t: _Ticket) -> None:
        self._waiting[t.backend].remove(t)
        t.granted = True
        t.start = time.monotonic()
        self._inflight_backend[t.backend] += 1
        if t.policy.low_priority:
            self._inflight_low[t.backend] += 1
        self._inflight_class[t.wclass] += 1
        self._inflight_ck[(t.wclass, t.key)] += 1
        self._inflight_key[t.key] += 1
        self._inflight_cg[(t.wclass, t.group)] += 1
        self._active[t.id] = t
        self._last_grant[(t.wclass, t.key)] = t.start
        self._last_grant_group[(t.wclass, t.group)] = t.start
        if len(self._last_grant) > 4096 or len(self._last_grant_group) > 4096:
            cutoff = t.start - 600
            self._last_grant = {k: v for k, v in self._last_grant.items() if v >= cutoff}
            self._last_grant_group = {k: v for k, v in self._last_grant_group.items() if v >= cutoff}
        p = max(self._pass[t.wclass], self._vt)
        self._vt = p
        self._pass[t.wclass] = p + 1.0 / t.policy.weight
        st = self._stats[t.wclass]
        st.granted += 1
        logger.debug("[AI_GW] grant backend=%s class=%s key=%s wait_ms=%.0f", t.backend, t.wclass.value,
                     t.key, (t.start - t.enq) * 1000.0)
        st.wait_ms.append((t.start - t.enq) * 1000.0)
        if self.guard is not None:
            self.guard.note_granted(t.backend)
        if t.event is not None:
            t.event.set()
        elif t.fut is not None and t.loop is not None:
            def _wake(f=t.fut):
                if not f.done():
                    f.set_result(True)
            try:
                t.loop.call_soon_threadsafe(_wake)
            except RuntimeError:   # 루프 종료 → 슬롯 즉시 반환
                self._release_locked(t, "cancelled")

    def _dispatch_locked(self) -> None:
        order = list(self.capacity.items())
        if self.guard is not None:
            target = self.guard.swap_target
            if target is not None and not self._waiting.get(target):
                self.guard.clear_swap(target)          # 기다리던 요청이 사라졌으면 swap 취소
                target = None
            if target is not None:
                # swap 대상 백엔드를 먼저 처리한다. 축출이 진행 중일 때만 대상만 배정한다(축출 직후 다른 쪽이
                # '적재 가능'으로 보여 먼저 슬롯을 가져가면 swap 이 왕복 반복 — 2026-10-27 재현). 축출 전 최소 상주
                # 대기 중에는 다른 쪽도 계속 처리해 GPU 를 놀리지 않는다(2026-10-28 리뷰: 양쪽 유휴 재현).
                order.sort(key=lambda bc: bc[0] != target)
                if self.guard.evicting:
                    order = [(b, c) for b, c in order if b == target]
        for backend, cap in order:
            while self._inflight_backend[backend] < cap and self._waiting.get(backend):
                if self.guard is not None:
                    if self.guard.blocks(backend):
                        break
                    ok, _reason = self.guard.admissible(backend, dict(self._inflight_backend),
                                                        {b: len(q) for b, q in self._waiting.items()})
                    if not ok:
                        break
                t = self._pick(backend)
                if t is None:
                    break
                self._grant(t)

    def kick(self) -> None:
        with self._lock:
            self._dispatch_locked()

    # ── 입장 ─────────────────────────────────────────────────────────────
    def _abandon(self, t: _Ticket, reason: str) -> bool:
        """대기 중 포기. 이미 배정됐으면 False(호출부가 Lease 로 받아야 함)."""
        with self._lock:
            if t.granted:
                return False
            try:
                self._waiting[t.backend].remove(t)
            except ValueError:
                pass
            t.done = True
            st = self._stats[t.wclass]
            if reason == "timeout":
                st.rejected_timeout += 1
            else:
                st.cancelled += 1
            self._dispatch_locked()
            return True

    def acquire_sync(self, backend: str, wclass: WorkloadClass, key: str = "anon", *,
                     timeout: Optional[float] = None, cancel_check: Optional[Callable[[], bool]] = None,
                     group: Optional[str] = None) -> Lease:
        t = self._enqueue_with_event(backend, wclass, key, timeout, group)
        limit = t.limit
        deadline = t.enq + limit
        while not t.granted:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if self._abandon(t, "timeout"):
                    raise GatewayRejected("QUEUE_TIMEOUT", f"waited {limit:.1f}s", retry_after=10,
                                          wclass=wclass, backend=backend)
                break
            t.event.wait(min(0.2, remaining))
            if t.done and not t.granted:
                raise GatewayRejected("SHUTTING_DOWN", "server is shutting down", wclass=wclass, backend=backend)
            if not t.granted and cancel_check is not None:
                try:
                    cancelled = bool(cancel_check())
                except Exception:  # noqa: BLE001
                    cancelled = False
                if cancelled and self._abandon(t, "cancel"):
                    raise GatewayRejected("CANCELLED", "client cancelled while queued", wclass=wclass, backend=backend)
        return Lease(self, t, (t.start - t.enq) * 1000.0)

    def _enqueue_with_event(self, backend: str, wclass: WorkloadClass, key: str,
                            timeout: Optional[float] = None, group: Optional[str] = None) -> _Ticket:
        # event 를 dispatch 전에 붙여야 즉시 배정 시 신호를 놓치지 않는다.
        def _mk(tid, b, c, k, p):
            tk = _Ticket(tid, b, c, k, p)
            tk.event = threading.Event()
            tk.limit = _limit(p, timeout)
            return tk
        return self._enqueue_factory(backend, wclass, key, _mk, group)

    def _enqueue_factory(self, backend, wclass, key, factory, group: Optional[str] = None) -> _Ticket:
        if backend not in self.capacity:
            self.configure_backend(backend, 1)
        pol = policy_for(wclass)
        with self._lock:
            if self.draining:
                raise GatewayRejected("SHUTTING_DOWN", "server is shutting down", wclass=wclass, backend=backend)
            st = self._stats[wclass]
            waiting_cls = sum(1 for q in self._waiting.values() for x in q if x.wclass == wclass)
            total_wait = sum(len(q) for q in self._waiting.values())
            slot_free_now = self._inflight_backend[backend] < self.capacity[backend] and not self._waiting[backend]
            if (waiting_cls >= pol.max_queue or total_wait >= self.max_queue_total) and not slot_free_now:
                st.rejected_full += 1
                raise GatewayRejected("QUEUE_FULL", f"{wclass.value} queue full", retry_after=10,
                                      wclass=wclass, backend=backend)
            key = key or "anon"
            if key != "anon":
                mine = sum(1 for q in self._waiting.values() for x in q if x.wclass == wclass and x.key == key)
                if mine >= pol.per_user_queue:
                    st.rejected_full += 1
                    raise GatewayRejected("USER_LIMIT", f"{wclass.value} per-user queue limit", retry_after=5,
                                          wclass=wclass, backend=backend)
            t = factory(next(self._ids), backend, wclass, key, pol)
            t.group = group or key
            if not pol.low_priority:
                self._last_interactive[backend] = time.monotonic()
            self._waiting[backend].append(t)
            st.max_waiting = max(st.max_waiting, waiting_cls + 1)
            try:
                self._dispatch_locked()
                self._ensure_ticker()
            except BaseException:
                # 대기열에 넣은 뒤 실패하면(스레드 생성 실패 등) 티켓을 회수한다 — 남겨 두면 나중에 배정돼
                # 아무도 반환하지 않는 lease 가 된다(리뷰 지적).
                if t.granted:
                    self._release_locked(t, "error")
                elif t in self._waiting.get(backend, []):
                    self._waiting[backend].remove(t)
                t.done = True
                raise
            return t

    async def acquire_async(self, backend: str, wclass: WorkloadClass, key: str = "anon", *,
                            timeout: Optional[float] = None, group: Optional[str] = None) -> Lease:
        loop = asyncio.get_running_loop()
        fut = loop.create_future()

        def _mk(tid, b, c, k, p):
            tk = _Ticket(tid, b, c, k, p)
            tk.fut, tk.loop = fut, loop
            tk.limit = _limit(p, timeout)
            return tk
        t = self._enqueue_factory(backend, wclass, key, _mk, group)
        limit = t.limit
        try:
            if not t.granted:
                await asyncio.wait_for(asyncio.shield(fut), timeout=limit)
        except asyncio.TimeoutError:
            if self._abandon(t, "timeout"):
                raise GatewayRejected("QUEUE_TIMEOUT", f"waited {limit:.1f}s", retry_after=10,
                                      wclass=wclass, backend=backend) from None
        except asyncio.CancelledError:
            if not self._abandon(t, "cancel"):
                self._release(t, "cancelled")     # 배정 직후 취소 → 슬롯 즉시 반환
            raise
        return Lease(self, t, (t.start - t.enq) * 1000.0)

    # ── 반환 ─────────────────────────────────────────────────────────────
    def _release_locked(self, t: _Ticket, outcome: str) -> None:
        if t.done or not t.granted:
            t.done = True
            return
        t.done = True
        self._active.pop(t.id, None)
        self._inflight_backend[t.backend] -= 1
        if t.policy.low_priority:
            self._inflight_low[t.backend] -= 1
        else:
            self._last_interactive[t.backend] = time.monotonic()
        self._inflight_class[t.wclass] -= 1
        self._inflight_ck[(t.wclass, t.key)] -= 1
        self._inflight_key[t.key] -= 1
        self._inflight_cg[(t.wclass, t.group)] -= 1
        for c in (self._inflight_ck, self._inflight_key, self._inflight_cg):
            for k in [k for k, v in c.items() if v <= 0]:
                del c[k]
        st = self._stats[t.wclass]
        st.run_ms.append((time.monotonic() - t.start) * 1000.0)
        if outcome == "ok":
            st.completed += 1
        elif outcome == "cancelled":
            st.cancelled += 1
        else:
            st.errors += 1
        if self.guard is not None:
            self.guard.note_released(t.backend)
        self._dispatch_locked()

    def _release(self, t: _Ticket, outcome: str = "ok") -> None:
        with self._lock:
            self._release_locked(t, outcome)

    # ── 백그라운드 tick: 텔레메트리 갱신 / 누수 lease 회수 / 재배정 ────────────
    def _ensure_ticker(self) -> None:
        if self._ticker is not None and self._ticker.is_alive():
            return
        self._ticker_stop.clear()
        self._ticker = threading.Thread(target=self._tick_loop, name="ai-gw-ticker", daemon=True)
        self._ticker.start()

    def _tick_loop(self) -> None:
        idle_since = None
        while not self._ticker_stop.is_set():
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 — ticker 는 절대 죽지 않는다
                logger.warning("[AI_GW] tick error: %s", e)
            with self._lock:
                busy = bool(self._active) or any(self._waiting.values())
                if busy:
                    idle_since = None
                else:
                    idle_since = idle_since or time.monotonic()
                    if time.monotonic() - idle_since > 60:
                        self._ticker = None     # busy 확인과 같은 lock 구간에서 내려야 enqueue 와 경합하지 않는다
                        return
            self._ticker_stop.wait(0.5 if busy else 2.0)

    def tick(self) -> None:
        if self.guard is not None:
            self.guard.refresh()
        now = time.monotonic()
        with self._lock:
            for t in [t for t in self._active.values() if now - t.start > self.lease_max_s]:
                logger.error("[AI_GW] lease leak reclaimed backend=%s class=%s held=%.0fs",
                             t.backend, t.wclass.value, now - t.start)
                self.leaked_releases += 1
                self._release_locked(t, "error")
            self._dispatch_locked()

    def stop(self) -> None:
        self._ticker_stop.set()

    # ── 관측 ─────────────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        with self._lock:
            classes = {}
            for c, st in self._stats.items():
                classes[c.value] = {
                    "inflight": self._inflight_class[c],
                    "waiting": sum(1 for q in self._waiting.values() for t in q if t.wclass == c),
                    "granted": st.granted, "completed": st.completed, "errors": st.errors,
                    "rejectedQueueFull": st.rejected_full, "rejectedTimeout": st.rejected_timeout,
                    "cancelled": st.cancelled, "maxWaiting": st.max_waiting,
                    "waitMs": {"p50": _pct(st.wait_ms, .5), "p95": _pct(st.wait_ms, .95), "p99": _pct(st.wait_ms, .99)},
                    "runMs": {"p50": _pct(st.run_ms, .5), "p95": _pct(st.run_ms, .95), "p99": _pct(st.run_ms, .99)},
                }
            return {
                "backends": {b: {"capacity": cap, "inflight": self._inflight_backend[b],
                                 "waiting": len(self._waiting.get(b) or [])}
                             for b, cap in self.capacity.items()},
                "classes": classes,
                "draining": self.draining,
                "leakedReleases": self.leaked_releases,
            }

    def start_draining(self) -> None:
        with self._lock:
            self.draining = True
            waiting = [t for q in self._waiting.values() for t in q]
        for t in waiting:
            if self._abandon(t, "cancel"):
                if t.event is not None:
                    t.event.set()
                elif t.fut is not None and t.loop is not None:
                    t.loop.call_soon_threadsafe(lambda f=t.fut: f.done() or f.set_exception(
                        GatewayRejected("SHUTTING_DOWN", "server is shutting down")))
