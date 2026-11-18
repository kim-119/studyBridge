"""
학습자 수준(INTRO/BACHELOR/MASTER/DOCTOR/EXPERT) 정책 중앙 모듈.

목적: "학습자 수준" 선택값이 실제 답변 깊이/길이/도구 사용/검증 범위에 반영되도록
멀티에이전트 라이브 SSE에서 공용으로 쓰는 단일 정책 소스.

원칙:
- 수준 매핑/최소 글자수/max_tokens/num_ctx/도구 게이팅을 여기 한 곳에서만 정의한다
  (서비스 코드에 magic value를 박지 않는다).
- 모든 값은 환경변수로 override 가능하다. 기능 전체는 AI_LEVEL_AWARE_ENABLED로 on/off.
- Qwen3=초안/본문 생성, 수준별로 max_tokens·외부 도구·OpenAI 검토 게이팅을 결정한다.
- OpenAI 최종 판정자가 아니라 "검토/보정" 용도이며, 실패 시 숨기지 않고 toolsFailed에 남긴다.
"""
import os
from typing import Any, Dict, List, Optional, Set

CANONICAL = ("INTRO", "BACHELOR", "MASTER", "DOCTOR", "EXPERT")

# 영문/한글 별칭 → 표준 enum
_ALIASES: Dict[str, str] = {
    "intro": "INTRO", "beginner": "INTRO", "입문": "INTRO", "입문 수준": "INTRO", "초급": "INTRO",
    "bachelor": "BACHELOR", "undergraduate": "BACHELOR", "학사": "BACHELOR",
    "학사 수준": "BACHELOR", "학부": "BACHELOR",
    "master": "MASTER", "graduate": "MASTER", "석사": "MASTER", "석사 수준": "MASTER",
    "doctor": "DOCTOR", "phd": "DOCTOR", "박사": "DOCTOR", "박사 수준": "DOCTOR",
    "expert": "EXPERT", "전문가": "EXPERT", "전문가 수준": "EXPERT",
}

_KOREAN_LABEL: Dict[str, str] = {
    "INTRO": "입문", "BACHELOR": "학사", "MASTER": "석사", "DOCTOR": "박사", "EXPERT": "전문가",
}

# ── 기본값 (모두 환경변수로 override 가능) ────────────────────────────────────
_DEFAULT_MIN_CHARS = {"INTRO": 1000, "BACHELOR": 1000, "MASTER": 2000, "DOCTOR": 3000, "EXPERT": 3000}
_DEFAULT_MAX_TOKENS = {"INTRO": 1400, "BACHELOR": 1600, "MASTER": 2800, "DOCTOR": 3800, "EXPERT": 3800}
_DEFAULT_NUM_CTX = {"INTRO": 4096, "BACHELOR": 4096, "MASTER": 5120, "DOCTOR": 7168, "EXPERT": 7168}

# 도구 게이팅 기준 (수준 순서 인덱스로 판단)
_ORDER = {lvl: i for i, lvl in enumerate(CANONICAL)}


def enabled() -> bool:
    """수준 인지 기능 전체 on/off. 기본 on. false면 기존 동작 그대로."""
    return os.getenv("AI_LEVEL_AWARE_ENABLED", "true").strip().lower() == "true"


def default_level() -> str:
    return normalize(os.getenv("AI_DEFAULT_KNOWLEDGE_LEVEL", "undergraduate"))


def normalize(value: Any) -> str:
    """영문/한글/혼용 입력을 표준 enum(INTRO..EXPERT)으로 정규화. 불명확 시 BACHELOR."""
    raw = str(value or "").strip()
    if not raw:
        return "BACHELOR"
    if raw.upper() in CANONICAL:
        return raw.upper()
    low = raw.lower()
    if low in _ALIASES:
        return _ALIASES[low]
    # 부분 매칭 (예: "박사 수준의 ...")
    for alias, canon in _ALIASES.items():
        if alias in low or alias in raw:
            return canon
    return "BACHELOR"


def korean_label(level: str) -> str:
    return _KOREAN_LABEL.get(normalize(level), "학사")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def min_chars(level: str) -> int:
    lvl = normalize(level)
    return _int_env(f"AI_LEVEL_MINCHARS_{lvl}", _DEFAULT_MIN_CHARS[lvl])


def max_tokens(level: str) -> int:
    lvl = normalize(level)
    return _int_env(f"AI_LEVEL_MAXTOKENS_{lvl}", _DEFAULT_MAX_TOKENS[lvl])


def num_ctx(level: str) -> int:
    lvl = normalize(level)
    return _int_env(f"AI_LEVEL_NUMCTX_{lvl}", _DEFAULT_NUM_CTX[lvl])


def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() == "true"


def use_web(level: str) -> bool:
    """석사 이상 Tavily/Wikipedia 사용."""
    lvl = normalize(level)
    return _bool_env(f"AI_LEVEL_USEWEB_{lvl}", _ORDER[lvl] >= _ORDER["MASTER"])


def use_openalex(level: str) -> bool:
    """박사/전문가 OpenAlex(논문 메타데이터) 사용."""
    lvl = normalize(level)
    return _bool_env(f"AI_LEVEL_USEOPENALEX_{lvl}", _ORDER[lvl] >= _ORDER["DOCTOR"])


def use_openai_review(level: str) -> bool:
    """학사 이상 OpenAI 검토/보정 사용 (입문은 Qwen 중심)."""
    lvl = normalize(level)
    return _bool_env(f"AI_LEVEL_USEOPENAI_{lvl}", _ORDER[lvl] >= _ORDER["BACHELOR"])


def qwen_model_name() -> str:
    return os.getenv("OLLAMA_MODEL", "qwen2.5:14b")


def planned_web_tools(level: str) -> List[str]:
    """해당 수준이 사용하기로 한 웹 검색 도구(소문자 표준명). OpenAlex는 별도 outcome으로 관리."""
    return ["tavily", "wikipedia"] if use_web(level) else []


def gen_params(level: str) -> Dict[str, Any]:
    """수준별 생성 파라미터(서비스가 stage params에 덮어쓸 값)."""
    return {"max_tokens": max_tokens(level), "num_ctx": num_ctx(level)}


def directive(level: str) -> str:
    """
    프롬프트 말미에 못박는 수준별 깊이·구조·최소 글자수 지시문.
    답변 길이 차이를 '재생성 루프 없이' 프롬프트로 유도한다.
    """
    lvl = normalize(level)
    label = _KOREAN_LABEL[lvl]
    mc = min_chars(lvl)
    base = (
        f"\n\n[학습자 수준 지침 — {label}]\n"
        f"- 이 답변은 '{label}' 학습자를 위한 것이다. 설명의 깊이와 분량을 이 수준에 맞춘다.\n"
        f"- 목표 분량: 최소 {mc}자 이상(불필요하게 늘리지 말고 수준에 맞는 깊이로 채운다).\n"
        "- 학습 자료(PDF/RAG) 맥락이 주어지면 그것을 최우선 근거로 삼는다.\n"
        "- 모르는 내용을 지어내지 않는다. 외부 검색 근거가 부족하면 그 사실을 간단히 밝힌다.\n"
    )
    sections = {
        "INTRO": (
            "- 구조: ①쉬운 정의 ②일상 비유 ③간단 예시 ④한 줄 정리.\n"
            "- 전문용어는 최소화하고, 쓰면 바로 쉬운 말로 풀어 설명한다."
        ),
        "BACHELOR": (
            "- 구조: ①핵심 정의 ②작동 원리 ③예시 ④자주 틀리는 점(오개념).\n"
            "- 학부 교과서 수준의 정확한 용어와 적당한 깊이를 유지한다."
        ),
        "MASTER": (
            "- 구조: ①개념과 배경 ②원리·메커니즘 ③유사 기법과의 비교/트레이드오프 "
            "④한계와 적용 조건 ⑤실제 적용.\n"
            "- '왜 이 방법인가'에 대한 분석을 포함한다."
        ),
        "DOCTOR": (
            "- 구조: ①이론적 배경 ②수학적/논리적 구조 ③연구 흐름·쟁점 "
            "④한계·반례·경계조건 ⑤응용/확장(Future Work).\n"
            "- 핵심 주장에는 근거를 제시하고 불확실한 것은 단정하지 않는다."
        ),
        "EXPERT": (
            "- 구조: (박사 수준 분석) + ⑥실무/연구 현장 관점: 설계 판단, 트레이드오프, "
            "리스크/장애 포인트, 디버깅·모니터링 포인트, 실전 적용 전략.\n"
            "- 박사 설명을 그대로 복붙하지 말고 '무엇을 언제 선택하는가'의 의사결정 기준을 더한다."
        ),
    }
    return base + sections[lvl]


def build_metadata(
    level: str,
    answer_text: str,
    *,
    web_sources_succeeded: Optional[Set[str]] = None,
    used_openai: bool = False,
    openalex_outcome: Optional[str] = None,
    openalex_status: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    응답 metadata 생성. (재생성 루프 없음 — lengthSatisfied만 정직하게 보고)
    web_sources_succeeded: 실제 결과를 돌려준 웹 검색 소스 표준명 집합(tavily/wikipedia).
    openalex_outcome: "used" | "cache" | "skipped" | "failed" | None (DOCTOR/EXPERT에서만 의미).
    openalex_status:  metadata.openalex 블록(있으면 그대로 첨부).
    """
    lvl = normalize(level)
    succeeded = {s.lower() for s in (web_sources_succeeded or set())}
    mc = min_chars(lvl)
    actual = len(answer_text or "")

    tools_used: List[str] = [qwen_model_name()]
    tools_failed: List[str] = []
    tools_skipped: List[str] = []

    if used_openai:
        tools_used.append("openai")
    elif use_openai_review(lvl):
        # 검토하기로 했으나 못 함(미설정/장애) → 숨기지 않고 기록
        tools_failed.append("openai")

    for tool in planned_web_tools(lvl):
        if tool in succeeded:
            tools_used.append(tool)
        else:
            tools_failed.append(tool)

    # OpenAlex는 outcome 기반으로 분류 (해당 수준이 사용 대상일 때만)
    if use_openalex(lvl):
        if openalex_outcome == "used":
            tools_used.append("openalex")
        elif openalex_outcome == "cache":
            tools_used.append("openalex-cache")
        elif openalex_outcome == "skipped":
            reason = "disabled" if (openalex_status or {}).get("status") == "disabled" else "not_needed"
            tools_skipped.append(f"openalex:{reason}")
        else:  # failed 또는 미수행
            tools_failed.append("openalex")

    meta: Dict[str, Any] = {
        "knowledgeLevel": lvl,
        "minChars": mc,
        "actualChars": actual,
        "lengthSatisfied": actual >= mc,
        "toolsUsed": tools_used,
        "toolsFailed": tools_failed,
        "toolsSkipped": tools_skipped,
        "qualityChecked": bool(used_openai),
    }
    if use_openalex(lvl) and openalex_status:
        meta["openalex"] = openalex_status
    return meta
