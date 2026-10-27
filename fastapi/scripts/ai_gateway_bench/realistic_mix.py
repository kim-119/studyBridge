"""실서비스형 open-loop 혼합 부하(가짜 Ollama, GPU 미사용) — 동시 버스트가 아니라 시간에 걸쳐 도착한다.

시나리오(실제 초, BENCH_SCALE 로 축척 재생):
  그룹스터디 G개: 그룹마다 멀티에이전트 질문(Poisson, 평균 MA_GAP 초) — intent 1회 + 에이전트 3명 순차
                  화면공유 질문(Poisson, 평균 VIS_GAP 초, 공유자 2명이 번갈아)
                  실시간 퀴즈 생성(Poisson, 평균 QUIZ_GAP 초)
  개인 사용자 P명: fetch-stream 채팅(Poisson, 평균 CHAT_GAP 초, 300 tok)
  자료 분석: 전체 Poisson 평균 DOC_GAP 초(1000 tok)
  heavy 사용자 1명(옵션): 멀티에이전트를 끝나자마자 다시 보내는 closed-loop(독점 시도)
usage: python realistic_mix.py LABEL OUT_JSON   (env: MIX_PROFILE=light|peak, MIX_HEAVY=0|1, MIX_DURATION)
"""
from __future__ import annotations

import json
import os
import random
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H  # noqa: E402  (BENCH_* env, run_a/run_b/run_c/run_d 재사용)

from app.ai_gateway.context import workload  # noqa: E402
from app.ai_gateway.policy import WorkloadClass as W  # noqa: E402
import app.ai_gateway as gw  # noqa: E402

PROFILES = {
    # 평균 도착 간격(실제 초). peak 은 P1 텍스트 사용률 ≈ 0.85 가 되도록 잡았다(78 tok/s 기준 계산).
    "light": dict(G=2, P=3, MA_GAP=180, VIS_GAP=60, QUIZ_GAP=600, CHAT_GAP=120, DOC_GAP=300),
    "peak": dict(G=2, P=3, MA_GAP=90, VIS_GAP=30, QUIZ_GAP=240, CHAT_GAP=40, DOC_GAP=150),
}
SCALE = H.SCALE


def run_chat(uid):
    from app.services.ai_fetch_stream_service import stream_ollama
    t0 = time.perf_counter()
    ttft = None
    for _ in stream_ollama("튜터", f"질문 {uid}", model=H.MODEL, max_tokens=300):
        if ttft is None:
            ttft = (time.perf_counter() - t0) * 1000
    return ttft


def main():
    label, out_path = sys.argv[1], sys.argv[2]
    prof = PROFILES[os.getenv("MIX_PROFILE", "peak")]
    duration = float(os.getenv("MIX_DURATION", "300"))
    rng = random.Random(int(os.getenv("MIX_SEED", "7")))
    events = []      # (t_real, kind, cls, key, group, fn)

    def poisson(gap, kind, cls, key, group, fn):
        t = rng.expovariate(1.0 / gap)
        while t < duration:
            events.append((t, kind, cls, key, group, fn))
            t += rng.expovariate(1.0 / gap)

    for g in range(prof["G"]):
        poisson(prof["MA_GAP"], "C", W.MULTI_AGENT, f"cu:g{g}m{g}", f"cg:{g}", H.run_c)
        poisson(prof["VIS_GAP"], "A", W.VISION, f"cu:g{g}s", f"cg:{g}", H.run_a)
        poisson(prof["QUIZ_GAP"], "B", W.DOCUMENT_QUIZ, f"cu:g{g}q", f"cg:{g}", H.run_b)
    for p in range(prof["P"]):
        poisson(prof["CHAT_GAP"], "E", W.INTERACTIVE_CHAT, f"cu:p{p}", None, run_chat)
    poisson(prof["DOC_GAP"], "D", W.DOCUMENT_ANALYSIS, "cu:doc", None, H.run_d)
    events.sort(key=lambda e: e[0])

    res, lock = [], threading.Lock()
    from app.ai_gateway.context import set_context, reset_context

    def fire(ev, idx):
        t_sched, kind, cls, key, group, fn = ev
        t0 = time.perf_counter()
        ok, err, extra = True, "", None
        tokens = set_context(cls, key, None, group or key)
        try:
            extra = fn(idx)
        except Exception as e:  # noqa: BLE001
            ok, err = False, f"{type(e).__name__}: {str(e)[:60]}"
        finally:
            reset_context(tokens)
        with lock:
            res.append({"kind": kind, "ok": ok, "err": err, "t": round(t_sched, 1),
                        "latency_s": round((time.perf_counter() - t0) / SCALE, 2),
                        "ttft_ms": round(extra / SCALE) if kind in ("C", "E") and isinstance(extra, (int, float)) else None})

    stop_heavy = threading.Event()

    def heavy():
        i = 0
        while not stop_heavy.is_set():
            t0 = time.perf_counter()
            ok = True
            tokens = set_context(W.MULTI_AGENT, "cu:heavy", None, "cu:heavy")
            try:
                H.run_c(10_000 + i)
            except Exception:  # noqa: BLE001
                ok = False
            finally:
                reset_context(tokens)
            with lock:
                res.append({"kind": "H", "ok": ok, "err": "", "t": 0, "latency_s": round((time.perf_counter() - t0) / SCALE, 2),
                            "ttft_ms": None})
            i += 1

    hth = None
    if os.getenv("MIX_HEAVY", "0") == "1":
        hth = threading.Thread(target=heavy, daemon=True)
        hth.start()
    start = time.perf_counter()
    ths = []
    for i, ev in enumerate(events):
        delay = ev[0] * SCALE - (time.perf_counter() - start)
        if delay > 0:
            time.sleep(delay)
        th = threading.Thread(target=fire, args=(ev, i), daemon=True)
        th.start()
        ths.append(th)
    for th in ths:
        th.join(timeout=900)
    stop_heavy.set()
    if hth:
        hth.join(timeout=120)

    def pct(v, q):
        if not v:
            return None
        s = sorted(v)
        return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 2)
    summary = {"label": label, "gateway": gw.enabled(), "profile": os.getenv("MIX_PROFILE", "peak"),
               "heavy": os.getenv("MIX_HEAVY", "0") == "1", "events": len(events), "byKind": {}}
    for k in "ACBDEH":
        rs = [r for r in res if r["kind"] == k]
        if not rs:
            continue
        lat = [r["latency_s"] for r in rs if r["ok"]]
        d = {"n": len(rs), "ok": len(lat), "p50": pct(lat, .5), "p95": pct(lat, .95), "p99": pct(lat, .99),
             "errors": sorted({r["err"] for r in rs if not r["ok"]})[:2]}
        tt = [r["ttft_ms"] for r in rs if r["ok"] and r["ttft_ms"] is not None]
        if tt:
            d["ttft_ms_p50"], d["ttft_ms_p95"] = pct(tt, .5), pct(tt, .95)
        summary["byKind"][k] = d
    json.dump({"summary": summary, "requests": res}, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
