"""
Tiki-Taka Turn Manager.
복수 에이전트가 순서대로 발화하는 멀티턴 대화를 관리한다.

구조:
  Round 1: Agent A(핵심 답변) → Agent B(보완/비판) → Agent C(쉬운 설명)
  Round 2: 필요 시 에이전트 1명 추가 반응
  Final:   Moderator가 3~5줄 정리

제한:
  max_round = 2
  max_agent_turns = 4 (A+B+C+optional)
  max_tokens_per_turn = 400
  무한 루프 없음: 라운드 종료 후 GPT 검증
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.services.qwen_service import ask_qwen

logger = logging.getLogger(__name__)

MAX_ROUND = 2
MAX_AGENT_TURNS = 4
MAX_TOKENS_PER_TURN = 400


@dataclass
class TikiTakaTurn:
    agent_name: str
    role_description: str
    content: str


def _build_agent_b_prompt(
    question: str,
    agent_a_answer: str,
    agent_a_name: str,
) -> tuple[str, str]:
    """Agent B (비판적 분석형): Agent A 답변에 보완/비판 반응 생성."""
    system = (
        "너는 학습 토론 보조 에이전트다. 다른 에이전트의 설명을 듣고 "
        "헷갈릴 수 있는 부분이나 보완할 점을 날카롭게 짚은 뒤, "
        "바로 올바른 방향을 제시한다. (츤데레 코치 스타일. 무례하지 않게.)"
        "\n반드시 한국어로 답변하라."
    )
    user = (
        f"원래 질문: {question}\n\n"
        f"[{agent_a_name}]의 설명:\n{agent_a_answer}\n\n"
        "위 설명에서 보완하거나 다르게 봐야 할 점을 지적하고 개선 방향을 제시하라. "
        "200자 내외로 간결하게."
    )
    return system, user


def _build_agent_c_prompt(
    question: str,
    agent_a_answer: str,
    agent_b_answer: str,
) -> tuple[str, str]:
    """Agent C (친절 요약형): 지금까지 대화를 쉽게 정리."""
    system = (
        "너는 학습자가 이해하기 쉽게 설명을 정리해 주는 에이전트다. "
        "앞 두 에이전트의 대화를 듣고 핵심만 쉬운 말로 정리한다. "
        "초보자도 이해할 수 있는 비유나 예시를 하나 포함한다."
        "\n반드시 한국어로 답변하라."
    )
    user = (
        f"질문: {question}\n\n"
        f"에이전트들의 대화 내용:\n{agent_a_answer}\n\n{agent_b_answer}\n\n"
        "위 내용을 입문자도 이해할 수 있게 100자 내외로 쉽게 정리하라."
    )
    return system, user


def _build_moderator_prompt(
    question: str,
    turns: list[TikiTakaTurn],
) -> tuple[str, str]:
    """Moderator: 전체 대화를 3~5줄로 최종 정리."""
    system = (
        "너는 토론 사회자다. 에이전트들의 대화를 듣고 "
        "핵심 결론을 3~5줄로 간결하게 정리한다. "
        "반드시 한국어로 답변하라."
    )
    dialogue_text = "\n\n".join(
        f"[{t.agent_name}]\n{t.content}" for t in turns
    )
    user = (
        f"원래 질문: {question}\n\n"
        f"에이전트 대화:\n{dialogue_text}\n\n"
        "핵심 결론을 3~5줄로 정리하라."
    )
    return system, user


def run_tiki_taka(
    question: str,
    agent_a_answer: str,
    agent_a_name: str = "에이전트A",
    agent_b_name: str = "에이전트B",
    agent_c_name: str = "에이전트C",
    moderator_name: str = "정리",
    enable_round2: bool = False,
) -> list[TikiTakaTurn]:
    """
    티키타카 대화를 생성하고 TikiTakaTurn 목록을 반환한다.

    Args:
        question:        원래 질문
        agent_a_answer:  Agent A가 이미 생성한 1차 답변
        agent_a_name:    Agent A 표시 이름
        agent_b_name:    Agent B 표시 이름
        agent_c_name:    Agent C 표시 이름
        moderator_name:  Moderator 표시 이름
        enable_round2:   True이면 Round 2 추가 발화 수행

    Returns:
        TikiTakaTurn 리스트 (Agent A 포함)
    """
    turns: list[TikiTakaTurn] = []

    # ── Agent A: 이미 생성된 1차 답변 ─────────────────────────────────
    turns.append(TikiTakaTurn(
        agent_name=agent_a_name,
        role_description="핵심 답변",
        content=agent_a_answer,
    ))

    # ── Agent B: 보완/비판 ────────────────────────────────────────────
    try:
        sys_b, usr_b = _build_agent_b_prompt(question, agent_a_answer, agent_a_name)
        b_answer = ask_qwen(sys_b, usr_b, max_tokens=MAX_TOKENS_PER_TURN)
        turns.append(TikiTakaTurn(
            agent_name=agent_b_name,
            role_description="보완 및 비판",
            content=b_answer,
        ))
    except Exception as e:
        logger.warning("Agent B 생성 실패: %s", e)
        turns.append(TikiTakaTurn(
            agent_name=agent_b_name,
            role_description="보완 및 비판",
            content="(Agent B 응답 생성 중 오류가 발생했습니다.)",
        ))

    # ── Agent C: 쉬운 요약 ────────────────────────────────────────────
    b_content = turns[-1].content
    try:
        sys_c, usr_c = _build_agent_c_prompt(question, agent_a_answer, b_content)
        c_answer = ask_qwen(sys_c, usr_c, max_tokens=MAX_TOKENS_PER_TURN)
        turns.append(TikiTakaTurn(
            agent_name=agent_c_name,
            role_description="쉬운 설명 및 요약",
            content=c_answer,
        ))
    except Exception as e:
        logger.warning("Agent C 생성 실패: %s", e)
        turns.append(TikiTakaTurn(
            agent_name=agent_c_name,
            role_description="쉬운 설명 및 요약",
            content="(Agent C 응답 생성 중 오류가 발생했습니다.)",
        ))

    # ── Round 2 (선택) ────────────────────────────────────────────────
    if enable_round2 and len(turns) < MAX_AGENT_TURNS:
        try:
            r2_sys = (
                "너는 보충 설명 에이전트다. 앞선 대화를 바탕으로 "
                "아직 설명이 부족한 한 가지 포인트만 골라 추가로 설명한다. "
                "반드시 한국어로 답변하라."
            )
            prev_summary = "\n".join(f"[{t.agent_name}] {t.content[:100]}..." for t in turns)
            r2_usr = (
                f"질문: {question}\n\n앞선 대화 요약:\n{prev_summary}\n\n"
                "가장 보충이 필요한 포인트 하나만 100자 이내로 추가 설명하라."
            )
            r2_answer = ask_qwen(r2_sys, r2_usr, max_tokens=MAX_TOKENS_PER_TURN)
            turns.append(TikiTakaTurn(
                agent_name="보충",
                role_description="Round 2 추가 설명",
                content=r2_answer,
            ))
        except Exception as e:
            logger.warning("Round 2 생성 실패: %s", e)

    # ── Moderator: 최종 정리 ──────────────────────────────────────────
    try:
        sys_m, usr_m = _build_moderator_prompt(question, turns)
        m_answer = ask_qwen(sys_m, usr_m, max_tokens=MAX_TOKENS_PER_TURN)
        turns.append(TikiTakaTurn(
            agent_name=moderator_name,
            role_description="최종 정리",
            content=m_answer,
        ))
    except Exception as e:
        logger.warning("Moderator 생성 실패: %s", e)
        turns.append(TikiTakaTurn(
            agent_name=moderator_name,
            role_description="최종 정리",
            content="(정리 에이전트 생성 중 오류가 발생했습니다.)",
        ))

    return turns
