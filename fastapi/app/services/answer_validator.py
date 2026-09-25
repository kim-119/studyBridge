"""
에이전트 답변 품질 검증 및 보정 wrapper.

agent_quality_policy.py의 validate_answer_quality / revise_answer_to_match_quality_policy를
래핑한다. import 실패 또는 GPT 미설정 시 원본 답변을 그대로 반환한다.
검증 metadata는 호출자 내부에서만 사용하고 사용자에게 노출하지 않는다.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def validate_and_revise_agent_answer(
    answer: str,
    agent_config: dict,
    user_message: str,
    openai_client=None,
) -> str:
    """
    답변 품질을 검증하고 기준 미달 시 GPT로 보정한다.

    Args:
        answer:        LLM이 생성한 원본 답변
        agent_config:  normalize_agent_config() 결과 (knowledge_depth_policy 등 포함)
        user_message:  사용자 질문 원문
        openai_client: OpenAI 클라이언트 (없으면 보정 스킵)

    Returns:
        검증/보정된 답변 (실패 시 원본 반환)
    """
    if not answer or not answer.strip():
        return answer

    try:
        from agent_quality_policy import (
            validate_answer_quality,
            revise_answer_to_match_quality_policy,
        )
    except ImportError:
        try:
            import sys
            import os
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
            from agent_quality_policy import (
                validate_answer_quality,
                revise_answer_to_match_quality_policy,
            )
        except ImportError:
            logger.debug("agent_quality_policy import 실패 — 검증 건너뜀")
            return answer

    try:
        result = validate_answer_quality(answer, agent_config, user_message)
        if result.get("passed", True):
            return answer
        logger.info(
            "답변 품질 검증 미달 (score=%.2f, issues=%s) — 보정 시도",
            result.get("score", 0),
            result.get("issues", []),
        )
        revised = revise_answer_to_match_quality_policy(
            answer, agent_config, result, user_message, openai_client
        )
        return revised
    except Exception as e:
        logger.warning("답변 품질 검증/보정 중 오류 — 원본 반환: %s", e)
        return answer
