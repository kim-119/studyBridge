"""
텍스트 처리 유틸리티.
"""
from app.core.config import (
    PREVIOUS_ANSWERS_LIMIT,
    PREVIOUS_ANSWERS_HARD_LIMIT,
    PREVIOUS_ANSWER_MAX_CHARS,
)


def build_context_from_previous_answers(previous_answers: list, max_items: int = PREVIOUS_ANSWERS_LIMIT) -> str:
    """
    이전 답변 목록에서 최근 N개를 선택하여 프롬프트 컨텍스트 문자열로 변환한다.

    - 최대 PREVIOUS_ANSWERS_HARD_LIMIT(100)개 허용, 실제 사용은 max_items개
    - 각 answer는 PREVIOUS_ANSWER_MAX_CHARS(300)자로 자름 (토큰 폭발 방지)
    """
    if not previous_answers:
        return ""

    # hard limit 초과 입력 방어
    capped = previous_answers[-PREVIOUS_ANSWERS_HARD_LIMIT:]
    recent = capped[-max_items:]
    lines = ["[이전 대화 맥락]"]
    for item in recent:
        agent_name = getattr(item, "agentName", "")
        answer = getattr(item, "answer", "")
        role = getattr(item, "role", "ASSISTANT")
        if answer.strip():
            lines.append(f"[{role}] {agent_name}: {answer.strip()[:PREVIOUS_ANSWER_MAX_CHARS]}")
    return "\n".join(lines)


def build_conversation_context(previous_answers: list, max_items: int = PREVIOUS_ANSWERS_LIMIT) -> str:
    """build_context_from_previous_answers의 alias. Spring 계약 명칭 준수."""
    return build_context_from_previous_answers(previous_answers, max_items)


def safe_str(value, default: str = "") -> str:
    """None-safe 문자열 변환."""
    if value is None:
        return default
    return str(value).strip() or default
