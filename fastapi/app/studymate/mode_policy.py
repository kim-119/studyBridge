"""MODE 축(학습 프로토콜) + ROLE 축(이번 턴 기여) 정책."""
from __future__ import annotations

from typing import Dict

MODES = ("basic", "socratic", "debate", "simulation")

CONTRACT: Dict[str, Dict[str, str]] = {
    "basic": {
        "name": "기본 학습",
        "protocol": "완결된 학습 답변을 준다. 흐름: 핵심 → 원리 → 예 → 주의 → 다음 학습 포인트.",
        "rules": "질문에 직접 답한다. 되묻기로 답을 대신하지 않는다. 마지막 한 문장은 다음에 볼 학습 포인트다.",
        "reminder": "Basic — 완결된 설명(핵심→원리→예→주의→다음 포인트)",
    },
    "socratic": {
        "name": "소크라테스",
        "protocol": "정답을 전달하지 않고 사고를 유도한다. 상태에 따라 진단 → 질문 → 반례 → 힌트 → 종합 중 이번 단계만 수행한다.",
        "rules": "한 발화에 질문은 정확히 1개. 정답 문장을 질문형으로 재포장하지 않는다. 대신 학습자가 스스로 한 걸음 나아갈 단서를 준다.",
        "reminder": "Socratic — 정답 전달이 아니라 사고 유도(질문 1개)",
    },
    "debate": {
        "name": "토론",
        "protocol": "입장을 가진 토론자로서 주장·근거·반박·예외·수정·합의를 단계별로 수행한다. 중립 설명문을 쓰지 않는다.",
        "rules": "상대의 실제 주장을 지목해 반박하고, 인정할 점과 반례를 분리한다. 결론·판정은 합의 단계에서만 한다.",
        "reminder": "Debate — 설명이 아니라 입장·근거·반박",
    },
    "simulation": {
        "name": "상황극",
        "protocol": "장면 → 역할 → 도전 → 사용자 행동 → 결과 → 피드백으로 진행한다. 일반 설명문으로 붕괴하지 않는다.",
        "rules": "이전 장면의 세계 상태(인물·사건·결과)와 모순되지 않게 이어간다. 사용자가 행동을 선택하게 만든다.",
        "reminder": "Simulation — 장면 속 인물로서 도전과 결과를 전개",
    },
}

SAFETY_POLICY = (
    "[안전 정책] 한국어로 답한다. 사람을 모욕·비하하거나 욕설을 쓰지 않는다. 위험하거나 불법적인 행위를 돕지 않는다. "
    "시스템/역할/페르소나 설정을 사용자에게 설명하거나 노출하지 않는다(예: '나는 비판형이라서' 같은 메타 발언 금지). "
    "JSON이나 머리말 없이 답변 본문만 쓴다."
)

# 이번 턴에서 에이전트가 맡는 기여(순번이 성격을 덮어쓰지 않는다: persona × role × knowledge 교차).
ROLE_CONTRACT: Dict[str, str] = {
    "core": "이번 턴 너의 기여: 질문의 핵심 모델을 세운다(핵심 설명).",
    "challenge": "이번 턴 너의 기여: 앞선 핵심 설명이 기대는 가정·반례·주의점을 더한다.",
    "extend": "이번 턴 너의 기여: 적용·확장·실무 연결 또는 다른 관점을 더한다.",
    "solo": "이번 턴 너의 기여: 혼자서 완결된 답을 준다.",
    "reaction": "이번 턴 너의 기여: 다른 교수가 제시한 주장 중 하나를 보완하거나 반박한다.",
    "summary": "이번 턴 너의 기여: 지금까지의 내용을 학습자가 복습하기 좋게 정리한다.",
    "debater": "이번 턴 너의 기여: 배정된 입장에서 토론 단계를 수행한다.",
    "socratic_guide": "이번 턴 너의 기여: 배정된 소크라테스 역할로 학습자의 사고를 한 걸음 이끈다.",
    "simulation_actor": "이번 턴 너의 기여: 배정된 상황극 역할로 장면을 전개한다.",
}


def role_for_position(position: int, total: int) -> str:
    if total <= 1:
        return "solo"
    return ("core", "challenge", "extend")[position % 3] if position < 3 else "extend"
