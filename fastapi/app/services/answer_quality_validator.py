"""
Answer Quality Validator — 방 모드 계약(ModeAIConfig) 기준 답변 품질 검증기.

mode_ai_config.ModeAIConfig가 정의한 답변 계약(전문용어 풀이 / 다관점 / 예시 /
한계 / 형식 / 근거 구분 등)을 답변 문자열이 충족했는지 휴리스틱으로 검사한다.

설계 원칙:
- 기본은 LLM을 호출하지 않는 로컬 휴리스틱(빠르고 비용 0, 데모 안전).
  필요 시 AI_QUALITY_LLM_JUDGE=true로 OpenAI 보조 평가를 켤 수 있다(기본 off).
- 검증 실패해도 예외를 던지지 않는다. 항상 결과 dict를 반환한다.
- 사용자에게 내부 검증 실패 메시지를 그대로 노출하지 않는다(이 모듈은 결과만 돌려준다).

반환 구조:
    {
      "passed": bool,
      "score": float,                 # 0.0 ~ 1.0
      "missing": list[str],           # 부족 항목(사람이 읽는 라벨)
      "rewrite_required": bool,
      "rewrite_instructions": str,    # 보강 재생성 시 모델에 줄 지시
    }
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _flag(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def validation_enabled() -> bool:
    return _flag("AI_QUALITY_VALIDATION_ENABLED", True)


# 전역 임계값 (.env로 튜닝)
MIN_TERMS = _int("AI_QUALITY_MIN_TERMS", 5)
REQUIRE_EXAMPLES = _flag("AI_QUALITY_REQUIRE_EXAMPLES", True)
REQUIRE_LIMITATIONS = _flag("AI_QUALITY_REQUIRE_LIMITATIONS", True)
REQUIRE_MULTI_PERSPECTIVES = _flag("AI_QUALITY_REQUIRE_MULTIPLE_PERSPECTIVES", True)
PASS_THRESHOLD = float(os.getenv("AI_QUALITY_PASS_THRESHOLD", "0.7"))


# ── 패턴 ──────────────────────────────────────────────────────────────────────
# "캡슐화(encapsulation)" 처럼 한국어/영문 용어 + 괄호 정의
_TERM_DEF_RE = re.compile(r"[가-힣A-Za-z][^\n()]{0,18}\([A-Za-z][^)\n]{1,40}\)")
_CODE_FENCE_RE = re.compile(r"```")
_JSON_FENCE_RE = re.compile(r"```json", re.I)
_TABLE_RE = re.compile(r"\|.+\|.*\n\s*\|?\s*-{2,}", re.M)
_PERSPECTIVE_MARKERS = ("이론", "실무", "설계", "아키텍처", "비판", "관점", "반론", "재반론", "찬성", "반대")
_LIMITATION_MARKERS = ("한계", "단점", "주의", "제약", "trade-off", "트레이드오프", "리스크", "위험", "예외")
_EXAMPLE_MARKERS = ("예시", "예를 들", "예)", "e.g", "가령", "사례")
_GROUNDING_MARKERS = ("문서에 없", "자료에 없", "일반 지식", "모델 지식", "근거", "출처", "추정")
_FAIL_MARKERS = ("현재 Ollama", "Ollama 응답", "[Ollama", "[GPT", "비활성화", "OPENAI_API_KEY", "일시적인 오류")


def _has_any(text: str, markers) -> bool:
    return any(m in text for m in markers)


def _looks_failed(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 15:
        return True
    return any(m in t[:60] for m in _FAIL_MARKERS)


def validate(
    answer: str,
    mode_config: Any,
    *,
    multi_perspective: Optional[bool] = None,
    format_hint: str = "markdown",
    min_terms_override: Optional[int] = None,
) -> Dict[str, Any]:
    """
    답변을 mode 계약에 비추어 검증한다.

    Args:
        answer:        검증할 답변 본문
        mode_config:   mode_ai_config.ModeAIConfig (require_* / answer_sections 사용)
        multi_perspective: 명시적 다관점 요구 여부(없으면 mode_config 값 사용)
        format_hint:   "json" | "table" | "code" | "markdown"
        min_terms_override: 전문용어 풀이 최소 개수 강제(예: beginner 완화)
    """
    if not validation_enabled():
        return {"passed": True, "score": 1.0, "missing": [],
                "rewrite_required": False, "rewrite_instructions": ""}

    a = answer or ""
    missing: List[str] = []

    if _looks_failed(a):
        return {"passed": False, "score": 0.0,
                "missing": ["답변 생성 실패(빈 응답/에러 메시지)"],
                "rewrite_required": True,
                "rewrite_instructions": "정상적인 본문을 처음부터 다시 생성하라."}

    # 가중 채점: 충족하면 점수를 더하고, 미충족이면 missing에 사유를 남긴다.
    checks: List[tuple] = []  # (label, ok, weight, fix_hint)

    require_terms = bool(getattr(mode_config, "require_terminology_explanation", True))
    require_examples = bool(getattr(mode_config, "require_examples", True)) and REQUIRE_EXAMPLES
    require_persp = (
        multi_perspective
        if multi_perspective is not None
        else bool(getattr(mode_config, "require_multiple_perspectives", False))
    ) and REQUIRE_MULTI_PERSPECTIVES
    require_citations = bool(getattr(mode_config, "require_citations", False))

    # 1) 전문용어 뜻풀이
    if require_terms:
        min_terms = min_terms_override if min_terms_override is not None else MIN_TERMS
        term_defs = len(_TERM_DEF_RE.findall(a))
        checks.append((
            "전문용어 뜻풀이", term_defs >= max(1, min_terms), 0.22,
            f"핵심 전문용어를 '용어(영문): 한 줄 정의' 형식으로 최소 {min_terms}개 풀어라.",
        ))

    # 2) 예시
    if require_examples:
        ok_ex = _CODE_FENCE_RE.search(a) is not None or _has_any(a, _EXAMPLE_MARKERS)
        checks.append(("구체적 예시", ok_ex, 0.15, "코드/JSON/시나리오 등 구체적 예시를 추가하라."))

    # 3) 다관점 비교
    if require_persp:
        marks = sum(1 for m in _PERSPECTIVE_MARKERS if m in a)
        checks.append(("여러 관점 비교", marks >= 3, 0.18,
                       "이론/실무/설계/비판 등 관점을 각각 소제목으로 분리해 비교하라."))

    # 4) 한계/주의
    if REQUIRE_LIMITATIONS and getattr(mode_config, "mode", "") in (
        "expert", "debate", "rag", "multi_agent", "research", "code_review",
    ):
        checks.append(("한계/주의점", _has_any(a, _LIMITATION_MARKERS), 0.12,
                       "한계·주의점·트레이드오프를 명시하라."))

    # 5) 근거/출처 구분 (citations 요구 모드)
    if require_citations:
        checks.append(("근거/출처 구분", _has_any(a, _GROUNDING_MARKERS), 0.13,
                       "사용한 근거(문서/검색/모델 지식)를 구분해 밝혀라."))

    # 6) 형식 반영 (json/table/code)
    if format_hint == "json":
        checks.append(("JSON 형식 반영", _JSON_FENCE_RE.search(a) is not None, 0.10,
                       "요청한 ```json 코드블록 예시를 포함하라."))
    elif format_hint == "table":
        checks.append(("표 형식 반영", _TABLE_RE.search(a) is not None, 0.10,
                       "요청한 마크다운 표 형식으로 정리하라."))
    elif format_hint == "code":
        checks.append(("코드 형식 반영", _CODE_FENCE_RE.search(a) is not None, 0.10,
                       "요청한 코드 예시를 코드블록으로 포함하라."))

    # 7) 답변 구조(섹션) 반영
    sections = getattr(mode_config, "answer_sections", None) or []
    if sections:
        hit = sum(1 for s in sections if _section_hit(a, s))
        need = max(2, int(len(sections) * 0.4))
        checks.append((
            "답변 구조(섹션)", hit >= need, 0.12,
            f"요구한 섹션 구조를 더 반영하라: {', '.join(sections)}",
        ))

    # 8) 분량(너무 얕음 방지)
    floor = _int("AI_QUALITY_MIN_CHARS", 350)
    checks.append(("충분한 깊이/분량", len(a) >= floor, 0.08,
                   "설명이 짧고 추상적이다. 더 깊고 구체적으로 확장하라."))

    # 채점
    total_w = sum(w for _, _, w, _ in checks) or 1.0
    got_w = sum(w for _, ok, w, _ in checks if ok)
    score = round(got_w / total_w, 3)

    fixes: List[str] = []
    for label, ok, _w, hint in checks:
        if not ok:
            missing.append(label)
            fixes.append(hint)

    passed = score >= PASS_THRESHOLD
    rewrite_required = not passed

    return {
        "passed": passed,
        "score": score,
        "missing": missing,
        "rewrite_required": rewrite_required,
        "rewrite_instructions": (" ".join(fixes)).strip(),
    }


def _section_hit(answer: str, section_title: str) -> bool:
    """섹션 제목 또는 핵심 키워드가 답변에 나타나는지(느슨하게) 확인한다."""
    title = (section_title or "").strip()
    if not title:
        return False
    if title in answer:
        return True
    # 제목의 첫 핵심 토큰(공백/슬래시 분리)이라도 포함되면 부분 인정
    head = re.split(r"[\s/()]", title)[0]
    return bool(head) and head in answer
