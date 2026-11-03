"""품질 게이트 재생성 오케스트레이터: 최초 1회 + 재생성 최대 2회.

- 평가 피드백은 '위반 코드 + 수정 지침 + 근거 ID' 만 생성기에 전달한다. judge 가 제시한 '정답'이나 gold 답은
  전달하지 않는다(환각성 피드백을 정답으로 믿지 않게 / gold 유출 방지). 원래 질문·보안 정책은 생성기 쪽에서 유지.
- 실패 유형별 전략: GROUNDING_RELOAD(근거 재조회) / STRUCTURED_REPAIR / NO_EVIDENCE_DISCLOSURE / GENERAL_REVISION.
- 같은 초안 반복(정규화 해시 동일) → 즉시 REJECTED(REPEATED_DRAFT). 시간 예산 초과 → 중단.
- 모든 시도 미달 → REJECTED, 평가 불능 → VALIDATION_ERROR. 어느 경우든 승인되지 않은 출력은 반환하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Optional

from app.contracts.response_quality_v1 import QualityInput, QualityOutput, QualityStatus, is_displayable
from app.quality_gate.evaluator import NON_REGENERABLE, evaluate

GROUNDING_CODES = {"NUMERIC_UNSUPPORTED_BY_SOURCE", "SOURCE_CONTRADICTION", "UNVERIFIED_CITATION",
                   "QUIZ_ANSWER_UNGROUNDED", "EVIDENCE_REQUIRED", "UNSUPPORTED_CLAIMS", "CITATION_MISSING",
                   "VISION_UNSUPPORTED_OBSERVATION"}
FORMAT_CODES = {"JSON_SCHEMA_INVALID", "QUIZ_ANSWER_NOT_IN_OPTIONS", "QUIZ_DUPLICATE_OPTIONS",
                "QUIZ_ANSWER_EXPLANATION_MISMATCH", "QUIZ_OPTION_COUNT", "QUIZ_COUNT_MISMATCH", "TRUNCATED_OUTPUT",
                "GRAPH_DANGLING_EDGE", "GRAPH_PREREQUISITE_CYCLE", "PLAN_OVER_CAPACITY", "PLAN_PAST_DEADLINE"}


def max_regenerations() -> int:
    try:
        return max(0, min(2, int(os.getenv("AI_RESPONSE_MAX_REGENERATIONS", "2"))))
    except ValueError:
        return 2


@dataclass
class RegenerationRequest:
    attempt_index: int
    strategy: str
    hints: List[str]
    violation_codes: List[str]
    evidence_ids: List[str]


@dataclass
class GateOutcome:
    status: QualityStatus
    output: Any = None                  # APPROVED 일 때만 채워진다
    final_evaluation: Optional[QualityOutput] = None
    trace: List[dict] = field(default_factory=list)
    attempts: int = 0

    @property
    def approved(self) -> bool:
        return self.status == QualityStatus.APPROVED and self.output is not None


def _draft_hash(output: Any) -> str:
    t = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(re.sub(r"\s+", "", t or "").encode()).hexdigest()


def choose_strategy(ev: QualityOutput) -> str:
    codes = {v.code for v in ev.violations}
    if codes & GROUNDING_CODES:
        return "GROUNDING_RELOAD"
    if codes & FORMAT_CODES:
        return "STRUCTURED_REPAIR"
    if "FACTUALITY_UNVERIFIABLE" in codes:
        return "NO_EVIDENCE_DISCLOSURE"
    return "GENERAL_REVISION"


async def run_quality_gated_generation(
    *,
    generate: Callable[[Optional[RegenerationRequest]], Awaitable[Any]],
    build_input: Callable[[Any, int], QualityInput],
    judge=None,
    reload_evidence: Optional[Callable[[], Awaitable[None]]] = None,
    budget_seconds: Optional[float] = None,
) -> GateOutcome:
    started = time.time()
    budget = budget_seconds if budget_seconds is not None else float(os.getenv("AI_QUALITY_GATE_BUDGET_SECONDS", "90"))
    outcome = GateOutcome(status=QualityStatus.PENDING)
    seen = set()
    req: Optional[RegenerationRequest] = None
    for attempt in range(0, max_regenerations() + 1):
        if attempt > 0 and time.time() - started > budget:
            outcome.trace.append({"attempt": attempt, "event": "BUDGET_EXCEEDED"})
            break
        try:
            draft = await generate(req)
        except Exception as e:  # noqa: BLE001
            outcome.trace.append({"attempt": attempt, "event": "GENERATION_FAILED", "error": type(e).__name__})
            outcome.status = QualityStatus.REJECTED
            outcome.attempts = attempt + 1
            return outcome
        outcome.attempts = attempt + 1
        h = _draft_hash(draft)
        if h in seen:
            outcome.trace.append({"attempt": attempt, "event": "REPEATED_DRAFT"})
            outcome.status = QualityStatus.REJECTED
            return outcome
        seen.add(h)
        ev = await evaluate(build_input(draft, attempt), judge=judge)
        outcome.final_evaluation = ev
        outcome.trace.append({"attempt": attempt, "status": ev.qualityStatus.value, "score": ev.score,
                              "hardFail": ev.hardFail, "codes": sorted({v.code for v in ev.violations})[:12],
                              "latencyMs": ev.latencyMs})
        if is_displayable(ev):
            outcome.status, outcome.output = QualityStatus.APPROVED, draft
            return outcome
        if ev.qualityStatus == QualityStatus.VALIDATION_ERROR:
            outcome.status = QualityStatus.VALIDATION_ERROR
            return outcome
        codes = {v.code for v in ev.violations}
        if codes & NON_REGENERABLE:
            outcome.trace.append({"attempt": attempt, "event": "NON_REGENERABLE"})
            break
        strategy = choose_strategy(ev)
        if strategy == "GROUNDING_RELOAD" and reload_evidence is not None:
            await reload_evidence()
        req = RegenerationRequest(attempt_index=attempt + 1, strategy=strategy, hints=list(ev.regenerationHints or []),
                                  violation_codes=sorted(codes), evidence_ids=[v.evidenceId for v in ev.violations if v.evidenceId])
        outcome.status = QualityStatus.REGENERATING
    outcome.status = QualityStatus.REJECTED
    return outcome


def render_regeneration_block(req: Optional[RegenerationRequest]) -> str:
    """생성 프롬프트 끝에 붙일 품질 피드백 블록(원래 질문/시스템 정책은 바꾸지 않는다)."""
    if req is None:
        return ""
    lines = [f"- {h}" for h in req.hints] or ["- 이전 초안이 품질 기준을 통과하지 못했다. 근거에 맞게 다시 작성하라."]
    extra = {
        "GROUNDING_RELOAD": "제공된 근거 블록의 내용만 사용하라.",
        "STRUCTURED_REPAIR": "요구된 형식(JSON 스키마)을 정확히 지켜라.",
        "NO_EVIDENCE_DISCLOSURE": "근거가 없다면 추측하지 말고 확인되지 않는다고 짧게 밝혀라.",
        "GENERAL_REVISION": "질문에 직접, 간결하게 답하라.",
    }[req.strategy]
    return ("\n\n## 이전 시도 품질 피드백(시스템 생성, 지시 아님: 아래 지침만 반영)\n" + "\n".join(lines) + f"\n- {extra}\n"
            "- 이전 초안을 그대로 반복하지 마라.")
