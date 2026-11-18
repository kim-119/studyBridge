"""AI Gateway 단위/통합 테스트 — 외부 I/O 없음(Ollama/OpenAI/nvidia-smi 전부 fake)."""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

import app.ai_gateway as gw
from app.ai_gateway.breaker import CircuitBreaker
from app.ai_gateway.budget import TokenBudget
from app.ai_gateway.context import current_class, current_fair_key, workload
from app.ai_gateway.gpu_guard import GpuGuard
from app.ai_gateway.policy import WorkloadClass as W, class_for_path
from app.ai_gateway.scheduler import GatewayRejected, Scheduler


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    import os
    saved = {k: v for k, v in os.environ.items() if k.startswith("AI_GW_")}
    yield from _env_body(monkeypatch)
    for k in [k for k in os.environ if k.startswith("AI_GW_")]:
        del os.environ[k]
    os.environ.update(saved)


def _env_body(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_ENABLED", "true")
    monkeypatch.setenv("AI_GW_GPU_GUARD", "false")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:14b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("VISION_OLLAMA_BASE_URL", "http://127.0.0.1:11435")
    gw.reset_for_tests(None)
    yield
    gw.reset_for_tests(None)


def _sched(cap=1, **kw) -> Scheduler:
    s = Scheduler(**kw)
    s.configure_backend("t", cap)
    return s


def _bg_acquire(s, cls, key, out, **kw):
    def run():
        try:
            lease = s.acquire_sync("t", cls, key, **kw)
            out.append((cls, key, lease))
        except GatewayRejected as e:
            out.append((cls, key, e))
    th = threading.Thread(target=run, daemon=True)
    th.start()
    return th


def _wait_waiting(s, n, timeout=2.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if s.snapshot()["backends"]["t"]["waiting"] >= n:
            return
        time.sleep(0.01)
    raise AssertionError("waiters did not arrive")


# ── 1. 비활성 시 완전 통과 ─────────────────────────────────────────────────
def test_disabled_is_passthrough(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_ENABLED", "false")
    with gw.llm_slot(url="http://127.0.0.1:11434") as lease:
        assert lease is None
    p = {"model": "qwen3:14b", "options": {"num_ctx": 1024}}
    assert gw.normalize_ollama_payload(p) == {"model": "qwen3:14b", "options": {"num_ctx": 1024}}
    assert gw.openai_allowed(10**9) is True


# ── 2. 우선순위: 실시간 채팅이 대기 중인 문서 작업보다 먼저 ─────────────────────
def test_chat_preempts_queued_document_in_order():
    s = _sched(1)
    first = s.acquire_sync("t", W.DOCUMENT_ANALYSIS, "u1")
    out = []
    _bg_acquire(s, W.DOCUMENT_ANALYSIS, "u2", out)
    _wait_waiting(s, 1)
    _bg_acquire(s, W.INTERACTIVE_CHAT, "u3", out)
    _wait_waiting(s, 2)
    first.release()
    t0 = time.time()
    while len(out) < 1 and time.time() - t0 < 2:
        time.sleep(0.01)
    assert out[0][0] == W.INTERACTIVE_CHAT
    out[0][2].release()
    while len(out) < 2 and time.time() - t0 < 2:
        time.sleep(0.01)
    assert out[1][0] == W.DOCUMENT_ANALYSIS
    out[1][2].release()
    assert s.snapshot()["backends"]["t"]["inflight"] == 0


# ── 3. 사용자 공정성: 한 사용자의 멀티에이전트 묶음이 다른 사용자를 굶기지 않음 ─────
def test_per_user_round_robin_within_class():
    s = _sched(1)
    hold = s.acquire_sync("t", W.MULTI_AGENT, "A")
    out = []
    for _ in range(3):
        _bg_acquire(s, W.MULTI_AGENT, "A", out)
    _wait_waiting(s, 3)
    _bg_acquire(s, W.MULTI_AGENT, "B", out)
    _wait_waiting(s, 4)
    hold.release()
    t0 = time.time()
    order = []
    while len(order) < 4 and time.time() - t0 < 3:
        if len(out) > len(order):
            cls, key, lease = out[len(order)]
            order.append(key)
            lease.release()
        time.sleep(0.005)
    assert order[0] == "B", order          # B 는 늦게 왔지만 A 의 다음 호출보다 먼저
    assert order.count("A") == 3


# ── 4. backpressure: 대기열 상한 / 대기 타임아웃 ────────────────────────────
def test_queue_full_rejects(monkeypatch):
    monkeypatch.setenv("AI_GW_VISION_MAX_QUEUE", "1")
    s = _sched(1)
    hold = s.acquire_sync("t", W.VISION, "g1")
    out = []
    _bg_acquire(s, W.VISION, "g2", out)
    _wait_waiting(s, 1)
    with pytest.raises(GatewayRejected) as ei:
        s.acquire_sync("t", W.VISION, "g3")
    assert ei.value.code == "QUEUE_FULL" and ei.value.http_status == 429
    hold.release()
    time.sleep(0.05)
    out[0][2].release()
    assert s.snapshot()["classes"]["VISION"]["rejectedQueueFull"] == 1


def test_queue_timeout_removes_ticket():
    s = _sched(1)
    hold = s.acquire_sync("t", W.INTERACTIVE_CHAT, "u1")
    t0 = time.time()
    with pytest.raises(GatewayRejected) as ei:
        s.acquire_sync("t", W.INTERACTIVE_CHAT, "u2", timeout=0.2)
    assert ei.value.code == "QUEUE_TIMEOUT" and 0.15 < time.time() - t0 < 1.0
    snap = s.snapshot()
    assert snap["backends"]["t"]["waiting"] == 0
    hold.release()
    assert s.snapshot()["backends"]["t"]["inflight"] == 0


# ── 5. 취소: 대기 중 취소 → 즉시 제거, 슬롯 누수 없음 ─────────────────────────
def test_sync_cancel_while_queued():
    s = _sched(1)
    hold = s.acquire_sync("t", W.MULTI_AGENT, "u1")
    flag = {"c": False}
    out = []
    th = _bg_acquire(s, W.MULTI_AGENT, "u2", out, cancel_check=lambda: flag["c"])
    _wait_waiting(s, 1)
    flag["c"] = True
    th.join(2)
    assert isinstance(out[0][2], GatewayRejected) and out[0][2].code == "CANCELLED"
    assert s.snapshot()["backends"]["t"]["waiting"] == 0
    hold.release()
    assert s.snapshot()["backends"]["t"]["inflight"] == 0


def test_async_cancel_does_not_leak_slot():
    async def main():
        s = _sched(1)
        hold = await s.acquire_async("t", W.VISION, "g1")
        task = asyncio.create_task(s.acquire_async("t", W.VISION, "g2"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert s.snapshot()["backends"]["t"]["waiting"] == 0
        hold.release()
        lease = await asyncio.wait_for(s.acquire_async("t", W.VISION, "g3"), 1)
        lease.release()
        assert s.snapshot()["backends"]["t"]["inflight"] == 0
    asyncio.run(main())


# ── 6. 슬롯 2개 이상이면 문서 작업은 마지막 슬롯을 못 가져간다 ─────────────────────
def test_low_priority_reserves_interactive_slot():
    s = _sched(2)
    s.acquire_sync("t", W.INTERACTIVE_CHAT, "u0").release()           # 최근 실시간 활동
    d1 = s.acquire_sync("t", W.DOCUMENT_QUIZ, "u1")
    with pytest.raises(GatewayRejected):
        s.acquire_sync("t", W.DOCUMENT_QUIZ, "u2", timeout=0.15)     # 두 번째 슬롯은 예약됨
    c = s.acquire_sync("t", W.INTERACTIVE_CHAT, "u3", timeout=0.5)    # 채팅은 즉시
    assert c.wait_ms < 100
    c.release(); d1.release()


def test_reservation_is_adaptive_when_no_interactive_traffic(monkeypatch):
    monkeypatch.setenv("AI_GW_RESERVE_HOLD_S", "0.2")
    s = _sched(2)
    d1 = s.acquire_sync("t", W.DOCUMENT_ANALYSIS, "u1")
    d2 = s.acquire_sync("t", W.DOCUMENT_ANALYSIS, "u2", timeout=0.3)   # 실시간 활동 없음 → 두 슬롯 모두 사용
    d1.release(); d2.release()
    c = s.acquire_sync("t", W.INTERACTIVE_CHAT, "u3")
    d3 = s.acquire_sync("t", W.DOCUMENT_ANALYSIS, "u4")
    c.release()
    with pytest.raises(GatewayRejected):                                  # 방금 채팅 활동 → 예약 유지
        s.acquire_sync("t", W.DOCUMENT_ANALYSIS, "u5", timeout=0.1)
    time.sleep(0.25)
    s.acquire_sync("t", W.DOCUMENT_ANALYSIS, "u6", timeout=0.3).release()  # hold 경과 → 다시 사용 가능
    d3.release()


# ── 7. aging: 오래 기다린 저우선 작업은 결국 선택된다(기아 방지) ─────────────────
def test_aging_prevents_starvation(monkeypatch):
    monkeypatch.setenv("AI_GW_AGING_FRACTION", "0.5")
    s = _sched(1)
    hold = s.acquire_sync("t", W.INTERACTIVE_CHAT, "u0")
    out = []
    _bg_acquire(s, W.BACKGROUND_AI_JOB, "bg", out, timeout=0.3)
    _wait_waiting(s, 1)
    time.sleep(0.2)                     # 0.2 ≥ 0.5 × 0.3 → aged
    _bg_acquire(s, W.INTERACTIVE_CHAT, "u1", out)
    _wait_waiting(s, 2)
    hold.release()
    t0 = time.time()
    while not out and time.time() - t0 < 2:
        time.sleep(0.01)
    assert out[0][0] == W.BACKGROUND_AI_JOB
    out[0][2].release()
    while len(out) < 2 and time.time() - t0 < 2:
        time.sleep(0.01)
    out[1][2].release()


def test_aging_is_relative_so_short_deadline_calls_are_not_starved(monkeypatch):
    """부하가 커서 긴 문서 작업이 많이 대기해도, 대기 한도가 짧은 대화형 호출이 먼저 마감에 걸리면 그것부터."""
    monkeypatch.setenv("AI_GW_AGING_FRACTION", "0.5")
    s = _sched(1)
    hold = s.acquire_sync("t", W.DOCUMENT_ANALYSIS, "d0")
    out = []
    for i in range(3):
        _bg_acquire(s, W.DOCUMENT_ANALYSIS, f"d{i+1}", out, timeout=10)
    _wait_waiting(s, 3)
    time.sleep(0.05)
    _bg_acquire(s, W.MULTI_AGENT, "c", out, timeout=0.6)
    _wait_waiting(s, 4)
    time.sleep(0.35)                    # 문서: 0.4/10 (미aged), 멀티에이전트: 0.35/0.6 (aged)
    hold.release()
    t0 = time.time()
    while not out and time.time() - t0 < 2:
        time.sleep(0.01)
    assert out[0][0] == W.MULTI_AGENT
    for _ in range(4):
        while len(out) < _ + 1 and time.time() - t0 < 3:
            time.sleep(0.01)
        out[_][2].release()


# ── 8. lease 누수 회수 ───────────────────────────────────────────────────
def test_leaked_lease_reclaimed(monkeypatch):
    monkeypatch.setenv("AI_GW_LEASE_MAX_S", "0.05")
    s = _sched(1)
    s.acquire_sync("t", W.INTERACTIVE_CHAT, "u1")     # release 하지 않음(버그 모사)
    time.sleep(0.08)
    s.tick()
    assert s.snapshot()["backends"]["t"]["inflight"] == 0
    assert s.leaked_releases == 1
    s.acquire_sync("t", W.INTERACTIVE_CHAT, "u2", timeout=0.2).release()


def test_draining_rejects_waiters():
    s = _sched(1)
    hold = s.acquire_sync("t", W.INTERACTIVE_CHAT, "u1")
    out = []
    th = _bg_acquire(s, W.INTERACTIVE_CHAT, "u2", out)
    _wait_waiting(s, 1)
    s.start_draining()
    th.join(2)
    assert isinstance(out[0][2], GatewayRejected) and out[0][2].code == "SHUTTING_DOWN"
    with pytest.raises(GatewayRejected):
        s.acquire_sync("t", W.INTERACTIVE_CHAT, "u3")
    hold.release()


# ── 9. circuit breaker ────────────────────────────────────────────────────
def test_breaker_open_half_open_close():
    b = CircuitBreaker("x", threshold=3, window_s=10, cooldown_s=0.1)
    for _ in range(3):
        b.record_failure()
    assert b.state == "open" and not b.allow()
    time.sleep(0.12)
    assert b.allow() is True          # half-open 탐침 1건
    assert b.allow() is False         # 탐침 결과 전에는 추가 통과 없음
    b.record_success()
    assert b.state == "closed" and b.allow()


def test_breaker_blocks_llm_slot():
    for _ in range(5):
        gw.breaker("ollama_text").record_failure()
    with pytest.raises(GatewayRejected) as ei:
        with gw.llm_slot(url="http://127.0.0.1:11434"):
            pass
    assert ei.value.code == "CIRCUIT_OPEN"


# ── 10. GPU guard: 상주 조정 ───────────────────────────────────────────────
class _FakeGpu:
    def __init__(self, total=16303, base_used=1600):
        self.total, self.base = total, base_used
        self.resident = {"http://t": {}, "http://v": {}}
        self.sizes = {"qwen3:14b": 10300, "qwen3-vl:4b-instruct": 4600}
        self.unloads = []
        self.partial = set()                # 부분 offload 로 적재된 모델

    def smi(self):
        used = self.base + sum(self.sizes[m] for r in self.resident.values() for m in r)
        return self.total, used

    def ps(self, url):
        return {m: ((self.sizes[m] // 2, self.sizes[m]) if m in self.partial else self.sizes[m])
                for m in self.resident[url]}

    def unload(self, url, model):
        self.unloads.append((url, model))
        self.resident[url].pop(model, None)
        return True


def _guarded(fake, margin=768, policy="swap"):
    import os
    os.environ["AI_GW_GPU_GUARD"] = "true"
    os.environ["AI_GW_VISION_PRESSURE_POLICY"] = policy
    os.environ["AI_GW_VRAM_MARGIN_MIB"] = str(margin)
    os.environ["AI_GW_MIN_RESIDENCY_S"] = "0"
    os.environ["AI_GW_TELEMETRY_INTERVAL_S"] = "0"
    g = GpuGuard(ps_fn=fake.ps, smi_fn=fake.smi, unload_fn=fake.unload)
    g.register("text", "http://t", 10600, protected=True)
    g.register("vision", "http://v", 4800)
    s = Scheduler(guard=g)
    s.configure_backend("text", 1)
    s.configure_backend("vision", 1)
    g.refresh(force=True)
    return s, g


def test_guard_swaps_after_text_drains():
    fake = _FakeGpu(base_used=1600)
    fake.resident["http://t"] = {"qwen3:14b": 10300}       # free = 16303-11900 = 4403 < 4800+768
    s, g = _guarded(fake)
    text_lease = s.acquire_sync("text", W.INTERACTIVE_CHAT, "u1")
    out = []

    def vis():
        try:
            out.append(s.acquire_sync("vision", W.VISION, "g1", timeout=5))
        except GatewayRejected as e:
            out.append(e)
    th = threading.Thread(target=vis, daemon=True)
    th.start()
    time.sleep(0.1)
    assert not out and g.swap_target == "vision"
    # swap 대기 중에는 텍스트 신규 배정이 멈춰 drain 된다
    with pytest.raises(GatewayRejected):
        s.acquire_sync("text", W.INTERACTIVE_CHAT, "u2", timeout=0.15)
    assert fake.unloads == []                                  # 실행 중 요청은 중단하지 않음
    text_lease.release()                                       # → evict → 재배정
    th.join(5)
    assert out and not isinstance(out[0], GatewayRejected), out
    assert fake.unloads == [("http://t", "qwen3:14b")]
    out[0].release()


def test_guard_adaptive_allows_degraded_vision_when_text_busy():
    fake = _FakeGpu(base_used=1600)
    fake.resident["http://t"] = {"qwen3:14b": 10300}
    s, g = _guarded(fake, policy="adaptive")
    t = s.acquire_sync("text", W.INTERACTIVE_CHAT, "u1")          # 텍스트 바쁨
    v = s.acquire_sync("vision", W.VISION, "g1", timeout=0.5)      # 막지 않음(부분 offload 감수)
    assert fake.unloads == [] and g.degraded == 1
    v.release(); t.release()


def test_guard_adaptive_swaps_free_when_text_idle():
    fake = _FakeGpu(base_used=1600)
    fake.resident["http://t"] = {"qwen3:14b": 10300}
    s, g = _guarded(fake, policy="adaptive")
    v = s.acquire_sync("vision", W.VISION, "g1", timeout=3)        # 텍스트 한가 → 내리고 VL 전부 GPU
    assert fake.unloads == [("http://t", "qwen3:14b")]
    v.release()


def test_guard_text_is_protected_from_offload():
    """VL 이 상주한 상태에서 텍스트가 적재돼야 하면, VL 이 끝나길 기다렸다가 내리고 텍스트를 올린다."""
    fake = _FakeGpu(base_used=1600)
    fake.resident["http://v"] = {"qwen3-vl:4b-instruct": 4600}   # free = 10103 < 10600+768
    s, g = _guarded(fake, policy="adaptive")
    v = s.acquire_sync("vision", W.VISION, "g1")
    out = []
    th = threading.Thread(target=lambda: out.append(s.acquire_sync("text", W.INTERACTIVE_CHAT, "u1", timeout=5)))
    th.start()
    time.sleep(0.15)
    assert not out and fake.unloads == []                          # 실행 중 VL 은 중단하지 않음
    v.release()
    th.join(5)
    assert out and fake.unloads == [("http://v", "qwen3-vl:4b-instruct")]
    out[0].release()


def test_guard_coexists_when_vram_fits():
    fake = _FakeGpu(base_used=100)                             # FastAPI 임베딩을 CPU 로 옮긴 상태
    fake.resident["http://t"] = {"qwen3:14b": 10300}       # free = 5903 ≥ 4800+768
    s, g = _guarded(fake)
    t = s.acquire_sync("text", W.INTERACTIVE_CHAT, "u1")
    v = s.acquire_sync("vision", W.VISION, "g1", timeout=0.5)
    assert fake.unloads == [] and g.swap_target is None
    v.release(); t.release()


def test_guard_pending_load_prevents_double_load():
    fake = _FakeGpu(base_used=1600)                            # 둘 다 비상주, 각각은 들어가나 합치면 초과
    s, g = _guarded(fake)
    t = s.acquire_sync("text", W.INTERACTIVE_CHAT, "u1")       # 적재 예약(아직 ps 에 안 보임)
    with pytest.raises(GatewayRejected):
        s.acquire_sync("vision", W.VISION, "g1", timeout=0.2)
    t.release()


def test_unknown_telemetry_policy(monkeypatch):
    """텔레메트리를 못 읽으면 여유가 있다고 가정하지 않는다: 비전 신규 적재 거부, 텍스트(주 서비스)는 허용."""
    fake = _FakeGpu()
    monkeypatch.setenv("AI_GW_GPU_GUARD", "true")
    monkeypatch.delenv("AI_GW_UNKNOWN_TELEMETRY_VISION", raising=False)
    g = GpuGuard(ps_fn=lambda u: None, smi_fn=lambda: None, unload_fn=fake.unload)
    g.register("text", "http://t", 10600, protected=True)
    g.register("vision", "http://v", 4800)
    g.refresh(force=True)
    assert g.admissible("vision", {}, {}) == (False, "no_telemetry_deny")
    assert g.admissible("text", {}, {}) == (True, "no_telemetry_primary")
    g.backends["vision"].resident = {"qwen3-vl:4b-instruct": 3406}      # 이미 상주 → 새 적재 아님 → 허용
    assert g.admissible("vision", {}, {})[0] is True
    monkeypatch.setenv("AI_GW_UNKNOWN_TELEMETRY_VISION", "allow")
    g2 = GpuGuard(ps_fn=lambda u: None, smi_fn=lambda: None, unload_fn=fake.unload)
    g2.register("vision", "http://v", 4800)
    assert g2.admissible("vision", {}, {}) == (True, "no_telemetry_allowed")


def test_telemetry_single_failure_uses_recent_sample(monkeypatch):
    monkeypatch.setenv("AI_GW_GPU_GUARD", "true")
    monkeypatch.setenv("AI_GW_TELEMETRY_STALE_S", "5")
    monkeypatch.setenv("AI_GW_TELEMETRY_INTERVAL_S", "0")
    seq = iter([(16303, 1600), None])
    g = GpuGuard(ps_fn=lambda u: {}, smi_fn=lambda: next(seq), unload_fn=lambda *a: True)
    g.register("vision", "http://v", 4800)
    g.refresh(force=True)
    g.refresh(force=True)                       # 두 번째 조회 실패 → 직전 정상 값 유지
    assert g.smi_ok and g.admissible("vision", {}, {}) == (True, "fits")


def test_vision_queue_denied_until_telemetry_returns(monkeypatch):
    """비전 신규 적재는 텔레메트리 복구 전까지 대기하고, 한도를 넘기면 QUEUE_TIMEOUT(→ VISION_QUEUE_TIMEOUT 503)."""
    monkeypatch.setenv("AI_GW_GPU_GUARD", "true")
    monkeypatch.setenv("AI_GW_TELEMETRY_INTERVAL_S", "0")
    state = {"smi": None}
    g = GpuGuard(ps_fn=lambda u: {}, smi_fn=lambda: state["smi"], unload_fn=lambda *a: True)
    g.register("vision", "http://v", 4800)
    s = Scheduler(guard=g)
    s.configure_backend("vision", 1)
    g.refresh(force=True)
    with pytest.raises(GatewayRejected) as ei:
        s.acquire_sync("vision", W.VISION, "g1", timeout=0.3)
    assert ei.value.code == "QUEUE_TIMEOUT"
    state["smi"] = (16303, 1600)
    s.acquire_sync("vision", W.VISION, "g1", timeout=2).release()


# ── 11. 옵션 정규화 ───────────────────────────────────────────────────────
def test_normalize_injects_keep_alive_and_raises_num_ctx(monkeypatch):
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "30m")
    monkeypatch.setenv("STUDYMATE_NUM_CTX", "8192")
    p = {"model": "qwen3:14b", "options": {"num_ctx": 4096, "num_predict": 300}}
    gw.normalize_ollama_payload(p, url="http://127.0.0.1:11434")
    assert p["keep_alive"] == "30m" and p["options"]["num_ctx"] == 8192
    big = {"model": "qwen3:14b", "keep_alive": "5m", "options": {"num_ctx": 16384}}
    gw.normalize_ollama_payload(big, url="http://127.0.0.1:11434")
    assert big["options"]["num_ctx"] == 16384 and big["keep_alive"] == "5m"   # 낮추지/덮지 않음
    other = {"model": "gemma3:12b", "options": {"num_ctx": 2048}}
    gw.normalize_ollama_payload(other, url="http://127.0.0.1:11434")
    assert other == {"model": "gemma3:12b", "options": {"num_ctx": 2048}}


def test_backend_for_url():
    assert gw.backend_for_url("http://localhost:11435") == gw.VISION
    assert gw.backend_for_url("http://127.0.0.1:11434") == gw.TEXT
    assert gw.backend_for_url(None) == gw.TEXT


# ── 12. OpenAI 예산 ──────────────────────────────────────────────────────
def test_budget_cap(monkeypatch):
    monkeypatch.setenv("AI_GW_OPENAI_DAILY_TOKEN_CAP", "1000")
    b = TokenBudget()
    assert b.allow(100)
    b.record("gpt-4o-mini", 600, 300)
    assert not b.allow(200)
    snap = b.snapshot()
    assert snap["usedTokens"] == 900 and snap["denied"] == 1 and snap["estCostUsd"] > 0


# ── 13. 경로 분류 + middleware 컨텍스트(스레드풀/스트리밍 상속 포함) ───────────────
def test_class_for_path():
    assert class_for_path("/api/ai/multi-chat/stream") == W.MULTI_AGENT
    assert class_for_path("/api/ai/vision/analyze") == W.VISION
    assert class_for_path("/api/ai/realtime-quiz/generate") == W.DOCUMENT_QUIZ
    assert class_for_path("/api/ai/major-analysis/note") == W.DOCUMENT_ANALYSIS
    assert class_for_path("/api/materials/5/ai/fetch-stream") == W.DOCUMENT_ANALYSIS
    assert class_for_path("/api/ai/chat") == W.INTERACTIVE_CHAT


def test_middleware_context_and_body_replay():
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse
    from fastapi.testclient import TestClient
    from app.ai_gateway.middleware import AIGatewayContextMiddleware

    app = FastAPI()
    app.add_middleware(AIGatewayContextMiddleware)

    @app.post("/api/ai/multi-chat/stream")
    def sync_stream(body: dict):
        def gen():                      # 동기 제너레이터 → Starlette threadpool 에서 순회
            yield f"{current_class().value}|{current_fair_key()}|{body.get('message')}\n"
        return StreamingResponse(gen(), media_type="text/plain")

    @app.post("/api/ai/quiz/generate")
    async def quiz(body: dict):
        cls = await asyncio.to_thread(lambda: current_class().value)
        return {"cls": cls, "key": current_fair_key(), "n": body["n"]}

    c = TestClient(app)
    # 본문 식별자는 '주장값'(cu:/cg:)으로 구분한다
    r = c.post("/api/ai/multi-chat/stream", json={"userId": 42, "message": "안녕"})
    assert r.text.strip() == "MULTI_AGENT|cu:42|안녕"
    r = c.post("/api/ai/quiz/generate", json={"roomId": "r9", "n": 3})
    assert r.json() == {"cls": "DOCUMENT_QUIZ", "key": "cg:r9", "n": 3}
    # 헤더 식별자는 내부 인증이 맞을 때만 검증값(u:)
    import os
    os.environ["AI_SERVER_API_KEY"] = "k-test"
    try:
        r = c.post("/api/ai/quiz/generate", json={"n": 1, "userId": 99},
                   headers={"X-AI-User-Id": "7", "Authorization": "Bearer k-test"})
        assert r.json()["key"] == "u:7"
        r = c.post("/api/ai/quiz/generate", json={"n": 1, "userId": 99},
                   headers={"X-AI-User-Id": "7", "Authorization": "Bearer wrong"})
        assert r.json()["key"] == "cu:99"         # 인증 실패 → 헤더 무시, 본문 주장값
        r = c.post("/api/ai/quiz/generate", json={"n": 1, "userId": "1; DROP"})
        assert r.json()["key"] == "anon"          # 형식 밖 값은 버린다
    finally:
        os.environ.pop("AI_SERVER_API_KEY", None)


def test_group_round_robin_before_users():
    """사용자 3명이 있는 그룹이 개인 사용자 1명을 밀어내지 않는다(그룹 → 사용자 2단계 라운드로빈)."""
    s = _sched(1)
    hold = s.acquire_sync("t", W.INTERACTIVE_CHAT, "x", group="gx")
    out = []

    def go(key, group):
        th = threading.Thread(target=lambda: out.append(s.acquire_sync("t", W.INTERACTIVE_CHAT, key, group=group)),
                              daemon=True)
        th.start()
    for i, u in enumerate(["a1", "a2", "a3"]):
        go(u, "gA")
        _wait_waiting(s, i + 1)
    go("b1", "gB")
    _wait_waiting(s, 4)
    hold.release()
    order = []
    t0 = time.time()
    while len(order) < 4 and time.time() - t0 < 3:
        if len(out) > len(order):
            lease = out[len(order)]
            order.append(lease._t.key)
            lease.release()
        time.sleep(0.005)
    assert order[:2] == ["a1", "b1"], order


def test_fairness_counters_are_class_scoped():
    """그룹의 비전 요청이 다른 백엔드에서 실행 중이어도 같은 그룹의 멀티에이전트 순번은 밀리지 않는다."""
    s = Scheduler()
    s.configure_backend("t", 1)
    s.configure_backend("v", 1)
    vis = s.acquire_sync("v", W.VISION, "cu:a-sharer", group="cg:A")      # 그룹 A 비전 실행 중
    hold = s.acquire_sync("t", W.MULTI_AGENT, "x", group="gx")
    out = []

    def go(key, group):
        threading.Thread(target=lambda: out.append(s.acquire_sync("t", W.MULTI_AGENT, key, group=group)),
                         daemon=True).start()
    go("cu:a1", "cg:A")
    t0 = time.time()
    while s.snapshot()["backends"]["t"]["waiting"] < 1 and time.time() - t0 < 2:
        time.sleep(0.01)
    go("cu:heavy", "cu:heavy")
    while s.snapshot()["backends"]["t"]["waiting"] < 2 and time.time() - t0 < 2:
        time.sleep(0.01)
    hold.release()
    while not out and time.time() - t0 < 3:
        time.sleep(0.01)
    assert out[0]._t.key == "cu:a1"            # 먼저 온 그룹 A 가 먼저(전역 카운터였다면 heavy 가 이김)
    out[0].release()
    while len(out) < 2 and time.time() - t0 < 3:
        time.sleep(0.01)
    out[1].release()
    vis.release()


def test_per_user_queue_limit_and_anon_exempt(monkeypatch):
    monkeypatch.setenv("AI_GW_INTERACTIVE_CHAT_PER_USER_QUEUE", "2")
    s = _sched(1)
    hold = s.acquire_sync("t", W.INTERACTIVE_CHAT, "busy")
    out = []
    for _ in range(2):
        _bg_acquire(s, W.INTERACTIVE_CHAT, "cu:5", out)
    _wait_waiting(s, 2)
    with pytest.raises(GatewayRejected) as ei:
        s.acquire_sync("t", W.INTERACTIVE_CHAT, "cu:5")
    assert ei.value.code == "USER_LIMIT" and ei.value.http_status == 429
    for _ in range(3):
        _bg_acquire(s, W.INTERACTIVE_CHAT, "anon", out)   # anon 은 사용자 한도 제외(클래스 한도만)
    _wait_waiting(s, 5)
    hold.release()
    t0 = time.time()
    done = 0
    while done < 5 and time.time() - t0 < 3:
        if len(out) > done:
            out[done][2].release()
            done += 1
        time.sleep(0.005)
    assert done == 5


def test_internal_gateway_error_fails_open(monkeypatch):
    s = gw.get_scheduler()

    def boom(*a, **k):
        raise RuntimeError("scheduler bug")
    monkeypatch.setattr(s, "acquire_sync", boom)
    before = gw.status()["internalErrors"]
    with gw.llm_slot(url="http://127.0.0.1:11434") as lease:
        assert lease is None                       # 추론은 슬롯 없이 그대로 진행
    assert gw.status()["internalErrors"] == before + 1
    with pytest.raises(GatewayRejected):           # 의도한 거부는 그대로 전달
        monkeypatch.setattr(s, "acquire_sync", lambda *a, **k: (_ for _ in ()).throw(
            GatewayRejected("QUEUE_FULL", "x")))
        with gw.llm_slot(url="http://127.0.0.1:11434"):
            pass


def test_adaptive_swap_requires_idle_period_no_pingpong(monkeypatch):
    """텍스트가 방금(swap_idle_s 이내) 쓰였으면 비전 때문에 내리지 않는다 → 번갈아 올 때 재적재 핑퐁 방지."""
    monkeypatch.setenv("AI_GW_SWAP_IDLE_S", "0.3")
    fake = _FakeGpu(base_used=1600)
    fake.resident["http://t"] = {"qwen3:14b": 10300}
    s, g = _guarded(fake, policy="adaptive")
    g.swap_idle_s = 0.3
    s.acquire_sync("text", W.INTERACTIVE_CHAT, "u1").release()            # 방금 텍스트 사용
    v = s.acquire_sync("vision", W.VISION, "g1", timeout=0.5)
    assert fake.unloads == [] and g.degraded == 1                          # 공존(축출 없음)
    v.release()
    fake.resident["http://v"] = {}
    g.backends["vision"].resident = {}
    g.backends["vision"].pending_load_until = 0
    time.sleep(0.35)                                                       # 텍스트 한가
    s.acquire_sync("vision", W.VISION, "g2", timeout=3).release()
    assert fake.unloads == [("http://t", "qwen3:14b")]


def test_repromote_degraded_vision_when_text_idle(monkeypatch):
    """부분 offload 로 상주 중인 VL 은 텍스트가 충분히 한가해지면 둘 다 내리고 전량 GPU 로 다시 올린다."""
    monkeypatch.setenv("AI_GW_SWAP_IDLE_S", "0.2")
    fake = _FakeGpu(base_used=1600)
    fake.resident["http://t"] = {"qwen3:14b": 10300}
    fake.resident["http://v"] = {"qwen3-vl:4b-instruct": 4600}
    fake.partial.add("qwen3-vl:4b-instruct")
    s, g = _guarded(fake, policy="adaptive")
    g.swap_idle_s = 0.2
    s.acquire_sync("text", W.INTERACTIVE_CHAT, "u1").release()          # 텍스트 방금 사용
    s.acquire_sync("vision", W.VISION, "g1", timeout=0.5).release()     # 아직 한가하지 않음 → 열화 상태 그대로 사용
    assert fake.unloads == [] and g.repromotions == 0
    time.sleep(0.25)
    v = s.acquire_sync("vision", W.VISION, "g2", timeout=3)             # 텍스트 한가 → 재승격
    assert ("http://t", "qwen3:14b") in fake.unloads and ("http://v", "qwen3-vl:4b-instruct") in fake.unloads
    assert g.repromotions == 1
    v.release()


def test_repromote_cooldown_and_busy_text_block_it(monkeypatch):
    monkeypatch.setenv("AI_GW_SWAP_IDLE_S", "0")
    fake = _FakeGpu(base_used=1600)
    fake.resident["http://t"] = {"qwen3:14b": 10300}
    fake.resident["http://v"] = {"qwen3-vl:4b-instruct": 4600}
    fake.partial.add("qwen3-vl:4b-instruct")
    s, g = _guarded(fake, policy="adaptive")
    t = s.acquire_sync("text", W.INTERACTIVE_CHAT, "u1")                 # 텍스트 사용 중 → 재승격 안 함
    s.acquire_sync("vision", W.VISION, "g1", timeout=0.5).release()
    assert g.repromotions == 0
    t.release()
    g.backends["vision"].last_repromote = time.monotonic()               # 방금 재승격했음 → cooldown
    s.acquire_sync("vision", W.VISION, "g2", timeout=0.5).release()
    assert g.repromotions == 0 and fake.unloads == []


def test_workload_override():
    with workload(W.BACKGROUND_AI_JOB, "job"):
        assert current_class() == W.BACKGROUND_AI_JOB and current_fair_key() == "job"
    assert current_class() == W.INTERACTIVE_CHAT


# ── 14. 호출부 통합: 계약 불변 ─────────────────────────────────────────────
class _Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._d


def test_ask_ollama_through_gateway(monkeypatch):
    from app.services import ollama_client as oc
    monkeypatch.setattr(oc, "OLLAMA_KEEP_ALIVE", "")
    monkeypatch.setenv("AI_GW_TEXT_KEEP_ALIVE", "30m")
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen.update(json)
        return _Resp({"message": {"content": " 답변 "}})
    monkeypatch.setattr(oc.requests, "post", fake_post)
    monkeypatch.setattr(oc, "OLLAMA_MODEL", "qwen3:14b")
    assert oc.ask_ollama("s", "u") == "답변"
    assert seen["keep_alive"] == "30m"
    snap = gw.status()["scheduler"]
    assert snap["classes"]["INTERACTIVE_CHAT"]["completed"] == 1
    assert snap["backends"]["ollama_text"]["inflight"] == 0


def test_ask_ollama_rejection_maps_to_timeout_text(monkeypatch):
    from app.services import ollama_client as oc
    monkeypatch.setenv("AI_GW_INTERACTIVE_CHAT_QUEUE_TIMEOUT_S", "0.1")
    s = gw.get_scheduler()
    hold = s.acquire_sync("ollama_text", W.INTERACTIVE_CHAT, "x")
    called = []
    monkeypatch.setattr(oc.requests, "post", lambda *a, **k: called.append(1))
    out = oc.ask_ollama("s", "u", timeout=5)
    hold.release()
    assert called == [] and out == oc._timeout_fallback(5)


def test_llm_gateway_queue_timeout_and_cancel(monkeypatch):
    from app.studymate import llm_gateway as lg
    from app.studymate.cancellation import CancelToken, CancelledByClient
    lg.set_transport(lambda req: iter([{"message": {"content": "ok"}, "done": True}]))
    try:
        req = lg.LLMRequest(task="t", system="s", user="u", model="qwen3:14b", num_ctx=8192,
                            num_predict=10, temperature=0.1, top_p=0.9, timeout_s=30)
        assert lg.generate(req).content == "ok"
        s = gw.get_scheduler()
        hold = s.acquire_sync("ollama_text", W.MULTI_AGENT, "x")
        with pytest.raises(lg.LLMTimeout):
            lg.generate(req, deadline=time.time() + 1.3)
        tok = CancelToken()
        threading.Timer(0.2, tok.cancel).start()
        with pytest.raises(CancelledByClient):
            lg.generate(req, cancel=tok)
        hold.release()
        assert s.snapshot()["backends"]["ollama_text"]["inflight"] == 0
    finally:
        lg.set_transport(None)


def test_stream_ollama_releases_slot_on_client_close(monkeypatch):
    from app.services import ai_fetch_stream_service as fs

    class _SResp:
        status_code = 200
        closed = False

        def raise_for_status(self):
            pass

        def iter_lines(self, decode_unicode=False):
            for i in range(100):
                yield b'{"message":{"content":"x"},"done":false}'

        def close(self):
            _SResp.closed = True
    monkeypatch.setattr(fs.requests, "post", lambda *a, **k: _SResp())
    g = fs.stream_ollama("s", "u", model="qwen3:14b")
    assert next(g) == "x"
    assert gw.get_scheduler().snapshot()["backends"]["ollama_text"]["inflight"] == 1
    g.close()                                   # 클라이언트 이탈
    assert _SResp.closed
    assert gw.get_scheduler().snapshot()["backends"]["ollama_text"]["inflight"] == 0


# ── 2026-10-28 독립 리뷰 결함 회귀 테스트 ──────────────────────────────────────
def test_breaker_probe_released_when_result_unreported(monkeypatch):
    """half-open 탐침이 성공/실패 보고 없이 끝나면(읽기 timeout 등) 회로가 영구히 막히지 않는다."""
    monkeypatch.setenv("AI_GW_BREAKER_COOLDOWN_S", "0.05")
    b = gw.breaker("ollama_text")
    b.cooldown_s = 0.05
    for _ in range(5):
        b.record_failure()
    time.sleep(0.06)
    with gw.llm_slot(url="http://127.0.0.1:11434") as lease:     # 탐침 — 결과 미보고(읽기 timeout 모사)
        assert lease is not None
    with gw.llm_slot(url="http://127.0.0.1:11434") as lease2:    # 반납됐으므로 다음 요청이 다시 탐침
        lease2.backend_ok()
    assert b.state == "closed"


def test_breaker_probe_released_on_queue_rejection(monkeypatch):
    monkeypatch.setenv("AI_GW_INTERACTIVE_CHAT_QUEUE_TIMEOUT_S", "0.1")
    b = gw.breaker("ollama_text")
    b.cooldown_s = 0.01
    s = gw.get_scheduler()
    hold = s.acquire_sync("ollama_text", W.INTERACTIVE_CHAT, "x")
    for _ in range(5):
        b.record_failure()
    time.sleep(0.02)
    with pytest.raises(GatewayRejected) as ei:
        with gw.llm_slot(url="http://127.0.0.1:11434"):
            pass
    assert ei.value.code == "QUEUE_TIMEOUT"
    hold.release()
    with gw.llm_slot(url="http://127.0.0.1:11434") as lease:      # CIRCUIT_OPEN 이 아니라 탐침으로 통과
        lease.backend_ok()
    assert b.state == "closed"


def test_executor_propagates_gateway_context():
    from app.ai_gateway.context import ContextThreadPoolExecutor
    from app.services import multi_agent_service as mas
    import main as main_mod
    assert mas.ThreadPoolExecutor is ContextThreadPoolExecutor
    assert main_mod.ThreadPoolExecutor is ContextThreadPoolExecutor
    with workload(W.MULTI_AGENT, "u:42"):
        with ContextThreadPoolExecutor(max_workers=3) as ex:
            got = list(ex.map(lambda _: (current_class(), current_fair_key()), range(3)))
    assert got == [(W.MULTI_AGENT, "u:42")] * 3
    with ContextThreadPoolExecutor(max_workers=1, wclass=W.BACKGROUND_AI_JOB) as ex:
        assert ex.submit(current_class).result() == W.BACKGROUND_AI_JOB


def test_swap_wait_keeps_other_backend_served_during_min_residency(monkeypatch):
    """swap 대기 중이라도 최소 상주 시간 동안은 다른 쪽(텍스트) 요청을 계속 처리한다(양쪽 유휴 금지)."""
    fake = _FakeGpu(base_used=1600)
    fake.resident["http://t"] = {"qwen3:14b": 10300}
    s, g = _guarded(fake, policy="swap")
    g.min_residency_s = 1.0
    g.backends["text"].resident_since = time.monotonic()       # 방금 적재됨
    t1 = s.acquire_sync("text", W.INTERACTIVE_CHAT, "u1")
    out = []
    th = threading.Thread(target=lambda: out.append(s.acquire_sync("vision", W.VISION, "g1", timeout=5)), daemon=True)
    th.start()
    time.sleep(0.1)
    assert g.swap_target == "vision"
    got = []
    th2 = threading.Thread(target=lambda: got.append(s.acquire_sync("text", W.INTERACTIVE_CHAT, "u2", timeout=0.5)),
                           daemon=True)
    th2.start()                                                  # 텍스트 대기자가 있는 상태에서 반환
    time.sleep(0.05)
    t1.release()
    th2.join(1)
    assert got and fake.unloads == []                            # 상주 1초 미만 → 텍스트 계속 처리(축출 보류)
    got[0].release()
    th.join(5)
    assert out and fake.unloads == [("http://t", "qwen3:14b")]
    out[0].release()


def test_degraded_admission_clears_swap_target():
    fake = _FakeGpu(base_used=1600)
    fake.resident["http://t"] = {"qwen3:14b": 10300}
    s, g = _guarded(fake, policy="adaptive")
    g.swap_target = "vision"                                     # 이전에 걸려 있던 swap
    t = s.acquire_sync("text", W.INTERACTIVE_CHAT, "u1")         # 텍스트 바쁨 → 비전은 열화 공존으로 허용
    v = s.acquire_sync("vision", W.VISION, "g1", timeout=0.5)
    assert g.swap_target is None
    t.release()
    t2 = s.acquire_sync("text", W.INTERACTIVE_CHAT, "u2", timeout=0.3)   # 텍스트가 묶이지 않는다
    t2.release()
    v.release()


def test_evicting_backend_is_not_granted():
    fake = _FakeGpu(base_used=1600)
    fake.resident["http://t"] = {"qwen3:14b": 10300}
    s, g = _guarded(fake, policy="adaptive")
    g._evicting_backends = {"text"}
    with pytest.raises(GatewayRejected):
        s.acquire_sync("text", W.INTERACTIVE_CHAT, "u1", timeout=0.2)
    g._evicting_backends = set()
    s.acquire_sync("text", W.INTERACTIVE_CHAT, "u1", timeout=0.3).release()


def test_enqueue_failure_does_not_leak_ticket(monkeypatch):
    s = _sched(1)
    monkeypatch.setattr(s, "_ensure_ticker", lambda: (_ for _ in ()).throw(RuntimeError("thread start failed")))
    with pytest.raises(RuntimeError):
        s.acquire_sync("t", W.INTERACTIVE_CHAT, "u1")
    snap = s.snapshot()["backends"]["t"]
    assert snap["waiting"] == 0 and snap["inflight"] == 0


def test_stale_telemetry_is_not_trusted(monkeypatch):
    monkeypatch.setenv("AI_GW_GPU_GUARD", "true")
    monkeypatch.setenv("AI_GW_TELEMETRY_STALE_S", "5")
    g = GpuGuard(ps_fn=lambda u: {}, smi_fn=lambda: (16303, 1600), unload_fn=lambda *a: True)
    g.register("vision", "http://v", 4800)
    g.refresh(force=True)
    assert g.admissible("vision", {}, {})[0] is True
    g.smi_at -= 60                                               # 마지막 샘플이 오래됨(ticker 정지 후 첫 요청)
    assert g.admissible("vision", {}, {}) == (False, "no_telemetry_deny")


def test_pdf_vl_caption_backs_off_after_gateway_rejection(monkeypatch):
    from app.services import ollama_vision_client as ovc
    monkeypatch.setenv("PDF_VL_BASE_URL", "http://127.0.0.1:11435")
    monkeypatch.setenv("PDF_VL_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("AI_GW_DOCUMENT_ANALYSIS_QUEUE_TIMEOUT_S", "0.2")
    monkeypatch.setattr(ovc, "_GW_BACKOFF_UNTIL", 0.0)
    called = []
    monkeypatch.setattr(ovc.requests, "post", lambda *a, **k: called.append(1))
    s = gw.get_scheduler()
    hold = s.acquire_sync("ollama_vision", W.VISION, "busy")
    with workload(W.DOCUMENT_ANALYSIS, "u:1"):
        t0 = time.time()
        with pytest.raises(GatewayRejected):
            ovc.caption_page_image(b"\x89PNG", 1)
        first = time.time() - t0
        t0 = time.time()
        with pytest.raises(GatewayRejected):
            ovc.caption_page_image(b"\x89PNG", 2)                # 백오프 → 즉시 실패
        second = time.time() - t0
    hold.release()
    assert called == [] and first >= 0.15 and second < 0.05
