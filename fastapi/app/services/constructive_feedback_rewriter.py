"""
에이전트 간 피드백을 건설적 표현으로 재작성하는 서비스.
Qwen을 사용해 독성 피드백을 논리 비판 + 개선 제안 형식으로 변환한다.
fallback 문구와 재작성 정책은 feedback_policy.yaml에서 읽는다.
"""
import logging

from app.schemas.feedback_validation_schema import FeedbackValidationResult
from app.services.inter_agent_feedback_validator import validate_inter_agent_feedback

logger = logging.getLogger(__name__)


def _get_safe_fallback() -> str:
    try:
        from app.core.policy_loader import get_safe_fallback
        return get_safe_fallback()
    except Exception:
        return "해당 피드백은 표현이 부적절하여 건설적인 개선 의견으로 대체되었습니다."


_REWRITE_SYSTEM = """\
너는 학습 피드백 품질 관리 에이전트다.
주어진 피드백이 비방·조롱·인신공격 표현을 포함하고 있을 때,
이를 아래 기준으로 건설적인 표현으로 재작성한다.

규칙:
1. 에이전트 자체(인격·능력)가 아니라 답변의 논리·근거·누락점만 비판한다.
2. 비판 후 반드시 개선 방향을 제시한다.
3. "틀렸다"고만 하지 말고 왜 부족한지 설명한다.
4. 조롱·욕설·모욕적 표현은 모두 제거한다.
5. 비판적 분석형은 허용하되, 인신공격형은 금지한다.
6. 반드시 한국어로 답변하라.
7. 재작성된 피드백만 출력하라. 추가 설명 없이.
"""


def rewrite_feedback_to_constructive(feedback: str) -> str:
    """
    Qwen으로 피드백을 건설적 표현으로 재작성한다.
    Qwen 실패 시 safe fallback 문구를 반환한다.
    """
    safe_fallback = _get_safe_fallback()
    try:
        from app.services.qwen_service import ask_qwen
        rewritten = ask_qwen(
            system_prompt=_REWRITE_SYSTEM,
            user_prompt=f"원본 피드백:\n{feedback}\n\n건설적 표현으로 재작성:",
            temperature=0.2,
            max_tokens=300,
        )
        if rewritten and len(rewritten.strip()) > 10:
            return rewritten.strip()
        return safe_fallback
    except Exception as e:
        logger.warning("피드백 재작성 실패: %s", e)
        return safe_fallback


def process_feedback(feedback: str) -> FeedbackValidationResult:
    """
    피드백 검증 → 필요 시 재작성 → FeedbackValidationResult 반환.
    재작성 후에도 독성이면 safe fallback으로 대체한다. 최대 1회 재작성.
    """
    safe_fallback = _get_safe_fallback()
    result = validate_inter_agent_feedback(feedback)

    if result.allowed:
        result.finalFeedback = feedback
        return result

    # 1차 재작성 (최대 1회 — validation_policy.yaml max_rewrite_attempts)
    rewritten = rewrite_feedback_to_constructive(feedback)

    if rewritten == safe_fallback:
        result.finalFeedback = safe_fallback
        result.wasRewritten = True
        result.wasBlocked = True
        return result

    # 재작성 후 재검증
    re_check = validate_inter_agent_feedback(rewritten)
    if re_check.allowed:
        result.finalFeedback = rewritten
        result.wasRewritten = True
        result.wasBlocked = False
    else:
        result.finalFeedback = safe_fallback
        result.wasRewritten = True
        result.wasBlocked = True

    return result
