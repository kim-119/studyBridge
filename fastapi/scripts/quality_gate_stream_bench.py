"""품질 게이트 스트림 벤치(Phase B4) — 실캡처 스트림(가짜 LLM 앞 실제 라우트 바이트)을 ai07 stream_gate 에 재생해
평가 중복/지연/동시성/취소 정리를 측정한다. GPU·외부 호출 없음(결정적 평가기 실측 + 주입 지연). 운영 수치가 아니다.

사용: python -m scripts.quality_gate_stream_bench --out /tmp/bench.json [--inject-ms 0,600] [--parallel 1,2]
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List

from app.contracts.response_quality_v1 import SCHEMA_VERSION, QualityInput
from app.quality_gate import evaluator as E
from app.quality_gate import stream_gate as G

CAP = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "stream_captures"


def _p95(xs: List[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


def _load(p: Path) -> Dict[str, Any]:
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _policy(rec, parallel: int):
    base = G.policy_for("roadmap" if "roadmap" in rec["name"] else ("studymate" if rec["name"].startswith("studymate") else None))
    import dataclasses
    return dataclasses.replace(base, max_parallel_evaluations=parallel) if hasattr(base, "max_parallel_evaluations") else base


async def _replay(rec, *, inject_ms: float, parallel: int, approve_all: bool) -> Dict[str, Any]:
    raw = rec["raw"].encode()
    calls: List[Dict[str, Any]] = []
    eval_lat: List[float] = []

    async def chunks():
        for i in range(0, len(raw), 2048):
            yield raw[i:i + 2048]

    async def ev(key, text, src, rid):
        t = time.perf_counter()
        inp = QualityInput.model_validate({
            "schemaVersion": SCHEMA_VERSION, "requestId": rid, "taskType": "STUDYMATE_BASIC" if rec["name"].startswith("studymate")
            else "GENERAL_EXPLANATION", "outputKind": "agent_message", "originalRequest": "벤치 질문",
            "proposedOutput": text, "groundingEvidence": [], "constraints": {}})
        q = await E.evaluate(inp)
        eval_lat.append((time.perf_counter() - t) * 1000)
        calls.append({"key": key, "chars": len(text), "aggregate": "#" in key})
        if inject_ms:
            await asyncio.sleep(inject_ms / 1000)
        if approve_all:   # 지연/중복 측정용: 실제 판정 대신 승인(본문 방출 경로를 끝까지 태운다)
            q = q.model_copy(update={"qualityStatus": q.qualityStatus.__class__.APPROVED, "score": 90.0, "verified": True,
                                     "hardFail": False, "violations": [], "mandatoryValidatorsPassed": True,
                                     "success": True})
        return q

    wrap = G.wrap_sse_stream if "event-stream" in rec["contentType"] else G.wrap_ndjson_stream
    E.clear_cache()
    t0 = time.perf_counter()
    first_body = None
    frames = 0
    async for s in wrap(chunks(), ev, policy=_policy(rec, parallel), request_id="bench-req-0001"):
        frames += 1
        if first_body is None and any(k in s for k in ('"content"', '"answer"', '"questions"', '"delta"', '"text"')) \
                and "quality_rejected" not in s and "agent_error" not in s:
            first_body = (time.perf_counter() - t0) * 1000
    total = (time.perf_counter() - t0) * 1000
    msg = [c for c in calls if not c["aggregate"]]
    agg = [c for c in calls if c["aggregate"]]
    return {"evaluations": len(calls), "messageEvaluations": len(msg), "aggregateEvaluations": len(agg),
            "evalLatencyMs": {"avg": round(statistics.mean(eval_lat), 2) if eval_lat else 0.0,
                              "p95": round(_p95(eval_lat), 2), "max": round(max(eval_lat or [0]), 2)},
            "firstBodyMs": None if first_body is None else round(first_body, 1), "turnMs": round(total, 1),
            "frames": frames, "maxMessageChars": max([c["chars"] for c in calls] or [0])}


async def _loop_block(chars: int) -> Dict[str, float]:
    """큰 본문 결정적 평가가 이벤트 루프를 얼마나 막는지(동시에 도는 10ms 틱의 최대 지연)."""
    text = ("TCP 는 연결 지향 프로토콜이며 3-way handshake 로 연결을 수립한다. " * (chars // 40 + 1))[:chars]
    inp = QualityInput.model_validate({"schemaVersion": SCHEMA_VERSION, "requestId": f"bench-block-{chars}",
                                       "taskType": "GENERAL_EXPLANATION", "outputKind": "text",
                                       "originalRequest": "q", "proposedOutput": text})
    lags: List[float] = []
    stop = asyncio.Event()

    async def ticker():
        while not stop.is_set():
            t = time.perf_counter()
            await asyncio.sleep(0.01)
            lags.append((time.perf_counter() - t) * 1000 - 10)
    E.clear_cache()
    task = asyncio.create_task(ticker())
    await asyncio.sleep(0.02)
    t = time.perf_counter()
    await E.evaluate(inp)
    took = (time.perf_counter() - t) * 1000
    stop.set()
    await task
    return {"chars": chars, "evalMs": round(took, 1), "maxLoopLagMs": round(max(lags or [0]), 1)}


async def _concurrency(n_streams: int, evaluator_ms: float, sem_n: int, queue_wait_s: float) -> Dict[str, Any]:
    """평가 API 와 같은 세마포어(AI_QUALITY_EVAL_MAX_CONCURRENCY)·대기 상한으로 동시 평가 요청 시 대기/429 비율."""
    sem = asyncio.Semaphore(sem_n)
    waits, busy = [], 0

    async def one():
        nonlocal busy
        t = time.perf_counter()
        try:
            await asyncio.wait_for(sem.acquire(), timeout=queue_wait_s)
        except asyncio.TimeoutError:
            busy += 1
            return
        waits.append((time.perf_counter() - t) * 1000)
        try:
            await asyncio.sleep(evaluator_ms / 1000)
        finally:
            sem.release()
    await asyncio.gather(*(one() for _ in range(n_streams)))
    return {"requests": n_streams, "concurrency": sem_n, "evaluatorMs": evaluator_ms, "queueWaitCapS": queue_wait_s,
            "busy429": busy, "queueWaitMs": {"avg": round(statistics.mean(waits), 1) if waits else None,
                                              "p95": round(_p95(waits), 1)}}


async def _cancel_cleanup() -> Dict[str, Any]:
    """소비자 취소 → 진행 중 평가와 상류 생성기 정리 시간."""
    closed = {"upstream": False, "evalCancelled": False}

    async def upstream():
        try:
            yield {"event": "agent_answer", "data": {"agentId": "a", "content": "본문"}}
            await asyncio.sleep(10)
        finally:
            closed["upstream"] = True

    async def slow_eval(key, text, src, rid):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            closed["evalCancelled"] = True
            raise

    async def consume():
        async for _ in G.gate_event_stream(upstream(), slow_eval):
            pass
    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    t = time.perf_counter()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    return {"cleanupMs": round((time.perf_counter() - t) * 1000, 2), **closed}


async def _pipelined_turn(*, gen_s: float, eval_s: float, agents: int, prefetch: int, parallel: int,
                          aggregate_dup: bool) -> Dict[str, Any]:
    """LLM 생성 시간(에이전트별)과 평가 시간이 겹치는지: 상류가 실제로 시간을 쓰는 합성 턴."""
    import dataclasses
    pol = dataclasses.replace(G.policy_for("studymate"), prefetch_events=prefetch, max_parallel_evaluations=parallel)
    n_eval = {"n": 0}

    async def upstream():
        yield {"event": "turn_start", "data": {"turnId": "t1"}}
        msgs = []
        for i in range(agents):
            await asyncio.sleep(gen_s)                       # 에이전트 i 생성
            c = f"에이전트 {i} 의 설명 본문입니다. 근거를 들어 단계별로 설명한다."
            msgs.append({"agentId": f"a{i}", "content": c})
            yield {"event": "agent_answer", "data": {"turnId": "t1", "agentId": f"a{i}", "content": c,
                                                     "question": "다음으로 무엇을 확인해야 할까?" if aggregate_dup else None}}
        yield {"event": "all_complete", "data": {"turnId": "t1", "messages": msgs}}

    async def ev(key, text, src, rid):
        n_eval["n"] += 1
        await asyncio.sleep(eval_s)
        from app.contracts.response_quality_v1 import QualityOutput
        return QualityOutput(schemaVersion=SCHEMA_VERSION, requestId=rid, taskType="STUDYMATE_SOCRATIC", success=True,
                             verified=True, qualityStatus="APPROVED", score=90.0, minimumScore=80, hardFail=False,
                             evaluatorVersion="bench", mandatoryValidatorsPassed=True)
    t0 = time.perf_counter()
    first = None
    async for o in G.gate_event_stream(upstream(), ev, policy=pol, request_id="bench-pipe-0001"):
        if first is None and o["event"] == "agent_answer":
            first = time.perf_counter() - t0
    return {"agents": agents, "genS": gen_s, "evalS": eval_s, "prefetch": prefetch, "parallel": parallel,
            "evaluations": n_eval["n"], "firstBodyS": round(first or 0, 3), "turnS": round(time.perf_counter() - t0, 3)}


async def main(out: str, inject: List[float], parallels: List[int]) -> Dict[str, Any]:
    report: Dict[str, Any] = {"note": "합성 측정(가짜 LLM 캡처 + 결정적 평가기, 지연 주입). 운영 실측 아님.", "captures": {}}
    for p in sorted(CAP.glob("*.json.gz")):
        rec = _load(p)
        rows = {}
        for ms in inject:
            for par in parallels:
                rows[f"inject{int(ms)}ms_parallel{par}"] = await _replay(rec, inject_ms=ms, parallel=par, approve_all=True)
        rows["realVerdicts"] = await _replay(rec, inject_ms=0, parallel=parallels[-1], approve_all=False)
        report["captures"][rec["name"]] = rows
    report["eventLoopBlocking"] = [await _loop_block(n) for n in (2_000, 12_000, 32_000, 60_000)]
    report["concurrency"] = [await _concurrency(n, ms, 2, 2.0) for n, ms in ((4, 600), (8, 600), (16, 600), (8, 2500))]
    report["cancel"] = await _cancel_cleanup()
    report["pipelinedTurn"] = [await _pipelined_turn(gen_s=1.0, eval_s=0.6, agents=3, prefetch=pf, parallel=par,
                                                     aggregate_dup=True)
                               for pf, par in ((0, 1), (128, 2))]
    Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--inject-ms", default="0,600")
    ap.add_argument("--parallel", default="1")
    a = ap.parse_args()
    r = asyncio.run(main(a.out, [float(x) for x in a.inject_ms.split(",")], [int(x) for x in a.parallel.split(",")]))
    print(json.dumps({k: v for k, v in r.items() if k != "captures"}, ensure_ascii=False))
    for name, rows in r["captures"].items():
        for k, v in rows.items():
            print(name, k, v["evaluations"], v["messageEvaluations"], v["aggregateEvaluations"], v["firstBodyMs"], v["turnMs"],
                  v["evalLatencyMs"])
