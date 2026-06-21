"""
StudyMate 에이전트 파이프라인 중앙 설정 (env 단일 관리).

원칙:
- stage별 provider / timeout / max_tokens, 성격별 생성 파라미터를 서비스 코드에 직접 박지 않는다.
- 모든 운영 값은 여기서 env로 읽고, 없으면 최소 fallback 기본값만 사용한다.
- 긴 성격 프롬프트/말투/금지표현/샘플톤은 여기 두지 않고 YAML(personality_prompt_builder)에서 관리한다.
- 채팅방 표시명만 프론트에서 하드코딩을 허용하며, 그 외 운영값은 모두 이 모듈을 거친다.
"""
import os
from pathlib import Path
from typing import Any, Dict, Optional

# ── env 파서 ──────────────────────────────────────────────────────────────────

def _f(key: str, default: float) -> float:
    try:
        v = os.getenv(key)
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _i(key: str, default: int) -> int:
    try:
        v = os.getenv(key)
        return int(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _s(key: str, default: str) -> str:
    v = os.getenv(key)
    return v if v not in (None, "") else default


def _b(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v in (None, ""):
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# ── stage별 provider / token / timeout ────────────────────────────────────────

def resolve_provider_for_stage(stage: int) -> str:
    """1차=Ollama 강제(기본), 2·3차는 env로 교체 가능."""
    if stage == 1:
        # 1차는 반드시 Ollama. env가 비정상이어도 ollama로 강제한다.
        provider = _s("AGENT_FIRST_PASS_PROVIDER", "ollama").strip().lower()
        return provider if provider == "ollama" else "ollama"
    if stage == 2:
        return _s("AGENT_SECOND_PASS_PROVIDER", "openai").strip().lower()
    return _s("AGENT_THIRD_PASS_PROVIDER", "openai").strip().lower()


def resolve_stage_max_tokens(stage: int) -> int:
    if stage == 1:
        # stage1은 Ollama num_predict 우선, 없으면 AGENT_STAGE1_MAX_TOKENS
        # (답변 잘림 방지: 기본값을 1200으로 둔다.)
        return _i("OLLAMA_STAGE1_NUM_PREDICT", _i("AGENT_STAGE1_MAX_TOKENS", 1200))
    if stage == 2:
        return _i("AGENT_STAGE2_MAX_TOKENS", 1800)
    return _i("AGENT_STAGE3_MAX_TOKENS", 1200)


def resolve_timeout_for_stage(stage: int) -> int:
    if stage == 1:
        return _i("OLLAMA_STAGE1_TIMEOUT_SECONDS", _i("AGENT_STAGE1_TIMEOUT_SECONDS", 120))
    if stage == 2:
        return _i("AGENT_STAGE2_TIMEOUT_SECONDS", 180)
    return _i("AGENT_STAGE3_TIMEOUT_SECONDS", 180)


def total_timeout_seconds() -> int:
    return _i("AGENT_TOTAL_TIMEOUT_SECONDS", 900)


# ── 파이프라인 토글 ───────────────────────────────────────────────────────────

def enable_parallel_stage1() -> bool:
    return _b("AGENT_ENABLE_PARALLEL_STAGE1", False)


def enable_parallel_stage2() -> bool:
    return _b("AGENT_ENABLE_PARALLEL_STAGE2", False)


def enable_cache() -> bool:
    return _b("AGENT_ENABLE_CACHE", True)


def cache_ttl_seconds() -> int:
    return _i("AGENT_CACHE_TTL_SECONDS", 600)


def enable_personality_validation() -> bool:
    return _b("AGENT_ENABLE_PERSONALITY_VALIDATION", True)


def enable_ai_debug_metadata() -> bool:
    """성격 검증 점수 등 내부 진단 메타데이터를 응답에 노출할지(기본 false).

    일반 사용자 화면에는 노출하지 않는다. env ENABLE_AI_DEBUG_METADATA=true이거나
    요청에 debugMetadata=true(관리자)가 있을 때만 노출한다(요청 플래그는 호출 측에서 OR).
    """
    return _b("ENABLE_AI_DEBUG_METADATA", False)


def personality_validation_min_score() -> float:
    return _f("AGENT_PERSONALITY_VALIDATION_MIN_SCORE", 0.72)


def personality_validation_max_retry() -> int:
    return _i("AGENT_PERSONALITY_VALIDATION_MAX_RETRY", 1)


def enable_persona_contrast_check() -> bool:
    return _b("AGENT_ENABLE_PERSONA_CONTRAST_CHECK", True)


def enable_auto_debate() -> bool:
    """모드 미지정 + 에이전트 2명 이상이면 자동으로 토론 모드로 진입할지."""
    return _b("AGENT_AUTO_DEBATE_MULTI", True)


# ── 2차 웹 근거 검증 (Tavily/Wikipedia/OpenAlex) ──────────────────────────────

def enable_stage2_web_verify() -> bool:
    """2차 검증 단계에서 외부 웹 근거(Tavily/Wikipedia/OpenAlex)를 수집할지."""
    return _b("AGENT_STAGE2_WEB_VERIFY", True)


def stage2_web_per_source_timeout() -> int:
    """검색 소스별 개별 타임아웃(초). best-effort."""
    return _i("AGENT_STAGE2_WEB_SOURCE_TIMEOUT_SECONDS", 12)


def stage2_web_total_timeout() -> int:
    """웹 근거 수집 전체 예산(초). 초과 소스는 버린다."""
    return _i("AGENT_STAGE2_WEB_TOTAL_TIMEOUT_SECONDS", 25)


def stage2_web_max_snippets() -> int:
    """프롬프트에 넣을 최대 근거 스니펫 수."""
    return _i("AGENT_STAGE2_WEB_MAX_SNIPPETS", 6)


# ── 성격별 생성 파라미터 ──────────────────────────────────────────────────────
# env 키 접두사는 정규 영문 키(friendly/critical/...) 기준. 미지정 성격은 DEFAULT로 fallback.

_DEFAULTS: Dict[str, float] = {
    "temperature": 0.55, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.08,
    "presence_penalty": 0.0, "frequency_penalty": 0.0,
    "strictness": 0.5, "creativity": 0.5, "verbosity": 0.6, "empathy": 0.5,
    "directness": 0.5, "example_density": 0.5, "metaphor_density": 0.4,
    "critique_density": 0.5, "structure_rigidity": 0.5, "humor_level": 0.3,
    "conclusion_strength": 0.6,
}

_NUMERIC_FIELDS = list(_DEFAULTS.keys())

# ── 성격별 생성수치 YAML 기본값 (env가 없을 때 적용) ──────────────────────────
# SSOT = policies/agent_generation_profiles.yaml. 우선순위: env > YAML > 코드 DEFAULT.
_GEN_PROFILE_PATH = (
    Path(__file__).resolve().parent.parent / "policies" / "agent_generation_profiles.yaml"
)
_gen_profiles_cache: Optional[Dict[str, Dict[str, float]]] = None


def _load_generation_profiles() -> Dict[str, Dict[str, float]]:
    """성격별 수치 기본값 YAML을 1회 로드/캐싱. 실패해도 서버를 죽이지 않는다."""
    global _gen_profiles_cache
    if _gen_profiles_cache is not None:
        return _gen_profiles_cache
    data: Dict[str, Dict[str, float]] = {}
    try:
        import yaml  # pyyaml
        path = Path(_s("AGENT_GENERATION_PROFILE_PATH", str(_GEN_PROFILE_PATH)))
        if path.exists():
            with open(path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                data = {
                    k: {fk: fv for fk, fv in (v or {}).items()}
                    for k, v in loaded.items() if isinstance(v, dict)
                }
    except Exception:
        data = {}
    _gen_profiles_cache = data
    return data


def reload_generation_profiles() -> None:
    """개발용: YAML 수치 프로필 캐시를 비운다(다음 호출 시 재로드)."""
    global _gen_profiles_cache
    _gen_profiles_cache = None


def _default_params() -> Dict[str, float]:
    return {
        "temperature":       _f("AGENT_DEFAULT_TEMPERATURE", _DEFAULTS["temperature"]),
        "top_p":             _f("AGENT_DEFAULT_TOP_P", _DEFAULTS["top_p"]),
        "top_k":             _i("AGENT_DEFAULT_TOP_K", int(_DEFAULTS["top_k"])),
        "repeat_penalty":    _f("AGENT_DEFAULT_REPEAT_PENALTY", _DEFAULTS["repeat_penalty"]),
        "presence_penalty":  _f("AGENT_DEFAULT_PRESENCE_PENALTY", _DEFAULTS["presence_penalty"]),
        "frequency_penalty": _f("AGENT_DEFAULT_FREQUENCY_PENALTY", _DEFAULTS["frequency_penalty"]),
        "strictness":        _DEFAULTS["strictness"], "creativity": _DEFAULTS["creativity"],
        "verbosity":         _DEFAULTS["verbosity"], "empathy": _DEFAULTS["empathy"],
        "directness":        _DEFAULTS["directness"], "example_density": _DEFAULTS["example_density"],
        "metaphor_density":  _DEFAULTS["metaphor_density"], "critique_density": _DEFAULTS["critique_density"],
        "structure_rigidity": _DEFAULTS["structure_rigidity"], "humor_level": _DEFAULTS["humor_level"],
        "conclusion_strength": _DEFAULTS["conclusion_strength"],
    }


def get_personality_params(canonical_key: str) -> Dict[str, float]:
    """
    성격별 운영 파라미터를 우선순위 env > YAML > 코드 DEFAULT 로 합성한다.
    canonical_key: friendly | critical | logical | creative | concise | professional | sardonic | custom

    - 코드 DEFAULT(_default_params): 모든 성격 공통 최소 기본값.
    - YAML(agent_generation_profiles.yaml): 성격별 기본값. env 미설정 시에도 성격 차등 보장.
    - env(AGENT_{KEY}_{FIELD}): 운영 override (최우선).
    """
    key = (canonical_key or "custom").lower()
    base = _default_params()
    # 1) YAML 성격 기본값 overlay (env가 없어도 성격이 살아있게 한다)
    yaml_profile = _load_generation_profiles().get(key, {})
    for field in _NUMERIC_FIELDS:
        if field in yaml_profile and yaml_profile[field] is not None:
            base[field] = yaml_profile[field]
    # 2) env override (최우선)
    prefix = f"AGENT_{key.upper()}_"
    out = dict(base)
    for field in _NUMERIC_FIELDS:
        env_key = prefix + field.upper()
        if field == "top_k":
            out[field] = _i(env_key, int(base[field]))
        else:
            out[field] = _f(env_key, base[field])
    return out


def resolve_agent_generation_params(canonical_key: str, stage: int) -> Dict[str, Any]:
    """
    성격 + stage를 합쳐 LLM 호출 파라미터를 반환한다.
    반환: provider/temperature/top_p/top_k/repeat_penalty/presence_penalty/frequency_penalty/max_tokens/timeout_seconds
    (provider별 미지원 파라미터는 호출 단계에서 무시된다.)
    """
    p = get_personality_params(canonical_key)
    provider = resolve_provider_for_stage(stage)
    return {
        "provider":          provider,
        "temperature":       p["temperature"],
        "top_p":             p["top_p"],
        "top_k":             int(p["top_k"]),
        "repeat_penalty":    p["repeat_penalty"],
        "presence_penalty":  p["presence_penalty"],
        "frequency_penalty": p["frequency_penalty"],
        "max_tokens":        resolve_stage_max_tokens(stage),
        "timeout_seconds":   resolve_timeout_for_stage(stage),
    }


def stage1_timeout_fallback_text() -> str:
    return _s(
        "AGENT_STAGE1_TIMEOUT_FALLBACK",
        "1차 빠른 답변 생성이 제한 시간 안에 완료되지 않았습니다. "
        "2차 검증 단계에서 보완 답변을 이어서 제공합니다.",
    )
