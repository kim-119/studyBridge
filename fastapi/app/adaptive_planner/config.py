"""적응형 학습 엔진 상수. 가중치·한도는 전부 여기서만 정의하고 env 로 덮어쓸 수 있다.

MANUAL_NEXT 점수 = 우선순위 + 마감 근접 + 지연(마감 경과/예정일 경과) + 진행 중 + 시간 적합 + 사용자 순서.
점수는 '설명용 정수'다. 응답의 scoreBreakdown 이 각 요인의 실제 기여분을 그대로 보여 준다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Tuple


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _flag(name: str, default: str) -> bool:
    return (os.getenv(name, default) or default).strip().lower() in ("1", "true", "yes", "on")


CONTRACT_VERSION = "adaptive-planner.v1"
ALLOWED_MINUTES: Tuple[int, ...] = (15, 30, 60)
DEFAULT_TIMEZONE = "Asia/Seoul"


@dataclass(frozen=True)
class ManualWeights:
    # 사용자 지정 우선순위. 미지정은 중립값(보통과 같음)이며 추천 이유에 인용하지 않는다.
    priority: Dict[str, int] = field(default_factory=lambda: {"URGENT": 40, "HIGH": 30, "MEDIUM": 15, "LOW": 5})
    priority_unset: int = 15
    # 마감 근접: 오늘 마감 due_max, 하루 멀어질 때마다 due_step 씩 감소(음수 없음).
    due_max: int = 40
    due_step: int = 5
    # 마감 경과(미완료): overdue_base + 경과일 × overdue_per_day (최대 overdue_cap 까지 가산).
    overdue_base: int = 45
    overdue_per_day: int = 2
    overdue_cap: int = 10
    # 예정일 경과(마감은 아직이거나 없음): delayed_base + 경과일 × delayed_per_day (최대 delayed_cap).
    delayed_base: int = 20
    delayed_per_day: int = 2
    delayed_cap: int = 10
    scheduled_today: int = 10
    in_progress: int = 8
    fits_available_time: int = 10
    # 사용자 순서: 미완료 항목 중 순서 r(0부터)에 max(0, order_max - r).
    order_max: int = 5


def manual_weights() -> ManualWeights:
    d = ManualWeights()
    return ManualWeights(
        priority={k: _int(f"ADAPTIVE_W_PRIORITY_{k}", v) for k, v in d.priority.items()},
        priority_unset=_int("ADAPTIVE_W_PRIORITY_UNSET", d.priority_unset),
        due_max=_int("ADAPTIVE_W_DUE_MAX", d.due_max),
        due_step=_int("ADAPTIVE_W_DUE_STEP", d.due_step),
        overdue_base=_int("ADAPTIVE_W_OVERDUE_BASE", d.overdue_base),
        overdue_per_day=_int("ADAPTIVE_W_OVERDUE_PER_DAY", d.overdue_per_day),
        overdue_cap=_int("ADAPTIVE_W_OVERDUE_CAP", d.overdue_cap),
        delayed_base=_int("ADAPTIVE_W_DELAYED_BASE", d.delayed_base),
        delayed_per_day=_int("ADAPTIVE_W_DELAYED_PER_DAY", d.delayed_per_day),
        delayed_cap=_int("ADAPTIVE_W_DELAYED_CAP", d.delayed_cap),
        scheduled_today=_int("ADAPTIVE_W_SCHEDULED_TODAY", d.scheduled_today),
        in_progress=_int("ADAPTIVE_W_IN_PROGRESS", d.in_progress),
        fits_available_time=_int("ADAPTIVE_W_FITS_TIME", d.fits_available_time),
        order_max=_int("ADAPTIVE_W_ORDER_MAX", d.order_max),
    )


# 시간 템플릿(분). core 는 실제 학습 활동, wrap 은 마무리 확인. 합계 = 선택 시간.
# 15분은 핵심 1개만, 60분은 개념→예제→적용까지 다룬다(분량과 범위가 실제로 달라진다).
ROADMAP_TEMPLATES: Dict[int, Dict] = {
    15: {"core": (("CONCEPT", 5), ("UNDERSTAND", 5)), "wrap": ("CHECK", 5), "remediation": 3, "max_tasks": 1},
    30: {"core": (("CONCEPT", 10), ("EXAMPLE", 15)), "wrap": ("REVIEW", 5), "remediation": 5, "max_tasks": 2},
    60: {"core": (("CONCEPT", 15), ("EXAMPLE", 20), ("PRACTICE", 20)), "wrap": ("REVIEW", 5),
         "remediation": 10, "max_tasks": 3},
}
# 수기 항목: 준비 → 본 학습 → 정리. 세션이 10분 이하이면 본 학습 하나만.
MANUAL_TEMPLATES: Dict[int, Dict] = {
    15: {"prep": 2, "wrap": 3, "max_tasks": 1},
    30: {"prep": 3, "wrap": 5, "max_tasks": 2},
    60: {"prep": 5, "wrap": 5, "max_tasks": 3},
}
MAX_RECOVERY_SESSIONS = 7
MAX_RECOVERY_ITEMS = 3
# 지연 복구 제안을 그날의 남은 시간에 끼워 넣을 때의 최소 분(그보다 짧게 남은 날은 건너뛴다).
MIN_RECOVERY_SESSION_MINUTES = 10
MAX_ALTERNATIVES = 2


@dataclass(frozen=True)
class Limits:
    max_body_bytes: int
    max_items: int
    max_tasks_per_item: int
    max_quiz_results: int
    title_chars: int
    description_chars: int
    task_chars: int
    question_chars: int
    concept_chars: int
    max_concepts_per_result: int


def limits() -> Limits:
    return Limits(
        max_body_bytes=_int("ADAPTIVE_MAX_BODY_BYTES", 262_144),
        max_items=_int("ADAPTIVE_MAX_ITEMS", 200),
        max_tasks_per_item=_int("ADAPTIVE_MAX_TASKS_PER_ITEM", 30),
        max_quiz_results=_int("ADAPTIVE_MAX_QUIZ_RESULTS", 200),
        title_chars=200, description_chars=2000, task_chars=300, question_chars=300,
        concept_chars=60, max_concepts_per_result=5,
    )


@dataclass(frozen=True)
class RuntimeSettings:
    enabled: bool
    llm_enabled: bool
    allow_unauthenticated: bool
    request_timeout_s: float
    llm_timeout_s: float
    llm_num_predict: int
    llm_temperature: float
    llm_skip_queue_depth: int
    max_inflight: int
    max_inflight_per_user: int


def runtime() -> RuntimeSettings:
    return RuntimeSettings(
        enabled=_flag("ADAPTIVE_PLANNER_ENABLED", "true"),
        llm_enabled=_flag("ADAPTIVE_PLANNER_LLM_ENABLED", "true"),
        # 로컬 개발 전용. AI_SERVER_API_KEY 가 없으면 기본은 503(fail-closed).
        allow_unauthenticated=_flag("ADAPTIVE_PLANNER_ALLOW_UNAUTHENTICATED", "false"),
        request_timeout_s=_float("ADAPTIVE_REQUEST_TIMEOUT_S", 30.0),
        llm_timeout_s=_float("ADAPTIVE_LLM_TIMEOUT_S", 20.0),
        llm_num_predict=_int("ADAPTIVE_LLM_NUM_PREDICT", 700),
        llm_temperature=_float("ADAPTIVE_LLM_TEMPERATURE", 0.3),
        # 텍스트 GPU 대기열이 이 깊이 이상이면 LLM 을 건너뛰고 규칙 결과를 즉시 낸다(Vision·멀티에이전트 보호).
        llm_skip_queue_depth=_int("ADAPTIVE_LLM_SKIP_QUEUE_DEPTH", 2),
        max_inflight=_int("ADAPTIVE_MAX_INFLIGHT", 8),
        max_inflight_per_user=_int("ADAPTIVE_MAX_INFLIGHT_PER_USER", 2),
    )
