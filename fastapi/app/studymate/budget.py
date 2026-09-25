"""Latency Budget Manager — 턴 단위 시간 예산.

모든 하위 LLM 호출 timeout 은 남은 예산보다 클 수 없다(llm_gateway 에 deadline 으로 전달).
남은 예산이 단계 최소치보다 작으면 그 단계를 '시작하지 않는다'.
  reviewer(judge) < JUDGE_MIN   → skip
  repair          < REPAIR_MIN  → skip
  regenerate      < REGEN_MIN   → 금지
  추가 발화(REACTION) < REACTION_MIN → skip
예산 소진 시: 이미 성공한 답변은 보존, 나머지는 TURN_TIMEOUT 으로 degraded finalize.

기본 예산은 2026-09-16 실측 baseline(basic 3인 37.6s / socratic 14.2s / simulation 7.2s /
debate 51.3s)에 여유를 둔 값이며 env 로 조정한다. 목표 p95 는 docs 벤치 결과 참조.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Dict, List

_DEFAULT_BUDGET_S = {
    "basic_single": 45.0,
    "basic_multi": 95.0,
    "socratic": 75.0,
    "simulation": 75.0,
    "debate": 180.0,
}

# 체감 지연 목표(soft). 하드 예산과 별개로 'repair 같은 선택적 품질 단계'를 이 안에서만 시작한다.
_DEFAULT_SOFT_S = {"basic_single": 15.0, "basic_multi": 42.0, "socratic": 25.0, "simulation": 25.0, "debate": 65.0}


def soft_seconds(kind: str) -> float:
    try:
        return float(os.getenv(f"STUDYMATE_SOFT_{kind.upper()}_S", str(_DEFAULT_SOFT_S.get(kind, 40.0))))
    except (TypeError, ValueError):
        return _DEFAULT_SOFT_S.get(kind, 40.0)


STAGE_MIN_S = {
    "render": 12.0,
    "planner": 10.0,
    "reaction": 14.0,
    "repair": 14.0,
    "regenerate": 18.0,
    "judge": 8.0,
    "grounding": 6.0,
}


def budget_seconds(kind: str) -> float:
    try:
        return float(os.getenv(f"STUDYMATE_BUDGET_{kind.upper()}_S", str(_DEFAULT_BUDGET_S.get(kind, 90.0))))
    except (TypeError, ValueError):
        return _DEFAULT_BUDGET_S.get(kind, 90.0)


def stage_min(stage: str) -> float:
    try:
        return float(os.getenv(f"STUDYMATE_STAGE_MIN_{stage.upper()}_S", str(STAGE_MIN_S.get(stage, 10.0))))
    except (TypeError, ValueError):
        return STAGE_MIN_S.get(stage, 10.0)


@dataclass
class TurnBudget:
    kind: str
    total_s: float
    started: float = field(default_factory=time.time)
    skipped: List[str] = field(default_factory=list)

    @classmethod
    def for_kind(cls, kind: str) -> "TurnBudget":
        return cls(kind=kind, total_s=budget_seconds(kind))

    @property
    def deadline(self) -> float:
        return self.started + self.total_s

    def soft_remaining(self) -> float:
        return self.started + soft_seconds(self.kind) - time.time()

    def remaining(self) -> float:
        return self.deadline - time.time()

    def elapsed_ms(self) -> int:
        return int((time.time() - self.started) * 1000)

    def exhausted(self) -> bool:
        return self.remaining() <= 0

    def allows(self, stage: str) -> bool:
        ok = self.remaining() >= stage_min(stage)
        if not ok:
            self.skipped.append(stage)
        return ok

    def snapshot(self) -> Dict[str, object]:
        return {"kind": self.kind, "totalS": self.total_s, "elapsedMs": self.elapsed_ms(),
                "remainingS": round(self.remaining(), 2), "skippedStages": list(self.skipped)}
