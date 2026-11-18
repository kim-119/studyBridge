"""A~D 혼합 동시 부하 하네스 — 실제 통합된 호출 함수를 그대로 부른다(라우트 계층 제외).

  A VISION            : app.vision.inference.run_inference (VisionGate.admit 안에서, 라우터와 동일)
  B DOCUMENT_QUIZ     : quiz_text_compat._call_quiz_llm  (non-stream, num_predict=B_TOKENS)
  C MULTI_AGENT       : intent 1회 + llm_gateway.generate 3회 순차(에이전트별, stream)
  D DOCUMENT_ANALYSIS : ollama_client.ask_ollama (non-stream, max_tokens=D_TOKENS)

usage: python harness.py USERS LABEL OUT_JSON   (env 로 엔드포인트/게이트웨이/축척 지정)
사용자 i 는 A,B,C,D 를 순환 배정, 모든 사용자가 같은 시각(barrier)에 시작한다.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.getcwd())

SCALE = float(os.getenv("BENCH_SCALE", "1.0"))
if os.getenv("BENCH_LOG"):
    import logging
    logging.basicConfig(level=getattr(logging, os.getenv("BENCH_LOG", "INFO")),
                        format="%(relativeCreated)7.0f %(name)s %(message)s")
B_TOKENS = int(os.getenv("BENCH_B_TOKENS", "1200"))
C_TOKENS = int(os.getenv("BENCH_C_TOKENS", "350"))
D_TOKENS = int(os.getenv("BENCH_D_TOKENS", "1000"))
MODEL = os.getenv("OLLAMA_MODEL", "qwen3:14b")

import app.ai_gateway as gw  # noqa: E402
from app.ai_gateway.context import workload  # noqa: E402
from app.ai_gateway.policy import WorkloadClass as W  # noqa: E402

JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbd3ffd9")


if os.getenv("BENCH_JPEG"):
    JPEG = open(os.environ["BENCH_JPEG"], "rb").read()


def _pct(v, q):
    if not v:
        return None
    s = sorted(v)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 2)


_LOOP = asyncio.new_event_loop()       # uvicorn 처럼 비전 요청은 단일 이벤트 루프에서 처리
threading.Thread(target=_LOOP.run_forever, daemon=True).start()


def run_a(uid):
    from app.vision.config import get_settings
    from app.vision.gate import gate
    from app.vision.inference import run_inference

    async def go():
        s = get_settings()
        async with gate.admit(f"bench-{uid}-{time.time_ns()}", f"grp{uid % 3}", s):
            return await run_inference(JPEG, "화면에 무엇이 보이나요?", s)
    return asyncio.run_coroutine_threadsafe(go(), _LOOP).result()


def run_b(uid):
    import quiz_text_compat as q
    q.QUIZ_MAX_TOKENS = B_TOKENS
    out = q._call_quiz_llm("너는 퀴즈 생성기다.", f"자료 {uid} 로 퀴즈 5문항", f"bench-{uid}")
    if not out:
        raise RuntimeError("quiz empty")
    return out


def run_c(uid):
    from app.api import intent_router_routes as ir
    from app.studymate import llm_gateway as lg
    ir._call_router_ollama("의도 분류", f"질문 {uid}")     # 실패해도 deterministic fallback(None) → 계속
    ttft = None
    for agent in range(3):
        req = lg.LLMRequest(system=f"agent{agent}", user=f"질문 {uid}", model=MODEL, num_ctx=8192,
                            num_predict=C_TOKENS, timeout_s=max(5.0, 180 * SCALE), task="render",
                            temperature=float(os.getenv("BENCH_TEMPERATURE", "0.5")),
                            seed=7 if os.getenv("BENCH_TEMPERATURE") else None)
        r = lg.generate(req)
        if ttft is None:
            ttft = r.ttft_ms
    return ttft


def run_d(uid):
    from app.services.ollama_client import ask_ollama, _timeout_fallback
    out = ask_ollama("자료 분석가", f"자료 {uid} 요약", max_tokens=D_TOKENS,
                     timeout=int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")))
    if "타임아웃" in out or "연결할 수 없습니다" in out or "시간이 초과" in out:
        raise RuntimeError("ollama fallback text: " + out[:40])
    return out


KINDS = [("A", W.VISION, run_a), ("B", W.DOCUMENT_QUIZ, run_b), ("C", W.MULTI_AGENT, run_c),
         ("D", W.DOCUMENT_ANALYSIS, run_d)]


def main():
    users, label, out_path = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    barrier = threading.Barrier(users)
    res = []
    lock = threading.Lock()

    def user(i):
        kind, cls, fn = KINDS[i % 4]
        barrier.wait()
        t0 = time.perf_counter()
        ok, err, extra = True, "", None
        try:
            with workload(cls, f"u:{i}"):
                extra = fn(i)
        except Exception as e:  # noqa: BLE001
            ok, err = False, f"{type(e).__name__}: {str(e)[:80]}"
        dt = (time.perf_counter() - t0) / SCALE
        with lock:
            res.append({"user": i, "kind": kind, "ok": ok, "err": err, "latency_s": round(dt, 2),
                        "ttft_ms": (extra / SCALE if (kind == "C" and isinstance(extra, (int, float))) else None)})

    t0 = time.perf_counter()
    ths = [threading.Thread(target=user, args=(i,)) for i in range(users)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    makespan = (time.perf_counter() - t0) / SCALE
    summary = {"label": label, "users": users, "gateway": gw.enabled(), "makespan_s": round(makespan, 2),
               "throughput_rps": round(users / makespan, 3), "success": sum(r["ok"] for r in res), "byKind": {}}
    for k, _, _ in KINDS:
        rs = [r for r in res if r["kind"] == k]
        lat = [r["latency_s"] for r in rs if r["ok"]]
        summary["byKind"][k] = {"n": len(rs), "ok": len(lat), "p50": _pct(lat, .5), "p95": _pct(lat, .95),
                                "p99": _pct(lat, .99), "max": max(lat) if lat else None,
                                "errors": sorted({r["err"] for r in rs if not r["ok"]})[:3]}
        if k == "C":
            tt = [r["ttft_ms"] for r in rs if r["ok"] and r["ttft_ms"] is not None]
            summary["byKind"][k]["ttft_ms_p50"] = _pct(tt, .5)
            summary["byKind"][k]["ttft_ms_p95"] = _pct(tt, .95)
    if gw.enabled():
        snap = gw.status()
        summary["gatewayQueue"] = {c: {"waitMs": {k: (None if x is None else round(x / SCALE, 1)) for k, x in v["waitMs"].items()}, "rejectedTimeout": v["rejectedTimeout"],
                                       "rejectedQueueFull": v["rejectedQueueFull"], "maxWaiting": v["maxWaiting"]}
                                   for c, v in snap["scheduler"]["classes"].items() if v["granted"] or v["rejectedTimeout"] or v["rejectedQueueFull"]}
    json.dump({"summary": summary, "requests": sorted(res, key=lambda r: r["user"])},
              open(out_path, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
