"""
에이전트 간 피드백 독성 검증기.
규칙 기반으로 독성/조롱/인신공격을 감지한다.
키워드·임계값은 feedback_policy.yaml에서 로드한다.
"""
import re
import logging
from typing import List

from app.schemas.feedback_validation_schema import FeedbackValidationResult

logger = logging.getLogger(__name__)

# ── 정책 캐시 (첫 호출 시 로드) ───────────────────────────────────────────────
_toxic_re: List[re.Pattern] = []
_personal_re: List[re.Pattern] = []
_policy_loaded = False


def _ensure_policy() -> None:
    global _toxic_re, _personal_re, _policy_loaded
    if _policy_loaded:
        return
    try:
        from app.core.policy_loader import get_feedback_policy
        policy = get_feedback_policy()
        blocked = policy.get("blocked_patterns", [])
        attacks = policy.get("personal_attack_patterns", [])
    except Exception:
        blocked = ["멍청", "쓰레기", "말도 안", "한심", "바보", "형편없", "최악", "개소리"]
        attacks = [r"\d+번\s*(에이전트|답변).*?(이상|못|안)"]

    _toxic_re = [re.compile(re.escape(p) if not any(c in p for c in r"\.+*?[](){}^$|") else p, re.IGNORECASE)
                 for p in blocked]
    _personal_re = [re.compile(p, re.IGNORECASE) for p in attacks]
    _policy_loaded = True


def _score_toxicity(text: str) -> float:
    _ensure_policy()
    try:
        from app.core.policy_loader import get_feedback_thresholds
        w = get_feedback_thresholds().get("toxicity_weight_per_match", 0.35)
    except Exception:
        w = 0.35
    matches = sum(1 for p in _toxic_re if p.search(text))
    return min(1.0, matches * w)


def _score_personal_attack(text: str) -> float:
    _ensure_policy()
    try:
        from app.core.policy_loader import get_feedback_thresholds
        w = get_feedback_thresholds().get("attack_weight_per_match", 0.5)
    except Exception:
        w = 0.5
    matches = sum(1 for p in _personal_re if p.search(text))
    return min(1.0, matches * w)


def _score_mockery(text: str) -> float:
    try:
        from app.core.policy_loader import get_mockery_terms, get_feedback_thresholds
        terms = get_mockery_terms()
        w = get_feedback_thresholds().get("mockery_weight_per_match", 0.4)
    except Exception:
        terms = ["ㅋㅋ", "ㅎㅎ", "웃기", "말도 안 되는", "진짜로?", "그게 전부?"]
        w = 0.4
    matches = sum(1 for t in terms if t in text)
    return min(1.0, matches * w)


def _score_constructiveness(text: str) -> float:
    try:
        from app.core.policy_loader import get_improvement_keywords, get_feedback_thresholds
        keywords = get_improvement_keywords()
        thresholds = get_feedback_thresholds()
        base = thresholds.get("constructiveness_base", 0.3) if len(text) > 30 else 0.1
        w = thresholds.get("constructiveness_weight_per_match", 0.15)
    except Exception:
        keywords = ["보완", "개선", "추가", "대신", "더 나은", "필요", "제안", "방향"]
        base = 0.3 if len(text) > 30 else 0.1
        w = 0.15
    matches = sum(1 for kw in keywords if kw in text)
    return min(1.0, base + matches * w)


def _has_improvement_suggestion(text: str) -> bool:
    try:
        from app.core.policy_loader import get_improvement_keywords
        keywords = get_improvement_keywords()
    except Exception:
        keywords = ["보완", "개선", "추가", "대신", "더 나은", "필요", "제안", "방향"]
    return any(kw in text for kw in keywords)


def validate_inter_agent_feedback(feedback: str) -> FeedbackValidationResult:
    """
    피드백 텍스트의 독성/인신공격/건설성을 점수화하고 허용 여부를 결정한다.
    임계값은 feedback_policy.yaml에서 읽는다.
    """
    try:
        from app.core.policy_loader import get_feedback_thresholds
        thresholds = get_feedback_thresholds()
        max_tox = thresholds.get("max_toxicity_score", 0.35)
        max_att = thresholds.get("max_personal_attack_score", 0.5)
        max_mock = thresholds.get("max_mockery_score", 0.4)
    except Exception:
        max_tox, max_att, max_mock = 0.35, 0.5, 0.4

    tox = _score_toxicity(feedback)
    attack = _score_personal_attack(feedback)
    mockery = _score_mockery(feedback)
    construct = _score_constructiveness(feedback)
    has_suggestion = _has_improvement_suggestion(feedback)

    rewrite_required = tox >= max_tox or attack >= max_att or mockery >= max_mock
    allowed = not rewrite_required

    return FeedbackValidationResult(
        originalFeedback=feedback,
        toxicityScore=round(tox, 2),
        personalAttackScore=round(attack, 2),
        mockeryScore=round(mockery, 2),
        constructivenessScore=round(construct, 2),
        hasImprovementSuggestion=has_suggestion,
        allowed=allowed,
        rewriteRequired=rewrite_required,
        finalFeedback=feedback if allowed else "",
        wasRewritten=False,
        wasBlocked=False,
    )
