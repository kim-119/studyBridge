"""
Mode Gate & Dispatcher — 방 모드별 AI 진입점을 "함수 단위"로 분리한다.

설계:
- should_use_expert_orchestrator(ctx): 메시지 신호 + 모드로 "전문가 오케스트레이터를 쓸지,
  어느 depth로, 어떤 도구로, 섹션/토큰/용어 강도는 얼마로" 를 ExpertGateResult로 결정한다.
- run_<mode>_room_ai(ctx, gate): 각 방 모드의 진입점. 게이트 결과를 generate_expert_answer의
  gate_overrides로 변환해 호출하고, 실패 시 call_primary_llm 폴백으로 안전하게 내려간다.
- run_mode_aware_ai(ctx): mode 정규화 → 게이트 → 모드별 함수 디스패치.

원칙(기존 구조 적응):
- 이 코드베이스는 **동기**다. router가 asyncio.to_thread로 run_agent_chat를 돌린다.
  따라서 본 모듈도 동기로 구현한다(스펙의 async 시그니처는 적용하지 않음).
- 설정/프롬프트 SSOT는 mode_ai_config(ModeAIConfig, normalize_mode, build_*)를 재사용한다.
- 합성기는 expert_answer_orchestrator.generate_expert_answer(module 함수)이며,
  객체 expert_orchestrator.answer 대신 gate_overrides dict로 인자를 확장해 호출한다.
- 어떤 단계가 실패해도 예외를 밖으로 던지지 않고 폴백 답변을 돌려준다.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

try:
    from typing import Literal
    Depth = Literal["light", "normal", "deep", "expert"]
    AnswerProfile = Literal[
        "casual", "tutor", "expert", "socratic", "debate", "roleplay",
        "rag", "multi_agent", "exam", "code_review", "research",
    ]
except Exception:  # pragma: no cover
    Depth = str          # type: ignore[misc,assignment]
    AnswerProfile = str  # type: ignore[misc,assignment]

# 설정/프롬프트 SSOT는 mode_ai_config 재사용(normalize_mode 등 중복 정의 금지)
from app.services.mode_ai_config import normalize_mode, get_mode_config

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 환경변수 헬퍼 (secret 미취급, 안전한 기본값)
# ──────────────────────────────────────────────────────────────────────────────
def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("[mode_gate] invalid int env %s → default", name)
        return default


# ──────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class ExpertGateResult:
    use_expert: bool
    reason: str
    depth: Depth
    answer_profile: AnswerProfile
    max_sections: int
    max_tokens: int
    min_terms: int
    use_tavily: bool = False
    use_wikipedia: bool = False
    use_rag: bool = False
    use_openai_refine: bool = False
    use_validator: bool = False
    require_examples: bool = True
    require_limitations: bool = False
    require_multiple_perspectives: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModeRuntimeContext:
    message: str
    mode: str = "basic"
    level: Optional[str] = None
    personality: Optional[str] = None
    room_type: Optional[str] = None
    material_id: Optional[str] = None
    document_id: Optional[str] = None
    file_id: Optional[str] = None
    custom_persona: Optional[str] = None
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModeAnswerResult:
    answer: str
    mode: str
    depth: Depth
    profile: AnswerProfile
    used_expert_orchestrator: bool
    used_tavily: bool = False
    used_wikipedia: bool = False
    used_rag: bool = False
    used_validator: bool = False
    fallback_used: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# 신호 유틸
# ──────────────────────────────────────────────────────────────────────────────
def contains_any(text: str, keywords: List[str]) -> bool:
    if not text:
        return False
    return any(k in text for k in keywords)


def is_casual_message(message: str) -> bool:
    text = (message or "").strip().lower()
    casual = {
        "안녕", "ㅎㅇ", "하이", "hello", "hi", "고마워", "감사", "ㄱㄱ", "ㅇㅇ",
        "ㅇㅋ", "ㅋㅋ", "ㅎㅎ", "알겠어", "맞아", "아니", "계속", "다시", "오케이", "ok",
    }
    if text in casual:
        return True
    if len(text) <= 4 and re.fullmatch(r"[ㅋㅎㅇㄱㄴ\s!?.,]+", text):
        return True
    return False


def is_short_confirmation(message: str) -> bool:
    text = (message or "").strip()
    patterns = {
        "맞음?", "가능?", "왜?", "이거임?", "됨?", "어때?",
        "맞아?", "가능함?", "이거 맞음?", "이거 돼?", "됨",
    }
    return text in patterns or (len(text) <= 8 and text.endswith("?"))


def has_history_topic(history: Optional[List[Dict[str, Any]]]) -> bool:
    if not history:
        return False
    recent = " ".join(str(item.get("content", "")) for item in history[-4:])
    return len(recent.strip()) >= 80


# ──────────────────────────────────────────────────────────────────────────────
# 신호 키워드
# ──────────────────────────────────────────────────────────────────────────────
EXPERT_KEYWORDS = [
    "전문적으로", "박사급", "깊게", "자세히", "상세히", "꼼꼼히",
    "여러 견해", "다각도", "비판적으로", "학문적으로", "논문 수준",
    "원리부터", "구조적으로", "실무 관점", "이론 관점",
    "아키텍처", "검증", "분석", "비교", "한계", "반론", "근거",
]
FRESHNESS_KEYWORDS = [
    "최신", "최근", "현재", "요즘", "동향", "가격", "버전",
    "정책", "법", "API 변경", "라이브러리 업데이트",
    "모델 성능", "논문 동향", "2025", "2026",
]
RAG_KEYWORDS = [
    "이 문서", "자료 기반", "pdf", "PDF", "강의자료",
    "업로드한 자료", "자료보관함", "오답노트", "복습세션",
]
ACADEMIC_DOMAIN_KEYWORDS = [
    "컴퓨터공학", "알고리즘", "운영체제", "네트워크", "데이터베이스", "보안",
    "AI", "ML", "DL", "LLM", "RAG", "머신러닝", "딥러닝",
    "수학", "미분", "적분", "선형대수", "확률", "통계",
    "물리", "화학", "생명과학", "생리학", "환경공학", "수처리",
    "심리학", "철학", "경제학", "법학", "사회과학",
]
SHORT_ANSWER_KEYWORDS = [
    "짧게", "요약", "한 줄로", "한문장", "한 문장",
    "발표용 한 문장", "표로만", "간단히",
]


# ──────────────────────────────────────────────────────────────────────────────
# depth / profile / sections
# ──────────────────────────────────────────────────────────────────────────────
def default_depth_for_mode(mode: str) -> Depth:
    mode = normalize_mode(mode)
    env_map = {
        "basic": ("AI_EXPERT_GATE_BASIC_DEFAULT_DEPTH", "light"),
        "expert": ("AI_EXPERT_GATE_EXPERT_DEFAULT_DEPTH", "deep"),
        "socratic": ("AI_EXPERT_GATE_SOCRATIC_DEFAULT_DEPTH", "normal"),
        "debate": ("AI_EXPERT_GATE_DEBATE_DEFAULT_DEPTH", "deep"),
        "roleplay": ("AI_EXPERT_GATE_ROLEPLAY_DEFAULT_DEPTH", "normal"),
        "rag": ("AI_EXPERT_GATE_RAG_DEFAULT_DEPTH", "deep"),
        "multi_agent": ("AI_EXPERT_GATE_MULTI_AGENT_DEFAULT_DEPTH", "deep"),
        "exam": ("AI_EXPERT_GATE_EXAM_DEFAULT_DEPTH", "normal"),
        "code_review": ("AI_EXPERT_GATE_CODE_REVIEW_DEFAULT_DEPTH", "expert"),
        "research": ("AI_EXPERT_GATE_RESEARCH_DEFAULT_DEPTH", "expert"),
    }
    env_name, fallback = env_map.get(mode, ("AI_EXPERT_GATE_BASIC_DEFAULT_DEPTH", "light"))
    value = os.getenv(env_name, fallback).strip().lower()
    return value if value in {"light", "normal", "deep", "expert"} else fallback  # type: ignore[return-value]


def depth_to_limits(depth: Depth) -> tuple:
    """(max_sections, max_tokens, min_terms)"""
    if depth == "light":
        return (env_int("AI_EXPERT_LIGHT_MAX_SECTIONS", 3),
                env_int("AI_EXPERT_GATE_LIGHT_MAX_TOKENS", 1800),
                env_int("AI_EXPERT_LIGHT_MIN_TERMS", 1))
    if depth == "normal":
        return (env_int("AI_EXPERT_NORMAL_MAX_SECTIONS", 5),
                env_int("AI_EXPERT_GATE_NORMAL_MAX_TOKENS", 3500),
                env_int("AI_EXPERT_NORMAL_MIN_TERMS", 3))
    if depth == "deep":
        return (env_int("AI_EXPERT_DEEP_MAX_SECTIONS", 7),
                env_int("AI_EXPERT_GATE_DEEP_MAX_TOKENS", 6000),
                env_int("AI_EXPERT_DEEP_MIN_TERMS", 5))
    return (env_int("AI_EXPERT_FULL_MAX_SECTIONS", 11),
            env_int("AI_EXPERT_GATE_EXPERT_MAX_TOKENS", 8192),
            env_int("AI_EXPERT_FULL_MIN_TERMS", 8))


def profile_for_mode(mode: str) -> AnswerProfile:
    mode = normalize_mode(mode)
    mapping: Dict[str, str] = {
        "basic": "tutor", "expert": "expert", "socratic": "socratic", "debate": "debate",
        "roleplay": "roleplay", "rag": "rag", "multi_agent": "multi_agent",
        "exam": "exam", "code_review": "code_review", "research": "research",
    }
    return mapping.get(mode, "tutor")  # type: ignore[return-value]


# basic/일반 모드는 depth로 섹션 깊이를 조절. 그 외 모드는 mode_ai_config가 SSOT.
_DEPTH_SECTIONS: Dict[str, List[str]] = {
    "light": ["핵심 답변", "쉬운 설명", "예시 또는 요약"],
    "normal": ["핵심 답변", "개념 설명", "전문용어 풀이", "예시", "요약"],
    "deep": ["한 줄 결론", "개념 정의", "핵심 원리", "전문용어 풀이", "관점 비교", "예시", "주의점/한계"],
    "expert": ["한 줄 결론", "학문적 정의", "핵심 원리", "전문용어 풀이", "이론적 관점",
               "실무/응용 관점", "비판적 관점", "예시", "흔한 오해", "한계", "최종 요약"],
}


def get_answer_sections(mode: str, depth: Depth, max_sections: int) -> List[str]:
    m = normalize_mode(mode)
    cfg = get_mode_config(m)
    if m == "basic":
        sections = list(_DEPTH_SECTIONS.get(depth, cfg.answer_sections))
    else:
        sections = list(cfg.answer_sections)  # mode_ai_config SSOT
    n = max(1, int(max_sections)) if max_sections else len(sections)
    return sections[:n]


# ──────────────────────────────────────────────────────────────────────────────
# 게이트(핵심) — 전문가 오케스트레이터 사용 여부 + depth + 도구 + 한도 결정
# ──────────────────────────────────────────────────────────────────────────────
def should_use_expert_orchestrator(ctx: ModeRuntimeContext) -> ExpertGateResult:
    enabled = env_bool("AI_EXPERT_GATE_ENABLED", True)
    default_use = env_bool("AI_EXPERT_GATE_DEFAULT", False)

    mode = normalize_mode(ctx.mode)
    text = (ctx.message or "").strip()

    def _light(reason: str, profile: str = "casual") -> ExpertGateResult:
        ms, mt, mterm = depth_to_limits("light")
        return ExpertGateResult(use_expert=False, reason=reason, depth="light",
                                answer_profile=profile, max_sections=ms, max_tokens=mt, min_terms=mterm)

    if not enabled:
        return _light("disabled")

    force_modes = {"expert", "debate", "research", "code_review", "rag", "multi_agent", "exam"}
    has_material = bool(ctx.material_id or ctx.document_id or ctx.file_id)
    has_expert_keyword = contains_any(text, EXPERT_KEYWORDS)
    has_freshness = contains_any(text, FRESHNESS_KEYWORDS)
    has_rag_signal = has_material or contains_any(text, RAG_KEYWORDS)
    has_domain_signal = contains_any(text, ACADEMIC_DOMAIN_KEYWORDS)
    wants_short = contains_any(text, SHORT_ANSWER_KEYWORDS)

    # 일상 대화/짧은 확인은 가볍게(모드가 force가 아닐 때만)
    if mode not in force_modes:
        if env_bool("AI_EXPERT_CASUAL_BYPASS_ENABLED", True) and is_casual_message(text):
            return _light("casual")
        if is_short_confirmation(text) and not has_history_topic(ctx.conversation_history):
            return _light("too_short")

    depth: Depth = default_depth_for_mode(mode)
    reason = "default"
    _strong = ["박사급", "논문 수준", "전문적으로", "여러 견해", "비판적으로"]

    if mode in force_modes:
        # 전용 모드는 기본 depth를 쓰되, 강한 전문 신호가 있으면 expert로 격상한다.
        reason = "mode_required"
        if contains_any(text, _strong):
            depth = "expert"
            reason = "mode_required_expert_kw"
    elif has_rag_signal:
        reason = "rag_required"
        depth = "deep"
    elif has_expert_keyword:
        reason = "expert_keyword"
        depth = "expert" if contains_any(text, _strong) else "deep"
    elif has_freshness:
        reason = "freshness_required"
        depth = "deep"
    elif has_domain_signal:
        reason = "academic_domain"
        depth = "normal"
    else:
        reason = "default" if default_use else "simple"
        depth = default_depth_for_mode(mode)

    if wants_short:
        depth = "light" if depth in {"light", "normal"} else "normal"
        reason = f"{reason}_shortened"

    min_len = env_int("AI_EXPERT_GATE_MIN_MESSAGE_LENGTH", 18)
    if env_bool("AI_EXPERT_SIMPLE_DEFINITION_LIGHT_MODE", True) and len(text) < min_len \
            and mode == "basic" and not has_expert_keyword:
        depth = "light"

    max_sections, max_tokens, min_terms = depth_to_limits(depth)

    use_expert = (
        default_use or mode in force_modes or has_expert_keyword
        or has_rag_signal or has_freshness or has_domain_signal
    )
    if mode == "basic" and depth == "light" and not has_expert_keyword and not has_rag_signal:
        use_expert = False

    use_tavily = use_wikipedia = use_rag = use_validator = use_openai_refine = False

    if depth == "light":
        use_tavily = env_bool("AI_EXPERT_USE_TAVILY_FOR_LIGHT", False) and has_freshness
        use_wikipedia = env_bool("AI_EXPERT_USE_WIKIPEDIA_FOR_LIGHT", False) and has_domain_signal
        use_validator = env_bool("AI_EXPERT_USE_VALIDATOR_FOR_LIGHT", False)
    elif depth == "normal":
        use_tavily = has_freshness
        use_wikipedia = has_domain_signal or has_expert_keyword
        use_validator = True
    elif depth == "deep":
        use_tavily = env_bool("AI_EXPERT_USE_TAVILY_FOR_DEEP", True) and (has_freshness or mode in {"research", "debate"})
        use_wikipedia = env_bool("AI_EXPERT_USE_WIKIPEDIA_FOR_DEEP", True)
        use_validator = env_bool("AI_EXPERT_USE_VALIDATOR_FOR_DEEP", True)
        use_openai_refine = True
    else:  # expert
        use_tavily = has_freshness or mode in {"research", "debate", "code_review"}
        use_wikipedia = True
        use_validator = env_bool("AI_EXPERT_USE_VALIDATOR_FOR_EXPERT", True)
        use_openai_refine = True

    if mode == "research":
        use_tavily = env_bool("AI_EXPERT_USE_TAVILY_FOR_RESEARCH", True)
        use_validator = True
        use_expert = env_bool("AI_EXPERT_FORCE_FOR_RESEARCH", True)
    if has_rag_signal or mode == "rag":
        use_rag = env_bool("AI_EXPERT_FORCE_FOR_RAG", True)
    if mode == "code_review":
        use_expert = env_bool("AI_EXPERT_FORCE_FOR_CODE_REVIEW", True)
        use_validator = True

    return ExpertGateResult(
        use_expert=use_expert,
        reason=reason,
        depth=depth,
        answer_profile=profile_for_mode(mode),
        max_sections=max_sections,
        max_tokens=max_tokens,
        min_terms=min_terms,
        use_tavily=use_tavily,
        use_wikipedia=use_wikipedia,
        use_rag=use_rag,
        use_openai_refine=use_openai_refine,
        use_validator=use_validator,
        require_examples=depth in {"normal", "deep", "expert"},
        require_limitations=depth in {"deep", "expert"},
        require_multiple_perspectives=depth == "expert" or mode in {"debate", "research", "multi_agent"},
        metadata={
            "mode": mode,
            "has_material": has_material,
            "has_expert_keyword": has_expert_keyword,
            "has_freshness": has_freshness,
            "has_rag_signal": has_rag_signal,
            "has_domain_signal": has_domain_signal,
            "wants_short": wants_short,
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# 어댑터 (실제 프로젝트 함수 시그니처에 맞춤)
#   - 합성: expert_answer_orchestrator.generate_expert_answer(..., gate_overrides=)
#   - 폴백: llm_engine_router.call_primary_llm(system_prompt, user_prompt, knowledge_level)
# ──────────────────────────────────────────────────────────────────────────────
def _to_int(v: Any) -> Optional[int]:
    try:
        if v is None or str(v).strip() == "":
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _level_instr(level: Optional[str]) -> str:
    try:
        from app.services.knowledge_level_controller import get_level_instruction
        return get_level_instruction(level) if level else ""
    except Exception:  # noqa: BLE001
        return ""


def _persona_instr(personality: Optional[str], custom_persona: Optional[str]) -> str:
    try:
        from app.services.personality_prompt_builder import build_personality_prompt
        return build_personality_prompt(personality or "친절_설명형", custom_persona)
    except Exception:  # noqa: BLE001
        return ""


def _extra_ctx(ctx: ModeRuntimeContext) -> str:
    return "\n\n".join(p for p in [_level_instr(ctx.level),
                                   _persona_instr(ctx.personality, ctx.custom_persona)] if p and p.strip())


def _role_base(ctx: ModeRuntimeContext, cfg: Any) -> str:
    base = ctx.extra.get("base_system_prompt") if ctx.extra else None
    if base and str(base).strip():
        return str(base)
    extra = _extra_ctx(ctx)
    return "\n\n".join(p for p in [getattr(cfg, "system_prompt", ""), extra] if p and p.strip())


def _rag_context(ctx: ModeRuntimeContext) -> str:
    return (ctx.extra.get("rag_context", "") if ctx.extra else "") or ""


def _call_orchestrator(ctx: ModeRuntimeContext, overrides: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from app.services.expert_answer_orchestrator import generate_expert_answer
    cfg = get_mode_config(ctx.mode)
    mat = _to_int(ctx.material_id) or _to_int(ctx.document_id) or _to_int(ctx.file_id)
    return generate_expert_answer(
        question=ctx.message,
        knowledge_level=ctx.level or "학사",
        personality=ctx.personality or "친절_설명형",
        custom_instruction=ctx.custom_persona,
        material_id=mat,
        rag_context=_rag_context(ctx),
        base_system_prompt=_role_base(ctx, cfg),
        mode=ctx.mode,
        gate_overrides=overrides,
    )


def _fallback_llm(ctx: ModeRuntimeContext) -> str:
    from app.services.llm_engine_router import call_primary_llm
    from app.services import mode_ai_config as mc
    cfg = mc.get_mode_config(ctx.mode)
    extra = _extra_ctx(ctx)
    system_prompt = mc.build_system_prompt(cfg, context=extra)
    rag = _rag_context(ctx)
    tool_ctx = mc.build_tool_context(rag_results=rag) if rag else ""
    user_prompt = mc.build_final_prompt(ctx.message, cfg, context=tool_ctx)
    return call_primary_llm(system_prompt=system_prompt, user_prompt=user_prompt, knowledge_level=ctx.level)


def _fallback_result(ctx: ModeRuntimeContext, gate: ExpertGateResult, profile: str) -> ModeAnswerResult:
    try:
        ans = _fallback_llm(ctx)
    except Exception:  # noqa: BLE001
        logger.exception("[mode_gate] %s fallback 실패", ctx.mode)
        ans = "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
    return ModeAnswerResult(answer=ans, mode=ctx.mode, depth=gate.depth, profile=profile,  # type: ignore[arg-type]
                            used_expert_orchestrator=False, metadata={"gate_reason": gate.reason})


def _synthesize_room(ctx: ModeRuntimeContext, gate: ExpertGateResult, *, profile: str,
                     flag_overrides: Optional[Dict[str, Any]] = None,
                     depth: Optional[str] = None) -> ModeAnswerResult:
    """게이트 결과 → generate_expert_answer(gate_overrides) 호출 + 실패 시 폴백. 모든 모드 공통."""
    mode = ctx.mode
    d = depth or gate.depth
    sections = get_answer_sections(mode, d, gate.max_sections)  # type: ignore[arg-type]
    overrides: Dict[str, Any] = {
        "use_tavily": gate.use_tavily,
        "use_wikipedia": gate.use_wikipedia,
        "use_rag": gate.use_rag,
        "use_validator": gate.use_validator,
        "multi_perspective": gate.require_multiple_perspectives,
        "max_tokens": gate.max_tokens,
        "max_sections": gate.max_sections,
        "sections": sections,
        "min_terms": gate.min_terms,
        "depth": d,
        "profile": profile,
    }
    if flag_overrides:
        overrides.update(flag_overrides)
    try:
        res = _call_orchestrator(ctx, overrides)
        if res and res.get("answer"):
            return ModeAnswerResult(
                answer=res["answer"], mode=mode, depth=d, profile=profile,  # type: ignore[arg-type]
                used_expert_orchestrator=True,
                used_tavily=bool(overrides.get("use_tavily")),
                used_wikipedia=bool(overrides.get("use_wikipedia")),
                used_rag=bool(overrides.get("use_rag")),
                used_validator=bool(overrides.get("use_validator")),
                metadata={"gate_reason": gate.reason, "process_logs": res.get("process_logs", [])},
            )
    except Exception:  # noqa: BLE001
        logger.exception("[mode_gate] %s orchestrator 실패 → 폴백", mode)
    res = _fallback_result(ctx, gate, profile)
    res.fallback_used = True
    return res


# ──────────────────────────────────────────────────────────────────────────────
# 방 모드별 진입 함수 (각 방의 도구/검증/관점 정책을 명시적으로 반영)
# ──────────────────────────────────────────────────────────────────────────────
def run_basic_room_ai(ctx: ModeRuntimeContext, gate: ExpertGateResult) -> ModeAnswerResult:
    """basic: 가벼운 질문은 기존 LLM 경로, expert 신호가 있을 때만 오케스트레이터."""
    if not gate.use_expert:
        return _fallback_result(ctx, gate, "tutor")
    return _synthesize_room(ctx, gate, profile="tutor")


def run_expert_room_ai(ctx: ModeRuntimeContext, gate: ExpertGateResult) -> ModeAnswerResult:
    """expert: 박사급. 용어풀이/다관점/한계/검증 강제."""
    return _synthesize_room(ctx, gate, profile="expert", flag_overrides={
        "use_wikipedia": True, "use_validator": True, "multi_perspective": True,
        "min_terms": max(gate.min_terms, 5),
    })


def run_socratic_room_ai(ctx: ModeRuntimeContext, gate: ExpertGateResult) -> ModeAnswerResult:
    """socratic: 장문 정답 금지. 질문/힌트 중심(다관점·웹검색 끔, 토큰 제한)."""
    if not gate.use_expert:
        return _fallback_result(ctx, gate, "socratic")
    return _synthesize_room(ctx, gate, profile="socratic", flag_overrides={
        "use_tavily": False, "multi_perspective": False,
        "max_tokens": min(gate.max_tokens, env_int("AI_MODE_SOCRATIC_MAX_TOKENS", 4096)),
    })


def run_debate_room_ai(ctx: ModeRuntimeContext, gate: ExpertGateResult) -> ModeAnswerResult:
    """debate: 찬반/반론/재반론. 다관점·검증 강제."""
    return _synthesize_room(ctx, gate, profile="debate", flag_overrides={
        "use_validator": True, "multi_perspective": True,
    })


def run_roleplay_room_ai(ctx: ModeRuntimeContext, gate: ExpertGateResult) -> ModeAnswerResult:
    """roleplay: 역할 유지, 상호작용 우선. 깊은 신호일 때만 오케스트레이터."""
    if gate.depth in ("deep", "expert"):
        return _synthesize_room(ctx, gate, profile="roleplay", flag_overrides={
            "use_validator": False, "multi_perspective": False,
            "max_tokens": min(gate.max_tokens, env_int("AI_MODE_ROLEPLAY_MAX_TOKENS", 4096)),
        })
    return _fallback_result(ctx, gate, "roleplay")


def run_rag_room_ai(ctx: ModeRuntimeContext, gate: ExpertGateResult) -> ModeAnswerResult:
    """rag: 문서 근거 우선, 웹검색 끔, RAG/검증 강제."""
    return _synthesize_room(ctx, gate, profile="rag", flag_overrides={
        "use_tavily": False, "use_rag": True, "use_validator": True,
    })


def run_multi_agent_room_ai(ctx: ModeRuntimeContext, gate: ExpertGateResult) -> ModeAnswerResult:
    """multi_agent: 서로 다른 관점 종합. 다관점·검증 강제."""
    return _synthesize_room(ctx, gate, profile="multi_agent", flag_overrides={
        "use_validator": True, "multi_perspective": True,
    })


def run_exam_room_ai(ctx: ModeRuntimeContext, gate: ExpertGateResult) -> ModeAnswerResult:
    """exam: 예상문제/정답/해설/오답포인트. 웹검색 끔, 검증 강제."""
    return _synthesize_room(ctx, gate, profile="exam", flag_overrides={
        "use_tavily": False, "use_validator": True,
    })


def run_code_review_room_ai(ctx: ModeRuntimeContext, gate: ExpertGateResult) -> ModeAnswerResult:
    """code_review: 근거 중심 시니어 리뷰. 위키 끔, 검증 강제, expert depth."""
    return _synthesize_room(ctx, gate, profile="code_review", depth="expert", flag_overrides={
        "use_wikipedia": False, "use_validator": True, "min_terms": max(gate.min_terms, 5),
    })


def run_research_room_ai(ctx: ModeRuntimeContext, gate: ExpertGateResult) -> ModeAnswerResult:
    """research: 딥서치/보고서. Tavily·다관점·검증 강제, expert depth."""
    return _synthesize_room(ctx, gate, profile="research", depth="expert", flag_overrides={
        "use_tavily": True, "use_validator": True, "multi_perspective": True,
    })


# ──────────────────────────────────────────────────────────────────────────────
# Dispatcher
# ──────────────────────────────────────────────────────────────────────────────
_DISPATCH: Dict[str, Callable[[ModeRuntimeContext, ExpertGateResult], ModeAnswerResult]] = {
    "basic": run_basic_room_ai,
    "expert": run_expert_room_ai,
    "socratic": run_socratic_room_ai,
    "debate": run_debate_room_ai,
    "roleplay": run_roleplay_room_ai,
    "rag": run_rag_room_ai,
    "multi_agent": run_multi_agent_room_ai,
    "exam": run_exam_room_ai,
    "code_review": run_code_review_room_ai,
    "research": run_research_room_ai,
}


def run_mode_aware_ai(ctx: ModeRuntimeContext) -> ModeAnswerResult:
    """전체 AI 방 모드 진입점: mode 정규화 → 게이트 → 모드별 함수 디스패치(+안전 폴백)."""
    mode = normalize_mode(ctx.mode)
    ctx.mode = mode
    gate = should_use_expert_orchestrator(ctx)
    fn = _DISPATCH.get(mode)
    try:
        if fn is None:
            logger.warning("[mode_gate] unknown mode '%s' → basic", mode)
            ctx.mode = "basic"
            return run_basic_room_ai(ctx, gate)
        return fn(ctx, gate)
    except Exception:  # noqa: BLE001
        logger.exception("[mode_gate] dispatch 실패 → 폴백")
        res = _fallback_result(ctx, gate, gate.answer_profile)  # type: ignore[arg-type]
        res.fallback_used = True
        return res
