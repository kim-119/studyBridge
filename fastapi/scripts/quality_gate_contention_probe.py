"""품질 평가기 지연·GPU 자원 경합 측정 하네스(Phase D 측정 계획의 실행 도구).

두 단계로 나뉜다.
  cpu  (기본, 안전): judge OFF 결정적 평가기를 실제 Spring 입력 모양(로드맵 2만 자 세그먼트, PDF QA 근거 32×8천 자 최대치,
        퀴즈 JSON, 비전 관측)으로 동시성 1/2/4/8 에서 돌려 P50/P95/P99·이벤트 루프 지연·대기 초과(429) 비율을 잰다.
        GPU·Ollama·네트워크를 쓰지 않는다. 결과는 '합성 CPU 측정'이며 운영 지연이 아니다.
  gpu  (가드 필수): 같은 GPU 를 쓰는 생성(qwen3:14b)과 judge 평가를 동시에 걸어 judge 지연·생성 TPS 저하·VRAM 최고치·온도를 잰다.
        운영 Ollama(단일 RTX 5070 Ti 16GB)를 실제로 점유하므로 다음을 모두 만족할 때만 시작한다:
          --allow-gpu 플래그 + AI_CONTENTION_PROBE_ALLOW=1 + 사전 점검 통과(GPU 사용률 ≤20%, 온도 ≤55°C, VRAM 여유 ≥3GiB,
          다른 모델 미적재) + 총 호출·시간 상한. 측정 중 온도 ≥60°C, VRAM ≥15GiB, 오류 3회 이상이면 즉시 중단한다.
        --dry-run 은 사전 점검과 시나리오 목록만 출력하고 아무 요청도 보내지 않는다.

  cd fastapi && python -m scripts.quality_gate_contention_probe --out /tmp/probe.json                 # cpu
  cd fastapi && python -m scripts.quality_gate_contention_probe --phase gpu --dry-run --out /tmp/p.json # 점검만
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from app.contracts.response_quality_v1 import SCHEMA_VERSION, QualityInput
from app.quality_gate import evaluator as E
from app.quality_gate import segments as SEG

GPU_LIMITS = {"maxStartUtil": 20, "maxStartTempC": 55, "minFreeVramMiB": 3072, "abortTempC": 60, "abortVramMiB": 15360,
              "maxErrors": 3, "maxWallS": 600, "maxCalls": 120}


def pct(xs: List[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(round(p * (len(s) - 1))))], 2)


def summary(xs: List[float]) -> Dict[str, float]:
    return {"n": len(xs), "p50": pct(xs, 0.5), "p95": pct(xs, 0.95), "p99": pct(xs, 0.99), "max": round(max(xs), 2) if xs else 0.0,
            "mean": round(statistics.mean(xs), 2) if xs else 0.0}


# ── 입력(실제 Spring 모양) ─────────────────────────────────────────────────────────
def _roadmap_inputs() -> List[QualityInput]:
    import app.services.study_action_router as sar
    orig = sar._llm_week_outline
    sar._llm_week_outline = lambda *a, **k: None
    try:
        ctx = sar.build_roadmap_ctx({"material_id": 1, "material_title": "측정용 자료", "document_text": "정규화 트랜잭션 인덱스 " * 400,
                                     "keywords": ["정규화", "트랜잭션", "인덱스"]})
        ctx["_no_llm"] = True
        doc = sar.finalize_roadmap_response(sar.generate_12week_7day_roadmap(ctx))
    finally:
        sar._llm_week_outline = orig
    out = []
    for rid, req, c in SEG.spring_segment_requests(doc, "측정용 84일 로드맵", "probe-roadmap-0001"):
        out.append(QualityInput.model_validate({
            "schemaVersion": SCHEMA_VERSION, "requestId": rid, "taskType": "PLANNER_COACHING", "outputKind": "plan_json",
            "originalRequest": req, "proposedOutput": c,
            "groundingEvidence": [{"sourceType": "PDF_ORIGINAL", "materialId": 1, "text": "정규화 트랜잭션 인덱스 " * 300}],
            "constraints": {"allowedMaterialIds": [1]}}))
    return out


def _pdf_qa_max() -> QualityInput:
    sent = "관계형 데이터베이스에서 정규화는 중복을 줄이고 갱신 이상을 막는다. "
    return QualityInput.model_validate({
        "schemaVersion": SCHEMA_VERSION, "requestId": "probe-pdfqa-0001", "taskType": "PDF_QA", "outputKind": "text",
        "originalRequest": "정규화가 왜 필요한가?", "proposedOutput": (sent * 1500)[:60000],
        "groundingEvidence": [{"sourceType": "PDF_ORIGINAL", "materialId": 1, "chunkId": f"m1-c{i}", "text": (sent * 300)[:8000]}
                              for i in range(32)],
        "constraints": {"allowedMaterialIds": [1]}})


def _quiz() -> QualityInput:
    qs = [{"question": f"정규화의 목적 {i}?", "options": ["중복 감소", "속도 저하", "보안 약화", "용량 증가"], "answer": "중복 감소",
           "explanation": "정규화는 중복을 줄인다."} for i in range(10)]
    return QualityInput.model_validate({
        "schemaVersion": SCHEMA_VERSION, "requestId": "probe-quiz-0001", "taskType": "PDF_QUIZ", "outputKind": "quiz_json",
        "originalRequest": "퀴즈 10문항", "proposedOutput": {"questions": qs},
        "groundingEvidence": [{"sourceType": "PDF_ORIGINAL", "materialId": 1, "text": "정규화는 중복을 줄인다. " * 50}],
        "constraints": {"allowedMaterialIds": [1], "expectedQuestionCount": 10, "expectedOptionCount": 4}})


def _vision() -> QualityInput:
    return QualityInput.model_validate({
        "schemaVersion": SCHEMA_VERSION, "requestId": "probe-vision-0001", "taskType": "VISION_CAPTION", "outputKind": "vision_text",
        "originalRequest": "이 코드 왜 틀려?", "proposedOutput": "화면의 return a - b 때문에 덧셈 함수가 뺄셈을 합니다.",
        "groundingEvidence": [{"evidenceId": "obs-1", "sourceType": "VISION_OBSERVATION", "text": "def add(a, b): return a - b"}],
        "constraints": {}})


# ── cpu 단계 ─────────────────────────────────────────────────────────────────────
async def _loop_lag(stop: asyncio.Event, lags: List[float]) -> None:
    while not stop.is_set():
        t = time.perf_counter()
        await asyncio.sleep(0.005)
        lags.append((time.perf_counter() - t - 0.005) * 1000)


async def _burst(inputs: List[QualityInput], concurrency: int, sem_n: int, queue_wait_s: float) -> Dict[str, Any]:
    """route.py 와 같은 규칙: 세마포어 sem_n, 대기 상한 queue_wait_s 초과 = 429."""
    sem = asyncio.Semaphore(sem_n)
    lat: List[float] = []
    busy = 0
    stop = asyncio.Event()
    lags: List[float] = []
    ticker = asyncio.create_task(_loop_lag(stop, lags))

    async def one(inp: QualityInput, k: int) -> None:
        nonlocal busy
        t = time.perf_counter()
        try:
            await asyncio.wait_for(sem.acquire(), timeout=queue_wait_s)
        except asyncio.TimeoutError:
            busy += 1
            return
        try:
            E.clear_cache() if k == 0 else None
            await E.evaluate(inp.model_copy(update={"requestId": f"{inp.requestId[:100]}.c{k}"}))
        finally:
            sem.release()
        lat.append((time.perf_counter() - t) * 1000)

    jobs = [inputs[i % len(inputs)] for i in range(concurrency * 4)]
    t0 = time.perf_counter()
    for i in range(0, len(jobs), concurrency):
        E.clear_cache()   # 캐시 적중을 빼고 실제 평가 시간만
        await asyncio.gather(*(one(inp, i + j) for j, inp in enumerate(jobs[i:i + concurrency])))
    stop.set()
    await ticker
    return {"concurrency": concurrency, "latencyMs": summary(lat), "busy429": busy, "requests": len(jobs),
            "loopLagMs": summary(lags), "wallMs": round((time.perf_counter() - t0) * 1000, 1)}


async def cpu_phase() -> Dict[str, Any]:
    os.environ.pop("AI_QUALITY_JUDGE", None)
    sets = {"roadmap_segment_20k": _roadmap_inputs(), "pdf_qa_contract_max": [_pdf_qa_max()], "quiz_json_10": [_quiz()],
            "vision_text": [_vision()]}
    sizes = {k: [len(SEG.jackson_compact(i.proposedOutput)) if not isinstance(i.proposedOutput, str) else len(i.proposedOutput)
                 for i in v] for k, v in sets.items()}
    res: Dict[str, Any] = {}
    for name, inputs in sets.items():
        single: List[float] = []
        for inp in inputs * 3:
            E.clear_cache()
            t = time.perf_counter()
            await E.evaluate(inp)
            single.append((time.perf_counter() - t) * 1000)
        res[name] = {"proposedOutputChars": {"min": min(sizes[name]), "max": max(sizes[name])}, "singleMs": summary(single),
                     "bursts": [await _burst(inputs, c, 2, 2.0) for c in (1, 2, 4, 8)]}
    return {"phase": "cpu", "judge": "OFF", "semaphore": 2, "queueWaitS": 2.0, "results": res,
            "note": "합성 CPU 측정(GPU·Ollama 미사용). 운영 지연이 아니다. 같은 코드가 운영에서 GPU 생성과 CPU 를 나눠 쓰면 더 느려질 수 있다."}


# ── gpu 단계(가드) ─────────────────────────────────────────────────────────────────
def gpu_snapshot() -> Dict[str, int]:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu",
                          "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout.strip().split(",")
    used, total, util, temp = (int(x) for x in out[:4])
    return {"vramUsedMiB": used, "vramTotalMiB": total, "util": util, "tempC": temp}


def gpu_preflight_decision(snap: Dict[str, int], loaded_models: List[str], allowed_models: List[str]) -> List[str]:
    """시작 거부 사유 목록(빈 목록 = 시작 가능). 순수 함수 — 단위 테스트 대상."""
    why = []
    if snap["util"] > GPU_LIMITS["maxStartUtil"]:
        why.append(f"GPU_BUSY util={snap['util']}")
    if snap["tempC"] > GPU_LIMITS["maxStartTempC"]:
        why.append(f"GPU_HOT temp={snap['tempC']}")
    if snap["vramTotalMiB"] - snap["vramUsedMiB"] < GPU_LIMITS["minFreeVramMiB"]:
        why.append("VRAM_HEADROOM_LOW")
    others = [m for m in loaded_models if m not in allowed_models]
    if others:
        why.append(f"OTHER_MODELS_LOADED {others}")
    return why


def gpu_abort_decision(snap: Dict[str, int], errors: int, started: float, calls: int) -> Optional[str]:
    if snap["tempC"] >= GPU_LIMITS["abortTempC"]:
        return "ABORT_TEMP"
    if snap["vramUsedMiB"] >= GPU_LIMITS["abortVramMiB"]:
        return "ABORT_VRAM"
    if errors >= GPU_LIMITS["maxErrors"]:
        return "ABORT_ERRORS"
    if time.time() - started > GPU_LIMITS["maxWallS"]:
        return "ABORT_WALL"
    if calls >= GPU_LIMITS["maxCalls"]:
        return "ABORT_CALLS"
    return None


SCENARIOS = [
    {"id": "G0", "desc": "기준선: judge 평가만 순차 10회(생성 없음)", "gen": 0, "judge": 10},
    {"id": "G1", "desc": "생성 1스트림(num_predict 256) + judge 평가 10회 동시", "gen": 1, "judge": 10},
    {"id": "G2", "desc": "생성 2스트림 + judge 평가 10회(동시 평가 2)", "gen": 2, "judge": 10},
    {"id": "G3", "desc": "G2 + 비전 판독 모델(qwen3-vl, :11435) 적재 상태", "gen": 2, "judge": 10, "vision": True},
    {"id": "G4", "desc": "judge OFF 결정적 평가 + 생성 2스트림(CPU 경합만)", "gen": 2, "judge": 0, "deterministic": 20},
]


class _Sampler(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.samples: List[Dict[str, int]] = []
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                self.samples.append(gpu_snapshot())
            except Exception:  # noqa: BLE001
                pass
            self._halt.wait(0.5)

    def stop(self) -> None:
        self._halt.set()


async def gpu_phase(dry_run: bool, base: str, model: str) -> Dict[str, Any]:
    import httpx
    snap = gpu_snapshot()
    try:
        loaded = [m["name"] for m in httpx.get(f"{base}/api/ps", timeout=5).json().get("models", [])]
    except Exception as e:  # noqa: BLE001
        return {"phase": "gpu", "status": "PREFLIGHT_ABORT", "reasons": [f"OLLAMA_UNREACHABLE {type(e).__name__}"]}
    reasons = gpu_preflight_decision(snap, loaded, [model])
    plan = {"phase": "gpu", "preflight": {"snapshot": snap, "loaded": loaded, "reasons": reasons}, "limits": GPU_LIMITS,
            "scenarios": SCENARIOS}
    if dry_run:
        return {**plan, "status": "DRY_RUN"}
    if reasons:
        return {**plan, "status": "PREFLIGHT_ABORT"}
    from app.quality_gate.judge import get_judge
    judge = get_judge()
    if judge is None:
        return {**plan, "status": "JUDGE_NOT_CONFIGURED"}
    sampler = _Sampler()
    sampler.start()
    started, errors, calls = time.time(), 0, 0
    out: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async def gen_stream(stop: asyncio.Event, tps: List[float]) -> None:
                nonlocal errors, calls
                while not stop.is_set():
                    calls += 1
                    try:
                        r = await client.post(f"{base}/api/chat", json={
                            "model": model, "stream": False, "think": False, "keep_alive": "60s",
                            "messages": [{"role": "user", "content": "데이터베이스 정규화를 다섯 문장으로 설명해줘."}],
                            "options": {"num_predict": 256, "temperature": 0.2, "num_ctx": 4096}})
                        d = r.json()
                        tps.append(d.get("eval_count", 0) / max(d.get("eval_duration", 1) / 1e9, 1e-6))
                    except Exception:  # noqa: BLE001
                        errors += 1
            for sc in SCENARIOS:
                why = gpu_abort_decision(sampler.samples[-1] if sampler.samples else snap, errors, started, calls)
                if why:
                    out.append({"id": sc["id"], "status": why})
                    break
                stop = asyncio.Event()
                tps: List[float] = []
                gens = [asyncio.create_task(gen_stream(stop, tps)) for _ in range(sc["gen"])]
                lat: List[float] = []
                inp = _pdf_qa_max().model_copy(update={"proposedOutput": "정규화는 중복을 줄이고 갱신 이상을 막는다."})
                for k in range(sc.get("judge", 0) or sc.get("deterministic", 0)):
                    E.clear_cache()
                    t = time.perf_counter()
                    try:
                        await E.evaluate(inp.model_copy(update={"requestId": f"probe-{sc['id']}-{k:04d}"}),
                                         judge=judge if sc.get("judge") else None)
                    except Exception:  # noqa: BLE001
                        errors += 1
                    lat.append((time.perf_counter() - t) * 1000)
                    calls += 1
                    why = gpu_abort_decision(sampler.samples[-1] if sampler.samples else snap, errors, started, calls)
                    if why:
                        break
                stop.set()
                await asyncio.gather(*gens, return_exceptions=True)
                out.append({"id": sc["id"], "evalLatencyMs": summary(lat), "genTps": summary(tps), "status": why or "DONE"})
                if why:
                    break
    finally:
        sampler.stop()
    return {**plan, "status": "DONE", "results": out, "errors": errors, "calls": calls,
            "vramPeakMiB": max((s["vramUsedMiB"] for s in sampler.samples), default=None),
            "tempPeakC": max((s["tempC"] for s in sampler.samples), default=None)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--phase", choices=["cpu", "gpu"], default="cpu")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-gpu", action="store_true")
    ap.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="qwen3:14b")
    a = ap.parse_args()
    if a.phase == "gpu" and not a.dry_run and not (a.allow_gpu and os.getenv("AI_CONTENTION_PROBE_ALLOW") == "1"):
        raise SystemExit("GPU_PHASE_NOT_AUTHORIZED: --allow-gpu 와 AI_CONTENTION_PROBE_ALLOW=1 이 모두 필요하다(운영 GPU 점유)")
    res = asyncio.run(cpu_phase() if a.phase == "cpu" else gpu_phase(a.dry_run, a.ollama_url, a.model))
    res["measuredAt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in res.items() if k != "results"}, ensure_ascii=False)[:2000])


if __name__ == "__main__":
    main()
