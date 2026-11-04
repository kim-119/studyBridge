"""측정 하네스(scripts/quality_gate_contention_probe.py)의 GPU 가드 — 운영 GPU 를 함부로 점유하지 않는다."""
from __future__ import annotations

import subprocess
import sys
import time

from scripts.quality_gate_contention_probe import (GPU_LIMITS, gpu_abort_decision, gpu_preflight_decision, pct, summary)

OK = {"vramUsedMiB": 1000, "vramTotalMiB": 16303, "util": 0, "tempC": 35}


def test_preflight_passes_only_on_idle_cool_gpu():
    assert gpu_preflight_decision(OK, ["qwen3:14b"], ["qwen3:14b"]) == []
    assert any(r.startswith("GPU_BUSY") for r in gpu_preflight_decision({**OK, "util": 55}, [], ["qwen3:14b"]))
    assert any(r.startswith("GPU_HOT") for r in gpu_preflight_decision({**OK, "tempC": 56}, [], ["qwen3:14b"]))
    assert "VRAM_HEADROOM_LOW" in gpu_preflight_decision({**OK, "vramUsedMiB": 14000}, [], ["qwen3:14b"])
    assert any(r.startswith("OTHER_MODELS_LOADED") for r in gpu_preflight_decision(OK, ["qwen3-vl:4b"], ["qwen3:14b"]))


def test_abort_rules_follow_thermal_guard():
    t0 = time.time()
    assert gpu_abort_decision(OK, 0, t0, 0) is None
    assert gpu_abort_decision({**OK, "tempC": GPU_LIMITS["abortTempC"]}, 0, t0, 0) == "ABORT_TEMP"
    assert gpu_abort_decision({**OK, "vramUsedMiB": 15400}, 0, t0, 0) == "ABORT_VRAM"
    assert gpu_abort_decision(OK, 3, t0, 0) == "ABORT_ERRORS"
    assert gpu_abort_decision(OK, 0, t0 - 601, 0) == "ABORT_WALL"
    assert gpu_abort_decision(OK, 0, t0, 120) == "ABORT_CALLS"


def test_gpu_phase_requires_two_explicit_opt_ins(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_CONTENTION_PROBE_ALLOW", raising=False)
    r = subprocess.run([sys.executable, "-m", "scripts.quality_gate_contention_probe", "--phase", "gpu", "--allow-gpu",
                        "--out", str(tmp_path / "x.json")], capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "GPU_PHASE_NOT_AUTHORIZED" in (r.stderr + r.stdout)


def test_percentiles():
    xs = [float(i) for i in range(1, 101)]
    assert pct(xs, 0.5) == 51.0 and pct(xs, 0.95) == 95.0 and pct([], 0.5) == 0.0
    assert summary(xs)["max"] == 100.0 and summary([])["n"] == 0
