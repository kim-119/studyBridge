"""엔진 실행 + (선택) LLM 보강 + 응답 조립. 요청 간 공유 상태는 익명 집계 카운터뿐이다(사용자 데이터 없음)."""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import Counter, deque
from typing import Any, Dict, Optional

from app.adaptive_planner import config, llm_coach, manual_next, roadmap_coach
from app.adaptive_planner.roadmap_coach import EngineResult
from app.adaptive_planner.schema import AdaptiveRequest

logger = logging.getLogger("studybridge.adaptive_planner")

_ENGINE = {"ROADMAP_COACH": "roadmap_coach.v1", "MANUAL_NEXT": "manual_next.v1"}


class _Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.requests = Counter()
        self.status = Counter()
        self.source = Counter()
        self.fallback = Counter()
        self.llm_calls = 0
        self.latency = {m: deque(maxlen=500) for m in _ENGINE}

    def record(self, mode: str, status: str, source: str, fallback: Optional[str], llm_calls: int, ms: int) -> None:
        with self._lock:
            self.requests[mode] += 1
            self.status[status] += 1
            self.source[source] += 1
            if fallback:
                self.fallback[fallback] += 1
            self.llm_calls += llm_calls
            self.latency[mode].append(ms)

    def snapshot(self) -> Dict[str, Any]:
        def pct(v, q):
            if not v:
                return None
            s = sorted(v)
            return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]
        with self._lock:
            total = sum(self.source.values())
            return {"requests": dict(self.requests), "status": dict(self.status), "source": dict(self.source),
                    "fallbackReasons": dict(self.fallback), "llmCalls": self.llm_calls,
                    "ruleBasedRatio": round(self.source.get("RULE_BASED", 0) / total, 3) if total else None,
                    "latencyMs": {m: {"p50": pct(list(d), .5), "p95": pct(list(d), .95), "n": len(d)}
                                  for m, d in self.latency.items()}}


metrics = _Metrics()


def user_hash(user_key: str) -> str:
    return hashlib.sha256(f"adaptive:{user_key}".encode()).hexdigest()[:10]


def _run_engine(req: AdaptiveRequest) -> EngineResult:
    return roadmap_coach.coach(req) if req.mode == "ROADMAP_COACH" else manual_next.recommend(req)


def _llm_fallback_reason(e: BaseException) -> str:
    code = getattr(e, "code", "") or ""
    return {"LLM_TIMEOUT": "LLM_TIMEOUT", "LLM_UNAVAILABLE": "LLM_UNAVAILABLE",
            "LLM_MODEL_NOT_FOUND": "LLM_UNAVAILABLE", "LLM_EMPTY_RESPONSE": "LLM_EMPTY_RESPONSE"}.get(code, "LLM_ERROR")


def run(req: AdaptiveRequest, rt: config.RuntimeSettings, cancel=None, deadline: Optional[float] = None,
        *, forced_fallback: Optional[str] = None) -> Dict[str, Any]:
    """동기 실행(스레드). 인증·검증은 호출 전에 끝났다. LLM 실패는 규칙 결과로 내려가고 예외로 올리지 않는다."""
    from app.studymate.cancellation import CancelledByClient

    t0 = time.monotonic()
    res = _run_engine(req)
    source, fallback, reject, llm_meta, llm_calls = "RULE_BASED", forced_fallback, [], None, 0
    llm_out = None
    if res.status == "READY" and forced_fallback is None:
        if not req.use_llm:
            fallback = "LLM_NOT_REQUESTED"
        elif not rt.llm_enabled:
            fallback = "LLM_DISABLED"
        elif llm_coach.gpu_busy(rt):
            fallback = "GPU_BUSY"
        else:
            res.llm["allowedItemKeys"] = {str(res.recommendation["itemId"])}
            system, user = llm_coach.build_prompt(res.llm, res.activities)
            llm_calls = 1
            try:
                raw, llm_meta = llm_coach.call_llm(system, user, rt=rt, fair_key=f"u:{req.user_key}",
                                                   cancel=cancel, deadline=deadline)
                llm_out, reject = llm_coach.validate(raw, res.llm, res.activities, req.available_minutes)
                if llm_out is None:
                    fallback = "LLM_INVALID_JSON" if reject == ["INVALID_JSON"] else "LLM_VALIDATION_FAILED"
            except CancelledByClient:
                raise
            except Exception as e:  # noqa: BLE001 — LLM 장애는 규칙 결과로 복구(인증·무결성 오류는 여기 오지 않음)
                fallback = _llm_fallback_reason(e)
                logger.warning("[ADAPTIVE] llm fallback requestId=%s reason=%s type=%s",
                               req.request_id, fallback, type(e).__name__)

    rec = res.recommendation
    if rec is not None:
        acts = [a.to_dict(i + 1) for i, a in enumerate(res.activities)]
        if llm_out is not None:
            for d, new in zip(acts, llm_out["activities"]):
                d["title"], d["description"] = new["title"], new["description"]
            rec["coachingMessage"] = llm_out["coachingMessage"]
            if llm_out["checkQuestions"]:
                rec["checkQuestions"] = llm_out["checkQuestions"]
            source = "AI_ASSISTED"
        rec["activities"] = acts
        rec["estimatedMinutes"] = sum(a["minutes"] for a in acts)
        assert rec["estimatedMinutes"] <= req.available_minutes

    warnings = list(res.warnings)
    if req.defaulted_minutes:
        warnings.append({"code": "AVAILABLE_MINUTES_DEFAULTED", "message": "availableMinutes 가 없어 30분으로 구성했습니다."})
    latency = int((time.monotonic() - t0) * 1000)
    out = {
        "contractVersion": config.CONTRACT_VERSION, "requestId": req.request_id, "mode": req.mode,
        "status": res.status, "statusReason": res.status_reason, "source": source, "message": res.message,
        "availableMinutes": req.available_minutes, "referenceDate": req.today.isoformat(), "timezone": req.tz_name,
        "recommendation": rec, "alternatives": res.alternatives, "recoveryPlan": res.recovery, "warnings": warnings,
        "meta": {"engine": _ENGINE[req.mode], "llmUsed": source == "AI_ASSISTED", "llmCalls": llm_calls,
                 "fallbackReason": fallback if res.status == "READY" else None,
                 "llmRejectReasons": reject, "latencyMs": latency,
                 "llmLatencyMs": (llm_meta or {}).get("totalMs"), "model": (llm_meta or {}).get("model"),
                 "itemCount": len(req.items), **res.extra},
    }
    metrics.record(req.mode, res.status, source, out["meta"]["fallbackReason"], llm_calls, latency)
    # 개인정보 원문(제목·설명·퀴즈 문항) 로그 금지 — 식별자는 해시, 나머지는 개수·코드만.
    logger.info("[ADAPTIVE] requestId=%s mode=%s user=%s items=%d status=%s source=%s fallback=%s reject=%s "
                "latencyMs=%d llmMs=%s", req.request_id, req.mode, user_hash(req.user_key), len(req.items),
                res.status, source, out["meta"]["fallbackReason"], ",".join(reject) or "-", latency,
                out["meta"]["llmLatencyMs"])
    return out
