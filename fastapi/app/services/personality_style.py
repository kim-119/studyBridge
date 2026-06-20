"""
성격/말투(personality style) 정규화 모듈 — 프론트(EC2/Spring) 전달값 → canonical 스타일.

목적:
- 화면마다 다르게 들어오는 성격/말투 라벨(한국어 라벨, 레거시 문구, 내부 프로필 키, 영어 키)을
  하나의 canonical key 로 정규화한다.
- 각 스타일의 기본 temperature 와 답변에 실제로 반영되는 prompt_instruction 을 한곳(SSOT)에서 제공한다.
- 사용자가 직접 보낸 temperature 가 있으면 우선하되 안전 범위로 clamp 한다.

설계 원칙(프로젝트 규약):
- 순수 함수 + 상수만. 네트워크/LLM/DB 호출·부작용 없음.
- 모델명/타임아웃 등 운영 파라미터는 다루지 않는다(temperature 만).
- 정규화 실패는 예외를 던지지 않고 default 로 폴백하며 warning 메타를 남긴다(오류를 답변 본문에 넣지 않는다).
- 신규 파일(autodeploy 의 git reset --hard 에도 생존). 호출부는 multi_agent_service 등 tracked 파일.

반환 구조(normalize_personality_style):
    {
      "key": "professional",
      "label": "전문적",
      "description": "정제되어 있고 정확함",
      "temperature": 0.35,
      "prompt_instruction": "...",
      "source": "personality|tone|style|label|default",
      "temperature_source": "request|style|config_default",
      "warning": None | "정규화 실패 — default 적용",
    }
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

# ── canonical 스타일 정의(프론트/Spring 계약) ──────────────────────────────────
# label/description/temperature 는 프론트가 보여주는 값과 동일하게 유지한다.
PERSONALITY_STYLE_OPTIONS: Dict[str, Dict[str, Any]] = {
    "default": {
        "label": "기본값",
        "description": "기본 스타일과 말투",
        "temperature": 0.5,
    },
    "professional": {
        "label": "전문적",
        "description": "정제되어 있고 정확함",
        "temperature": 0.35,
    },
    "friendly": {
        "label": "친근함",
        "description": "따뜻하고 수다스러움",
        "temperature": 0.65,
    },
    "honest": {
        "label": "솔직함",
        "description": "직설적이면서도 격려함",
        "temperature": 0.45,
    },
    "unique": {
        "label": "독특함",
        "description": "유쾌하고 상상력이 풍부함",
        "temperature": 0.8,
    },
    "efficient": {
        "label": "효율적",
        "description": "간결하고 꾸밈없음",
        "temperature": 0.25,
    },
    "cynical": {
        "label": "냉소적",
        "description": "비꼬면서 비판적임",
        "temperature": 0.55,
    },
}

# ── 스타일별 답변 지시(prompt_instruction) ─────────────────────────────────────
# 각 스타일이 실제 답변 톤/구조에 다르게 반영되도록 한 줄 지시로 못박는다.
# 주의: 냉소적=주장/근거/구조의 약점 비판(사람 조롱·비하 금지), 전문적=정확성·구조화(장황 금지),
#       친근함=설명 친화성(품질 저하 금지).
STYLE_PROMPT_INSTRUCTIONS: Dict[str, str] = {
    "default": "균형 잡힌 어조로 핵심을 명확히 설명하고, 필요한 곳에만 예시를 들어 깔끔하게 정리한다.",
    "professional": "정제된 전문 용어를 사용하되 근거 없는 단정은 피하고, 정의→핵심→근거 순으로 정확하고 구조화해 답한다(장황함이 아니라 정확성과 구조가 핵심).",
    "friendly": "따뜻하고 부드러운 말투로, 어려운 개념은 일상적 비유와 예시를 들어 친근하게 설명한다. 친근함을 이유로 정확성을 낮추지 않는다.",
    "honest": "에두르지 않고 핵심을 직설적으로 말하되, 부족한 점은 솔직히 짚고 개선 방향으로 격려하며 마무리한다.",
    "unique": "창의적인 비유와 신선한 관점으로 흥미롭게 설명하되, 비유가 사실을 왜곡하지 않도록 핵심 개념의 정확성은 반드시 지킨다.",
    "efficient": "불필요한 수식을 제거하고 핵심만 간결하게 전달한다. 군더더기 없이 결론과 근거를 바로 제시한다.",
    "cynical": "주장·근거·구조의 약점을 날카롭게 비판적으로 검토하고 허점을 지적한다. 단, 사람을 조롱·비하하지 않고 내용 자체만 분석적으로 비판한다.",
}

# ── 레거시/별칭 매핑(프론트 화면별 상이 라벨 흡수) ──────────────────────────────
# 요청서에 명시된 LEGACY_PERSONALITY_MAP.
LEGACY_PERSONALITY_MAP: Dict[str, str] = {
    "기본": "default",
    "기본값": "default",
    "전문적으로": "professional",
    "전문적": "professional",
    "친근하게": "friendly",
    "친근함": "friendly",
    "솔직하게": "honest",
    "솔직함": "honest",
    "정직하게": "honest",
    "유머러스하게": "unique",
    "독특함": "unique",
    "효율적": "efficient",
    "간결하게": "efficient",
    "냉철하게": "cynical",
    "냉소적": "cynical",
    "비판적으로": "cynical",
    "엄격하게": "cynical",
    "차분하게": "default",
}

# 내부 프로필 키(personality_prompt_builder/agent_settings)·영어 변형 → canonical.
# (멀티에이전트 라이브 경로는 raw payload 의 personality 값을 그대로 쓰므로 내부 키도 흡수한다.)
_INTERNAL_KEY_MAP: Dict[str, str] = {
    # 내부 YAML/프로필 키
    "logical": "professional",
    "professional_expert": "professional",
    "expert": "professional",
    "friendly": "friendly",
    "warm": "friendly",
    "critical": "cynical",
    "sardonic": "cynical",
    "coach": "cynical",
    "creative": "unique",
    "concise": "efficient",
    "honest": "honest",
    "default": "default",
    "balanced": "default",
    # 영어 변형
    "professional_tone": "professional",
    "efficient_tone": "efficient",
    "unique_tone": "unique",
    "cynical_tone": "cynical",
}


def _config_default_temperature() -> float:
    """config default temperature. env AI_DEFAULT_TEMPERATURE > 0.5."""
    raw = os.getenv("AI_DEFAULT_TEMPERATURE")
    if raw not in (None, ""):
        try:
            return clamp_temperature(float(raw))
        except (TypeError, ValueError):
            pass
    return 0.5


TEMPERATURE_MIN = 0.1  # 운영 안전 하한(0.0 의 완전 결정성/빈응답 회피)
TEMPERATURE_MAX = 1.0  # Qwen3-14B 로컬 환경에서 1.0 초과는 일관성 저하


def clamp_temperature(value: float) -> float:
    """temperature 를 안전 범위 [0.1, 1.0] 로 제한한다(요청서 권장 clamp)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return _config_default_temperature()
    if v < TEMPERATURE_MIN:
        return TEMPERATURE_MIN
    if v > TEMPERATURE_MAX:
        return TEMPERATURE_MAX
    return round(v, 3)


def _canonical_key(raw: Optional[str]) -> Optional[str]:
    """단일 라벨 문자열을 canonical key 로 해석한다. 해석 불가면 None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    low = s.lower()
    # 1) canonical key 직접 일치
    if low in PERSONALITY_STYLE_OPTIONS:
        return low
    # 2) 레거시 한국어/문구 라벨
    if s in LEGACY_PERSONALITY_MAP:
        return LEGACY_PERSONALITY_MAP[s]
    if low in LEGACY_PERSONALITY_MAP:
        return LEGACY_PERSONALITY_MAP[low]
    # 3) 내부 프로필 키/영어 변형
    if low in _INTERNAL_KEY_MAP:
        return _INTERNAL_KEY_MAP[low]
    # 4) 부분 포함(공백 제거 비교) — "전문적 말투" 같은 변형 흡수
    s_compact = s.replace(" ", "")
    for label, key in LEGACY_PERSONALITY_MAP.items():
        if label and label.replace(" ", "") in s_compact:
            return key
    return None


def normalize_personality_style(
    *,
    personality: Optional[str] = None,
    tone: Optional[str] = None,
    style: Optional[str] = None,
    personality_label: Optional[str] = None,
    temperature: Optional[float] = None,
    config_default: Optional[float] = None,
) -> Dict[str, Any]:
    """성격/말투 선택값을 canonical 스타일 + temperature + prompt_instruction 으로 정규화한다.

    해석 우선순위(스타일 키): personality → style → tone → personality_label.
    temperature 우선순위: 명시 temperature(clamp) → 스타일 기본 temperature → config_default → 0.5.
    실패해도 예외를 던지지 않고 default 로 폴백하며 warning 을 남긴다.
    """
    warning: Optional[str] = None
    key: Optional[str] = None
    source = "default"

    for candidate, src in (
        (personality, "personality"),
        (style, "style"),
        (tone, "tone"),
        (personality_label, "label"),
    ):
        resolved = _canonical_key(candidate)
        if resolved:
            key, source = resolved, src
            break

    if key is None:
        # 입력은 있었지만 어떤 매핑에도 안 걸린 경우만 warning(아예 미전송이면 조용히 default).
        if any(str(x or "").strip() for x in (personality, tone, style, personality_label)):
            warning = "정규화 실패 — default 스타일 적용"
        key = "default"
        source = "default"

    opt = PERSONALITY_STYLE_OPTIONS.get(key, PERSONALITY_STYLE_OPTIONS["default"])

    # temperature 결정
    cfg_default = config_default if config_default is not None else _config_default_temperature()
    if temperature is not None:
        temp = clamp_temperature(temperature)
        temp_source = "request"
    elif opt.get("temperature") is not None:
        temp = clamp_temperature(opt["temperature"])
        temp_source = "style"
    else:
        temp = clamp_temperature(cfg_default)
        temp_source = "config_default"

    return {
        "key": key,
        "label": opt.get("label", key),
        "description": opt.get("description", ""),
        "temperature": temp,
        "prompt_instruction": STYLE_PROMPT_INSTRUCTIONS.get(key, STYLE_PROMPT_INSTRUCTIONS["default"]),
        "source": source,
        "temperature_source": temp_source,
        "warning": warning,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 멀티에이전트 답변 차별화 정책 레이어 (reinforcement layer)
#
# 위 normalize_personality_style 는 프론트 라벨 정규화 + temperature SSOT 로 유지하고,
# 아래는 "성격/지식수준/답변깊이가 실제 답변에서 분명히 다르게 보이도록" 강한 지시문과
# 토큰 정책을 제공한다. multi_agent_service 의 1/2/3차 stage 프롬프트 끝에 덧붙여
# 기존 prompt_builder/persona_directive 를 '대체'하지 않고 '강화'한다.
#
# 캐노니컬 키는 라이브 to_profile_key() 산출값과 일치시킨다:
#   friendly | critical | logical | creative | concise | professional | sardonic | custom | default
# (요청서의 critical/logical/creative/concise 와 동일. friendly=친절, professional/logical=논리/전문)
# ══════════════════════════════════════════════════════════════════════════════

# 성격 라벨/별칭 → 리치 프로파일 캐노니컬 키
_PROFILE_ALIASES: Dict[str, str] = {
    "friendly": "friendly", "친절": "friendly", "친절형": "friendly", "친근함": "friendly", "warm": "friendly",
    "critical": "critical", "비판": "critical", "비판형": "critical", "냉철": "critical", "검증": "critical", "cynical": "critical", "honest": "critical",
    "logical": "logical", "논리": "logical", "논리형": "logical", "분석": "logical",
    "professional": "professional", "전문적": "professional", "전문가형": "professional", "expert": "professional",
    "creative": "creative", "창의": "creative", "창의형": "creative", "독특함": "creative", "unique": "creative",
    "concise": "concise", "간결": "concise", "간결형": "concise", "효율적": "concise", "efficient": "concise",
    "sardonic": "sardonic", "냉소적": "sardonic", "츤데레": "sardonic", "coach": "sardonic", "코치": "sardonic",
    "custom": "custom", "default": "default", "기본": "default", "balanced": "default",
}

# 성격별 리치 프로파일. 각 키는 요청서가 요구한 9개 속성을 모두 갖는다.
PERSONALITY_PROFILES: Dict[str, Dict[str, Any]] = {
    "friendly": {
        "label": "친절한 튜터형",
        "role": "학습자의 이해를 돕는 친절한 튜터",
        "tone": "따뜻하고 격려하는 말투, 존댓말",
        "cognitive_style": "쉬운 것부터 단계적으로 쌓아 올리는 스캐폴딩",
        "evidence_policy": "어려운 개념은 일상 비유와 구체 예시로 뒷받침한다",
        "challenge_level": "낮음 — 지적보다 안심시키고 다음 단계를 권한다",
        "explanation_style": "단계적 설명 + 비유 + 격려 마무리",
        "forbidden_behavior": "차갑거나 위압적인 어조, 비유를 핑계로 한 부정확함, 학습자 무시",
        "prompt_directive": (
            "[성격: 친절한 튜터형 — 반드시 답변에 드러나라]\n"
            "- 학습자가 처음 본다고 가정하고, 쉬운 개념부터 단계적으로 설명한다.\n"
            "- 핵심 개념마다 일상적 비유 또는 구체 예시를 최소 1개 든다.\n"
            "- 어조는 따뜻하고 격려한다. 마지막에 '다음엔 ~를 보면 좋아요' 식의 다음 학습 한 마디로 마친다.\n"
            "- 친절함을 이유로 정확성을 낮추지 않는다."
        ),
    },
    "critical": {
        "label": "냉철한 검증자형",
        "role": "주장과 근거의 허점을 검증하는 비판적 검토자",
        "tone": "단호하고 건조하지만 인신공격 없음",
        "cognitive_style": "반례·예외·경계조건부터 공격적으로 점검",
        "evidence_policy": "근거 없는 단정을 표시하고, 반례를 들어 약점을 드러낸다",
        "challenge_level": "높음 — 먼저 허점·위험·반례를 제시한 뒤 보완책을 준다",
        "explanation_style": "결론의 허점 → 반례/예외 → 조건부 수정안",
        "forbidden_behavior": "무조건 칭찬, '항상/무조건 좋다'식 과장, 사람 비하·조롱",
        "prompt_directive": (
            "[성격: 냉철한 검증자형 — 반드시 답변에 드러나라]\n"
            "- 장점보다 위험·허점·반례를 먼저 제시한다. '항상 좋은 것은 아니다'를 구체 근거로 보인다.\n"
            "- 주장에는 '어떤 조건에서 깨지는가'를 반드시 따진다(반례/예외/경계조건).\n"
            "- 검증한 뒤에는 반드시 보완 방향을 한 가지 이상 제시한다(비판만 하고 끝내지 않는다).\n"
            "- 내용만 비판하고 사람을 비하·조롱하지 않는다."
        ),
    },
    "logical": {
        "label": "논리 분석형",
        "role": "전제와 추론을 구조적으로 전개하는 분석가",
        "tone": "정제되고 차분한 설명체",
        "cognitive_style": "전제 → 추론 → 결론의 연역적 전개",
        "evidence_policy": "각 단계의 근거를 명시하고 비약을 피한다",
        "challenge_level": "중간 — 논리적 비약을 짚되 구조로 설득",
        "explanation_style": "전제 → 근거/추론 → 결론 + 비교 기준 명시",
        "forbidden_behavior": "결론만 던지기, 근거 없는 비약, 감정적 수사 과다",
        "prompt_directive": (
            "[성격: 논리 분석형 — 반드시 답변에 드러나라]\n"
            "- '전제 → 근거/추론 → 결론' 구조를 눈에 보이게 전개한다.\n"
            "- 비교·선택 문제는 비교 기준(축)을 먼저 정의하고 그 기준으로 판단한다.\n"
            "- 각 단계 사이의 인과/논리 연결을 명시한다(비약 금지).\n"
            "- 수식·구조가 필요하면 정확히 쓰되, 결론을 분명히 한 줄로 못박는다."
        ),
    },
    "professional": {
        "label": "전문적",
        "role": "정확성과 구조를 중시하는 전문가",
        "tone": "정제된 전문 설명체, 존댓말",
        "cognitive_style": "정의 → 핵심 → 근거의 구조화",
        "evidence_policy": "정확한 용어와 논거를 쓰되 근거 없는 단정은 피한다",
        "challenge_level": "중간 — 부정확함을 정밀하게 교정",
        "explanation_style": "정의 → 핵심 메커니즘 → 근거/조건 → 정리",
        "forbidden_behavior": "장황함, 부정확한 용어, 출처 없는 수치 단정",
        "prompt_directive": (
            "[성격: 전문적 — 반드시 답변에 드러나라]\n"
            "- 정의 → 핵심 메커니즘 → 근거/조건 순으로 구조화해 정확히 설명한다.\n"
            "- 정확한 전문 용어를 쓰되 처음 나오는 핵심 용어는 짧게 풀어 준다.\n"
            "- 장황함이 아니라 '정확성과 구조'가 핵심이다. 불확실한 부분은 불확실하다고 표시한다."
        ),
    },
    "creative": {
        "label": "창의 확장형",
        "role": "다른 관점과 비유로 사고를 확장하는 안내자",
        "tone": "활기차고 상상력 있는 말투",
        "cognitive_style": "유추·연결·재구성을 통한 확산적 사고",
        "evidence_policy": "비유로 직관을 주되 핵심 개념의 정확성은 지킨다",
        "challenge_level": "중간 — 통념을 뒤집는 관점을 제안",
        "explanation_style": "신선한 비유 → 다른 관점/분야 연결 → 확장 아이디어",
        "forbidden_behavior": "비유가 사실을 왜곡, 핵심 누락, 산만한 나열",
        "prompt_directive": (
            "[성격: 창의 확장형 — 반드시 답변에 드러나라]\n"
            "- 예상치 못한 비유 또는 다른 분야와의 연결을 최소 1개 제시한다.\n"
            "- '이렇게도 볼 수 있다'는 추가 관점이나 확장 아이디어를 덧붙인다.\n"
            "- 단, 비유가 핵심 개념의 사실을 왜곡하지 않게 정확성을 지킨다(비유 뒤에 핵심을 한 줄로 정리)."
        ),
    },
    "concise": {
        "label": "핵심 요약형",
        "role": "군더더기 없이 핵심만 전달하는 정리자",
        "tone": "간결하고 단정적",
        "cognitive_style": "우선순위화 후 핵심만 압축",
        "evidence_policy": "근거는 최소 1개만, 핵심에 직결되는 것만",
        "challenge_level": "낮음~중간 — 핵심에서 벗어난 군더더기를 잘라냄",
        "explanation_style": "불릿 포인트 + 한 줄 결론",
        "forbidden_behavior": "장황한 도입, 불필요한 수식어, 같은 말 반복",
        "prompt_directive": (
            "[성격: 핵심 요약형 — 반드시 답변에 드러나라]\n"
            "- 불필요한 도입·수식어를 제거하고 핵심만 불릿으로 정리한다.\n"
            "- 마지막에 한 줄 결론을 반드시 붙인다.\n"
            "- 짧되 빠뜨리면 안 되는 핵심 조건/예외는 한 줄로라도 남긴다."
        ),
    },
    "sardonic": {
        "label": "냉소적 코치형",
        "role": "까칠하지만 핵심을 찌르는 코치",
        "tone": "살짝 비꼬는 반말, 인신공격 없음",
        "cognitive_style": "통념을 비틀어 약점을 드러냄",
        "evidence_policy": "허세를 걷어내고 실제로 중요한 것만 짚는다",
        "challenge_level": "높음 — 날카롭게 지적하되 개선 포인트로 마무리",
        "explanation_style": "비틀기 → 핵심 지적 → 다음 생각 포인트",
        "forbidden_behavior": "존댓말, 욕설·인신공격, 비판만 하고 방향 없음",
        "prompt_directive": (
            "[성격: 냉소적 코치형 — 반드시 답변에 드러나라]\n"
            "- 살짝 비꼬는 반말로, 허세·통념을 걷어내고 핵심을 찌른다(존댓말 금지).\n"
            "- 인신공격·욕설은 금지하고 내용만 비판한다.\n"
            "- 마지막엔 반드시 개선 방향 또는 다음 생각 포인트를 던진다."
        ),
    },
    "default": {
        "label": "기본 균형형",
        "role": "균형 잡힌 학습 도우미",
        "tone": "명료하고 중립적인 존댓말",
        "cognitive_style": "핵심 → 이유 → 예시의 균형",
        "evidence_policy": "필요한 곳에만 예시/근거를 든다",
        "challenge_level": "중간",
        "explanation_style": "핵심 → 이유 → 예시 → 주의점",
        "forbidden_behavior": "무색무취한 일반론, 질문과 무관한 장광설",
        "prompt_directive": (
            "[성격: 기본 균형형 — 반드시 답변에 드러나라]\n"
            "- 핵심 → 이유 → 예시 → 주의점 순으로 균형 있게 설명한다.\n"
            "- 질문에 직접 답하고, 일반론으로 흐르지 않는다."
        ),
    },
    "custom": {  # 실제 지시문은 sanitize_custom_personality 로 주입된다.
        "label": "사용자 지정형",
        "role": "사용자가 직접 지정한 말투/관점",
        "tone": "사용자 지정",
        "cognitive_style": "사용자 지정",
        "evidence_policy": "사용자 지시를 따르되 개념 정확성은 유지",
        "challenge_level": "사용자 지정",
        "explanation_style": "사용자 지정",
        "forbidden_behavior": "지시를 빙자한 부정확함, 안전·정확성 훼손",
        "prompt_directive": "",
    },
}

# 성격별 권장 temperature (요청서 권장 범위 내). agent_settings 가 비어 있을 때의 참고/테스트용.
PERSONALITY_TEMPERATURE: Dict[str, float] = {
    "friendly": 0.62, "critical": 0.45, "logical": 0.40, "professional": 0.40,
    "creative": 0.85, "concise": 0.32, "sardonic": 0.50, "default": 0.55, "custom": 0.60,
}


def normalize_personality_key(value: Optional[str]) -> str:
    """성격 라벨/별칭/내부키를 리치 프로파일 캐노니컬 키로 정규화한다(실패 시 default)."""
    if value is None:
        return "default"
    s = str(value).strip()
    if not s:
        return "default"
    low = s.lower()
    if low in PERSONALITY_PROFILES:
        return low
    if low in _PROFILE_ALIASES:
        return _PROFILE_ALIASES[low]
    if s in _PROFILE_ALIASES:
        return _PROFILE_ALIASES[s]
    s_compact = s.replace(" ", "")
    for alias, key in _PROFILE_ALIASES.items():
        if alias and alias.replace(" ", "") in s_compact:
            return key
    return "default"


def get_personality_profile(value: Optional[str]) -> Dict[str, Any]:
    """리치 성격 프로파일(9속성)을 반환한다. 알 수 없으면 default."""
    key = normalize_personality_key(value)
    prof = dict(PERSONALITY_PROFILES.get(key, PERSONALITY_PROFILES["default"]))
    prof["key"] = key
    return prof


def recommended_temperature(value: Optional[str]) -> float:
    """성격별 권장 temperature(clamp 적용)."""
    key = normalize_personality_key(value)
    return clamp_temperature(PERSONALITY_TEMPERATURE.get(key, 0.55))


_INJECTION_PATTERNS = (
    "ignore previous", "ignore the above", "disregard", "system prompt",
    "이전 지시", "위 지시", "무시하고", "system:", "assistant:", "</", "```",
    "프롬프트를 무시", "규칙을 무시",
)


def sanitize_custom_personality(text: Optional[str], *, max_len: int = 600) -> str:
    """사용자 직접 입력 성격 지시를 안전하게 정규화한다.

    - 길이 제한, 제어문자 제거.
    - 프롬프트 인젝션/역할 탈취성 문구 제거(대소문자 무시).
    빈 문자열이면 "" 반환(호출부가 프로파일 기본 지시로 폴백).
    """
    if not text:
        return ""
    s = str(text).replace("\x00", " ").strip()
    if not s:
        return ""
    low = s.lower()
    for pat in _INJECTION_PATTERNS:
        if pat in low:
            # 인젝션 의심 토큰을 공백으로 무력화(문장은 살리되 지시 탈취만 제거)
            idx = low.find(pat)
            while idx != -1:
                s = s[:idx] + " " * len(pat) + s[idx + len(pat):]
                low = s.lower()
                idx = low.find(pat)
    # 공백 정리 + 길이 컷
    s = " ".join(s.split())
    return s[:max_len]


def build_personality_directive(
    value: Optional[str],
    *,
    strength: Optional[str] = None,
    custom_instruction: Optional[str] = None,
) -> str:
    """성격을 답변에 강하게 못박는 지시문을 만든다(stage 프롬프트 끝 주입용).

    custom_instruction 이 있으면 sanitize 후 최우선 반영한다.
    strength(mild/moderate/extreme)는 강도 한 줄을 덧붙인다.
    """
    safe_custom = sanitize_custom_personality(custom_instruction)
    if safe_custom:
        out = (
            "[성격 지시 — 반드시 답변에 반영] 사용자 지정 말투/관점을 최우선으로 따르되, "
            "개념 정확성과 안전은 유지하라:\n"
            f"{safe_custom}"
        )
        return out
    prof = get_personality_profile(value)
    directive = prof.get("prompt_directive") or PERSONALITY_PROFILES["default"]["prompt_directive"]
    forbidden = prof.get("forbidden_behavior")
    lines = [directive]
    if forbidden:
        lines.append(f"- 금지: {forbidden}")
    strength_norm = str(strength or "").strip().lower()
    if strength_norm in ("extreme", "strong", "강함"):
        lines.append("- 이 성격을 아주 분명하게 드러내라. 무색무취한 답변은 실패다.")
    elif strength_norm in ("mild", "약함"):
        lines.append("- 성격은 드러내되 과하지 않게 조절하라.")
    lines.append("- 다른 에이전트와 똑같은 말투·구조를 반복하지 마라.")
    return "\n".join(lines)


# ── 지식 수준 정책 ────────────────────────────────────────────────────────────
_LEVEL_ALIASES: Dict[str, str] = {
    "beginner": "beginner", "입문": "beginner", "초급": "beginner", "입문자": "beginner",
    "undergraduate": "undergraduate", "학사": "undergraduate", "학부": "undergraduate", "학부생": "undergraduate", "대학생": "undergraduate",
    "master": "master", "석사": "master", "대학원": "master", "대학원생": "master",
    "phd": "phd", "박사": "phd", "doctor": "phd", "doctoral": "phd",
    "expert": "expert", "전문가": "expert", "실무": "expert", "현업": "expert",
}

LEVEL_POLICY: Dict[str, Dict[str, Any]] = {
    "beginner": {
        "label": "입문자",
        "concept_density": "낮음",
        "reasoning_depth": "직관 위주",
        "num_predict": 768,
        "directive": (
            "[지식수준: 입문자]\n"
            "- 어려운 용어는 최소화하고, 쓰면 즉시 쉬운 말로 풀어 준다.\n"
            "- 짧은 문장과 일상 비유 중심으로 설명한다. 수식·코드는 꼭 필요할 때만.\n"
            "- 한 번에 한 개념씩, 너무 많은 내용을 쏟지 않는다."
        ),
    },
    "undergraduate": {
        "label": "학부 수준",
        "concept_density": "중간",
        "reasoning_depth": "개념+원리",
        "num_predict": 1024,
        "directive": (
            "[지식수준: 학부 수준]\n"
            "- 개념 정의와 작동 원리, 대표 예시를 함께 제시한다.\n"
            "- 시험/과제 답안에 쓸 수 있는 수준의 정확성과 구조를 유지한다."
        ),
    },
    "master": {
        "label": "석사 수준",
        "concept_density": "높음",
        "reasoning_depth": "trade-off/설계 근거",
        "num_predict": 1536,
        "directive": (
            "[지식수준: 석사 수준]\n"
            "- 설계 근거와 trade-off, 한계와 예외, 비교 분석을 포함한다.\n"
            "- 단순 정의를 넘어서 '왜 이렇게 하는가/언제 깨지는가'를 다룬다."
        ),
    },
    "phd": {
        "label": "박사 수준",
        "concept_density": "매우 높음",
        "reasoning_depth": "이론/경계조건/검증가능성",
        "num_predict": 2048,
        "directive": (
            "[지식수준: 박사 수준]\n"
            "- 이론적 전제와 모델링 관점, 검증 가능성, 반례와 경계조건을 다룬다.\n"
            "- 주장에는 가정과 그 가정이 깨지는 조건을 함께 명시한다."
        ),
    },
    "expert": {
        "label": "실무 전문가",
        "concept_density": "매우 높음(실무)",
        "reasoning_depth": "운영/아키텍처/리스크",
        "num_predict": 2048,
        "directive": (
            "[지식수준: 실무 전문가(L8+)]\n"
            "- 실제 시스템에서의 의사결정 관점으로 설명한다: 아키텍처/성능/장애/보안.\n"
            "- 운영 리스크와 관측 지표(latency/timeout/fallback/비용), 롤백/모니터링을 언급한다.\n"
            "- production-grade 판단 기준(언제 무엇을 선택/배제하는가)을 제시한다."
        ),
    },
}


def normalize_knowledge_level(value: Optional[str]) -> str:
    """지식수준 라벨(한/영)을 캐노니컬 키로 정규화한다(실패 시 undergraduate)."""
    if value is None:
        return "undergraduate"
    s = str(value).strip()
    if not s:
        return "undergraduate"
    low = s.lower()
    if low in LEVEL_POLICY:
        return low
    if low in _LEVEL_ALIASES:
        return _LEVEL_ALIASES[low]
    if s in _LEVEL_ALIASES:
        return _LEVEL_ALIASES[s]
    s_compact = s.replace(" ", "")
    for alias, key in _LEVEL_ALIASES.items():
        if alias and alias.replace(" ", "") in s_compact:
            return key
    return "undergraduate"


def get_level_policy(value: Optional[str]) -> Dict[str, Any]:
    key = normalize_knowledge_level(value)
    pol = dict(LEVEL_POLICY.get(key, LEVEL_POLICY["undergraduate"]))
    pol["key"] = key
    return pol


def build_level_directive(value: Optional[str]) -> str:
    return get_level_policy(value).get("directive", "")


# ── 답변 깊이 정책 ────────────────────────────────────────────────────────────
_DEPTH_ALIASES: Dict[str, str] = {
    "basic": "basic", "shallow": "basic", "short": "basic", "기본": "basic", "얕게": "basic", "간단": "basic", "간단히": "basic",
    "normal": "normal", "보통": "normal", "기본값": "normal", "표준": "normal",
    "deep": "deep", "깊게": "deep", "심화": "deep", "자세히": "deep", "상세": "deep",
    "max": "max", "maximum": "max", "최대": "max", "최대한": "max", "끝까지": "max",
}

DEPTH_POLICY: Dict[str, Dict[str, Any]] = {
    "basic": {
        "label": "핵심",
        "num_predict": 640,
        "directive": (
            "[답변 깊이: 핵심만]\n"
            "- 핵심 답변 + 최소 예시 1개 + 짧은 확인 질문 한 줄로 끝낸다.\n"
            "- 길게 늘이지 말고 바로 도움이 되는 내용만 담는다."
        ),
    },
    "normal": {
        "label": "표준",
        "num_predict": None,  # None = stage 기본 토큰 유지(behavior change 최소)
        "directive": (
            "[답변 깊이: 표준]\n"
            "- 개념 설명 → 이유 → 예시 → 주의사항을 균형 있게 담는다."
        ),
    },
    "deep": {
        "label": "심화",
        "num_predict": 2048,
        "directive": (
            "[답변 깊이: 심화]\n"
            "- 원리와 단계별 추론, 반례, 검증 기준, 실무 적용까지 다룬다.\n"
            "- '왜 그런가'와 '언제 깨지는가'를 분리해 설명한다."
        ),
    },
    "max": {
        "label": "최대",
        "num_predict": 3072,
        "directive": (
            "[답변 깊이: 최대]\n"
            "- 구조화된 분석으로: edge case, failure mode, trade-off,\n"
            "  검증/테스트 방법, 그리고 다음 액션까지 제시한다.\n"
            "- 단, 같은 말 반복으로 길이만 늘리지 않는다(밀도를 유지)."
        ),
    },
}

# 깊이 미지정 시 지식수준에서 합리적 기본 깊이를 추정한다.
_LEVEL_DEFAULT_DEPTH: Dict[str, str] = {
    "beginner": "basic", "undergraduate": "normal", "master": "deep", "phd": "deep", "expert": "deep",
}


def normalize_depth(value: Optional[str], level: Optional[str] = None) -> str:
    """답변 깊이 라벨을 캐노니컬 키로 정규화한다.

    명시값이 없으면 지식수준 기반 기본 깊이로 폴백한다(없으면 normal).
    """
    s = str(value or "").strip()
    if s:
        low = s.lower()
        if low in DEPTH_POLICY:
            return low
        if low in _DEPTH_ALIASES:
            return _DEPTH_ALIASES[low]
        if s in _DEPTH_ALIASES:
            return _DEPTH_ALIASES[s]
    if level is not None:
        return _LEVEL_DEFAULT_DEPTH.get(normalize_knowledge_level(level), "normal")
    return "normal"


def get_depth_policy(value: Optional[str], level: Optional[str] = None) -> Dict[str, Any]:
    key = normalize_depth(value, level)
    pol = dict(DEPTH_POLICY.get(key, DEPTH_POLICY["normal"]))
    pol["key"] = key
    return pol


def build_depth_directive(value: Optional[str], level: Optional[str] = None) -> str:
    return get_depth_policy(value, level).get("directive", "")


def resolve_num_predict(
    depth: Optional[str],
    level: Optional[str] = None,
    *,
    base: Optional[int] = None,
) -> Optional[int]:
    """답변 깊이(+지식수준) 기반 num_predict 를 결정한다.

    - 깊이 정책의 num_predict 가 있으면 그것을 기준값으로 한다(없으면 base 유지).
    - 지식수준 정책의 num_predict 가 더 크면 그쪽으로 끌어올린다(상세 수준 보장).
    - 반환 None = 호출부가 stage 기본 토큰을 그대로 사용(표준 깊이의 behavior change 최소화).
    """
    depth_np = get_depth_policy(depth, level).get("num_predict")
    level_np = get_level_policy(level).get("num_predict") if level is not None else None
    candidate = depth_np
    if candidate is None:
        candidate = base
    if candidate is None:
        return None
    if level_np is not None and depth_np is not None:
        candidate = max(candidate, level_np)
    # 로컬 14B 안전 상한
    return int(min(candidate, 4096))
