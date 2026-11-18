"""작업 유형(WorkloadClass)별 스케줄링 정책.

모든 값은 env 로 덮어쓸 수 있다(AI_GW_<CLASS>_<FIELD>). 기본값은 2026-10-27 ai07 실측
(운영 Ollama 호출 p50 4.1s / p95 15.5s / p99 26.4s, 동시 최대 4건)을 기준으로 잡았다.

weight          : 같은 백엔드 슬롯을 두고 경쟁할 때의 가중치(stride 스케줄링). 클수록 자주 선택.
max_concurrency : 이 클래스가 동시에 점유할 수 있는 GPU 슬롯 수 상한.
max_queue       : 이 클래스의 대기열 상한. 초과 시 즉시 거부(backpressure).
queue_timeout_s : 슬롯 대기 상한. 초과 시 거부(호출부의 기존 timeout 경로로 매핑).
per_user_inflight: 한 사용자(fair key)가 이 클래스에서 동시에 점유하는 슬롯 상한.
                  다른 대기자가 없으면 초과 허용(work-conserving).
per_user_queue  : 한 사용자(fair key)가 이 클래스에서 동시에 대기시킬 수 있는 요청 수. 초과 시 429 USER_LIMIT.
                  식별자 없는 요청(anon)은 적용 제외(그룹스터디 멀티챗은 현재 Spring 이 사용자 id 를 보내지 않음).
                  키가 클라이언트 주장값이면 키를 바꿔 우회할 수 있으므로 '최선 노력' 한도이고, 클래스 단위 상한
                  (max_queue/max_concurrency)은 키와 무관하게 항상 적용된다.
low_priority    : True 면 슬롯이 2개 이상일 때 마지막 1개를 실시간 클래스용으로 남긴다.
external_allowed: OpenAI overflow 대상이 될 수 있는지(데이터 외부 전송 허용 여부).
max_tokens      : 요청당 num_predict 상한(0 = 호출부 값 유지).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from enum import Enum
from typing import Dict


class WorkloadClass(str, Enum):
    VISION = "VISION"
    INTERACTIVE_CHAT = "INTERACTIVE_CHAT"
    MULTI_AGENT = "MULTI_AGENT"
    DOCUMENT_QUIZ = "DOCUMENT_QUIZ"
    DOCUMENT_ANALYSIS = "DOCUMENT_ANALYSIS"
    BACKGROUND_AI_JOB = "BACKGROUND_AI_JOB"


@dataclass(frozen=True)
class Policy:
    weight: float
    max_concurrency: int
    max_queue: int
    queue_timeout_s: float
    per_user_inflight: int
    low_priority: bool
    needs_local_gpu: bool
    external_allowed: bool
    max_tokens: int = 0
    retry: int = 0
    per_user_queue: int = 4


_DEFAULTS: Dict[WorkloadClass, Policy] = {
    WorkloadClass.INTERACTIVE_CHAT: Policy(8.0, 4, 32, 60.0, 1, False, True, False, per_user_queue=4),
    WorkloadClass.MULTI_AGENT: Policy(6.0, 4, 48, 90.0, 1, False, True, False, per_user_queue=4),
    WorkloadClass.VISION: Policy(6.0, 1, 8, 30.0, 1, False, True, False, per_user_queue=2),
    WorkloadClass.DOCUMENT_QUIZ: Policy(3.0, 2, 16, 180.0, 1, True, True, False, per_user_queue=2),
    WorkloadClass.DOCUMENT_ANALYSIS: Policy(2.0, 2, 16, 240.0, 1, True, True, False, per_user_queue=4),
    WorkloadClass.BACKGROUND_AI_JOB: Policy(1.0, 1, 16, 300.0, 1, True, True, False, per_user_queue=4),
}


def _env(name: str, cast, default):
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        if cast is bool:
            return str(raw).strip().lower() in ("1", "true", "yes", "on")
        return cast(raw)
    except (TypeError, ValueError):
        return default


def policy_for(cls: WorkloadClass) -> Policy:
    base = _DEFAULTS[cls]
    p = f"AI_GW_{cls.value}_"
    return replace(
        base,
        weight=max(0.1, _env(p + "WEIGHT", float, base.weight)),
        max_concurrency=max(1, _env(p + "MAX_CONCURRENCY", int, base.max_concurrency)),
        max_queue=max(0, _env(p + "MAX_QUEUE", int, base.max_queue)),
        queue_timeout_s=max(0.1, _env(p + "QUEUE_TIMEOUT_S", float, base.queue_timeout_s)),
        per_user_inflight=max(1, _env(p + "PER_USER_INFLIGHT", int, base.per_user_inflight)),
        low_priority=_env(p + "LOW_PRIORITY", bool, base.low_priority),
        external_allowed=_env(p + "EXTERNAL_ALLOWED", bool, base.external_allowed),
        max_tokens=max(0, _env(p + "MAX_TOKENS", int, base.max_tokens)),
        per_user_queue=max(1, _env(p + "PER_USER_QUEUE", int, base.per_user_queue)),
    )


def all_policies() -> Dict[WorkloadClass, Policy]:
    return {c: policy_for(c) for c in WorkloadClass}


def parse_class(value, default: WorkloadClass = WorkloadClass.INTERACTIVE_CHAT) -> WorkloadClass:
    if isinstance(value, WorkloadClass):
        return value
    try:
        return WorkloadClass(str(value).strip().upper())
    except ValueError:
        return default


# ── 경로 → 작업 유형 매핑 (middleware 가 사용) ──────────────────────────────────
# 앞에서부터 첫 매치. 실측 openapi 경로 목록(2026-10-27, 74개) 기준.
_PATH_RULES = (
    ("/api/ai/vision", WorkloadClass.VISION),
    ("/api/ai/multi-chat", WorkloadClass.MULTI_AGENT),
    ("/api/ai/agents/", WorkloadClass.MULTI_AGENT),
    ("/api/agent/", WorkloadClass.MULTI_AGENT),
    ("/api/ai/learning-mate", WorkloadClass.MULTI_AGENT),
    ("/api/ai/realtime-quiz", WorkloadClass.DOCUMENT_QUIZ),
    ("/api/ai/quiz", WorkloadClass.DOCUMENT_QUIZ),
    ("/api/quiz", WorkloadClass.DOCUMENT_QUIZ),
    ("/api/ai/material/quiz", WorkloadClass.DOCUMENT_QUIZ),
    ("/api/ai/review", WorkloadClass.DOCUMENT_QUIZ),
    ("/api/ai/major-analysis", WorkloadClass.DOCUMENT_ANALYSIS),
    ("/api/ai/material", WorkloadClass.DOCUMENT_ANALYSIS),
    ("/api/ai/summary", WorkloadClass.DOCUMENT_ANALYSIS),
    ("/api/ai/keyword", WorkloadClass.DOCUMENT_ANALYSIS),
    ("/api/materials/", WorkloadClass.DOCUMENT_ANALYSIS),
    ("/api/rag", WorkloadClass.DOCUMENT_ANALYSIS),
    ("/api/ai/rag", WorkloadClass.DOCUMENT_ANALYSIS),
    ("/api/extract", WorkloadClass.DOCUMENT_ANALYSIS),
    ("/api/ai/roadmap", WorkloadClass.BACKGROUND_AI_JOB),
    ("/api/ai/planner", WorkloadClass.BACKGROUND_AI_JOB),
    ("/api/ai/plan-", WorkloadClass.BACKGROUND_AI_JOB),
    ("/api/ai/mindmap", WorkloadClass.BACKGROUND_AI_JOB),
    ("/api/ai/study-journal", WorkloadClass.BACKGROUND_AI_JOB),
    ("/api/ai/learning-loop", WorkloadClass.BACKGROUND_AI_JOB),
    ("/api/training-candidates", WorkloadClass.BACKGROUND_AI_JOB),
)


def class_for_path(path: str) -> WorkloadClass:
    for prefix, cls in _PATH_RULES:
        if path.startswith(prefix):
            return cls
    return WorkloadClass.INTERACTIVE_CHAT
