"""GPU 메모리 보호 + 모델 상주(residency) 조정.

배경(2026-10-27 실측): 시스템 Ollama(:11434, qwen3:14b)와 사용자 공간 Ollama(:11435, qwen3-vl:4b)는
서로의 VRAM 사용을 모른다. 합계가 16GB 를 넘으면 늦게 적재된 쪽이 레이어 일부를 CPU 로 내려
(40/41, 30/37 layers) keep_alive 동안 계속 느려진다(q14b 82→38 tok/s, VL 1.5→9s).

두 데몬의 유일한 클라이언트인 FastAPI 가 중재한다:
  * 대상 모델이 이미 상주 중이면 → 통과(새 적재 없음).
  * 상주하지 않으면 → nvidia-smi 여유 VRAM 이 (모델 footprint + 안전 여유) 이상일 때만 통과.
  * 부족하면:
      - 보호 백엔드(텍스트 qwen3:14b): 절대 부분 offload 로 적재시키지 않는다 → 다른 쪽 신규 배정을 멈춰
        drain 하고 in-flight 0 이 되면 keep_alive=0 으로 내린 뒤 통과(실행 중 요청은 중단하지 않음).
        (q14b 가 offload 되면 keep_alive(30m) 내내 전 채팅이 82→38 tok/s)
      - 비보호 백엔드(비전) 정책 AI_GW_VISION_PRESSURE_POLICY:
          adaptive(기본) 텍스트가 바쁘거나 최근 AI_GW_SWAP_IDLE_S(30s) 안에 쓰였으면 막지 않고 VL 부분 offload
                         공존 허용(실측 단건 4.2s, 텍스트 82 tok/s 유지). 그보다 오래 한가했을 때만 텍스트를 내리고
                         VL 을 전부 GPU 에(실측 0.56s warm). 최근 사용 조건이 없으면 비전·채팅이 번갈아 올 때마다
                         내렸다 올리는 핑퐁(회당 1.3~1.7s 재적재)이 생긴다.
          swap           항상 텍스트 drain → 축출 후 VL 적재
          coexist        항상 통과(가드 이전 동작)
  * 재승격: 대상 모델이 상주 중이어도 부분 offload 상태(/api/ps size_vram < size)면, 다른 백엔드가 한가할 때
    (비보호 대상은 AI_GW_SWAP_IDLE_S 이상) 둘 다 내리고 다시 전량 GPU 로 적재한다. 부하 중 열화 공존으로 올라간
    VL 이 이후 텍스트가 한가해져도 keep_alive 가 계속 갱신돼 열화 상태로 남던 문제(2026-10-27 실측: 1건 7~16s,
    전량 GPU 일 때 1.0~2.9s). 재적재 반복은 AI_GW_REPROMOTE_COOLDOWN_S(60s)로 막는다.
  * 텔레메트리(nvidia-smi)를 못 읽으면 '여유가 있다'고 가정하지 않는다(AI_GW_TELEMETRY_STALE_S 초 이내의
    마지막 정상 값까지만 사용):
      - 이미 상주한 모델로 가는 요청 → 새 적재가 없으므로 통과
      - 보호 백엔드(텍스트) 신규 적재 → 통과(주 서비스. Ollama 가 자체 NVML 로 적재 가능량을 계산해 OOM 대신
        부분 offload 로 떨어진다) + 경고 로그/카운터
      - 비보호 백엔드(비전) 신규 적재 → 기본 거부(AI_GW_UNKNOWN_TELEMETRY_VISION=deny). 텔레메트리가 돌아오면
        그때 판정하고, 대기 한도를 넘기면 503 으로 끝난다.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _fl(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class BackendSpec:
    name: str
    base_url: str
    footprint_mib: int
    resident: Dict[str, int] = field(default_factory=dict)   # model -> size_vram MiB
    resident_since: float = 0.0
    ps_ok: bool = False
    pending_load_until: float = 0.0   # 배정했지만 아직 /api/ps 에 안 보이는 적재(이중 적재 경합 방지)
    protected: bool = False           # True 면 부분 offload 적재를 절대 허용하지 않음
    last_active: float = 0.0          # 마지막 배정/반환 시각(adaptive swap 의 '한가함' 판정)
    offloaded: bool = False           # 상주 모델 일부가 CPU 에 있음(size_vram < size)
    last_repromote: float = -1e9


def _default_ps(base_url: str) -> Optional[Dict[str, int]]:
    try:
        r = requests.get(f"{base_url}/api/ps", timeout=1.5)
        if r.status_code != 200:
            return None
        out: Dict[str, Tuple[int, int]] = {}
        for m in r.json().get("models", []) or []:
            vram = int(m.get("size_vram") or 0) // (1024 * 1024)
            total = int(m.get("size") or 0) // (1024 * 1024) or vram
            out[str(m.get("name") or m.get("model"))] = (vram, total)
        return out
    except Exception:
        return None


def _default_smi() -> Optional[Tuple[int, int]]:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode != 0:
            return None
        total, used = out.stdout.strip().splitlines()[0].split(",")
        return int(total), int(used)
    except Exception:
        return None


def _default_unload(base_url: str, model: str) -> bool:
    try:
        r = requests.post(f"{base_url}/api/generate", json={"model": model, "keep_alive": 0}, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


class GpuGuard:
    def __init__(self, *, ps_fn: Callable = _default_ps, smi_fn: Callable = _default_smi,
                 unload_fn: Callable = _default_unload) -> None:
        self.enabled = os.getenv("AI_GW_GPU_GUARD", "true").strip().lower() in ("1", "true", "yes", "on")
        self.margin_mib = _i("AI_GW_VRAM_MARGIN_MIB", 768)
        self.min_residency_s = _fl("AI_GW_MIN_RESIDENCY_S", 15.0)
        self.refresh_interval_s = _fl("AI_GW_TELEMETRY_INTERVAL_S", 1.0)
        self._ps_fn, self._smi_fn, self._unload_fn = ps_fn, smi_fn, unload_fn
        self._lock = threading.RLock()
        self.backends: Dict[str, BackendSpec] = {}
        self.gpu_total = 0
        self.gpu_used = 0
        self.gpu_used_peak = 0
        self.smi_ok = False
        self.smi_at = 0.0                 # 마지막 정상 nvidia-smi 시각
        self.stale_s = _fl("AI_GW_TELEMETRY_STALE_S", 10.0)
        self.swap_idle_s = _fl("AI_GW_SWAP_IDLE_S", 30.0)
        self.unknown_vision_policy = os.getenv("AI_GW_UNKNOWN_TELEMETRY_VISION", "deny").strip().lower()
        self.unknown_telemetry_denials = 0
        self.unknown_telemetry_primary_loads = 0
        self._last_refresh = 0.0
        self.swap_target: Optional[str] = None
        self.evicting = False
        self._evicting_backends: set = set()      # 지금 내리는 중인 백엔드 — 이쪽으로는 배정하지 않는다
        self.swap_fail_until = 0.0                # 언로드가 실패하면 잠시 swap 을 포기하고 열화 공존으로 진행
        self.swap_failures = 0
        self.evictions = 0
        self.denials = 0
        self.degraded = 0
        self.repromotions = 0
        self.repromote_cooldown_s = _fl("AI_GW_REPROMOTE_COOLDOWN_S", 60.0)
        self.vision_policy = os.getenv("AI_GW_VISION_PRESSURE_POLICY", "adaptive").strip().lower()
        self.on_change: Optional[Callable[[], None]] = None

    # ── 등록/텔레메트리 ────────────────────────────────────────────────────
    def register(self, name: str, base_url: str, footprint_mib: int, *, protected: bool = False) -> None:
        with self._lock:
            if name not in self.backends:
                self.backends[name] = BackendSpec(name, base_url.rstrip("/"), int(footprint_mib), protected=protected)

    def refresh(self, force: bool = False) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        with self._lock:
            if not force and now - self._last_refresh < self.refresh_interval_s:
                return
            self._last_refresh = now
            specs = list(self.backends.values())
        # 순서 중요: /api/ps 를 먼저, nvidia-smi 를 나중에 읽는다. 반대로 읽으면 두 조회 사이에 적재가 끝난 모델이
        # '상주'로 보이면서 VRAM 사용량에는 빠져 여유가 있다고 오판한다(2026-10-27 재현). 이 순서면 오차가
        # 항상 보수적(사용량 과대) 방향이다.
        ps = {s.name: self._ps_fn(s.base_url) for s in specs}
        smi = self._smi_fn()
        with self._lock:
            if smi:
                self.gpu_total, self.gpu_used = smi
                self.gpu_used_peak = max(self.gpu_used_peak, self.gpu_used)
                self.smi_ok = True
                self.smi_at = now
            else:
                # 한 번 실패로 바로 '불명'이 되지 않게 stale_s 동안은 마지막 정상 값을 쓴다.
                self.smi_ok = self.smi_at > 0 and now - self.smi_at <= self.stale_s
            for s in specs:
                res = ps.get(s.name)
                s.ps_ok = res is not None
                if res is None:
                    continue
                norm = {m: (v if isinstance(v, tuple) else (int(v), int(v))) for m, v in res.items()}
                if norm and not s.resident:
                    s.resident_since = now
                if norm:
                    s.pending_load_until = 0.0
                s.resident = {m: v[0] for m, v in norm.items()}
                s.offloaded = any(v[1] > 0 and v[0] < v[1] * 0.97 for v in norm.values())

    # ── 판정 ─────────────────────────────────────────────────────────────
    def _telemetry_fresh(self) -> bool:
        return self.smi_ok and time.monotonic() - self.smi_at <= self.stale_s

    def free_mib(self, exclude: Optional[str] = None) -> int:
        now = time.monotonic()
        reserved = sum(s.footprint_mib for s in self.backends.values()
                       if s.name != exclude and not s.resident and s.pending_load_until > now)
        return max(0, self.gpu_total - self.gpu_used - reserved)

    def note_granted(self, backend: str) -> None:
        """비상주 백엔드에 배정했으면 적재가 /api/ps 에 보일 때까지 footprint 를 예약해 둔다."""
        with self._lock:
            spec = self.backends.get(backend)
            if spec is None:
                return
            spec.last_active = time.monotonic()
            if not spec.resident:
                spec.pending_load_until = time.monotonic() + _fl("AI_GW_PENDING_LOAD_S", 60.0)

    def admissible(self, backend: str, inflight: Dict[str, int], waiting: Dict[str, int]) -> Tuple[bool, str]:
        """backend 로 새 요청을 보내도 되는지. 스케줄러 lock 안에서 호출되므로 I/O 없음."""
        if not self.enabled:
            return True, "guard_off"
        with self._lock:
            spec = self.backends.get(backend)
            if spec is None:
                return True, "unknown_backend"
            if spec.resident and spec.offloaded and self.vision_policy != "coexist" and not self.evicting:
                now_r = time.monotonic()
                others = [o for o in self.backends.values() if o.name != backend and o.resident]
                idle = all(inflight.get(o.name, 0) == 0 and waiting.get(o.name, 0) == 0
                           and (spec.protected or now_r - o.last_active >= self.swap_idle_s) for o in others)
                if others and idle and inflight.get(backend, 0) == 0 \
                        and now_r - spec.last_repromote >= self.repromote_cooldown_s \
                        and now_r >= self.swap_fail_until:
                    spec.last_repromote = now_r
                    self.swap_target = backend
                    self.repromotions += 1
                    logger.info("[AI_GW] repromote %s (partially offloaded) — unloading %s + self",
                                backend, [o.name for o in others])
                    self._start_evict(others + [spec], "ai-gw-repromote")
                    return False, "repromote"
            if spec.resident or spec.pending_load_until > time.monotonic():
                if self.swap_target == backend:
                    self.swap_target = None
                return True, "resident"
            if not self._telemetry_fresh():
                if spec.protected:
                    self.unknown_telemetry_primary_loads += 1
                    logger.warning("[AI_GW] GPU telemetry unavailable — primary backend %s load allowed", backend)
                    return True, "no_telemetry_primary"
                if self.unknown_vision_policy == "allow":
                    return True, "no_telemetry_allowed"
                self.unknown_telemetry_denials += 1
                return False, "no_telemetry_deny"
            if self.free_mib(exclude=backend) - spec.footprint_mib >= self.margin_mib:
                if self.swap_target == backend:
                    self.swap_target = None
                return True, "fits"
            others = [o for o in self.backends.values()
                      if o.name != backend and (o.resident or o.pending_load_until > time.monotonic())]
            if not others:
                # 비울 수 있는 우리 쪽 모델이 없다(외부 프로세스 점유). 더 기다려도 해결 안 되므로 통과.
                self._clear_swap_locked(backend)
                return True, "no_evictable"
            if time.monotonic() < self.swap_fail_until:
                # 직전 언로드가 실패했다 → 무한 재시도로 다른 쪽을 얼리지 않고 열화 공존으로 진행
                self._clear_swap_locked(backend)
                self.degraded += 1
                return True, "swap_failed_fallback"
            if not spec.protected:
                if self.vision_policy == "coexist":
                    self._clear_swap_locked(backend)
                    self.degraded += 1
                    return True, "coexist"
                now_t = time.monotonic()
                if self.vision_policy == "adaptive" and any(
                        inflight.get(o.name, 0) > 0 or waiting.get(o.name, 0) > 0
                        or now_t - o.last_active < self.swap_idle_s for o in others):
                    self._clear_swap_locked(backend)
                    self.degraded += 1
                    return True, "degraded_coexist"
            if self.swap_target != backend:
                logger.info("[AI_GW] swap requested target=%s free=%sMiB need=%sMiB+%s others=%s",
                            backend, self.free_mib(exclude=backend), spec.footprint_mib, self.margin_mib,
                            [o.name for o in others])
            self.swap_target = backend
            self.denials += 1
            now = time.monotonic()
            ready = all(
                inflight.get(o.name, 0) == 0
                and (waiting.get(o.name, 0) == 0 or now - o.resident_since >= self.min_residency_s)
                for o in others
            )
            if ready and not self.evicting:
                self._start_evict([o for o in others if o.resident], "ai-gw-evict")
            return False, "vram_swap_pending"

    def _clear_swap_locked(self, backend: str) -> None:
        if self.swap_target == backend:
            self.swap_target = None

    def _start_evict(self, specs: List[BackendSpec], name: str) -> None:
        """lock 보유 상태에서 호출. 축출 대상 백엔드는 축출이 끝날 때까지 배정 금지."""
        self.evicting = True
        self._evicting_backends = {o.name for o in specs}
        targets = [(o.base_url, list(o.resident)) for o in specs]
        threading.Thread(target=self._evict, args=(targets,), name=name, daemon=True).start()

    def note_released(self, backend: str) -> None:
        """요청이 끝났는데 아직 상주로 안 보이면(적재 실패 등) 예약을 곧 풀어 다른 백엔드를 막지 않는다."""
        with self._lock:
            spec = self.backends.get(backend)
            if spec is None:
                return
            spec.last_active = time.monotonic()
            if not spec.resident and spec.pending_load_until:
                spec.pending_load_until = min(spec.pending_load_until, time.monotonic() + 3.0)

    def clear_swap(self, backend: str) -> None:
        with self._lock:
            if self.swap_target == backend:
                self.swap_target = None

    def blocks(self, backend: str) -> bool:
        """swap 진행 중에는 비워질 쪽 백엔드의 신규 배정을 멈춰 drain 시킨다."""
        if not self.enabled:
            return False
        with self._lock:
            if backend in self._evicting_backends:
                return True             # 내리는 중인 모델로 새 요청을 보내지 않는다
            spec = self.backends.get(backend)
            if self.swap_target is None or self.swap_target == backend or spec is None:
                return False
            if spec.resident and time.monotonic() - spec.resident_since < self.min_residency_s:
                return False            # 최소 상주 시간 동안은 계속 처리(GPU 를 놀리며 기다리지 않는다)
            return bool(spec.resident) or spec.pending_load_until > time.monotonic()

    def _evict(self, targets: List[Tuple[str, List[str]]]) -> None:
        try:
            for base_url, models in targets:
                for m in models:
                    ok = self._unload_fn(base_url, m)
                    logger.info("[AI_GW] evict model=%s base=%s ok=%s", m, base_url, ok)
            deadline = time.monotonic() + _fl("AI_GW_EVICT_WAIT_S", 15.0)
            still = True
            while time.monotonic() < deadline:
                self.refresh(force=True)
                with self._lock:
                    still = any(s.resident for s in self.backends.values()
                                if any(s.base_url == b for b, _ in targets))
                if not still:
                    break
                time.sleep(0.3)
            with self._lock:
                self.evictions += 1
                if still:
                    # 언로드 실패(모델이 계속 상주) → 반복 재시도로 다른 쪽을 얼리지 않게 잠시 swap 포기
                    self.swap_failures += 1
                    self.swap_fail_until = time.monotonic() + _fl("AI_GW_SWAP_FAIL_BACKOFF_S", 60.0)
                    self.swap_target = None
                    logger.error("[AI_GW] eviction did not complete within wait — swap disabled for backoff")
        finally:
            with self._lock:
                self.evicting = False
                self._evicting_backends = set()
            cb = self.on_change
            if cb:
                cb()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "enabled": self.enabled,
                "gpuTotalMiB": self.gpu_total, "gpuUsedMiB": self.gpu_used, "gpuUsedPeakMiB": self.gpu_used_peak,
                "telemetryOk": self.smi_ok, "marginMiB": self.margin_mib,
                "unknownTelemetryVisionPolicy": self.unknown_vision_policy,
                "unknownTelemetryDenials": self.unknown_telemetry_denials,
                "unknownTelemetryPrimaryLoads": self.unknown_telemetry_primary_loads,
                "swapIdleS": self.swap_idle_s,
                "swapTarget": self.swap_target, "evicting": self.evicting,
                "evictions": self.evictions, "denials": self.denials, "degradedCoexist": self.degraded,
                "repromotions": self.repromotions, "swapFailures": self.swap_failures,
                "visionPolicy": self.vision_policy,
                "backends": {n: {"resident": dict(s.resident), "offloaded": s.offloaded,
                                 "footprintMiB": s.footprint_mib, "psOk": s.ps_ok}
                             for n, s in self.backends.items()},
            }
