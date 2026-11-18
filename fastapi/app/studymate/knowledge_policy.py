"""KNOWLEDGE LEVEL 축 정책 — 깊이는 '길이'가 아니라 추상화/형식화/근거 수준으로 정의한다."""
from __future__ import annotations

from typing import Dict, List, Tuple

CONTRACT: Dict[str, Dict[str, object]] = {
    "beginner": {
        "name": "입문",
        "required": [
            "왜 이것이 중요한지(why it matters)를 먼저 한두 문장으로 말한다",
            "구체적인 예시 1개를 든다",
            "전문용어(영어 약어·기술 용어 포함)는 꼭 필요한 1~2개만 쓰고, 쓸 때마다 바로 괄호나 '즉'으로 쉬운 말 풀이를 붙인다",
            "일상 장면 비유 1개로 직관을 먼저 준다",
            "정식 정의보다 직관을 먼저 준다",
            "전체를 8문장 안팎으로 짧게 유지한다",
        ],
        "avoid": "번호 매긴 형식 추론, 알고리즘 이름 나열(예: 버전·변종 이름), 풀이 없는 약어, 수식·복잡도·구현 세부를 쓰지 않는다. 다음 학습 포인트도 쉬운 말로 쓴다(약어 금지). 성격의 형식 규칙도 입문 눈높이에 맞춰 쉬운 말로 완화한다.",
    },
    "bachelor": {
        "name": "학사",
        "required": [
            "정확한 정의를 제시한다",
            "동작 원리(mechanism)를 단계로 설명한다",
            "표준 알고리즘·구현 방식을 언급한다",
            "해당되면 기본 시간/공간 복잡도를 말한다",
        ],
        "avoid": "직관 비유만으로 끝내지 않는다. 대신 교과서 수준의 정확한 메커니즘을 준다.",
    },
    "master": {
        "name": "석사",
        "required": [
            "구성 요소 간 아키텍처/구조 관점에서 설명한다",
            "대안과 비교한 트레이드오프를 1개 이상 제시한다",
            "대표적인 실패 모드(failure mode)를 1개 이상 말한다",
            "실무 또는 연구와의 연결을 짚는다",
        ],
        "avoid": "정의 반복에 분량을 쓰지 않는다. 대신 선택의 기준과 대가를 설명한다.",
    },
    "phd": {
        "name": "박사",
        "required": [
            "성립에 필요한 가정(assumptions)을 명시한다",
            "한계(limitations)를 명시한다",
            "경계조건(boundary conditions)을 제시한다",
            "반례 또는 실패 영역을 제시한다",
            "핵심 동작을 형식 모델 1개(간단한 수식·상태 전이·불변식 중 하나)로 표현하고 그 모델이 깨지는 조건을 논한다",
        ],
        "avoid": "석사식 아키텍처·도구 나열로 분량을 채우지 않는다. 대신 모델·가정·경계조건의 엄밀함으로 깊이를 보인다. 근거 없는 논문명·벤치마크 수치·버전 번호를 만들지 않는다.",
    },
    "expert": {
        "name": "전문가",
        "required": [
            "첫 문단부터 운영 환경(production) 아키텍처 관점으로 시작한다(교과서식 동작 원리 재설명은 1~2문장으로 제한)",
            "신뢰성(reliability)과 장애 대응을 다룬다",
            "관측 가능성(observability: 지표/로그/트레이스)을 다룬다",
            "용량 계획(capacity)과 보안 영향(security implications)을 다룬다",
            "구현 제약과 운영상 트레이드오프를 제시한다",
        ],
        "avoid": "입문식 비유로 분량을 쓰지 않는다. 대신 운영 결정에 필요한 판단 기준을 준다. 근거 없는 수치는 만들지 않는다.",
    },
}

EVIDENCE_POLICY_LEVELS = ("phd", "expert")

# 수준별 구체 목차. 작은/중형 모델은 추상 요구 목록보다 순서가 정해진 목차를 훨씬 잘 따른다(2026-09-17 라이브 측정).
OUTLINE = {
    "beginner": "일상 장면 → 왜 필요한지 → 한 단계씩 쉬운 설명 → 쉬운 다음 걸음",
    "bachelor": "정의 → 동작 단계 → 표준 방식(해당 시 복잡도) → 예시 → 주의점",
    "master": "구조(구성 요소) → 설계 선택과 대안 비교(트레이드오프) → 대표 실패 모드 → 실무·연구 연결",
    "phd": "형식 모델(간단한 수식·상태전이·불변식 중 하나) → 모델이 성립하는 가정 → 경계조건 → 반례·실패 영역 → 한계와 열린 문제",
    "expert": "운영 아키텍처 → 신뢰성·장애 대응 → 관측 지표(무엇을 모니터링) → 용량·보안 영향 → 운영 트레이드오프와 구현 제약",
}
EVIDENCE_POLICY = (
    "[근거 정책] 제공된 [근거 자료]에 없는 구체적 수치(성능 %, 지연 ms, 배수), 논문명·저자·연도, "
    "표준/소프트웨어 버전 번호를 임의로 만들지 않는다. 필요하면 '환경에 따라 다르다', "
    "'측정이 필요하다'처럼 조건으로 표현한다."
)

PLAN_FIELDS: Dict[str, List[Tuple[str, str, int]]] = {
    "beginner": [("why_it_matters", "string", 0), ("concrete_example", "string", 0)],
    "bachelor": [("definition", "string", 0), ("mechanism", "array", 1)],
    "master": [("tradeoffs", "array", 1), ("failure_modes", "array", 1)],
    "phd": [("assumptions", "array", 1), ("limitations", "array", 1), ("boundary_conditions", "array", 1),
            ("formal_model", "string", 0)],
    "expert": [("production_constraints", "array", 1), ("failure_domains", "array", 1), ("operational_tradeoffs", "array", 1)],
}

RUBRIC: Dict[str, List[Tuple[str, str]]] = {
    "beginner": [
        ("why_it_matters", "왜 중요한지 설명했다"),
        ("concrete_example", "구체적 예시가 있다"),
        ("jargon_explained", "전문용어를 쉬운 말로 풀었다"),
        ("intuition_first", "공식 정의보다 직관이 먼저 나온다"),
    ],
    "bachelor": [
        ("definition", "정확한 정의가 있다"),
        ("mechanism", "동작 원리를 단계로 설명했다"),
        ("standard_approach", "표준 알고리즘/구현을 언급했다"),
        ("no_research_depth_only", "구체적 메커니즘 없이 추상론만 하지 않았다"),
    ],
    "master": [
        ("architecture", "구조/아키텍처 관점이 있다"),
        ("tradeoff", "트레이드오프를 제시했다"),
        ("failure_mode", "실패 모드를 제시했다"),
        ("practical_connection", "실무/연구 연결이 있다"),
    ],
    "phd": [
        ("states_assumptions", "가정을 명시했다"),
        ("has_limitation", "한계를 명시했다"),
        ("has_boundary_condition", "경계조건을 제시했다"),
        ("counterexample_or_failure_domain", "반례나 실패 영역을 제시했다"),
    ],
    "expert": [
        ("production_architecture", "운영 아키텍처 관점이 있다"),
        ("reliability_or_observability", "신뢰성 또는 관측 가능성을 다뤘다"),
        ("capacity_or_security", "용량 또는 보안 영향을 다뤘다"),
        ("operational_tradeoff", "운영상 트레이드오프/구현 제약을 제시했다"),
    ],
}
