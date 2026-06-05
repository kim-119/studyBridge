"""
에이전트 간 피드백 독성 검증기.
규칙 기반 + 프롬프트 기반으로 독성/조롱/인신공격을 감지한다.
"""
import re
import logging

from app.schemas.feedback_validation_schema import FeedbackValidationResult

logger = logging.getLogger(__name__)

# 독성 키워드 패턴 (욕설/조롱/비하)
_TOXIC_PATTERNS = [
    r"멍청",
    r"쓰레기",
    r"바보",
    r"뇌가\s*없",
    r"형편없",
    r"최악",
    r"말도\s*안\s*됨",
    r"말도\s*안\s*돼",
    r"개소리",
    r"헛소리",
    r"수준\s*이하",
    r"그게\s*무슨\s*답",
    r"이게\s*무슨\s*답",
    r"답\s*이\s*아니",
    r"완전히?\s*틀렸",
    r"아무\s*것도\s*모르",
    r"글렀",
    r"조잡",
    r"엉망",
]

# 인신공격 패턴 (에이전트 자체를 공격)
_PERSONAL_ATTACK_PATTERNS = [
    r"\d+번\s*(에이전트|답변).*?(이상|못|안)",
    r"이\s*(에이전트|답).*?(가치\s*없|무능)",
    r"저\s*(에이전트|답).*?(가치\s*없|무능)",
]

# 개선 방향 포함 여부 키워드
_IMPROVEMENT_KEYWORDS = [
    "보완",
    "개선",
    "추가",
    "대신",
    "더 나은",
    "더욱",
    "이렇게",
    "하면 좋",
    "하면 더",
    "해야",
    "필요",
    "제안",
    "방향",
]

_TOXIC_RE = [re.compile(p, re.IGNORECASE) for p in _TOXIC_PATTERNS]
_PERSONAL_RE = [re.compile(p, re.IGNORECASE) for p in _PERSONAL_ATTACK_PATTERNS]


def _score_toxicity(text: str) -> float:
    matches = sum(1 for p in _TOXIC_RE if p.search(text))
    return min(1.0, matches * 0.35)


def _score_personal_attack(text: str) -> float:
    matches = sum(1 for p in _PERSONAL_RE if p.search(text))
    return min(1.0, matches * 0.5)


def _score_mockery(text: str) -> float:
    mockery_terms = ["ㅋㅋ", "ㅎㅎ", "웃기", "말도 안 되는", "진짜로?", "그게 전부?"]
    matches = sum(1 for t in mockery_terms if t in text)
    return min(1.0, matches * 0.4)


def _score_constructiveness(text: str) -> float:
    matches = sum(1 for kw in _IMPROVEMENT_KEYWORDS if kw in text)
    base = 0.3 if len(text) > 30 else 0.1
    return min(1.0, base + matches * 0.15)


def _has_improvement_suggestion(text: str) -> bool:
    return any(kw in text for kw in _IMPROVEMENT_KEYWORDS)


def validate_inter_agent_feedback(feedback: str) -> FeedbackValidationResult:
    """
    피드백 텍스트의 독성/인신공격/건설성을 점수화하고 허용 여부를 결정한다.
    독성 점수 >= 0.35 또는 인신공격 >= 0.5이면 재작성 필요로 판정한다.
    """
    tox = _score_toxicity(feedback)
    attack = _score_personal_attack(feedback)
    mockery = _score_mockery(feedback)
    construct = _score_constructiveness(feedback)
    has_suggestion = _has_improvement_suggestion(feedback)

    rewrite_required = tox >= 0.35 or attack >= 0.5 or mockery >= 0.4
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
