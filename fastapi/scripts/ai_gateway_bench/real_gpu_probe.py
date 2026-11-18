"""실제 GPU 검증(운영 Ollama :11434 + 사용자 공간 비전 Ollama :11435) — 저부하 전용(1/2/4건).

안전장치:
  * 시작 전/중 운영 트래픽 감시: studybridge-ai 저널에 POST /api/ 가 보이면 즉시 중단·복구.
  * VRAM 샘플러(200ms): 사용량이 AI_GW_PROBE_ABORT_MIB(기본 15800MiB) 이상이면 중단.
  * 종료 시 항상 복구: 비전 데몬 PID 종료, 두 모델 keep_alive=0 언로드(시작 시 상주 모델 없음 확인).
측정:
  R0 기준선  — qwen3:14b 콜드 적재/warm TTFT·tok/s, VL 단독, VL+q14b 공존(가드 없음 = 변경 전 동작)
  R1 변경 후 — 게이트웨이+GPU 가드로 A~D 혼합 1/2/4건(harness.py), swap 횟수/VRAM 피크/offload 로그
usage: python real_gpu_probe.py OUT_DIR
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
TEXT, VIS = "http://127.0.0.1:11434", "http://127.0.0.1:11435"
QM, VM = "qwen3:14b", "qwen3-vl:4b-instruct"
ABORT_MIB = int(os.getenv("AI_GW_PROBE_ABORT_MIB", "15800"))
HOME = os.path.expanduser("~")
PY = sys.executable
JPEG_PATH = os.path.join(OUT, "screen.jpg")
log_lines = []


def log(msg):
    line = f"{datetime.now().strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    log_lines.append(line)


class Abort(Exception):
    pass


# ── 감시 ─────────────────────────────────────────────────────────────────
START = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
samples = []
stop_sampler = threading.Event()
abort_reason = {"r": ""}


def smi():
    o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=3).stdout.strip().split(",")
    return int(o[0]), int(o[1])


def sampler():
    while not stop_sampler.is_set():
        try:
            used, util = smi()
            samples.append((time.time(), used, util))
            if used >= ABORT_MIB:
                abort_reason["r"] = f"VRAM {used}MiB >= {ABORT_MIB}"
        except Exception:
            pass
        stop_sampler.wait(0.2)


def prod_requests_since(since):
    o = subprocess.run(["journalctl", "-u", "studybridge-ai", "--since", since, "--no-pager", "-o", "cat"],
                       capture_output=True, text=True, timeout=10).stdout
    return [l for l in o.splitlines() if '"POST /api/' in l]


def check():
    if abort_reason["r"]:
        raise Abort(abort_reason["r"])
    hits = prod_requests_since(START)
    if hits:
        raise Abort(f"PROD TRAFFIC DETECTED: {hits[0][:120]}")


def peak(t0, t1):
    xs = [u for (t, u, _) in samples if t0 <= t <= t1]
    return max(xs) if xs else None


def ps(url):
    try:
        return {m["name"]: m.get("size_vram", 0) // 2**20 for m in requests.get(f"{url}/api/ps", timeout=3).json().get("models", [])}
    except Exception:
        return None


def unload(url, model):
    try:
        requests.post(f"{url}/api/generate", json={"model": model, "keep_alive": 0}, timeout=30)
    except Exception:
        pass


def wait_unloaded(url, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not ps(url):
            return True
        time.sleep(0.3)
    return False


def text_once(num_predict=256, stream=True, num_ctx=8192, base=None):
    body = {"model": QM, "messages": [{"role": "system", "content": "너는 친절한 튜터다."},
                                      {"role": "user", "content": "운영체제에서 프로세스와 스레드의 차이를 설명해줘."}],
            "stream": stream, "think": False, "keep_alive": "5m",
            "options": {"num_ctx": num_ctx, "num_predict": num_predict, "temperature": 0.4}}
    t0 = time.perf_counter()
    r = requests.post(f"{base or TEXT}/api/chat", json=body, stream=stream, timeout=300)
    ttft, final = None, {}
    if stream:
        for line in r.iter_lines():
            if not line:
                continue
            o = json.loads(line)
            if ttft is None and (o.get("message") or {}).get("content"):
                ttft = time.perf_counter() - t0
            if o.get("done"):
                final = o
    else:
        final = r.json()
    total = time.perf_counter() - t0
    ev, evd = final.get("eval_count") or 0, (final.get("eval_duration") or 1) / 1e9
    return {"total_s": round(total, 2), "ttft_s": round(ttft, 3) if ttft else None,
            "load_s": round((final.get("load_duration") or 0) / 1e9, 2), "eval_tps": round(ev / evd, 1),
            "eval_count": ev}


def vision_once():
    import base64
    body = {"model": VM, "stream": False, "keep_alive": "2m",
            "messages": [{"role": "user", "content": "이 화면에 무엇이 보이는지 3문장으로 설명해줘.",
                          "images": [base64.b64encode(open(JPEG_PATH, "rb").read()).decode()]}],
            "options": {"num_ctx": 4096, "num_predict": 200, "temperature": 0.2}}
    t0 = time.perf_counter()
    d = requests.post(f"{VIS}/api/chat", json=body, timeout=300).json()
    return {"total_s": round(time.perf_counter() - t0, 2), "load_s": round((d.get("load_duration") or 0) / 1e9, 2),
            "eval_tps": round((d.get("eval_count") or 0) / max(1e-9, (d.get("eval_duration") or 1) / 1e9), 1),
            "chars": len((d.get("message") or {}).get("content") or "")}


def make_jpeg():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (1280, 720), (245, 245, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, 1240, 120], fill=(40, 80, 160))
    for i in range(12):
        d.text((60, 160 + i * 40), f"Line {i}: def schedule(queue, slots): return wfq(queue)[:{i}]", fill=(20, 20, 20))
    d.rectangle([800, 200, 1200, 600], outline=(200, 30, 30), width=4)
    img.save(JPEG_PATH, "JPEG", quality=85)


def vision_log_offload(since_bytes):
    p = os.path.join(OUT, "vision_serve.log")
    try:
        with open(p, "rb") as f:
            f.seek(since_bytes)
            txt = f.read().decode(errors="ignore")
    except FileNotFoundError:
        return []
    return [l.strip()[-60:] for l in txt.splitlines() if "offloaded" in l]


def text_offload_since(since):
    o = subprocess.run(["journalctl", "-u", "ollama", "--since", since, "--no-pager", "-o", "cat"],
                       capture_output=True, text=True, timeout=10).stdout
    return [l.split("msg=")[-1][:60] for l in o.splitlines() if "offloaded" in l]


QUALITY = [
    ("explain", "TCP 3-way handshake 를 학부생에게 5문장으로 설명해줘.", None),
    ("explain", "데드락의 4가지 필요조건과 예방 방법을 정리해줘.", None),
    ("explain", "트랜스포머의 self-attention 계산 과정을 단계별로 설명해줘.", None),
    ("json", "다음 내용으로 객관식 3문항을 JSON 으로 만들어라: 프로세스는 독립 주소공간, 스레드는 주소공간 공유.",
     {"type": "object", "properties": {"questions": {"type": "array", "items": {"type": "object", "properties": {
         "question": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}},
         "answerIndex": {"type": "integer"}}, "required": ["question", "options", "answerIndex"]}}},
      "required": ["questions"]}),
    ("json", "다음 내용으로 OX 2문항을 JSON 으로 만들어라: 캐시는 지역성을 이용한다.",
     {"type": "object", "properties": {"questions": {"type": "array", "items": {"type": "object", "properties": {
         "question": {"type": "string"}, "answer": {"type": "boolean"}}, "required": ["question", "answer"]}}},
      "required": ["questions"]}),
]


def quality_set(base):
    out = []
    for kind, prompt, schema in QUALITY:
        body = {"model": QM, "stream": False, "think": False, "keep_alive": "5m",
                "messages": [{"role": "user", "content": prompt}],
                "options": {"num_ctx": 8192, "num_predict": 400, "temperature": 0, "seed": 7}}
        if schema:
            body["format"] = schema
        d = requests.post(f"{base}/api/chat", json=body, timeout=300).json()
        txt = (d.get("message") or {}).get("content") or ""
        valid = None
        if schema:
            try:
                valid = bool(json.loads(txt).get("questions"))
            except Exception:
                valid = False
        out.append({"kind": kind, "text": txt, "json_valid": valid})
    return out


def similarity(a, b):
    import difflib
    return [round(difflib.SequenceMatcher(None, x["text"], y["text"]).ratio(), 3) for x, y in zip(a, b)]


def harness(n, label, extra_env, text_url=None):
    env = dict(os.environ, OLLAMA_BASE_URL=text_url or TEXT, VISION_OLLAMA_BASE_URL=VIS, OLLAMA_MODEL=QM, VISION_MODEL=VM,
               VISION_BACKEND="ollama", VISION_KEEP_ALIVE="2m", OLLAMA_KEEP_ALIVE="5m", OPENAI_API_KEY="",
               AI_GATEWAY_ENABLED="true", BENCH_SCALE="1.0", BENCH_JPEG=JPEG_PATH,
               OLLAMA_TIMEOUT_SECONDS="180", QUIZ_TIMEOUT_SECONDS="180", **extra_env)
    t0 = time.time()
    p = subprocess.run([PY, "scripts/ai_gateway_bench/harness.py", str(n), label, os.path.join(OUT, f"{label}.json")],
                       env=env, capture_output=True, text=True, timeout=900)
    t1 = time.time()
    open(os.path.join(OUT, f"{label}.stderr"), "w").write(p.stderr[-20000:])
    summ = json.loads(p.stdout.strip().splitlines()[-1])
    summ["vram_peak_mib"] = peak(t0, t1)
    return summ, t0, t1


def main():
    results = {"start": START}
    pre_text, pre_vis = ps(TEXT), None
    used0, _ = smi()
    results["pre"] = {"text_ps": pre_text, "gpu_used_mib": used0}
    log(f"pre: text_ps={pre_text} gpu_used={used0}MiB")
    if pre_text:
        raise Abort("qwen3:14b 가 이미 상주(운영 사용 중일 수 있음) — 중단")
    if prod_requests_since("-3min"):
        raise Abort("최근 3분 내 운영 트래픽 — 중단")
    make_jpeg()
    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    vlog = open(os.path.join(OUT, "vision_serve.log"), "ab")
    venv = dict(os.environ, OLLAMA_HOST="127.0.0.1:11435", OLLAMA_MODELS=f"{HOME}/ollama-vision/models",
                OLLAMA_MAX_LOADED_MODELS="1", OLLAMA_NUM_PARALLEL="1", OLLAMA_KEEP_ALIVE="2m")
    vproc = subprocess.Popen([f"{HOME}/ollama-vision/bin/ollama", "serve"], env=venv, stdout=vlog, stderr=vlog)
    try:
        for _ in range(60):
            try:
                requests.get(f"{VIS}/api/version", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        log(f"vision daemon pid={vproc.pid} up")
        # ── R0: 기준선 ─────────────────────────────────────────────────
        r0 = {}
        since = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        r0["text_cold"] = text_once(64); check()
        r0["text_warm"] = [text_once(256) for _ in range(3)]; check()
        r0["text_ps"] = ps(TEXT); r0["gpu_used_text_only"] = smi()[0]
        r0["text_offload_log"] = text_offload_since(since)
        log(f"R0 text cold={r0['text_cold']} warm={r0['text_warm'][-1]} ps={r0['text_ps']} used={r0['gpu_used_text_only']}")
        # 공존(가드 없음 = 변경 전): q14b 상주 상태에서 VL 적재
        vpos = os.path.getsize(os.path.join(OUT, "vision_serve.log"))
        r0["vision_coexist"] = [vision_once() for _ in range(3)]; check()
        r0["vision_coexist_offload"] = vision_log_offload(vpos)
        r0["gpu_used_both"] = smi()[0]; r0["vis_ps_coexist"] = ps(VIS)
        r0["text_while_vl_resident"] = text_once(256); check()
        log(f"R0 coexist vision={r0['vision_coexist'][-1]} offload={r0['vision_coexist_offload']} used={r0['gpu_used_both']} text={r0['text_while_vl_resident']}")
        # VL 단독(텍스트 내림) = 전체 GPU 적재 기준
        unload(VIS, VM); wait_unloaded(VIS); unload(TEXT, QM); wait_unloaded(TEXT)
        t_sw = time.perf_counter(); vpos = os.path.getsize(os.path.join(OUT, "vision_serve.log"))
        r0["vision_alone"] = [vision_once() for _ in range(3)]; check()
        r0["vision_alone_offload"] = vision_log_offload(vpos)
        r0["vis_ps_alone"] = ps(VIS); r0["gpu_used_vision_only"] = smi()[0]
        log(f"R0 vision alone={r0['vision_alone']} offload={r0['vision_alone_offload']} ps={r0['vis_ps_alone']} used={r0['gpu_used_vision_only']}")
        unload(VIS, VM); wait_unloaded(VIS)
        results["R0"] = r0
        json.dump(results, open(os.path.join(OUT, "real_results.json"), "w"), ensure_ascii=False, indent=1)
        # ── R1: 게이트웨이 + GPU 가드 ───────────────────────────────────────
        r1 = {}
        fp = {"AI_GW_GPU_GUARD": "true", "AI_GW_TEXT_FOOTPRINT_MIB": os.getenv("PROBE_TEXT_FP", "10600"),
              "AI_GW_VISION_FOOTPRINT_MIB": os.getenv("PROBE_VIS_FP", "4800"), "AI_GW_MIN_RESIDENCY_S": "5"}
        for n in (1, 2, 4):
            since = datetime.now().strftime("%Y-%m-%d %H:%M:%S"); vpos = os.path.getsize(os.path.join(OUT, "vision_serve.log"))
            s, t0, t1 = harness(n, f"real_gw_guard_n{n}", fp); check()
            s["text_offload_log"] = text_offload_since(since); s["vision_offload_log"] = vision_log_offload(vpos)
            r1[f"n{n}"] = s
            log(f"R1 n={n} {json.dumps(s, ensure_ascii=False)[:600]}")
        # 같은 4건을 가드 OFF(게이트웨이 스케줄링만)로 — 공존 offload 재현 비교
        unload(VIS, VM); wait_unloaded(VIS); unload(TEXT, QM); wait_unloaded(TEXT)
        since = datetime.now().strftime("%Y-%m-%d %H:%M:%S"); vpos = os.path.getsize(os.path.join(OUT, "vision_serve.log"))
        s, t0, t1 = harness(4, "real_gw_noguard_n4", {"AI_GW_GPU_GUARD": "false"}); check()
        s["text_offload_log"] = text_offload_since(since); s["vision_offload_log"] = vision_log_offload(vpos)
        r1["n4_noguard"] = s
        log(f"R1 n=4 noguard {json.dumps(s, ensure_ascii=False)[:600]}")
        unload(VIS, VM); wait_unloaded(VIS); unload(TEXT, QM); wait_unloaded(TEXT)
        s, t0, t1 = harness(10, "real_gw_guard_n10", fp); check()
        r1["n10"] = s
        log(f"R1 n=10 {json.dumps(s, ensure_ascii=False)[:600]}")
        unload(VIS, VM); wait_unloaded(VIS)
        r1["quality_p1_a"] = quality_set(TEXT); r1["quality_p1_b"] = quality_set(TEXT); check()
        results["R1"] = r1
        unload(TEXT, QM); wait_unloaded(TEXT)
        json.dump(results, open(os.path.join(OUT, "real_results.json"), "w"), ensure_ascii=False, indent=1)
        # ── R2: 격리 튜닝 데몬(:11436, NUM_PARALLEL=2 + FA + KV q8_0), 운영 데몬 설정은 그대로 ──────
        TUNED = "http://127.0.0.1:11436"
        tlog = open(os.path.join(OUT, "tuned_serve.log"), "ab")
        tenv = dict(os.environ, OLLAMA_HOST="127.0.0.1:11436", OLLAMA_MODELS=f"{HOME}/ollama-bench/models",
                    OLLAMA_NUM_PARALLEL="2", OLLAMA_FLASH_ATTENTION="1", OLLAMA_KV_CACHE_TYPE="q8_0",
                    OLLAMA_MAX_LOADED_MODELS="1", OLLAMA_KEEP_ALIVE="5m")
        tproc = subprocess.Popen(["/usr/local/bin/ollama", "serve"], env=tenv, stdout=tlog, stderr=tlog)
        r2 = {}
        try:
            for _ in range(60):
                try:
                    requests.get(f"{TUNED}/api/version", timeout=1)
                    break
                except Exception:
                    time.sleep(0.5)
            r2["text_cold"] = text_once(64, base=TUNED); check()
            r2["text_warm"] = [text_once(256, base=TUNED) for _ in range(3)]; check()
            r2["text_ps"] = ps(TUNED); r2["gpu_used_text_only"] = smi()[0]
            log(f"R2 tuned cold={r2['text_cold']} warm={r2['text_warm'][-1]} ps={r2['text_ps']} used={r2['gpu_used_text_only']}")
            r2["quality_p2q8"] = quality_set(TUNED); check()
            fp2 = dict(fp, AI_GW_TEXT_SLOTS="2", AI_GW_TEXT_FOOTPRINT_MIB=os.getenv("PROBE_TUNED_FP", "10600"))
            for n in (4, 10):
                s, t0, t1 = harness(n, f"real_tuned_gw_n{n}", fp2, text_url=TUNED); check()
                r2[f"n{n}"] = s
                log(f"R2 n={n} {json.dumps(s, ensure_ascii=False)[:600]}")
        finally:
            unload(TUNED, QM); unload(VIS, VM)
            tproc.terminate()
            try:
                tproc.wait(15)
            except Exception:
                tproc.kill()
            results["R2"] = r2
        q1a, q1b, q2 = results["R1"]["quality_p1_a"], results["R1"]["quality_p1_b"], r2.get("quality_p2q8") or []
        results["quality"] = {"self_similarity_p1_f16": similarity(q1a, q1b),
                              "p1_f16_vs_p2_q8": similarity(q1a, q2),
                              "json_valid_p1": [x["json_valid"] for x in q1a if x["kind"] == "json"],
                              "json_valid_p2q8": [x["json_valid"] for x in q2 if x["kind"] == "json"]}
        log(f"quality {results['quality']}")
    except Abort as e:
        results["aborted"] = str(e)
        log(f"ABORT: {e}")
    finally:
        unload(VIS, VM); unload(TEXT, QM)
        vproc.terminate()
        try:
            vproc.wait(15)
        except Exception:
            vproc.kill()
        stop_sampler.set()
        time.sleep(1)
        results["post"] = {"text_ps": ps(TEXT), "gpu_used_mib": smi()[0],
                           "vram_peak_overall_mib": max((u for _, u, _ in samples), default=None)}
        results["log"] = log_lines
        json.dump(results, open(os.path.join(OUT, "real_results.json"), "w"), ensure_ascii=False, indent=1)
        log(f"restored: {results['post']}")


if __name__ == "__main__":
    main()
