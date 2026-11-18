"""실제 GPU 전후 비교(저부하): 동일 A~D 혼합(온도 0) × 3 구성 × N=4/10.

  before      : 게이트웨이 OFF, 운영 데몬(:11434, NUM_PARALLEL=1 f16) + 비전 데몬(:11435) — 현재 운영 동작
  after_code  : 게이트웨이 ON(adaptive GPU 가드), 같은 데몬
  after_tuned : 게이트웨이 ON(slots=2), 격리 튜닝 데몬(:11436, NUM_PARALLEL=2 + FA + KV q8_0)
안전장치/복구는 real_gpu_probe.py 와 같다(운영 트래픽 감지 시 중단, VRAM 15800MiB 중단, 종료 시 언로드).
usage: python real_compare.py OUT_DIR
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

import requests

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
HOME = os.path.expanduser("~")
PY = sys.executable
PROD, VIS, TUNED = "http://127.0.0.1:11434", "http://127.0.0.1:11435", "http://127.0.0.1:11436"
QM, VM = "qwen3:14b", "qwen3-vl:4b-instruct"
START = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
samples, stop = [], threading.Event()
abort = {"r": ""}


def smi():
    o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=3).stdout.strip()
    return int(o)


def sampler():
    while not stop.is_set():
        try:
            u = smi()
            samples.append((time.time(), u))
            if u >= 15800:
                abort["r"] = f"VRAM {u}"
        except Exception:
            pass
        stop.wait(0.2)


def check():
    if abort["r"]:
        raise RuntimeError("ABORT " + abort["r"])
    o = subprocess.run(["journalctl", "-u", "studybridge-ai", "--since", START, "--no-pager", "-o", "cat"],
                       capture_output=True, text=True, timeout=10).stdout
    if '"POST /api/' in o:
        raise RuntimeError("ABORT prod traffic")


def ps(u):
    try:
        return {m["name"]: m.get("size_vram", 0) // 2**20 for m in requests.get(f"{u}/api/ps", timeout=3).json()["models"]}
    except Exception:
        return None


def unload_all():
    for u, m in ((PROD, QM), (VIS, VM), (TUNED, QM)):
        try:
            requests.post(f"{u}/api/generate", json={"model": m, "keep_alive": 0}, timeout=30)
        except Exception:
            pass
    t0 = time.time()
    while time.time() - t0 < 20 and any(ps(u) for u in (PROD, VIS, TUNED)):
        time.sleep(0.3)


def offload_lines(path, pos):
    try:
        with open(path, "rb") as f:
            f.seek(pos)
            return [l.strip()[-45:] for l in f.read().decode(errors="ignore").splitlines() if "offloaded" in l]
    except FileNotFoundError:
        return []


def journal_offload(since):
    o = subprocess.run(["journalctl", "-u", "ollama", "--since", since, "--no-pager", "-o", "cat"],
                       capture_output=True, text=True, timeout=10).stdout
    return [l.split("msg=")[-1][:40] for l in o.splitlines() if "offloaded" in l]


def daemon(cmd, env, log):
    return subprocess.Popen(cmd, env=dict(os.environ, **env), stdout=open(log, "ab"), stderr=subprocess.STDOUT)


def wait_up(u):
    for _ in range(60):
        try:
            requests.get(f"{u}/api/version", timeout=1)
            return
        except Exception:
            time.sleep(0.5)


def run(label, n, text_url, gw, extra=None):
    env = dict(os.environ, OLLAMA_BASE_URL=text_url, VISION_OLLAMA_BASE_URL=VIS, OLLAMA_MODEL=QM, VISION_MODEL=VM,
               VISION_BACKEND="ollama", VISION_KEEP_ALIVE="2m", OLLAMA_KEEP_ALIVE="5m", OPENAI_API_KEY="",
               AI_GATEWAY_ENABLED=gw, BENCH_SCALE="1.0", BENCH_JPEG=os.path.join(OUT, "screen.jpg"),
               OLLAMA_TIMEOUT_SECONDS="180", QUIZ_TIMEOUT_SECONDS="180", OLLAMA_TEMPERATURE="0", QUIZ_TEMPERATURE="0",
               BENCH_TEMPERATURE="0", BENCH_LOG="INFO", AI_GW_TEXT_FOOTPRINT_MIB="10600",
               AI_GW_VISION_FOOTPRINT_MIB="4800")
    env.update(extra or {})
    since = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    vpos = os.path.getsize(os.path.join(OUT, "vision.log"))
    tpos = os.path.getsize(os.path.join(OUT, "tuned.log")) if os.path.exists(os.path.join(OUT, "tuned.log")) else 0
    t0 = time.time()
    p = subprocess.run([PY, "scripts/ai_gateway_bench/harness.py", str(n), label, os.path.join(OUT, f"{label}.json")],
                       env=env, capture_output=True, text=True, timeout=900)
    t1 = time.time()
    open(os.path.join(OUT, f"{label}.stderr"), "w").write(p.stderr[-40000:])
    s = json.loads(p.stdout.strip().splitlines()[-1])
    s["vram_peak_mib"] = max((u for t, u in samples if t0 <= t <= t1), default=None)
    s["offload_text"] = journal_offload(since) if text_url == PROD else offload_lines(os.path.join(OUT, "tuned.log"), tpos)
    s["offload_vision"] = offload_lines(os.path.join(OUT, "vision.log"), vpos)
    with open(os.path.join(OUT, "compare.jsonl"), "a") as f:
        f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(datetime.now().strftime("%H:%M:%S"), label, json.dumps({k: s[k] for k in ("makespan_s", "success", "vram_peak_mib", "offload_text", "offload_vision")}, ensure_ascii=False), flush=True)
    check()
    unload_all()


def main():
    if ps(PROD):
        sys.exit("qwen3:14b resident — abort")
    from PIL import Image, ImageDraw                      # 합성 화면(실사용자 데이터 아님)
    img = Image.new("RGB", (1280, 720), (245, 245, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, 1240, 120], fill=(40, 80, 160))
    for i in range(12):
        d.text((60, 160 + i * 40), f"Line {i}: def schedule(queue, slots): return wfq(queue)[:{i}]", fill=(20, 20, 20))
    img.save(os.path.join(OUT, "screen.jpg"), "JPEG", quality=85)
    threading.Thread(target=sampler, daemon=True).start()
    vp = daemon([f"{HOME}/ollama-vision/bin/ollama", "serve"],
                {"OLLAMA_HOST": "127.0.0.1:11435", "OLLAMA_MODELS": f"{HOME}/ollama-vision/models",
                 "OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_NUM_PARALLEL": "1", "OLLAMA_KEEP_ALIVE": "2m"},
                os.path.join(OUT, "vision.log"))
    tp = None
    try:
        wait_up(VIS)
        plan = os.getenv("COMPARE_PLAN", "default")
        if plan == "tuned_only":
            pass
        elif plan == "before20":
            run("before_n20", 20, PROD, "false")
        elif plan == "noguard":
            for rep in range(int(os.getenv("REPS", "2"))):
                run(f"gw_noguard_n10_r{rep}", 10, PROD, "true", {"AI_GW_GPU_GUARD": "false"})
            return
        elif plan == "reps":
            for rep in range(int(os.getenv("REPS", "3"))):
                run(f"before_n10_r{rep}", 10, PROD, "false")
                run(f"after_code_n10_r{rep}", 10, PROD, "true", {"AI_GW_GPU_GUARD": "true"})
            return
        elif plan == "default":
            for n in (4, 10):
                run(f"before_n{n}", n, PROD, "false")
                run(f"after_code_n{n}", n, PROD, "true", {"AI_GW_GPU_GUARD": "true"})
        else:
            for n in (4, 10):
                run(f"swap_p1_n{n}", n, PROD, "true", {"AI_GW_GPU_GUARD": "true", "AI_GW_VISION_PRESSURE_POLICY": "swap"})
        par, kv = os.getenv("TUNED_PAR", "2"), os.getenv("TUNED_KV", "q8_0")
        tp = daemon(["/usr/local/bin/ollama", "serve"],
                    {"OLLAMA_HOST": "127.0.0.1:11436", "OLLAMA_MODELS": f"{HOME}/ollama-bench/models",
                     "OLLAMA_NUM_PARALLEL": par, "OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": kv,
                     "OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_KEEP_ALIVE": "5m"}, os.path.join(OUT, "tuned.log"))
        wait_up(TUNED)
        pol = os.getenv("TUNED_POLICY", "adaptive")
        for n in [int(x) for x in os.getenv("TUNED_NS", "4,10").split(",")]:
            run(f"tuned_p{par}_{kv}_{pol}_n{n}_{int(time.time()) % 1000}", n, TUNED, "true",
                {"AI_GW_GPU_GUARD": "true", "AI_GW_TEXT_SLOTS": par, "AI_GW_VISION_PRESSURE_POLICY": pol,
                 "AI_GW_TEXT_FOOTPRINT_MIB": os.getenv("TUNED_FP", "10600")})
    except Exception as e:  # noqa: BLE001
        print("STOPPED:", e, flush=True)
    finally:
        unload_all()
        for p in (vp, tp):
            if p is not None:
                p.terminate()
                try:
                    p.wait(15)
                except Exception:
                    p.kill()
        stop.set()
        time.sleep(1)
        print("restored", {"prod_ps": ps(PROD), "gpu_used": smi(),
                           "peak": max((u for _, u in samples), default=None)}, flush=True)


if __name__ == "__main__":
    main()
