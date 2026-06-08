"""
멀티 에이전트 토론용 프롬프트 빌더.
에이전트 성격, 지식수준, 말투, 커스텀 지시사항을 반영한 시스템 프롬프트를 생성한다.
"""
from typing import Optional

from app.schemas.multi_chat_schema import AgentProfile

_KNOWLEDGE_INSTRUCTIONS = {
    "입문": "상대는 해당 분야를 처음 접한 입문자다. 어려운 용어를 최소화하고 쉬운 비유를 사용하라.",
    "학사": "상대는 학부생 수준이다. 개념 정의와 작동 원리, 기본 예시를 포함하라.",
    "석사": "상대는 대학원생 수준이다. 구조, 한계, 적용 조건을 포함하라.",
    "박사": "상대는 박사급 연구자다. 이론적 배경, 예외, 구조적 분석을 포함하라.",
    "전문가": "상대는 현업 전문가다. 실서비스 기준, 병목, 장애 대응, 운영 리스크 관점으로 설명하라.",
}

_PERSONALITY_INSTRUCTIONS = {
    "친절_설명형": "따뜻하고 친근한 말투로, 예시와 비유를 풍부하게 사용하며 설명하라.",
    "비판적_분析형": "상대의 질문에서 빠진 부분이나 오해를 살짝 지적하되, 바로 개선 방향을 제시하는 코치형으로 답하라. 무례하지 않게.",
    "논리적_탐구형": "원인 → 구조 → 결과 순서로 단계적으로 추론하라. 논리 접속사를 적절히 사용하라.",
    "창의적_확장형": "예상치 못한 비유나 다른 분야와의 연결을 시도하라. 확장적 사고를 유도하라.",
    "간결_요약형": "핵심만 압축해서 전달하라. 글머리 기호로 정리하고 마지막에 한 줄 결론을 넣어라.",
    "전문적": "전문적이고 학술적인 어조로, 정확한 용어와 논거를 사용하여 설명하라.",
}


def _get_knowledge_instruction(level: Optional[str]) -> str:
    if not level:
        return _KNOWLEDGE_INSTRUCTIONS["학사"]
    return _KNOWLEDGE_INSTRUCTIONS.get(level, _KNOWLEDGE_INSTRUCTIONS["학사"])


def _get_personality_instruction(
    personality: Optional[str],
    tone: Optional[str],
    style: Optional[str],
    custom_instruction: Optional[str],
) -> str:
    if custom_instruction and custom_instruction.strip():
        return f"[사용자 지정 지시사항] {custom_instruction.strip()}"
    base = ""
    if personality:
        base = _PERSONALITY_INSTRUCTIONS.get(personality, "")
    if not base and tone:
        base = _PERSONALITY_INSTRUCTIONS.get(tone, f"어조: {tone}")
    if not base and style:
        base = f"스타일: {style}"
    return base or "명확하고 친절하게 설명하라."


def build_agent_system_prompt(agent: AgentProfile, context: str = "") -> str:
    """
    에이전트 프로필에서 시스템 프롬프트를 생성한다.

    Args:
        agent: AgentProfile 객체
        context: 이전 대화 맥락 (선택)

    Returns:
        시스템 프롬프트 문자열
    """
    knowledge_instr = _get_knowledge_instruction(agent.knowledgeLevel)
    personality_instr = _get_personality_instruction(
        agent.personality, agent.tone, agent.style, agent.customInstruction
    )

    role_desc = agent.role or agent.name

    prompt_parts = [
        f"너는 StudyBridge AI 에이전트 '{agent.name}'이다.",
        f"역할: {role_desc}",
        "",
        f"[지식 수준 지시사항]\n{knowledge_instr}",
        "",
        f"[말투/성격 지시사항]\n{personality_instr}",
        "",
        "공통 규칙:",
        "- 반드시 한국어로 답변한다.",
        "- 다른 에이전트와 완전히 같은 말투나 내용을 반복하지 않는다.",
        "- 학습에 도움이 되는 실질적인 내용을 제공한다.",
    ]

    if context:
        prompt_parts.extend(["", context])

    return "\n".join(prompt_parts)


def build_tikitaka_role_prompt(agent_index: int, total_agents: int, agent: AgentProfile) -> str:
    """
    티키타카 스타일로 각 에이전트에 역할을 부여한다.
    첫 번째는 핵심 설명, 두 번째는 보완/비판, 세 번째는 쉬운 정리.
    """
    if total_agents == 1:
        return ""

    if agent_index == 0:
        return "이 질문의 핵심 개념과 원리를 설명하라."
    elif agent_index == 1:
        return "앞서 설명된 내용을 보완하거나, 놓친 부분이나 주의할 점을 지적하라."
    elif agent_index == 2:
        return "앞의 설명을 쉽게 요약하여 초보자도 이해할 수 있게 정리하라."
    else:
        return "추가적인 관점이나 실용적인 응용 사례를 제시하라."
