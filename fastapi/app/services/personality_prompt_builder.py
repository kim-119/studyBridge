"""
에이전트 성격/말투 프롬프트 빌더.
성격 유형을 시스템 프롬프트 지시사항으로 변환한다.

성격 정의의 단일 출처(SSOT)는 policies/agent_personality_profiles.yaml 이다.
아래 _PERSONALITY_PROMPTS는 YAML 부재/로드 실패 시에만 쓰는 fallback이다(중복 정의 아님).
"""
from enum import Enum
from pathlib import Path
from typing import Optional


class PersonalityType(str, Enum):
    FRIENDLY     = "친절_설명형"
    CRITICAL     = "비판적_분석형"
    LOGICAL      = "논리적_탐구형"
    CREATIVE     = "창의적_확장형"
    CONCISE      = "간결_요약형"
    PROFESSIONAL = "전문적"
    SARDONIC     = "냉소적"
    CUSTOM       = "직접_입력"


_PERSONALITY_PROMPTS: dict[PersonalityType, str] = {
    PersonalityType.FRIENDLY: """\
말투와 성격: 친절 설명형
- 따뜻하고 친근한 말투로 설명한다.
- "어렵게 생각하지 않아도 돼요!", "이렇게 생각하면 쉬워요!" 같은 격려 표현을 자연스럽게 섞는다.
- 단계별로 차근차근 설명하며, 이해하기 쉬운 비유와 예시를 풍부하게 사용한다.
- 독자가 틀렸더라도 부드럽게 바로잡는다. 위압적이거나 딱딱하게 말하지 않는다.
- GPT처럼 무색무취한 답변은 금지. 따뜻한 개성이 있어야 한다.""",

    PersonalityType.CRITICAL: """\
말투와 성격: 비판적 분석형 (StudyBridge 기준 츤데레 코치형)
- 헷갈리기 쉬운 부분이나 자주 틀리는 지점을 먼저 살짝 지적하되, 바로 개선 방향을 제시한다.
- "그렇게만 이해하면 반은 맞고 반은 틀려", "여기서 많이 실수하는데..." 같은 직설적이지만 도움이 되는 표현을 사용한다.
- 문제점 지적 → 올바른 설명 순서를 유지한다.
- 무례하거나 공격적이지 않도록 한다. 비판은 오직 학습을 위한 것이다.
- GPT처럼 밋밋한 답변은 금지. 날카롭지만 유용한 개성이 있어야 한다.""",

    PersonalityType.LOGICAL: """\
말투와 성격: 논리적 탐구형
- 원인 → 구조 → 결과 순서로 단계적으로 추론한다.
- "왜냐하면", "따라서", "결과적으로" 같은 논리 접속사를 적절히 활용한다.
- 근거 없는 주장은 하지 않는다. 모든 주장에 이유를 명시한다.
- 수학적 논증이나 단계별 증명처럼 설명한다.
- 모순이나 반례가 있으면 반드시 언급하고 해소한다.""",

    PersonalityType.CREATIVE: """\
말투와 성격: 창의적 확장형
- 예상치 못한 비유나 다른 분야와의 연결을 시도한다.
- "만약 이 개념이 없었다면?", "다른 분야에 적용하면?" 같은 확장적 사고를 유도한다.
- 독자가 "오, 이렇게 볼 수도 있구나!" 반응이 나오도록 한다.
- 개념을 새로운 시각으로 바라보는 질문을 포함한다.
- 기존 틀을 벗어나되, 핵심 정확성은 반드시 유지한다.""",

    PersonalityType.CONCISE: """\
말투와 성격: 간결 요약형
- 핵심만 압축해서 전달한다. 불필요한 서론·감탄사·중복 설명을 제거한다.
- 글머리 기호(•, -) 또는 번호 목록으로 정리한다.
- 한 포인트는 한 줄 이내.
- 답변 마지막에 반드시 한 줄 결론을 넣는다.
- 길면 틀린 것이다. 짧고 명확하게.""",

    PersonalityType.PROFESSIONAL: """\
말투와 성격: 전문적/학술형
- 정확한 전문 용어와 명확한 정의로 설명한다. 용어를 처음 쓸 때는 짧게 풀이한다.
- 개념 → 근거 → 적용/한계 순서로 밀도 있게 전개한다.
- "일반적으로", "아마도" 같은 모호한 표현 대신 구체적 기준과 조건을 제시한다.
- 감탄사나 과장 없이 신뢰감 있는 어조를 유지한다.
- GPT처럼 평범하고 두루뭉술한 답변은 금지. 전문가다운 정확성과 밀도가 있어야 한다.""",

    PersonalityType.SARDONIC: """\
말투와 성격: 냉소적 리뷰어형
- 냉정하고 직설적으로 핵심을 찌르되, 비아냥이 아니라 정확한 지적이어야 한다.
- "이거 자주 틀리는 부분인데", "대충 외우면 시험에서 그대로 깨진다" 같은 시니컬하지만 현실적인 표현을 쓴다.
- 틀린 부분은 봐주지 않고 정확히 교정한 뒤, 올바른 기준을 못 박는다.
- 인신공격·욕설·과한 조롱은 금지. 냉소는 오직 개념을 또렷하게 만들기 위한 도구다.
- GPT처럼 친절하기만 한 무난한 답변은 금지. 차갑지만 쓸모 있는 개성이 있어야 한다.""",
}

_VALIDATION_CRITERIA: dict[PersonalityType, str] = {
    PersonalityType.FRIENDLY:     "따뜻하고 친근한가? 예시·비유가 있는가? 위압적이지 않은가?",
    PersonalityType.CRITICAL:     "문제점 지적 후 개선 방향을 제시하는가? 무례하지 않은가? 개성이 있는가?",
    PersonalityType.LOGICAL:      "원인→구조→결과 순서인가? 논리 접속사가 적절한가? 근거가 명확한가?",
    PersonalityType.CREATIVE:     "새로운 비유·연결이 있는가? 확장적 사고가 포함되었는가? 독창성이 있는가?",
    PersonalityType.CONCISE:      "불필요한 장문이 없는가? 목록 형식인가? 한 줄 결론이 있는가?",
    PersonalityType.PROFESSIONAL: "정확한 용어와 근거가 있는가? 모호한 표현 없이 밀도 있는가?",
    PersonalityType.SARDONIC:     "틀린 부분을 정확히 교정했는가? 냉소가 조롱이 아닌 지적에 그치는가?",
}

# 프론트엔드 표시 라벨 / 요구사항 라벨 / 레거시 라벨을 정규 PersonalityType으로 매핑한다.
# (프론트는 '전문적/친근함/솔직함/독특함/효율적/냉소적'를 보내지만 프롬프트 키는 달랐다 → 성격이 죽던 원인)
_ALIAS: dict[str, PersonalityType] = {
    "전문적": PersonalityType.PROFESSIONAL, "전문": PersonalityType.PROFESSIONAL, "학술": PersonalityType.PROFESSIONAL,
    "친근함": PersonalityType.FRIENDLY, "친절형": PersonalityType.FRIENDLY, "친절": PersonalityType.FRIENDLY,
    "솔직함": PersonalityType.CRITICAL, "비판적 분석형": PersonalityType.CRITICAL, "비판형": PersonalityType.CRITICAL, "비판적": PersonalityType.CRITICAL,
    "논리형": PersonalityType.LOGICAL, "논리적": PersonalityType.LOGICAL, "논리": PersonalityType.LOGICAL,
    "독특함": PersonalityType.CREATIVE, "창의형": PersonalityType.CREATIVE, "창의적": PersonalityType.CREATIVE, "창의": PersonalityType.CREATIVE,
    "효율적": PersonalityType.CONCISE, "간결형": PersonalityType.CONCISE, "간결": PersonalityType.CONCISE,
    "냉소적": PersonalityType.SARDONIC, "냉정": PersonalityType.SARDONIC,
    "직접입력형": PersonalityType.CUSTOM, "직접입력": PersonalityType.CUSTOM,
    # 프론트(src/utils/personality.js)가 보내는 영문 키 — 백엔드 어휘(sardonic/critical/concise)와 달라
    # 매핑이 없으면 친절형으로 폴백되어 성격이 죽는다. 6종 전부 명시 매핑한다.
    "professional": PersonalityType.PROFESSIONAL,
    "friendly": PersonalityType.FRIENDLY, "default": PersonalityType.FRIENDLY,
    "honest": PersonalityType.CRITICAL,
    "unique": PersonalityType.CREATIVE,
    "efficient": PersonalityType.CONCISE,
    "cynical": PersonalityType.SARDONIC,
    "custom": PersonalityType.CUSTOM,
}

# 성격별 LLM 샘플링 파라미터 (call_primary_llm은 temperature/max_tokens만 지원 → temperature 위주로 차등).
_GEN_PARAMS: dict[PersonalityType, dict] = {
    PersonalityType.FRIENDLY:     {"temperature": 0.6},
    PersonalityType.CRITICAL:     {"temperature": 0.45},
    PersonalityType.LOGICAL:      {"temperature": 0.35},
    PersonalityType.CREATIVE:     {"temperature": 0.85},
    PersonalityType.CONCISE:      {"temperature": 0.35},
    PersonalityType.PROFESSIONAL: {"temperature": 0.4},
    PersonalityType.SARDONIC:     {"temperature": 0.5},
    PersonalityType.CUSTOM:       {"temperature": 0.6},
}


# PersonalityType → YAML/env 정규 영문 키
_PROFILE_KEY: dict[PersonalityType, str] = {
    PersonalityType.FRIENDLY: "friendly",
    PersonalityType.CRITICAL: "critical",
    PersonalityType.LOGICAL: "logical",
    PersonalityType.CREATIVE: "creative",
    PersonalityType.CONCISE: "concise",
    PersonalityType.PROFESSIONAL: "professional",
    PersonalityType.SARDONIC: "sardonic",
    PersonalityType.CUSTOM: "custom",
}

# 정규 영문 키 → PersonalityType (YAML aliases를 normalize에 쓰기 위한 역매핑)
_KEY_TO_TYPE: dict[str, PersonalityType] = {v: k for k, v in _PROFILE_KEY.items()}

_PROFILES_PATH = Path(__file__).resolve().parent.parent / "policies" / "agent_personality_profiles.yaml"
_profiles_cache: Optional[dict] = None


def _load_profiles() -> dict:
    """YAML 성격 프로필을 1회 로드/캐싱. 실패해도 서버를 죽이지 않는다."""
    global _profiles_cache
    if _profiles_cache is not None:
        return _profiles_cache
    data: dict = {}
    try:
        import yaml  # pyyaml
        if _PROFILES_PATH.exists():
            with open(_PROFILES_PATH, encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                data = loaded
    except Exception:
        data = {}
    _profiles_cache = data
    return data


_yaml_alias_cache: Optional[dict] = None


def _yaml_alias_map() -> dict:
    """YAML 프로필의 aliases를 {라벨소문자: 정규키}로 1회 빌드/캐싱한다(없으면 빈 dict)."""
    global _yaml_alias_cache
    if _yaml_alias_cache is not None:
        return _yaml_alias_cache
    out: dict = {}
    for key, profile in _load_profiles().items():
        if not isinstance(profile, dict):
            continue
        for alias in (profile.get("aliases") or []):
            if alias:
                out[str(alias).strip().lower()] = key
        out[key.lower()] = key  # 정규 키 자기 자신도 매칭
    _yaml_alias_cache = out
    return out


def to_profile_key(personality: Optional[str]) -> str:
    """성격 라벨을 정규 영문 키로 변환한다(friendly/critical/...)."""
    return _PROFILE_KEY.get(normalize_personality(personality), "friendly")


def get_profile(personality: Optional[str]) -> dict:
    """성격 YAML 프로필(dict)을 반환한다. 없으면 빈 dict."""
    return _load_profiles().get(to_profile_key(personality), {})


def normalize_personality(raw: Optional[str]) -> PersonalityType:
    """프론트/요구사항/레거시 라벨을 정규 PersonalityType으로 변환한다. 미상은 FRIENDLY."""
    if not raw:
        return PersonalityType.FRIENDLY
    s = str(raw).strip()
    try:
        return PersonalityType(s)  # 정규 enum 값과 정확히 일치
    except ValueError:
        pass
    # 1) YAML aliases(SSOT) 우선 — 정확 매칭
    yaml_aliases = _yaml_alias_map()
    sl = s.lower()
    if sl in yaml_aliases:
        return _KEY_TO_TYPE.get(yaml_aliases[sl], PersonalityType.FRIENDLY)
    # 2) 코드 _ALIAS fallback — 정확 매칭
    if s in _ALIAS:
        return _ALIAS[s]
    # 3) 부분 매칭 (예: '비판적 분석형(직설)') — YAML → 코드 순
    for alias_label, key in yaml_aliases.items():
        if alias_label and (alias_label in sl or sl in alias_label):
            return _KEY_TO_TYPE.get(key, PersonalityType.FRIENDLY)
    for key, val in _ALIAS.items():
        if key in s or s in key:
            return val
    return PersonalityType.FRIENDLY


def get_generation_params(personality: Optional[str]) -> dict:
    """성격별 생성 파라미터(temperature 등)를 반환한다."""
    return dict(_GEN_PARAMS.get(normalize_personality(personality), {"temperature": 0.5}))


def _compose_prompt_from_profile(profile: dict) -> str:
    """YAML 프로필(dict)을 시스템 프롬프트 블록으로 조립한다."""
    lines = []
    # coreDirective(사용자 지정 행동 지시문)는 다른 어떤 규칙보다 우선이며 맨 앞에 그대로 둔다.
    core = profile.get("coreDirective")
    if core and str(core).strip():
        lines.append(f"[성격 핵심 지시 — 최우선, 반드시 이 톤으로]\n{str(core).strip()}")
    name = profile.get("displayName", "")
    tone = profile.get("toneProfile", "")
    lines.append(f"말투와 성격: {name} — {tone}".strip(" —"))
    if str(profile.get("speechRegister", "")).strip() == "반말":
        lines.append("말투 규칙: 반드시 반말로 답한다(존댓말 '~입니다/~합니다/~하세요' 금지). 까칠하되 욕설·인신공격 금지, 마지막엔 개선 방향을 준다.")
    if profile.get("identity"):
        lines.append(f"정체성: {profile['identity']}")
    if profile.get("reasoningStyle"):
        lines.append(f"설명 방식: {profile['reasoningStyle']}")
    if profile.get("feedbackStyle"):
        lines.append(f"피드백 방식: {profile['feedbackStyle']}")
    shape = profile.get("answerShape") or []
    if shape:
        lines.append("답변 구성(권장 순서): " + " → ".join(str(s) for s in shape))
    must = profile.get("mustUse") or []
    if must:
        lines.append("이런 표현/뉘앙스를 자연스럽게 살려라: " + ", ".join(f'"{m}"' for m in must))

    # 비유 규칙 (creative 등): 비유 밀도/허용 소재/필수 조건을 강하게 지시
    mr = profile.get("metaphorRules") or {}
    if isinstance(mr, dict) and mr:
        parts = []
        if mr.get("requirement"):
            parts.append(str(mr["requirement"]))
        domains = mr.get("allowedDomains") or []
        if domains:
            parts.append("비유 소재 예: " + ", ".join(str(d) for d in domains))
        if mr.get("density"):
            parts.append(f"비유 밀도: {mr['density']}")
        if parts:
            lines.append("비유 규칙: " + " / ".join(parts))

    # 문장 리듬 규칙 (creative 등): bullet만 나열 금지 등
    rr = profile.get("rhythmRules") or {}
    if isinstance(rr, dict) and rr:
        parts = []
        if rr.get("sentenceLength"):
            parts.append(f"문장 길이 {rr['sentenceLength']}")
        if rr.get("variation"):
            parts.append(f"리듬 변화 {rr['variation']}")
        if rr.get("avoidUniformBulletOnly"):
            parts.append("단순 bullet 나열만으로 답하지 말 것(문장과 비유를 섞어라)")
        if parts:
            lines.append("문장 리듬: " + " / ".join(parts))

    forbidden = profile.get("forbidden") or []
    if forbidden:
        lines.append("금지: " + ", ".join(str(f) for f in forbidden))
    if profile.get("sampleTone"):
        lines.append(f"예시 톤(이 톤과 구조를 모방하라):\n{str(profile['sampleTone']).strip()}")
    lines.append("GPT처럼 무색무취한 답변은 금지. 위 성격이 실제 문장 톤에 분명히 드러나야 한다.")
    return "\n".join(lines)


def build_personality_prompt(
    personality: str,
    custom_instruction: Optional[str] = None,
) -> str:
    """
    성격 타입 문자열을 시스템 프롬프트에 삽입할 지시사항으로 반환한다.
    우선순위: coreDirective(6종 사용자 지정 행동지시문, 무조건 최우선)
            > custom_instruction > YAML 프로필 > 내장 fallback.
    (coreDirective가 있으면 프리셋의 customInstruction이 있어도 성격을 덮지 못한다.)
    """
    p_type = normalize_personality(personality)
    profile = _load_profiles().get(_PROFILE_KEY.get(p_type, "friendly"), {})

    # coreDirective는 무엇보다 우선한다(customInstruction보다도 위).
    if profile.get("coreDirective"):
        return _compose_prompt_from_profile(profile)

    if custom_instruction and custom_instruction.strip():
        return f"말투와 성격 (사용자 지정):\n{custom_instruction.strip()}"

    if profile:
        return _compose_prompt_from_profile(profile)
    return _PERSONALITY_PROMPTS.get(p_type, _PERSONALITY_PROMPTS[PersonalityType.FRIENDLY])


def build_persona_directive(
    personality: Optional[str],
    custom_instruction: Optional[str] = None,
    repair_instruction: Optional[str] = None,
) -> str:
    """
    LLM user 프롬프트의 '마지막'에 넣을 강한 성격 지시를 YAML 프로필에서 조립한다.
    (system 프롬프트만으로는 모델이 정확성 지시에 눌려 성격을 버리므로, user 턴 끝에 다시 못박는다.)
    하드코딩 없이 전부 프로필(answerShape/mustUse/metaphorRules/forbidden)에서 가져온다.
    """
    profile = get_profile(personality)
    name = profile.get("displayName", "") or "지정된 성격"
    core = profile.get("coreDirective")

    # coreDirective(6종)는 customInstruction보다도 우선 — 무조건 이 성격으로 못박는다.
    if core and str(core).strip():
        out = [
            f"[성격 지시 — 반드시 답변 문장에 드러나라] 너의 성격: {name}",
            f"- ★ {str(core).strip()}",
        ]
        if str(profile.get("speechRegister", "")).strip() == "반말":
            out.append("- ★ 반드시 반말로 답한다. '~입니다/~합니다/~하세요/~예요' 같은 존댓말은 절대 금지. 인신공격·욕설은 금지.")
        out.append("- 다른 에이전트와 똑같은 말투·구조로 쓰지 마라. GPT식 무색무취 답변은 실패다.")
        if repair_instruction:
            out.append(f"- 보정 지시: {repair_instruction}")
        return "\n".join(out)

    if custom_instruction and custom_instruction.strip():
        base = (
            "[성격 지시 — 반드시 답변에 반영] 사용자 지정 말투/지시를 최우선으로 따르되 "
            f"개념 정확성은 유지하라:\n{custom_instruction.strip()}"
        )
        return base + (f"\n- 보정 지시: {repair_instruction}" if repair_instruction else "")

    lines = [f"[성격 지시 — 반드시 답변 문장에 드러나라] 너의 성격: {name}"]
    # 반말 레지스터(냉소적/비판형 등): 존댓말 금지를 강하게 못박는다.
    if str(profile.get("speechRegister", "")).strip() == "반말":
        lines.append(
            "- ★ 반드시 반말로 답한다. '~입니다/~합니다/~하세요/~예요' 같은 존댓말은 절대 금지. "
            "까칠하고 살짝 비꼬되(약하게), 인신공격·욕설은 금지. 마지막엔 반드시 개선 방향이나 다음 생각 포인트를 준다."
        )
    if profile.get("identity"):
        lines.append(f"- 정체성: {profile['identity']}")
    shape = profile.get("answerShape") or []
    if shape:
        lines.append("- 답변 구조(이 순서를 지켜라): " + " → ".join(str(s) for s in shape))
    must = profile.get("mustUse") or []
    if must:
        lines.append("- 이런 표현을 자연스럽게 써라: " + ", ".join(f'"{m}"' for m in must))
    mr = profile.get("metaphorRules") or {}
    if isinstance(mr, dict) and mr.get("requirement"):
        domains = mr.get("allowedDomains") or []
        dtxt = f" (소재 예: {', '.join(str(d) for d in domains[:6])})" if domains else ""
        lines.append(f"- {mr['requirement']}{dtxt}")
    forbidden = profile.get("forbidden") or []
    if forbidden:
        lines.append("- 금지: " + ", ".join(str(f) for f in forbidden))
    lines.append("- 다른 에이전트와 똑같은 말투·구조로 쓰지 마라. GPT식 무색무취 답변은 실패다.")
    if repair_instruction:
        lines.append(f"- 보정 지시(직전 답변이 성격을 충분히 못 살림): {repair_instruction}")
    return "\n".join(lines)


def get_validation_criteria(personality: str) -> str:
    """GPT 검증 시 사용할 성격별 체크 항목을 반환한다."""
    return _VALIDATION_CRITERIA.get(
        normalize_personality(personality), "성격에 맞게 답변했는가? GPT처럼 평범하지 않은가?"
    )


def get_validation_hints(personality: Optional[str]) -> list[str]:
    """YAML 프로필의 validationHints(성격별 휴리스틱 체크리스트)를 반환한다. 없으면 빈 리스트."""
    hints = get_profile(personality).get("validationHints") or []
    return [str(h) for h in hints]


def get_socratic_style(personality: Optional[str]) -> str:
    """소크라테스 모드에서 성격별 '질문 방식'(socraticStyle)을 반환한다. 없으면 기본 문구."""
    style = get_profile(personality).get("socraticStyle")
    if style:
        return str(style)
    return "성격 톤을 유지하되 정답은 직접 주지 않고 꼬리질문으로 유도한다."


def build_personality_system_prompt(agent, stage: int = 1, question: str = "") -> str:
    """
    agent + stage(+question)를 받아 성격 시스템 프롬프트 블록을 만든다.
    실제 전체 시스템 프롬프트(역할/지식수준 포함)는 prompt_builder.build_agent_system_prompt가
    이 빌더(build_personality_prompt)를 호출해 조립한다. 본 함수는 성격 블록 + stage 역할 힌트만 반환하는
    경량 진입점이다(직접 호출/테스트용).
    """
    label = getattr(agent, "personality", None) or getattr(agent, "tone", None) or getattr(agent, "style", None)
    custom = getattr(agent, "customInstruction", None)
    block = build_personality_prompt(label, custom)
    stage_hint = {
        1: "[1차] 네 성격을 살려 빠른 초안을 작성하라. 정확성은 유지하되 톤은 분명히 드러내라.",
        2: "[2차] 1차 답변을 네 성격 기준으로 검증·보강하라. 빠진 정확성과 톤을 함께 채워라.",
        3: "[3차] 다른 에이전트 답변을 네 성격 관점에서 평가/피드백하라.",
    }.get(stage, "")
    parts = [block]
    if stage_hint:
        parts.append(stage_hint)
    return "\n".join(parts)


def list_personalities() -> list[str]:
    """사용 가능한 성격 유형 목록을 반환한다."""
    return [p.value for p in PersonalityType]
