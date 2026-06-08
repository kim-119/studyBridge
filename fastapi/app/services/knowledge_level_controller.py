"""
지식수준별 프롬프트 지시사항 생성기.
5단계(입문/학사/석사/박사/전문가)로 답변 깊이와 어휘 수준을 제어한다.
"""
from enum import Enum


class KnowledgeLevel(str, Enum):
    BEGINNER      = "입문"
    UNDERGRADUATE = "학사"
    GRADUATE      = "석사"
    PHD           = "박사"
    EXPERT        = "전문가"


_LEVEL_INSTRUCTIONS: dict[KnowledgeLevel, str] = {
    KnowledgeLevel.BEGINNER: """\
지식수준: 입문
- 전문 용어를 최소화하고, 꼭 필요하면 쉬운 말로 풀어서 설명한다.
- 일상 비유(레고, 요리, 교통 등)나 실생활 예시를 반드시 포함한다.
- 핵심 개념 1~2개에만 집중하고 나머지는 생략한다.
- "왜 알아야 하는가"부터 시작하면 좋다.
- 한 문단은 3~4문장 이내로 짧게 끊는다.""",

    KnowledgeLevel.UNDERGRADUATE: """\
지식수준: 학사
- 기본 개념 정의와 작동 원리를 명확히 설명한다.
- 전공 용어는 처음 등장할 때 괄호로 짧게 설명한다.
- 기본 예시와 간단한 비교(장단점 포함)를 포함한다.
- 이론과 실제 구현 사이 연결고리를 보여준다.
- 교과서 수준의 설명 깊이.""",

    KnowledgeLevel.GRADUATE: """\
지식수준: 석사
- 구조적 설명: 배경 → 원리 → 한계 → 적용 조건 순서.
- 유사 기법 또는 접근법과의 트레이드오프 비교가 포함되어야 한다.
- 성능, 복잡도, 예외 상황을 구체적으로 언급한다.
- 실무 적용 또는 논문/연구 관점을 일부 포함한다.
- 단순 설명이 아니라 "왜 이 방법인가"에 대한 분석이 있어야 한다.""",

    KnowledgeLevel.PHD: """\
지식수준: 박사
- 이론적 구조와 수학적·논리적 근거를 포함한다.
- 엣지 케이스, 경계 조건, 예외 상황을 반드시 분석한다.
- 구조적 한계와 확장 가능성(Future Work)을 논의한다.
- 기존 연구의 가정에 의문을 제기하거나 대안 관점을 제시한다.
- 박사 세미나 발표 수준의 분석 깊이. 핵심 문장에 근거가 있어야 한다.""",

    KnowledgeLevel.EXPERT: """\
지식수준: 전문가 (실서비스 운영 기준)
- 실서비스 운영 경험 기반 판단을 우선한다.
- 병목 지점, 장애 가능성, 비용 구조, 모니터링 지표를 반드시 포함한다.
- 대응 순서와 의사결정 기준(어떤 상황에서 무엇을 선택하는가)을 명시한다.
- SLA, 가용성, 확장성, 비용 최적화 관점을 포함한다.
- 이론보다 실전 트러블슈팅 경험 기반 조언을 우선한다.""",
}

_VALIDATION_CRITERIA: dict[str, str] = {
    "입문":    "비유·쉬운 예시가 포함되었는가? 전문 용어 남발은 없는가? 핵심만 설명했는가?",
    "학사":    "개념 정의가 명확한가? 작동 원리가 설명되었는가? 기본 예시와 비교가 있는가?",
    "석사":    "구조적 설명이 있는가? 비교 분석이 포함되었는가? 한계·적용 조건이 언급되었는가?",
    "박사":    "이론적 근거가 있는가? 엣지 케이스가 분석되었는가? 구조적 한계가 논의되었는가?",
    "전문가":  "실서비스 운영 관점인가? 병목·장애·비용이 포함되었는가? 의사결정 기준이 있는가?",
}


def get_level_instruction(level: str) -> str:
    """지식수준 문자열을 받아 시스템 프롬프트에 삽입할 지시사항을 반환한다."""
    try:
        key = KnowledgeLevel(level)
    except ValueError:
        key = KnowledgeLevel.UNDERGRADUATE
    return _LEVEL_INSTRUCTIONS[key]


def get_validation_criteria(level: str) -> str:
    """GPT 검증 시 사용할 지식수준별 체크 항목을 반환한다."""
    return _VALIDATION_CRITERIA.get(level, _VALIDATION_CRITERIA["학사"])


def list_levels() -> list[str]:
    """사용 가능한 지식수준 목록을 반환한다."""
    return [lvl.value for lvl in KnowledgeLevel]
