"""
학습메이트 정책 레지스트리 (단일 출처).

mode / tone / learnerLevel / quickAction 정책을 여기 한 곳에서만 관리한다.
endpoint·prompt_builder는 이 레지스트리를 lookup만 한다 → mode 추가/수정 시 이 파일만 바꾸면 된다.

검증 방식: 방식 B(알 수 없는 값은 기본값으로 보정하고 로그 기록).
Spring이 다른 라벨/필드명(knowledgeLevel, 한글 라벨 등)을 보내도 alias로 흡수한다.
"""
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("studybridge.learning_mate")

# ── Mode ──────────────────────────────────────────────────────────────────────
MODE_POLICIES: Dict[str, dict] = {
    "explain": {
        "label": "기본 설명",
        "purpose": "빠른 개념 이해",
        "structure": ["정의", "핵심 원리", "쉬운 예시", "핵심 요약", "다음 질문 제안"],
        "instruction": ("사용자의 질문에 대해 개념을 구조적으로 설명하라. "
                        "정의, 핵심 원리, 쉬운 예시, 짧은 요약 순서로 답하라."),
        "resultTags": ["개념 정리", "예시", "핵심 요약"],
        "maxTokens": 1000,
    },
    "socratic": {
        "label": "소크라테스",
        "purpose": "스스로 이해하도록 유도",
        "structure": ["질문", "힌트", "사고 유도", "오개념 확인", "부분 설명"],
        "instruction": ("정답을 처음부터 길게 다 말하지 마라. 먼저 사용자가 생각할 수 있는 질문을 던지고, "
                        "필요한 힌트를 제공하라. 단, 사용자가 완전히 막히지 않도록 최소한의 단서는 제공하라."),
        "resultTags": ["단계별 질문", "힌트", "오개념 확인"],
        "maxTokens": 800,
    },
    "debate": {
        "label": "토론",
        "purpose": "비판적 사고와 개념 확장",
        "structure": ["핵심 주장", "근거", "장점", "한계", "반론", "조건부 결론"],
        "instruction": ("개념의 장점, 단점, 한계, 반론, 조건부 결론을 제시하라. "
                        "근거 없이 단정하지 말고, 어떤 상황에서 유리하고 불리한지 비교하라."),
        "resultTags": ["주장", "근거", "반박", "결론"],
        "maxTokens": 1300,
    },
    "roleplay": {
        "label": "상황극",
        "purpose": "개념을 실제 상황에서 체험",
        "structure": ["상황 제시", "사용자 역할", "선택지 또는 판단 요청", "피드백", "개념 연결"],
        "instruction": ("사용자에게 현실적인 역할과 상황을 부여하라. 선택지 또는 판단 요청을 포함하라. "
                        "마지막에는 상황과 개념을 연결해 피드백하라."),
        "resultTags": ["시나리오", "선택지", "피드백"],
        "maxTokens": 1100,
    },
}

# ── Tone ──────────────────────────────────────────────────────────────────────
TONE_POLICIES: Dict[str, dict] = {
    "friendly": {"label": "친근한 말투", "instruction": "친근하고 부담 없는 말투를 사용한다."},
    "calm": {"label": "차분한 말투", "instruction": "차분하고 정돈된 말투를 사용한다."},
    "strict": {"label": "엄격한 말투",
               "instruction": "엄격하지만 무례하지 않게 부족한 부분을 분명히 짚는다. 모욕적이거나 공격적으로 말하지 않는다."},
    "cold": {"label": "냉철한 말투",
             "instruction": "감정 표현을 줄이고 분석적이고 냉철하게 말한다. 공격적이지 않게 한다."},
    "humorous": {"label": "유머러스한 말투",
                 "instruction": "가벼운 유머를 섞되 설명의 정확성을 해치지 않는다."},
}

# ── Learner Level (설명 난이도/깊이 — AI 전문성과 무관) ───────────────────────
LEARNER_LEVEL_POLICIES: Dict[str, dict] = {
    "beginner": {"label": "입문자 맞춤",
                 "instruction": "전문 용어를 최소화하고 쉬운 예시를 사용한다. 필요한 용어는 반드시 풀어서 설명한다."},
    "undergraduate": {"label": "학부 수준",
                      "instruction": "전공 학부 수준의 용어와 기본 개념을 사용한다. 개념 간 관계를 설명한다."},
    "advanced": {"label": "심화 수준",
                 "instruction": "심화 개념, 예외, 한계, 설계 판단 기준까지 포함한다."},
    "expert": {"label": "전문가 수준",
               "instruction": ("전문가 수준의 용어와 구조적 분석을 사용한다. "
                               "단순 설명보다 논점, 트레이드오프, 설계 판단을 중심으로 답한다.")},
}

# ── Quick Action ──────────────────────────────────────────────────────────────
QUICK_ACTION_POLICIES: Dict[str, dict] = {
    "easier": {"label": "더 쉽게",
               "instruction": "기존 질문과 현재 모드를 유지하되 더 쉬운 표현과 쉬운 예시로 다시 설명한다."},
    "deeper": {"label": "더 깊게",
               "instruction": "기존 질문과 현재 모드를 유지하되 더 깊고 심화된 내용까지 포함한다."},
    "add_example": {"label": "예시 추가",
                    "instruction": "기존 질문과 현재 모드를 유지하되 예시를 더 많이 포함한다."},
    "code_example": {"label": "코드 예시",
                     "instruction": ("프로그래밍 질문이면 코드 예시를 포함한다. "
                                     "프로그래밍 질문이 아니면 적절한 예시 중심으로 설명한다.")},
    "short_summary": {"label": "짧게 요약",
                      "instruction": "기존 질문과 현재 모드를 유지하되 핵심만 짧게 요약한다."},
}

# ── 기본값 ────────────────────────────────────────────────────────────────────
DEFAULT_MODE = "explain"
DEFAULT_TONE = "friendly"
DEFAULT_LEVEL = "beginner"

# ── alias (Spring 호환: 다른 필드명/라벨을 표준 key로 흡수) ───────────────────
_LEVEL_ALIASES = {
    # 영문 변형
    "intro": "beginner", "novice": "beginner", "basic": "beginner",
    "undergrad": "undergraduate", "bachelor": "undergraduate", "intermediate": "undergraduate",
    "advance": "advanced", "deep": "advanced",
    "pro": "expert", "professional": "expert",
    # 한글 라벨/지식수준 표현
    "입문": "beginner", "입문자": "beginner", "초급": "beginner",
    "학부": "undergraduate", "학사": "undergraduate", "학부생": "undergraduate",
    "심화": "advanced", "고급": "advanced", "석사": "advanced",
    "전문가": "expert", "박사": "expert",
}
_TONE_ALIASES = {
    "친근": "friendly", "친근한": "friendly", "친절": "friendly",
    "차분": "calm", "차분한": "calm",
    "엄격": "strict", "엄격한": "strict",
    "냉철": "cold", "냉철한": "cold", "냉정": "cold",
    "유머": "humorous", "유머러스": "humorous",
}
_MODE_ALIASES = {
    "설명": "explain", "기본설명": "explain", "default": "explain",
    "소크라테스": "socratic", "socratic_method": "socratic",
    "토론": "debate",
    "상황극": "roleplay", "role_play": "roleplay", "role-play": "roleplay",
}


def _norm_key(value: Optional[str]) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _resolve(value: Optional[str], registry: Dict[str, dict], aliases: Dict[str, str],
             default: str, kind: str) -> str:
    """알 수 없는 값은 기본값으로 보정하고 로그를 남긴다(검증 방식 B)."""
    raw = str(value or "").strip()
    key = _norm_key(raw)
    if key in registry:
        return key
    # alias: 정규화 키 또는 원문(한글 라벨) 둘 다 시도
    if key in aliases:
        return aliases[key]
    if raw in aliases:
        return aliases[raw]
    if not raw:
        return default
    logger.info("learning_mate: 알 수 없는 %s=%r → 기본값 %r 보정", kind, raw, default)
    return default


# ── 외부 공개 lookup ──────────────────────────────────────────────────────────
def resolve_mode(value: Optional[str]) -> str:
    return _resolve(value, MODE_POLICIES, _MODE_ALIASES, DEFAULT_MODE, "mode")


def resolve_tone(value: Optional[str]) -> str:
    return _resolve(value, TONE_POLICIES, _TONE_ALIASES, DEFAULT_TONE, "tone")


def resolve_level(value: Optional[str]) -> str:
    return _resolve(value, LEARNER_LEVEL_POLICIES, _LEVEL_ALIASES, DEFAULT_LEVEL, "learnerLevel")


def resolve_quick_action(value: Optional[str]) -> Optional[str]:
    """quickAction은 None 허용. 알 수 없으면 None 보정 + 로그."""
    if value is None or str(value).strip() == "":
        return None
    key = _norm_key(value)
    if key in QUICK_ACTION_POLICIES:
        return key
    logger.info("learning_mate: 알 수 없는 quickAction=%r → None 보정", value)
    return None


def mode_policy(key: str) -> dict:
    return MODE_POLICIES.get(key, MODE_POLICIES[DEFAULT_MODE])


def tone_policy(key: str) -> dict:
    return TONE_POLICIES.get(key, TONE_POLICIES[DEFAULT_TONE])


def level_policy(key: str) -> dict:
    return LEARNER_LEVEL_POLICIES.get(key, LEARNER_LEVEL_POLICIES[DEFAULT_LEVEL])


def quick_action_policy(key: Optional[str]) -> Optional[dict]:
    return QUICK_ACTION_POLICIES.get(key) if key else None


def available_modes() -> List[str]:
    return list(MODE_POLICIES.keys())


def available_quick_actions() -> List[str]:
    return list(QUICK_ACTION_POLICIES.keys())


def labels(mode: str, tone: str, level: str) -> Tuple[str, str, str, str]:
    """(modeLabel, toneLabel, learnerLevelLabel, summaryLabel)"""
    ml = mode_policy(mode)["label"]
    tl = tone_policy(tone)["label"]
    ll = level_policy(level)["label"]
    return ml, tl, ll, f"{ml} · {tl} · {ll}"
