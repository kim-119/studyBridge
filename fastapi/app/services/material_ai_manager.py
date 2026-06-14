"""
자료보관함 AI 매니저 (GPT 70% + Qwen 30% 혼합 구조).
PDF 요약, 문서 분석, 퀴즈 생성, 로드맵 생성, RAG Q&A를 처리한다.

혼합 전략:
  GPT:  구조적 분석, 정확성, 퀴즈/로드맵/요약 본문 생성 (70%)
  Qwen: 에이전트 말투/성격 반영, 사용자 친화적 표현 보정 (30%)
"""
import logging
import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from app.core.config import OPENAI_API_KEY
from app.services.qwen_service import ask_qwen

logger = logging.getLogger(__name__)

_sync_client = None

# 모델 라우팅 / 검증 토글 (환경변수)
OLLAMA_SUMMARY_MODEL = os.getenv("OLLAMA_SUMMARY_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5:14b"))
AI_ENABLE_GPT_FALLBACK = os.getenv("AI_ENABLE_GPT_FALLBACK", "true").lower() in ("true", "1", "yes")
AI_ENABLE_RESULT_VALIDATION = os.getenv("AI_ENABLE_RESULT_VALIDATION", "true").lower() in ("true", "1", "yes")

# PDF 텍스트 추출 검증 기준 (자)
_TEXT_MIN_OK = 300       # 이상이면 정상 처리 가능
_TEXT_MIN_WARN = 1       # 1~299자는 부족(warning)

# 키워드/요약에 절대 남으면 안 되는 임시·무의미 값
_JUNK_KEYWORDS = {
    "ㅇㅇ", "ㅎㅎ", "ㅋㅋ", "테스트", "test", "asdf", "abc",
    "null", "undefined", "none", "n/a", "na", "...", "-",
}


# ── 검증 함수 (빠른 rule-based) ──────────────────────────────────────────────

def validate_extracted_text(text: Optional[str]) -> Dict[str, Any]:
    """
    AI 처리 전 PDF 추출 텍스트 상태를 검증한다.
    Returns: {ok, status, textLength, warnings, errorCode}
      status: empty | too_short | ok
    """
    t = (text or "").strip()
    length = len(t)
    if length == 0:
        return {
            "ok": False, "status": "empty", "textLength": 0, "warnings": [],
            "errorCode": "PDF_TEXT_EMPTY",
        }
    if length < _TEXT_MIN_OK:
        # 짧아도 완전 차단하지 않고 warning으로 진행 가능
        return {
            "ok": True, "status": "too_short", "textLength": length,
            "warnings": ["추출된 텍스트가 매우 짧습니다. 결과 품질이 낮을 수 있습니다."],
            "errorCode": None,
        }
    return {"ok": True, "status": "ok", "textLength": length, "warnings": [], "errorCode": None}


def _sentences_from_text(text: str, limit: int = 8) -> List[str]:
    candidates = re.split(r"(?<=[.!?。])\s+|\n+", text or "")
    cleaned: List[str] = []
    for sentence in candidates:
        sentence = re.sub(r"\s+", " ", sentence).strip(" -\t")
        if len(sentence) >= 25:
            cleaned.append(sentence)
        if len(cleaned) >= limit:
            break
    return cleaned


def _keywords_from_text(text: str, limit: int = 15) -> List[str]:
    tokens = re.findall(r"[가-힣A-Za-z][가-힣A-Za-z0-9+_.#-]{1,}", text or "")
    stop = {"그리고", "그러나", "입니다", "합니다", "위해", "대한", "있는", "없는", "사용", "문서", "내용", "학습"}
    scored: Dict[str, int] = {}
    for token in tokens:
        token = token.strip("._-#")
        if len(token) <= 1 or token.lower() in _JUNK_KEYWORDS or token in stop:
            continue
        scored[token] = scored.get(token, 0) + 1
    ranked = sorted(scored, key=lambda k: (-scored[k], len(k), k))
    # PDF 메타데이터(날짜/연도/페이지/교수명/반복문구)는 키워드로 승격 금지
    from app.utils.pdf_noise_filter import detect_repeated_lines, filter_keywords
    repeated = detect_repeated_lines([text or ""])
    ranked = filter_keywords(ranked, repeated=repeated)
    return sanitize_keywords(ranked, limit=limit)


def validate_summary_result(result: Dict[str, Any], source_text: str = "") -> Dict[str, Any]:
    """요약 결과 구조/키워드/길이 검증. 부족한 섹션은 문서 텍스트 기반으로 보정한다."""
    warnings = list(result.get("warnings") or [])
    overview = (result.get("overview") or "").strip()
    keywords = result.get("keywords") if isinstance(result.get("keywords"), list) else []
    sections = result.get("sections") if isinstance(result.get("sections"), list) else []

    source_sentences = _sentences_from_text(source_text, limit=10)
    if not overview or len(overview) < 120:
        fallback = " ".join(source_sentences[:6]).strip()
        if fallback:
            overview = fallback
            warnings.append("문서 개요가 짧아 원문 핵심 문장으로 보정했습니다.")

    keywords = sanitize_keywords(keywords, limit=15)
    if len(keywords) < 8:
        merged = keywords + [kw for kw in _keywords_from_text(source_text, limit=15) if kw not in keywords]
        keywords = sanitize_keywords(merged, limit=15)
        warnings.append("핵심 키워드 수가 부족해 원문 키워드로 보정했습니다.")

    normalized_sections: List[Dict[str, str]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "세부 핵심 내용").strip()
        content = str(section.get("content") or section.get("description") or "").strip()
        if title and content:
            normalized_sections.append({"title": title, "content": content, "description": content})

    if len(normalized_sections) < 5:
        for idx, sentence in enumerate(source_sentences[:5], start=1):
            normalized_sections.append({
                "title": f"핵심 내용 {idx}",
                "content": sentence,
                "description": sentence,
            })
        warnings.append("세부 핵심 내용이 부족해 원문 기반 항목을 보강했습니다.")

    result["overview"] = overview
    result["keywords"] = keywords
    result["sections"] = normalized_sections[:8]
    result["warnings"] = warnings
    return result


ROADMAP_FIXED_WEEKS = 12


def _listify(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        return [line.strip(" -\t") for line in value.splitlines() if line.strip(" -\t")]
    return []


def _text_from_any(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("title", "content", "description", "task", "name", "text"):
            if value.get(key):
                return str(value.get(key)).strip()
        return " ".join(str(v).strip() for v in value.values() if v)
    return str(value).strip()


def _fallback_roadmap_weeks(source_text: str) -> List[Dict[str, Any]]:
    keywords = _keywords_from_text(source_text, limit=12) or ["핵심 개념", "문서 구조", "실습", "복습"]
    phases = [
        "문서 개요와 학습 범위 파악", "핵심 용어와 배경 지식 정리", "주요 구성 요소 분석", "기본 사용 흐름 실습",
        "세부 개념 심화", "예제 기반 적용", "오류 사례와 주의점 점검", "응용 과제 수행",
        "전체 구조 재정리", "실전 문제 해결", "개인 프로젝트 적용", "최종 복습과 자기점검",
    ]
    weeks: List[Dict[str, Any]] = []
    for i in range(ROADMAP_FIXED_WEEKS):
        concept = keywords[i % len(keywords)]
        weeks.append({
            "weekNumber": i + 1,
            "title": f"{i + 1}주차: {phases[i]}",
            "goal": f"{concept}을 중심으로 {phases[i]}을 수행한다.",
            "keyConcepts": [concept] + keywords[:3],
            "tasks": [
                f"문서에서 {concept} 관련 내용을 찾아 요약하기",
                f"{phases[i]}에 맞는 예제나 체크리스트 작성하기",
                "이해가 부족한 항목을 질문 목록으로 정리하기",
            ],
            "deliverable": "요약 노트 1개와 자기점검 체크리스트",
            "estimatedHours": 3,
        })
    return weeks


def validate_roadmap_result(result: Dict[str, Any], source_text: str = "") -> Dict[str, Any]:
    """로드맵 결과를 Spring/React가 저장 가능한 12주 구조로 보정한다."""
    warnings = list(result.get("warnings") or [])
    weeks = result.get("weeks") if isinstance(result.get("weeks"), list) else []
    cleaned: List[Dict[str, Any]] = []

    for idx, wk in enumerate(weeks):
        if not isinstance(wk, dict):
            continue
        tasks = []
        for key in ("tasks", "taskList", "activities", "todos", "assignments", "checkpoints"):
            tasks.extend(_listify(wk.get(key)))
        normalized_tasks = [_text_from_any(t) for t in tasks]
        normalized_tasks = [t for t in normalized_tasks if t]
        title = _text_from_any(wk.get("title") or wk.get("name") or wk.get("weekTitle"))
        goal = _text_from_any(wk.get("goal") or wk.get("objective") or wk.get("learningGoal") or wk.get("description"))
        key_concepts = [_text_from_any(v) for v in _listify(wk.get("keyConcepts") or wk.get("coreConcepts") or wk.get("concepts"))]
        deliverable = _text_from_any(wk.get("deliverable") or wk.get("output") or wk.get("selfCheck") or wk.get("checklist"))
        if title or goal or normalized_tasks:
            cleaned.append({
                "weekNumber": wk.get("weekNumber") or wk.get("week") or wk.get("stepOrder") or (idx + 1),
                "title": title,
                "goal": goal,
                "keyConcepts": [c for c in key_concepts if c],
                "tasks": normalized_tasks,
                "deliverable": deliverable,
                "estimatedHours": wk.get("estimatedHours") or wk.get("hours") or wk.get("studyHours") or 3,
            })

    if not cleaned:
        cleaned = _fallback_roadmap_weeks(source_text)
        warnings.append("로드맵 주차 정보가 없어 원문 기반 기본 로드맵으로 보정했습니다.")

    if len(cleaned) > ROADMAP_FIXED_WEEKS:
        cleaned = cleaned[:ROADMAP_FIXED_WEEKS]
        warnings.append("로드맵이 12주를 초과하여 12주로 정규화되었습니다.")
    elif len(cleaned) < ROADMAP_FIXED_WEEKS:
        fallback = _fallback_roadmap_weeks(source_text)
        warnings.append("로드맵 주차가 12주 미만이라 부족한 주차를 보정했습니다.")
        cleaned.extend(fallback[len(cleaned):ROADMAP_FIXED_WEEKS])

    fallback = _fallback_roadmap_weeks(source_text)
    for i, wk in enumerate(cleaned):
        fb = fallback[i]
        wk["weekNumber"] = i + 1
        wk["title"] = _text_from_any(wk.get("title")) or fb["title"]
        wk["goal"] = _text_from_any(wk.get("goal")) or fb["goal"]
        concepts = [_text_from_any(v) for v in _listify(wk.get("keyConcepts"))]
        wk["keyConcepts"] = [c for c in concepts if c] or fb["keyConcepts"]
        tasks = [_text_from_any(t) for t in _listify(wk.get("tasks"))]
        tasks = [t for t in tasks if t]
        while len(tasks) < 2:
            tasks.append(fb["tasks"][len(tasks) % len(fb["tasks"])])
        wk["tasks"] = tasks
        wk["deliverable"] = _text_from_any(wk.get("deliverable")) or fb["deliverable"]
        try:
            hours = int(wk.get("estimatedHours") or 3)
        except (TypeError, ValueError):
            hours = 3
        wk["estimatedHours"] = max(hours, 1)

    result["weeks"] = cleaned
    result["totalWeeks"] = ROADMAP_FIXED_WEEKS

    # PDF 메타데이터(날짜/연도/교수명/표지/footer) 최종 정제 — 학습 주제 오염 차단
    from app.utils.pdf_noise_filter import (
        detect_repeated_lines, find_noise_violations, sanitize_text_fields,
    )
    repeated = detect_repeated_lines([source_text or ""])
    fb_title = _text_from_any(result.get("title")) or (
        (_keywords_from_text(source_text, limit=1) or ["학습 주제"])[0]
    )
    before = find_noise_violations(result["weeks"], repeated=repeated)
    result["weeks"] = sanitize_text_fields(result["weeks"], repeated=repeated, title=fb_title)
    if before:
        warnings.append(f"메타데이터 노이즈 {len(before)}건을 학습 주제에서 제거했습니다.")
        logger.info("roadmap noise 제거(%d건): %s", len(before), before[:5])

    result["warnings"] = warnings
    return result


def validate_quiz_result(result: Dict[str, Any], source_text: str = "") -> Dict[str, Any]:
    """퀴즈 결과 검증. 문제/선택지/정답/해설 확인."""
    warnings = list(result.get("warnings") or [])
    questions = result.get("questions") if isinstance(result.get("questions"), list) else []
    valid = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        if not (q.get("question") or "").strip():
            continue
        opts = q.get("options") if isinstance(q.get("options"), list) else []
        if opts and len(opts) < 4:
            warnings.append("일부 문항의 선택지가 4개 미만입니다.")
        if q.get("answer") in (None, "", []):
            warnings.append("일부 문항의 정답이 누락되었습니다.")
        if not (q.get("explanation") or "").strip():
            warnings.append("일부 문항의 해설이 누락되었습니다.")
        valid.append(q)
    if not valid:
        warnings.append("유효한 퀴즈 문항을 생성하지 못했습니다.")
    result["questions"] = valid
    result["warnings"] = warnings
    return result


def validate_qa_result(answer: str, question: str = "", context: str = "") -> Dict[str, Any]:
    """Q&A 답변 검증. 빈 답변/근거 없음 표시."""
    warnings: List[str] = []
    ans = (answer or "").strip()
    if not ans:
        return {
            "answer": "문서 기준으로는 확인되지 않습니다. 자료 텍스트가 충분한지 확인해 주세요.",
            "warnings": ["답변이 비어 있습니다."],
        }
    if not (context or "").strip():
        warnings.append("참고할 자료 문맥이 없어 일반 지식 기반일 수 있습니다.")
    return {"answer": ans, "warnings": warnings}


def sanitize_keywords(keywords: List[str], limit: int = 8) -> List[str]:
    """
    키워드 목록을 정제한다.
    - 앞의 '#' 및 공백 제거
    - 빈 문자열/한 글자 이하 제거
    - 무의미 임시값(ㅇㅇ, test, null 등) 제거
    - 순수 기호/숫자만인 값 제거
    - 중복 제거(순서 보존), 최대 limit개
    키워드가 없으면 빈 배열을 반환한다.
    """
    from app.utils.pdf_noise_filter import clean_topic, is_metadata_noise
    cleaned: List[str] = []
    seen = set()
    for kw in keywords or []:
        if not kw:
            continue
        token = str(kw).strip().lstrip("#").strip()
        token = re.sub(r"\s+", " ", token)
        if len(token) <= 1:
            continue
        low = token.lower()
        if low in _JUNK_KEYWORDS:
            continue
        # 한글/영문/숫자가 하나도 없는(순수 기호) 값 제외
        if not re.search(r"[가-힣A-Za-z0-9]", token):
            continue
        # 숫자만으로 이루어진 값 제외
        if re.fullmatch(r"\d+", token):
            continue
        # PDF 메타데이터(날짜/연도/페이지/교수명) 제외 + 정제(기술 용어 보존)
        if is_metadata_noise(token):
            continue
        token = clean_topic(token) or token
        low = token.lower()
        if low in seen:
            continue
        seen.add(low)
        cleaned.append(token)
        if len(cleaned) >= limit:
            break
    return cleaned


def _get_gpt_client():
    global _sync_client
    if _sync_client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
        from openai import OpenAI
        _sync_client = OpenAI(api_key=OPENAI_API_KEY)
    return _sync_client


def _call_gpt(system: str, user: str, max_tokens: int = 1200) -> str:
    """GPT-4o-mini 동기 호출 (자료보관함 메인 처리)."""
    if not OPENAI_API_KEY:
        return "[GPT 미설정] OPENAI_API_KEY를 .env에 추가하세요."
    try:
        client = _get_gpt_client()
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        logger.error("GPT 호출 실패: %s", e)
        return f"[GPT 오류] {type(e).__name__}: {e}"


def _apply_qwen_tone(
    gpt_answer: str,
    personality: str,
    agent_name: str,
) -> str:
    """Qwen으로 GPT 답변에 에이전트 말투를 입힌다 (30% 역할)."""
    from app.services.personality_prompt_builder import build_personality_prompt
    personality_instr = build_personality_prompt(personality)
    system = (
        f"너는 StudyBridge 에이전트 '{agent_name}'이다.\n"
        f"{personality_instr}\n"
        "주어진 내용을 위 말투에 맞게 자연스럽게 다듬어라. "
        "핵심 내용은 변경하지 마라. 반드시 한국어로 출력하라."
    )
    user = (
        f"다음 내용을 '{agent_name}'의 말투로 자연스럽게 다듬어라:\n\n{gpt_answer}"
    )
    try:
        return ask_qwen(system_prompt=system, user_prompt=user, max_tokens=1200)
    except Exception as e:
        logger.warning("Qwen 말투 보정 실패, GPT 원본 반환: %s", e)
        return gpt_answer


# ── PDF RAG Q&A ─────────────────────────────────────────────────────────────

def answer_from_pdf(
    question: str,
    rag_chunks: list[dict],
    personality: str = "친절_설명형",
    agent_name: str = "자료봇",
    knowledge_level: str = "학사",
) -> dict:
    """
    PDF 청크 기반 Q&A.
    GPT가 구조적 답변 → Qwen이 말투 보정.

    Returns:
        {"answer": str, "sources": list[dict], "gpt_raw": str}
    """
    if not rag_chunks:
        return {
            "answer": "관련 PDF 자료를 찾지 못했습니다. 자료를 업로드하셨는지 확인해 주세요.",
            "sources": [],
            "gpt_raw": "",
        }

    context = "\n".join(
        f"[청크 {c.get('chunk_index',0)}] {c.get('content','')}" for c in rag_chunks
    )
    from app.services.knowledge_level_controller import get_level_instruction
    level_instr = get_level_instruction(knowledge_level)

    gpt_system = (
        "너는 PDF 문서 기반 Q&A 전문가다.\n"
        f"{level_instr}\n"
        "PDF_CONTEXT에 없는 내용은 단정하지 말고 '자료에 없는 내용'이라고 명시한다. "
        "답변은 한국어로 작성한다."
    )
    gpt_user = (
        f"## PDF_CONTEXT\n{context}\n\n"
        f"## 질문\n{question}\n\n"
        "위 자료를 근거로 정확하고 구조적으로 답변하라."
    )
    gpt_raw = _call_gpt(gpt_system, gpt_user)
    final_answer = _apply_qwen_tone(gpt_raw, personality, agent_name)
    return {
        "answer":  final_answer,
        "sources": rag_chunks,
        "gpt_raw": gpt_raw,
    }


# ── PDF 요약 ─────────────────────────────────────────────────────────────────

def _bullets_from_content(content: str) -> List[str]:
    """섹션 본문을 불릿 리스트로 분해한다 (불릿 마커/줄바꿈 기준)."""
    items: List[str] = []
    for ln in (content or "").splitlines():
        ln = ln.strip()
        ln = re.sub(r"^\s*(?:[-•*]|\d+[.)])\s*", "", ln).strip()
        if ln:
            items.append(ln)
    return items


def _parse_summary_sections(raw: str) -> Dict[str, Any]:
    """요약 마크다운을 overview/keywords/sections + 학습/실습/질문 버킷으로 파싱한다."""
    overview = ""
    keywords: List[str] = []
    sections: List[Dict[str, str]] = []
    learning_points: List[str] = []
    practice_points: List[str] = []
    study_questions: List[str] = []
    if not raw:
        return {"overview": "", "keywords": [], "sections": [],
                "learningPoints": [], "practicePoints": [], "studyQuestions": []}

    blocks: List[Dict[str, str]] = []
    current = None
    for line in raw.splitlines():
        header = re.match(r"^\s*#{2,6}\s*(.+?)\s*$", line)
        if header:
            current = {"title": header.group(1).strip(), "content": ""}
            blocks.append(current)
        elif current is not None:
            current["content"] += line + "\n"
        else:
            # 헤더 이전 텍스트는 개요로 누적
            overview += line + "\n"

    for b in blocks:
        title = b["title"]
        content = b["content"].strip()
        if not content:
            continue
        # 1) 개요
        if any(k in title for k in ("개요", "전체 요약")) and not overview.strip():
            overview = content
            continue
        # 2) 키워드
        if any(k in title for k in ("키워드", "핵심 개념")):
            raw_kw: List[str] = []
            for ln in content.splitlines():
                ln = ln.strip().lstrip("-•*").strip()
                if not ln:
                    continue
                raw_kw.extend(re.split(r"[,/·|]", ln))
            keywords = sanitize_keywords(raw_kw, limit=15)
            continue
        # 3) 학습 포인트
        if "학습 포인트" in title or "학습포인트" in title:
            learning_points = _bullets_from_content(content)
            continue
        # 4) 실습/적용 포인트
        if any(k in title for k in ("실습", "적용", "실무")):
            practice_points = _bullets_from_content(content)
            continue
        # 5) AI 학습 질문
        if "질문" in title:
            study_questions = _bullets_from_content(content)
            continue
        # 6) 그 외 → 세부 핵심 내용 섹션
        sections.append({"title": title, "content": content})

    overview = overview.strip()
    if not overview and sections:
        overview = sections[0]["content"][:400]
    if not sections and raw.strip():
        sections = [{"title": "요약", "content": raw.strip()}]
    return {"overview": overview, "keywords": keywords, "sections": sections,
            "learningPoints": learning_points, "practicePoints": practice_points,
            "studyQuestions": study_questions}


def summarize_document(
    document_title: str,
    text: str,
    personality: str = "간결_요약형",
    agent_name: str = "요약봇",
) -> dict:
    """
    PDF 전체 텍스트를 요약한다.
    모델 라우팅: Ollama/Qwen 우선 (call_primary_llm 내부에 GPT fallback 포함).

    Returns (하위호환 유지):
        {"summary", "key_points", "gpt_raw",
         "overview", "keywords", "sections", "warnings", "provider", "usedFallback"}
    """
    system = (
        "너는 학술 문서 요약 전문가다. 문서 내용에 근거해서만 한국어로 정리한다. "
        "문서에 없는 내용은 추측하지 마라. 아래 형식을 정확히 지켜라."
    )
    user = (
        f"## 문서 제목\n{document_title}\n\n"
        f"## 문서 내용 (최대 6000자)\n{text[:6000]}\n\n"
        "아래 형식을 지켜 충분히 구체적으로 작성하라:\n"
        "## 문서 개요\n4~6문장으로 문서의 목적, 배경, 핵심 흐름, 학습자가 얻을 내용을 설명한다.\n"
        "## 핵심 키워드\n문서에서 중요한 명사형 키워드 8~15개를 쉼표로 구분한다.\n"
        "## 세부 핵심 내용\n최소 5개 불릿으로 개념 정의, 구성 요소, 처리 흐름, 설정/의존성, 예제 활용, 오류 주의점을 문서 근거에 맞게 정리한다.\n"
        "## 학습 포인트\n3~5개 불릿으로 시험/실습/복습 관점의 포인트를 적는다.\n"
        "## 실습/적용 포인트\n기술 문서라면 Gradle 의존성, 권한/설정, 인터페이스/API 정의, ViewModel/Coroutine 같은 연계, 실습 흐름, 주의할 오류를 가능한 범위에서 포함한다.\n"
        "## AI 학습 질문\n학습자가 이 문서를 깊이 이해했는지 점검할 수 있는 질문 3~5개를 불릿으로 적는다."
    )

    provider = "ollama_qwen"
    used_fallback = False
    warnings: List[str] = []
    raw = ""
    try:
        from app.services.llm_engine_router import call_primary_llm
        raw = call_primary_llm(system_prompt=system, user_prompt=user, max_tokens=2200, temperature=0.35)
        if not raw or raw.strip().startswith("["):
            raise RuntimeError(f"primary LLM 응답 실패: {raw[:60] if raw else 'empty'}")
    except Exception as e:
        logger.warning("요약 Ollama/Qwen 실패: %s", e)
        if AI_ENABLE_GPT_FALLBACK:
            raw = _call_gpt(system, user, max_tokens=2200)
            provider = "openai_gpt"
            used_fallback = True
        else:
            raw = ""
            warnings.append("Ollama/Qwen 요약 생성에 실패했습니다.")

    if raw and raw.strip().startswith("["):  # GPT도 비활성/실패
        warnings.append("요약 생성에 실패했습니다.")
        raw = ""

    parsed = _parse_summary_sections(raw)

    result = {
        # 하위호환 필드
        "summary":    raw.strip(),
        "key_points": parsed["keywords"],
        "gpt_raw":    raw,
        # 확장 필드 (정규화)
        "overview":   parsed["overview"],
        "keywords":   parsed["keywords"],
        "sections":   parsed["sections"],
        "learningPoints":  parsed["learningPoints"],
        "practicePoints":  parsed["practicePoints"],
        "studyQuestions":  parsed["studyQuestions"],
        "warnings":   warnings,
        "provider":   provider,
        "usedFallback": used_fallback,
    }
    if AI_ENABLE_RESULT_VALIDATION:
        result = validate_summary_result(result, text)
    return result


# ── 퀴즈 생성 ────────────────────────────────────────────────────────────────

def generate_quiz(
    document_title: str,
    context: str,
    num_questions: int = 5,
    knowledge_level: str = "학사",
) -> dict:
    """
    PDF 내용 기반 퀴즈를 생성한다 (GPT 전담).

    Returns:
        {"quiz": str, "question_count": int}
    """
    from app.services.knowledge_level_controller import get_level_instruction
    level_instr = get_level_instruction(knowledge_level)

    gpt_system = (
        "너는 교육용 퀴즈 출제 전문가다. "
        f"{level_instr} "
        "사지선다형 객관식 문제를 출제하고, 정답과 해설을 포함한다. "
        "한국어로 작성한다."
    )
    gpt_user = (
        f"## 문서: {document_title}\n\n"
        f"## 내용 (최대 2000자)\n{context[:2000]}\n\n"
        f"위 내용을 바탕으로 {num_questions}개 사지선다 문제를 출제하라.\n"
        "형식:\nQ1. [문제]\n① ... ② ... ③ ... ④ ...\n정답: ③\n해설: ..."
    )
    quiz_text = _call_gpt(gpt_system, gpt_user, max_tokens=1500)
    actual_count = quiz_text.count("Q") if quiz_text else 0
    return {
        "quiz":           quiz_text,
        "question_count": min(actual_count, num_questions),
    }


# ── 학습 로드맵 생성 ──────────────────────────────────────────────────────────

def generate_roadmap(
    document_title: str,
    context: str,
    knowledge_level: str = "학사",
) -> dict:
    """
    문서 기반 학습 로드맵을 생성한다 (GPT 전담).

    Returns:
        {"roadmap": str}
    """
    from app.services.knowledge_level_controller import get_level_instruction
    level_instr = get_level_instruction(knowledge_level)

    gpt_system = (
        "너는 학습 커리큘럼 설계 전문가다. "
        f"{level_instr} "
        "문서 내용을 분석해 단계적 학습 로드맵을 설계한다. "
        "한국어로 작성한다. "
        "PDF의 날짜·연도·교수명·강의자료 표지/footer/header·슬라이드 번호는 학습 주제로 쓰지 말고, "
        "학습 항목은 개념·구조·원리·구현·비교·적용 단위로 작성한다."
    )
    gpt_user = (
        f"## 문서: {document_title}\n\n"
        f"## 내용 (최대 2000자)\n{context[:2000]}\n\n"
        "이 문서를 효과적으로 학습하기 위한 단계별 로드맵을 설계하라.\n"
        "형식:\n## 학습 목표\n## 선수 지식\n## 단계별 학습 계획 (1주차~)\n## 심화 학습 방향"
    )
    roadmap_text = _call_gpt(gpt_system, gpt_user, max_tokens=1200)
    return {"roadmap": roadmap_text}


# ── 문서 chunk 파이프라인 (전체 텍스트 일괄 투입 금지) ───────────────────────────

import hashlib

AI_CHUNK_SIZE = int(os.getenv("AI_CHUNK_SIZE", "1200"))
AI_CHUNK_OVERLAP = int(os.getenv("AI_CHUNK_OVERLAP", "150"))
AI_MAX_CHUNKS = int(os.getenv("AI_MAX_CHUNKS", "80"))
AI_QA_TOP_K = int(os.getenv("AI_QA_TOP_K", "8"))
AI_SUMMARY_MAX_CHUNKS = int(os.getenv("AI_SUMMARY_MAX_CHUNKS", "40"))
AI_ROADMAP_MAX_CHUNKS = int(os.getenv("AI_ROADMAP_MAX_CHUNKS", "30"))
AI_QUIZ_MAX_CHUNKS = int(os.getenv("AI_QUIZ_MAX_CHUNKS", "30"))

OCR_ENABLED = os.getenv("OCR_ENABLED", "false").lower() in ("true", "1", "yes")
OCR_MAX_PAGES = int(os.getenv("OCR_MAX_PAGES", "5"))
OCR_TIMEOUT_SECONDS = int(os.getenv("OCR_TIMEOUT_SECONDS", "45"))


def normalize_pdf_text(text: Optional[str]) -> str:
    """PDF 추출 텍스트를 chunk 생성 전 안정적으로 정규화한다."""
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def estimate_tokens(text: str) -> int:
    """대략적 토큰 추정 (한국어 혼합 기준 ~2.5자/토큰)."""
    return int(len(text or "") / 2.5)


def build_chunks_from_text(text: str, document_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    추출 텍스트를 chunk로 분해한다. 문단 우선 → 길면 글자수 기준, overlap 적용.
    빈/30자 미만 chunk 제거, chunk마다 hash 부여(중복 방지).
    """
    t = normalize_pdf_text(text)
    if not t:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
    units: List[str] = []
    for p in paragraphs:
        if len(p) <= AI_CHUNK_SIZE:
            units.append(p)
        else:
            start = 0
            while start < len(p):
                units.append(p[start:start + AI_CHUNK_SIZE])
                start += max(AI_CHUNK_SIZE - AI_CHUNK_OVERLAP, 1)

    chunks: List[Dict[str, Any]] = []
    seen_hashes = set()
    for unit in units:
        content = unit.strip()
        if len(content) < 30:
            continue
        h = hashlib.sha1(content.encode("utf-8")).hexdigest()
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        chunks.append({
            "documentId": document_id,
            "chunkIndex": len(chunks),
            "content": content,
            "charLength": len(content),
            "tokenEstimate": estimate_tokens(content),
            "hash": h,
        })
        if len(chunks) >= AI_MAX_CHUNKS:
            break
    return chunks


def select_relevant_chunks(question: str, chunks: List[Dict[str, Any]], top_k: int = AI_QA_TOP_K) -> List[Dict[str, Any]]:
    """임베딩 없이 키워드/문자열 유사도로 관련 chunk Top-K 선택 (fallback)."""
    if not chunks:
        return []
    q_terms = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", (question or "").lower()))
    if not q_terms:
        return chunks[:top_k]
    scored = []
    for c in chunks:
        text = c["content"].lower()
        score = sum(1 for term in q_terms if term in text)
        scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    relevant = [c for s, c in scored if s > 0][:top_k]
    return relevant or chunks[:top_k]


def build_summary_context(chunks: List[Dict[str, Any]], char_cap: int = 6000) -> str:
    """요약용 bounded context (대표 chunk를 char_cap 내로 결합 — 전체 일괄 투입 금지)."""
    return build_limited_context(chunks, AI_SUMMARY_MAX_CHUNKS, char_cap)


def build_limited_context(chunks: List[Dict[str, Any]], max_chunks: int, char_cap: int = 6000) -> str:
    """기능별 최대 chunk 수와 문자 상한을 지키는 bounded context."""
    parts: List[str] = []
    total = 0
    for c in chunks[:max_chunks]:
        content = c.get("content", "")
        if total + len(content) > char_cap:
            break
        parts.append(content)
        total += len(content)
    return "\n\n".join(parts)


def ocr_unavailable_status() -> Dict[str, Any]:
    """OCR 의존성/설정 상태를 서버를 죽이지 않고 표준 상태로 반환한다."""
    try:
        from app.services.ocr_service import ocr_status
        status = ocr_status()
    except Exception:
        status = {"enabled": OCR_ENABLED, "available": False}
    status.update({
        "maxPages": OCR_MAX_PAGES,
        "timeoutSeconds": OCR_TIMEOUT_SECONDS,
        "errorCode": None if status.get("available") else "PDF_OCR_REQUIRED",
    })
    return status


# ── 구조화 JSON 생성 (GPT) + 검증 연결 ────────────────────────────────────────

def _extract_json(raw: str) -> Optional[Any]:
    """LLM 출력에서 JSON 블록을 추출/파싱한다 (코드펜스/잡텍스트 제거, 1회 repair)."""
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"[\[{].*[\]}]", s, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def generate_quiz_json(context: str, difficulty: str = "보통", num_questions: int = 5,
                       knowledge_level: str = "학사") -> Dict[str, Any]:
    """Ollama/Qwen 우선 구조화 퀴즈 JSON 생성 → validate_quiz_result 연결."""
    num_questions = max(1, min(int(num_questions or 5), 20))
    variant_seed = uuid.uuid4().hex[:10]
    system = (
        "너는 교육용 퀴즈 출제 전문가다. 제공된 문서 내용에 근거해서만 한국어로 출제한다. "
        "반드시 JSON 배열만 출력한다. 각 항목은 "
        '{"question","options"(4개),"answerIndex"(0~3 정수),"answer"(정답 텍스트),"explanation","difficulty"} 형식이다. '
        "재생성 요청마다 서로 다른 개념 포인트, 문제 표현, 오답 보기를 사용한다."
    )
    user = (
        f"## 난이도\n{difficulty}\n## 문항 수\n{num_questions}\n## 재생성 변형 seed\n{variant_seed}\n\n"
        f"## 문서 내용\n{context[:6000]}\n\n"
        "위 내용을 바탕으로 정확히 요청 문항 수만큼 사지선다 문제를 JSON 배열로만 출력하라. "
        "정의/설정/처리 흐름/주의점/적용 사례를 고르게 섞고, 같은 근거 문장만 반복하지 마라."
    )
    provider = "ollama_qwen"
    try:
        from app.services.llm_engine_router import call_primary_llm
        raw = call_primary_llm(system_prompt=system, user_prompt=user, max_tokens=max(2000, num_questions * 420), temperature=0.55)
        if not raw or raw.strip().startswith("[") and raw.strip().startswith("[GPT"):
            raise RuntimeError("primary LLM unavailable")
    except Exception as e:
        logger.warning("퀴즈 Ollama/Qwen 실패: %s", e)
        raw = _call_gpt(system, user, max_tokens=max(2000, num_questions * 420))
        provider = "openai_gpt"
    parsed = _extract_json(raw)
    questions: List[Dict[str, Any]] = []
    if isinstance(parsed, list):
        for q in parsed:
            if not isinstance(q, dict):
                continue
            opts = q.get("options") or q.get("choices") or []
            ans_idx = q.get("answerIndex")
            if ans_idx is None and isinstance(q.get("answer"), int):
                ans_idx = q.get("answer")
            if ans_idx is None and isinstance(opts, list) and q.get("answer") in opts:
                ans_idx = opts.index(q.get("answer"))
            try:
                ans_idx = int(ans_idx)
            except (TypeError, ValueError):
                ans_idx = 0
            questions.append({
                "question": (q.get("question") or "").strip(),
                "options": opts,
                "answer": ans_idx,  # 프론트 parseQuizQuestions는 숫자 인덱스를 기대
                "answerIndex": ans_idx,
                "explanation": (q.get("explanation") or "").strip(),
                "difficulty": q.get("difficulty") or difficulty,
            })
    result = {"questions": questions, "warnings": [], "provider": provider, "raw": raw}
    if AI_ENABLE_RESULT_VALIDATION:
        result = validate_quiz_result(result, context)
    return result


def generate_roadmap_json(context: str, user_goal: str = "학습 목표 달성",
                          knowledge_level: str = "학사") -> Dict[str, Any]:
    """GPT로 구조화 로드맵 JSON 생성 → validate_roadmap_result 연결."""
    system = (
        "너는 학습 커리큘럼 설계 전문가다. 제공된 문서 내용에 근거해 한국어로 설계한다. "
        "마크다운, 설명문, 코드블록 없이 JSON 객체만 출력한다. 형식: "
        '{"title":"문서 기반 학습 로드맵","totalWeeks":12,"weeks":[{"weekNumber":1,"title":"1주차 제목","goal":"학습 목표",'
        '"keyConcepts":["핵심 개념"],"tasks":["구체 태스크1","구체 태스크2","구체 태스크3"],'
        '"deliverable":"산출물 또는 자기점검","estimatedHours":3}]}. '
        "weeks는 정확히 12개가 가장 좋고 최소 4개 이상이어야 한다. 각 주차 tasks는 빈 배열 금지이며 최소 2개 이상이다."
    )
    user = (
        f"## 학습 목표\n{user_goal}\n\n## 문서 내용\n{context[:6000]}\n\n"
        "문서 개요부터 실습/복습까지 이어지는 주차별 학습 로드맵을 JSON으로만 출력하라. "
        "각 주차에는 주차 번호, 제목, 학습 목표, 핵심 개념, 학습 태스크 목록, 산출물/자기점검, 예상 학습 시간을 포함하라."
    )
    raw = _call_gpt(system, user, max_tokens=3200)
    parsed = _extract_json(raw)
    title = "AI 생성 학습 로드맵"
    weeks: List[Dict[str, Any]] = []
    if isinstance(parsed, dict):
        title = (parsed.get("title") or title).strip() or title
        raw_weeks = parsed.get("weeks") or parsed.get("steps") or parsed.get("roadmap") or []
        if isinstance(raw_weeks, dict):
            raw_weeks = raw_weeks.get("weeks") or raw_weeks.get("steps") or []
        for wk in raw_weeks:
            if not isinstance(wk, dict):
                continue
            tasks: List[Any] = []
            for key in ("tasks", "taskList", "activities", "todos", "assignments", "checkpoints"):
                tasks.extend(_listify(wk.get(key)))
            weeks.append({
                "weekNumber": wk.get("weekNumber") or wk.get("week") or wk.get("stepOrder"),
                "title": _text_from_any(wk.get("title") or wk.get("name") or wk.get("weekTitle")),
                "goal": _text_from_any(wk.get("goal") or wk.get("objective") or wk.get("learningGoal") or wk.get("description")),
                "keyConcepts": [_text_from_any(v) for v in _listify(wk.get("keyConcepts") or wk.get("coreConcepts") or wk.get("concepts"))],
                "tasks": [_text_from_any(t) for t in tasks if _text_from_any(t)],
                "deliverable": _text_from_any(wk.get("deliverable") or wk.get("output") or wk.get("selfCheck") or wk.get("checklist")),
                "estimatedHours": wk.get("estimatedHours") or wk.get("hours") or wk.get("studyHours") or 0,
            })
    result = {"title": title, "weeks": weeks, "warnings": [], "provider": "openai_gpt", "raw": raw}
    if AI_ENABLE_RESULT_VALIDATION:
        result = validate_roadmap_result(result, context)
    return result
