"""
박사/전문가 답변이 깊이 기준 미달일 때 최대 1회 재작성한다.
재작성 후에도 기준 미달이면 metadata에 warning을 남긴다.
사용자는 자연스러운 최종 답변만 본다.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def rewrite(
    original_answer: str,
    domain: str,
    knowledge_level: str,
    missing_requirements: list,
    question: str,
    additional_context: str = "",
) -> "DepthRewriteResult":  # noqa: F821
    """
    깊이 부족 답변을 재작성한다. 최대 1회.
    반환: DepthRewriteResult
    """
    from app.schemas.academic_depth_schema import DepthRewriteResult
    from app.services.academic_depth_verifier import verify

    missing_str = "、".join(missing_requirements[:5]) if missing_requirements else ""

    rewrite_instruction = (
        f"아래 답변은 '{knowledge_level}' 수준의 학문적 깊이가 부족하다.\n"
        f"도메인: {domain}\n"
        f"보완 필요 항목: {missing_str if missing_str else '이론적 배경, 한계, 반례'}\n\n"
        "다음 원칙에 따라 답변을 보완하라:\n"
        "1. 이론적 배경과 핵심 개념을 엄밀하게 제시한다.\n"
        "2. 방법론적 한계나 예외 사례를 포함한다.\n"
        "3. 대안 관점이나 논쟁점을 언급한다.\n"
        "4. 출처명(논문명, DOI, 인용 수 등)을 직접 노출하지 않는다.\n"
        "5. 원래 답변의 핵심을 유지하면서 깊이를 추가한다.\n\n"
    )

    if additional_context:
        rewrite_instruction += f"[참고 컨텍스트]\n{additional_context[:500]}\n\n"

    rewrite_instruction += f"[원래 답변]\n{original_answer}\n\n[보완된 답변]"

    try:
        from app.services.llm_engine_router import call_primary_llm
        from app.services.generation_config_resolver import resolve as resolve_config
        gen_cfg = resolve_config(knowledge_level=knowledge_level, domain=domain)

        rewritten = call_primary_llm(
            system_prompt=(
                f"너는 {domain} 분야 {knowledge_level} 수준의 학문적 답변 전문가다. "
                "주어진 지시에 따라 답변의 깊이를 보완하라."
            ),
            user_prompt=rewrite_instruction,
            max_tokens=gen_cfg.get("max_tokens", 1900),
            temperature=gen_cfg.get("temperature", 0.5),
        )
    except Exception as e:
        logger.warning("depth rewrite LLM 호출 실패: %s", e)
        return DepthRewriteResult(
            original_answer=original_answer,
            rewritten_answer=original_answer,
            rewrite_applied=False,
            rewrite_reason=f"LLM 호출 실패: {e}",
        )

    if not rewritten or rewritten.startswith("["):
        return DepthRewriteResult(
            original_answer=original_answer,
            rewritten_answer=original_answer,
            rewrite_applied=False,
            rewrite_reason="LLM fallback 응답",
        )

    # 재작성 후 검증
    post_verify = verify(rewritten, domain, knowledge_level)
    warning = None
    if post_verify.rewrite_required:
        warning = f"재작성 후에도 깊이 기준 미달 (coverage={post_verify.domain_depth_coverage:.2f})"
        logger.warning("depth rewrite 후에도 기준 미달: %s", warning)

    post_verify.warning_message = warning
    return DepthRewriteResult(
        original_answer=original_answer,
        rewritten_answer=rewritten,
        rewrite_applied=True,
        rewrite_reason=f"domain_depth_coverage 미달 ({missing_str})",
        verification_after_rewrite=post_verify,
    )
