"""
자료보관함 요약 품질 강화 빌더 (구조화 JSON + 마크다운 제거 + 분량 강제).

목표:
  - "핵심 내용(core_contents)"을 최소 10개, "세부 핵심 내용(detailed_core_contents)"을
    최소 40개로 보장하고, 각 항목을 문서 기반으로 구체적으로 확장한다.
  - 마크다운 기호(**, ###, -, *, ``` 등)와 HTML 태그가 UI에 노출되지 않도록 모든
    사용자 표시 필드를 sanitize_markdown_text로 정제한다.
  - LLM 응답이 분량/형식을 못 맞추면 (1) OpenAI refiner → (2) Ollama → (3) deterministic
    fallback 순으로 보강해 항상 10개/40개 구조를 만든다.

이 모듈은 기존 멀티에이전트/그룹스터디 SSE와 무관한 "자료보관함 전용" 경로이며,
기존 summarize_document(material_ai_manager)는 건드리지 않는다.
"""
import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional

from app.services.material_ai_manager import (
    _call_gpt,
    _extract_json,
    _keywords_from_text,
    _sentences_from_text,
    sanitize_keywords,
    validate_extracted_text,
)

logger = logging.getLogger(__name__)

MIN_CORE = int(os.getenv("AI_SUMMARY_MIN_CORE", "10"))
MIN_DETAIL = int(os.getenv("AI_SUMMARY_MIN_DETAIL", "40"))
MIN_KEYWORDS = int(os.getenv("AI_SUMMARY_MIN_KEYWORDS", "5"))
MIN_OVERVIEW_CHARS = int(os.getenv("AI_SUMMARY_MIN_OVERVIEW", "500"))

AI_ENABLE_GPT_FALLBACK = os.getenv("AI_ENABLE_GPT_FALLBACK", "true").lower() in ("true", "1", "yes")

ProgressCb = Optional[Callable[[str, int], None]]


# ── 마크다운/HTML 제거 ────────────────────────────────────────────────────────

_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_HTML_TAG = re.compile(r"<[^>]+>")


def sanitize_markdown_text(text: Any) -> str:
    """
    마크다운/HTML 기호를 제거해 UI에 그대로 노출되지 않는 일반 문장으로 만든다.

    제거 대상: ```코드펜스```, `인라인코드`, ### 헤더, **강조**/*기울임*/__/_,
    줄머리 불릿(- * +), 번호목록, 인용(>), [텍스트](URL) 링크, HTML 태그.
    검증식(validate)에서 금지하는 '**', '###', '```'는 결과에 절대 남지 않는다.
    """
    if text is None:
        return ""
    s = str(text)
    s = s.replace("\r\n", "\n").replace("\r", "\n")

    # 코드 펜스/인라인 코드 (백틱) 제거 — 내부 텍스트는 살린다
    s = re.sub(r"```[a-zA-Z0-9]*\n?", "", s)
    s = s.replace("`", "")

    # 줄머리 헤더/인용/불릿/번호 마커 제거
    s = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", s)
    s = re.sub(r"(?m)^\s{0,3}>\s?", "", s)
    s = re.sub(r"(?m)^\s{0,3}[-*+]\s+", "", s)
    s = re.sub(r"(?m)^\s{0,3}\d+[.)]\s+", "", s)

    # 강조/기울임/취소선
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)
    s = re.sub(r"__([^_]+)__", r"\1", s)
    s = re.sub(r"~~([^~]+)~~", r"\1", s)

    # 마크다운 링크 → "텍스트 (URL)"
    s = _MD_LINK.sub(r"\1 (\2)", s)

    # HTML 태그 제거
    s = _HTML_TAG.sub("", s)

    # 잔여 마크다운 기호 강제 제거 (검증 통과 보장)
    s = s.replace("*", "")
    s = re.sub(r"#{2,}", "", s)

    # 공백 정리
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _sanitize_list(values: Any) -> List[str]:
    out: List[str] = []
    for v in values or []:
        t = sanitize_markdown_text(v)
        if t:
            out.append(t)
    return out


def _count_sentences(text: str) -> int:
    parts = re.split(r"(?<=[.!?。！？])\s+", (text or "").strip())
    return len([p for p in parts if p.strip()])


def _ensure_sentences(content: str, topic: str, min_sentences: int = 2) -> str:
    """content가 최소 문장 수를 만족하도록 문서 기반 보조 문장을 덧붙인다."""
    content = sanitize_markdown_text(content).strip()
    fillers = [
        f"이 항목은 문서 내용을 기준으로 정리한 학습 포인트다.",
        f"{topic}을(를) 다른 개념과 연결해 이해하면 전체 흐름 파악에 도움이 된다.",
        f"문서에 제시된 맥락에서 {topic}의 역할과 활용 방식을 함께 확인하는 것이 좋다.",
    ]
    i = 0
    while _count_sentences(content) < min_sentences and i < len(fillers):
        sep = " " if content and not content.endswith((".", "。", "!", "?")) else " "
        add = fillers[i]
        if add not in content:
            content = (content + sep + add).strip() if content else add
        i += 1
    if not content:
        content = f"{topic}에 대한 문서 기반 설명이다. " + fillers[0]
    return content


# ── 프롬프트 ──────────────────────────────────────────────────────────────────

def _build_prompt(document_title: str, text: str) -> tuple[str, str]:
    system = (
        "너는 학술/기술 문서 분석 전문가다. 제공된 문서 내용에 근거해서만 한국어로 정리한다. "
        "문서에 없는 사실을 지어내지 말고, 문서에서 추론 가능한 범위로만 확장한다. "
        "마크다운 기호(**, ###, -, *, ```)나 HTML 태그를 절대 쓰지 말고, 모든 값은 일반 문장으로 작성한다. "
        "반드시 아래 스키마의 JSON 객체 '하나만' 출력한다(설명문/코드블록 금지)."
    )
    schema = (
        '{'
        '"title":"문서 제목",'
        '"overview":"문서 전체 개요를 최소 500자 이상 구체적으로",'
        '"core_contents":[{"title":"핵심 내용 제목","content":"두 문장 이상 설명"}],'
        '"detailed_core_contents":[{"line_no":1,"title":"세부 항목 제목","content":"한두 문장 설명"}],'
        '"keywords":[{"keyword":"용어","importance":"문서 안에서 왜 중요한지","definition_preview":"한 줄 정의"}],'
        '"study_points":["학습 포인트 문장"],'
        '"practice_points":["실습 관점 문장"],'
        '"study_questions":["문서 기반 학습 질문"]'
        '}'
    )
    user = (
        f"## 문서 제목\n{document_title}\n\n"
        f"## 문서 내용 (최대 6000자)\n{(text or '')[:6000]}\n\n"
        "위 문서를 분석해 다음 JSON 스키마로만 출력하라:\n"
        f"{schema}\n\n"
        "분량 규칙:\n"
        f"- core_contents는 최소 {MIN_CORE}개. 각 content는 두 문장 이상.\n"
        f"- detailed_core_contents는 최소 {MIN_DETAIL}개. line_no는 1부터 순서대로. 각 content는 한두 문장 이상.\n"
        "- 문서의 API/설정/코드 흐름/라이브러리/실습 절차/오류 가능성/학습 포인트를 세분화한다.\n"
        "- URL만 한 줄로 넣지 말고 그 URL이 어떤 역할인지 설명한다.\n"
        "- 같은 문장을 반복하지 않는다."
    )
    return system, user


def _parse_llm_json(raw: str) -> Optional[Dict[str, Any]]:
    parsed = _extract_json(raw)
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):  # 모델이 배열만 준 경우
        return {"detailed_core_contents": parsed}
    return None


# ── deterministic 보강 ────────────────────────────────────────────────────────

def _fact_pool(text: str) -> List[str]:
    """문서에서 의미 있는 문장 후보를 넓게 모은다 (중복 제거)."""
    facts: List[str] = []
    seen = set()
    candidates = re.split(r"(?<=[.!?。！？])\s+|\n+", text or "")
    for s in candidates:
        s = re.sub(r"\s+", " ", s).strip(" -•*\t")
        s = sanitize_markdown_text(s)
        if len(s) < 20:
            continue
        key = s[:40]
        if key in seen:
            continue
        seen.add(key)
        facts.append(s)
    return facts


def _pad_core(core: List[Dict[str, str]], facts: List[str], keywords: List[str],
              need: int) -> tuple[List[Dict[str, str]], bool]:
    """core_contents를 need개까지 문서 기반으로 채운다. padding 발생 여부 반환."""
    out: List[Dict[str, str]] = []
    seen_titles = set()
    for item in core:
        title = sanitize_markdown_text(item.get("title")) or "핵심 내용"
        content = _ensure_sentences(item.get("content") or item.get("description") or title, title, 2)
        tkey = title[:30]
        if tkey in seen_titles:
            continue
        seen_titles.add(tkey)
        out.append({"title": title, "content": content})

    padded = False
    idx = 0
    # 키워드 기반 핵심 내용 보강 (관련 문장 endorse)
    while len(out) < need and idx < len(keywords):
        kw = keywords[idx]
        idx += 1
        if kw[:30] in seen_titles:
            continue
        related = [f for f in facts if kw in f][:2]
        content = " ".join(related) if related else f"{kw}은(는) 문서에서 다루는 핵심 개념이다."
        out.append({"title": kw, "content": _ensure_sentences(content, kw, 2)})
        seen_titles.add(kw[:30])
        padded = True

    # 문장 묶음 기반 보강
    fi = 0
    n = 1
    while len(out) < need and fi < len(facts):
        chunk = facts[fi:fi + 2]
        fi += 2
        if not chunk:
            break
        content = _ensure_sentences(" ".join(chunk), "문서 핵심", 2)
        out.append({"title": f"핵심 내용 {len(out) + 1}", "content": content})
        padded = True
        n += 1

    # 그래도 부족하면 일반 학습 항목으로 채움
    base = keywords or ["핵심 개념"]
    while len(out) < need:
        kw = base[len(out) % len(base)]
        out.append({
            "title": f"핵심 내용 {len(out) + 1}: {kw}",
            "content": _ensure_sentences(f"{kw}을(를) 중심으로 문서의 핵심 흐름을 정리한다.", kw, 2),
        })
        padded = True
    return out[:max(need, len(out))], padded


def _pad_detail(detail: List[Dict[str, Any]], facts: List[str], keywords: List[str],
                need: int) -> tuple[List[Dict[str, Any]], bool]:
    """detailed_core_contents를 need개까지 문서 기반으로 채우고 line_no를 재부여한다."""
    out: List[Dict[str, Any]] = []
    seen = set()

    def _push(title: str, content: str) -> None:
        title = sanitize_markdown_text(title) or "세부 핵심 내용"
        content = _ensure_sentences(content, title, 1)
        key = content[:40]
        if key in seen:
            return
        seen.add(key)
        out.append({"line_no": len(out) + 1, "title": title, "content": content})

    for item in detail:
        if isinstance(item, dict):
            _push(item.get("title") or "세부 핵심 내용",
                  item.get("content") or item.get("description") or item.get("title") or "")
        elif isinstance(item, str):
            _push("세부 핵심 내용", item)

    padded = False
    # 문장 단위 세분화
    for f in facts:
        if len(out) >= need:
            break
        _push("문서 세부 내용", f)
        padded = True

    # 키워드 기반 세부 항목
    for kw in keywords:
        if len(out) >= need:
            break
        related = [f for f in facts if kw in f][:1]
        content = related[0] if related else f"{kw}은(는) 문서에서 언급되는 요소로, 그 의미와 사용 맥락을 확인하면 학습에 도움이 된다."
        _push(kw, content)
        padded = True

    # 그래도 부족하면 학습 관점 세부 항목 생성
    aspects = [
        "개념 정의", "구성 요소", "처리 흐름", "설정/의존성", "사용 예시",
        "오류 가능성", "주의할 점", "학습 포인트", "실습 절차", "복습 관점",
    ]
    base = keywords or ["핵심 개념"]
    ai = 0
    while len(out) < need:
        kw = base[ai % len(base)]
        aspect = aspects[ai % len(aspects)]
        ai += 1
        _push(f"{kw} - {aspect}",
              f"{kw}의 {aspect}을(를) 문서 내용을 기준으로 정리한다.")
        padded = True
    return out, padded


def _pad_overview(overview: str, facts: List[str], keywords: List[str]) -> tuple[str, bool]:
    overview = sanitize_markdown_text(overview)
    padded = False
    fi = 0
    while len(overview) < MIN_OVERVIEW_CHARS and fi < len(facts):
        add = facts[fi]
        fi += 1
        if add not in overview:
            overview = (overview + " " + add).strip()
            padded = True
    if len(overview) < MIN_OVERVIEW_CHARS:
        kw_line = ", ".join(keywords[:10]) if keywords else "핵심 개념"
        overview = (overview + " " + (
            f"이 문서는 {kw_line} 등을 중심으로 구성되어 있으며, 학습자는 이를 통해 핵심 개념과 "
            "실제 활용 방법을 단계적으로 이해할 수 있다. 문서의 흐름을 따라가며 주요 용어를 정리하고 "
            "예시와 실습을 함께 확인하면 전체 구조를 효과적으로 파악할 수 있다.")).strip()
        padded = True
    # 여전히 짧으면 키워드별 설명 문장을 덧붙여 최소 분량을 채운다
    base = keywords or ["핵심 개념"]
    ki = 0
    while len(overview) < MIN_OVERVIEW_CHARS:
        kw = base[ki % len(base)]
        ki += 1
        overview = (overview + " " + (
            f"또한 {kw}와(과) 관련된 내용을 문서 맥락에서 함께 살펴보면 전체 구조를 더 깊이 이해할 수 있다.")).strip()
        padded = True
        if ki > len(base) * 4:  # 안전장치
            break
    return overview, padded


def _build_keywords(kw_objs: List[Any], kw_strings: List[str], source_provider: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()
    for k in kw_objs or []:
        if isinstance(k, dict):
            term = sanitize_markdown_text(k.get("keyword") or k.get("term") or k.get("name"))
            if not term or term.lower() in seen:
                continue
            seen.add(term.lower())
            out.append({
                "keyword": term,
                "importance": sanitize_markdown_text(k.get("importance")) or f"{term}은(는) 문서의 핵심 개념 중 하나다.",
                "definition_preview": sanitize_markdown_text(k.get("definition_preview") or k.get("definition")) or f"{term}에 대한 문서 기반 한 줄 정의.",
                "source_hint": k.get("source_hint") or source_provider,
            })
    for term in kw_strings or []:
        term = sanitize_markdown_text(term)
        if not term or term.lower() in seen:
            continue
        seen.add(term.lower())
        out.append({
            "keyword": term,
            "importance": f"{term}은(는) 문서에서 반복적으로 등장하는 핵심 용어다.",
            "definition_preview": f"{term}에 대한 문서 기반 한 줄 정의.",
            "source_hint": "mixed",
        })
    return out


def _build_detailed_sections(result: Dict[str, Any]) -> List[Dict[str, str]]:
    """기존 EC2 호환용 detailed_sections (마크다운 없는 자연어 묶음)."""
    core_text = " ".join(
        f"{c['title']}: {c['content']}" for c in result["core_contents"]
    )
    detail_text = " ".join(
        f"{d['line_no']}) {d['title']}: {d['content']}" for d in result["detailed_core_contents"]
    )
    study_text = " ".join(result["study_points"]) or "문서 학습 포인트를 정리한다."
    practice_text = " ".join(result["practice_points"]) or "문서의 실습 관점을 정리한다."
    return [
        {"heading": "문서 개요", "content": sanitize_markdown_text(result["overview"])},
        {"heading": "핵심 내용", "content": sanitize_markdown_text(core_text)},
        {"heading": "세부 핵심 내용", "content": sanitize_markdown_text(detail_text)},
        {"heading": "학습 포인트", "content": sanitize_markdown_text(study_text)},
        {"heading": "실습 관점 정리", "content": sanitize_markdown_text(practice_text)},
    ]


# ── 검증 ──────────────────────────────────────────────────────────────────────

def validate_summary_quality(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    응답 직전 분량/마크다운/빈값 검증.
    Returns: {"ok": bool, "errors": [str]}
    """
    errors: List[str] = []
    core = response.get("core_contents") or []
    detail = response.get("detailed_core_contents") or []
    keywords = response.get("keywords") or []

    if len(core) < MIN_CORE:
        errors.append(f"core_contents가 {MIN_CORE}개 미만 ({len(core)})")
    if len(detail) < MIN_DETAIL:
        errors.append(f"detailed_core_contents가 {MIN_DETAIL}개 미만 ({len(detail)})")
    if len(keywords) < MIN_KEYWORDS:
        errors.append(f"keywords가 {MIN_KEYWORDS}개 미만 ({len(keywords)})")

    for i, c in enumerate(core):
        if not (c.get("content") or "").strip():
            errors.append(f"core_contents[{i}] content 비어있음")
    for i, d in enumerate(detail):
        if not (d.get("content") or "").strip():
            errors.append(f"detailed_core_contents[{i}] content 비어있음")

    blob = json.dumps(response, ensure_ascii=False)
    if "**" in blob:
        errors.append("마크다운 강조(**) 잔존")
    if "###" in blob:
        errors.append("마크다운 헤더(###) 잔존")
    if "```" in blob:
        errors.append("코드펜스(```) 잔존")

    return {"ok": not errors, "errors": errors}


# ── 메인 빌더 ─────────────────────────────────────────────────────────────────

def _llm_attempt(document_title: str, text: str, use_gpt: bool) -> tuple[Optional[Dict[str, Any]], str]:
    """1회 LLM 호출 후 JSON 파싱. (parsed_or_none, provider)"""
    system, user = _build_prompt(document_title, text)
    provider = "ollama_qwen"
    raw = ""
    if not use_gpt:
        try:
            from app.services.llm_engine_router import call_primary_llm
            raw = call_primary_llm(system_prompt=system, user_prompt=user, max_tokens=4096, temperature=0.35)
            if not raw or raw.strip().startswith("["):
                raise RuntimeError(f"primary LLM 실패: {raw[:60] if raw else 'empty'}")
        except Exception as e:
            logger.warning("구조화 요약 primary LLM 실패: %s", e)
            raw = ""
    if not raw and (use_gpt or AI_ENABLE_GPT_FALLBACK):
        raw = _call_gpt(system, user, max_tokens=4096)
        provider = "openai_gpt"
    if raw and raw.strip().startswith("["):
        raw = ""
    return _parse_llm_json(raw), provider


def build_structured_summary(
    document_title: str,
    text: str,
    progress_cb: ProgressCb = None,
) -> Dict[str, Any]:
    """
    문서 텍스트를 구조화 요약 JSON으로 변환한다.
    분량(core 10+/detail 40+/overview 500+)과 마크다운 제거를 보장한다.

    Returns 구조화 dict (사용자 표시 필드는 모두 sanitize 적용 완료).
    """
    def _report(stage: str, pct: int) -> None:
        if progress_cb:
            try:
                progress_cb(stage, pct)
            except Exception:
                pass

    text = text or ""
    ts = validate_extracted_text(text)
    short_doc = ts["status"] != "ok"

    facts = _fact_pool(text)
    kw_strings = _keywords_from_text(text, limit=30)

    _report("summarizing", 20)
    parsed, provider = _llm_attempt(document_title, text, use_gpt=False)

    # 2차: 분량이 크게 부족하면 GPT refiner로 보강 시도
    used_fallback = False
    needs_refine = (parsed is None
                    or len(parsed.get("core_contents") or []) < MIN_CORE
                    or len(parsed.get("detailed_core_contents") or []) < MIN_DETAIL)
    if needs_refine and AI_ENABLE_GPT_FALLBACK:
        _report("summarizing", 45)
        refined, rprovider = _llm_attempt(document_title, text, use_gpt=True)
        if refined is not None:
            # 더 풍부한 쪽을 채택 (병합)
            if parsed is None:
                parsed, provider = refined, rprovider
            else:
                if len(refined.get("core_contents") or []) > len(parsed.get("core_contents") or []):
                    parsed["core_contents"] = refined.get("core_contents")
                if len(refined.get("detailed_core_contents") or []) > len(parsed.get("detailed_core_contents") or []):
                    parsed["detailed_core_contents"] = refined.get("detailed_core_contents")
                if not parsed.get("overview") and refined.get("overview"):
                    parsed["overview"] = refined.get("overview")
            provider = f"{provider}+{rprovider}"

    parsed = parsed or {}

    _report("keywords", 70)
    title = sanitize_markdown_text(parsed.get("title")) or (document_title or "문서").strip()
    overview, ov_pad = _pad_overview(parsed.get("overview") or "", facts, kw_strings)

    core_raw = parsed.get("core_contents") if isinstance(parsed.get("core_contents"), list) else []
    detail_raw = parsed.get("detailed_core_contents") if isinstance(parsed.get("detailed_core_contents"), list) else []

    core, core_pad = _pad_core(core_raw, facts, kw_strings, MIN_CORE)
    detail, detail_pad = _pad_detail(detail_raw, facts, kw_strings, MIN_DETAIL)
    if core_pad or detail_pad or ov_pad:
        used_fallback = used_fallback or (not core_raw or not detail_raw)

    keywords = _build_keywords(
        parsed.get("keywords") if isinstance(parsed.get("keywords"), list) else [],
        kw_strings, provider.split("+")[0],
    )
    if len(keywords) < MIN_KEYWORDS:
        keywords = _build_keywords([], sanitize_keywords(kw_strings, limit=15) or ["핵심 개념", "문서 구조", "학습", "실습", "복습"], "mixed")

    study_points = _sanitize_list(parsed.get("study_points")) or [
        sanitize_markdown_text(c["title"]) + " 관련 내용을 시험/복습 관점에서 정리한다." for c in core[:5]
    ]
    practice_points = _sanitize_list(parsed.get("practice_points")) or [
        f"{kw} 관련 설정/사용 흐름을 직접 실습하며 확인한다." for kw in kw_strings[:5]
    ] or ["문서에 제시된 절차를 직접 따라 하며 결과를 확인한다."]
    study_questions = _sanitize_list(parsed.get("study_questions")) or [
        f"{kw}은(는) 문서에서 어떤 역할을 하는가?" for kw in kw_strings[:5]
    ] or ["이 문서의 핵심 주제는 무엇인가?"]

    assumption_notice = None
    if short_doc or used_fallback:
        assumption_notice = (
            "원문 분량이 충분하지 않아 일부 항목은 문서에서 추론 가능한 범위로 확장했습니다."
            if short_doc else
            "AI 생성 분량이 부족해 일부 항목은 문서 기반 보강 규칙으로 채웠습니다."
        )

    result: Dict[str, Any] = {
        "title": title,
        "overview": overview,
        "core_contents": core,
        "detailed_core_contents": detail,
        "keywords": keywords,
        "study_points": study_points,
        "practice_points": practice_points,
        "study_questions": study_questions,
        "assumption_notice": assumption_notice,
        "error_code": None,
        "warning": None,
        "provider": provider,
        "usedFallback": used_fallback,
    }
    result["detailed_sections"] = _build_detailed_sections(result)

    # 최종 검증 — 실패 시 deterministic으로 한 번 더 강제
    check = validate_summary_quality(result)
    if not check["ok"]:
        logger.warning("요약 검증 실패 → deterministic 보강: %s", check["errors"])
        result["core_contents"], _ = _pad_core(result["core_contents"], facts, kw_strings, MIN_CORE)
        result["detailed_core_contents"], _ = _pad_detail(result["detailed_core_contents"], facts, kw_strings, MIN_DETAIL)
        # 모든 표시 필드 재-sanitize
        result["overview"] = sanitize_markdown_text(result["overview"])
        for c in result["core_contents"]:
            c["title"] = sanitize_markdown_text(c["title"])
            c["content"] = sanitize_markdown_text(c["content"])
        for d in result["detailed_core_contents"]:
            d["title"] = sanitize_markdown_text(d["title"])
            d["content"] = sanitize_markdown_text(d["content"])
        result["detailed_sections"] = _build_detailed_sections(result)
        result["warning"] = "검증 기준을 맞추기 위해 문서 기반 fallback으로 보강했습니다."
        recheck = validate_summary_quality(result)
        if not recheck["ok"]:
            result["warning"] = "; ".join(recheck["errors"])

    _report("done", 100)
    return result
