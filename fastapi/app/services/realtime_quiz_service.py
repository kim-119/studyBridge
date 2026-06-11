"""
Realtime quiz generation service.

The service is deliberately defensive: LLM output is treated as untrusted text,
JSON is extracted/repaired/validated, and a document-grounded fallback is built
when model output is unusable. Do not log full source documents here.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.schemas.realtime_quiz_schema import RealtimeQuizGenerateRequest

logger = logging.getLogger(__name__)

_ALLOWED_TYPES = {"multiple_choice", "true_false", "short_answer"}
_DIFFICULTIES = {"easy", "medium", "hard"}
_MAX_CONTEXT_CHARS = 9000
_MIN_TEXT_CHARS = 20

_STOPWORDS = {
    "그리고", "그러나", "입니다", "합니다", "있는", "없는", "대한", "위해", "에서", "으로", "한다", "된다",
    "the", "and", "for", "with", "that", "this", "from", "into", "about", "using",
}


def normalize_difficulty(value: Optional[str]) -> str:
    value = str(value or "medium").strip().lower()
    mapping = {"쉬움": "easy", "보통": "medium", "중간": "medium", "어려움": "hard", "normal": "medium"}
    return mapping.get(value, value if value in _DIFFICULTIES else "medium")


def normalize_question_types(values: Optional[Iterable[str]]) -> List[str]:
    if not values:
        return ["multiple_choice"]
    out: List[str] = []
    mapping = {"객관식": "multiple_choice", "참거짓": "true_false", "ox": "true_false", "주관식": "short_answer"}
    for raw in values:
        value = mapping.get(str(raw or "").strip().lower(), str(raw or "").strip().lower())
        if value in _ALLOWED_TYPES and value not in out:
            out.append(value)
    return out or ["multiple_choice"]


def _sentence_split(text: str, limit: int = 80) -> List[str]:
    compact = re.sub(r"\s+", " ", text or " ").strip()
    parts = re.split(r"(?<=[.!?。！？다요]\s)|(?<=[.!?。！？])\s+|\n+", compact)
    sentences: List[str] = []
    for part in parts:
        s = re.sub(r"\s+", " ", part).strip(" -\t")
        if len(s) >= 18:
            sentences.append(s[:500])
        if len(sentences) >= limit:
            break
    if not sentences and compact:
        sentences = [compact[:500]]
    return sentences


def _keywords(text: str, limit: int = 24) -> List[str]:
    tokens = re.findall(r"[가-힣A-Za-z][가-힣A-Za-z0-9+_.#-]{1,}", text or "")
    scored: Dict[str, int] = {}
    for token in tokens:
        t = token.strip("._-#").lower()
        if len(t) < 2 or t in _STOPWORDS:
            continue
        scored[t] = scored.get(t, 0) + 1
    ranked = sorted(scored, key=lambda k: (-scored[k], -len(k), k))
    return ranked[:limit]


def _context_from_text(text: str) -> Tuple[str, List[str]]:
    sentences = _sentence_split(text, limit=80)
    if len(text) <= _MAX_CONTEXT_CHARS:
        return text.strip(), sentences
    # Prefer the beginning plus keyword-dense sentences. This keeps prompts bounded without logging/storing full text.
    kws = set(_keywords(text, limit=20))
    scored = []
    for idx, sent in enumerate(sentences):
        score = sum(1 for kw in kws if kw and kw in sent.lower())
        if idx < 8:
            score += 2
        scored.append((score, idx, sent))
    selected = [s for _, _, s in sorted(scored, key=lambda x: (-x[0], x[1]))[:28]]
    context = "\n".join(selected)
    return context[:_MAX_CONTEXT_CHARS], selected


def _retrieve_text_from_rag(material_id: Optional[int]) -> str:
    if not material_id:
        return ""
    try:
        from app.services.rag_retriever import retrieve_similar_chunks
        query = "문서의 핵심 개념 정의 사용 방법 예시 주의점 요약"
        chunks = retrieve_similar_chunks(query, material_id=material_id, top_k=12)
        contents = []
        for chunk in chunks or []:
            content = str(chunk.get("content") or "").strip()
            if content:
                contents.append(content)
        return "\n\n".join(contents)
    except Exception as e:
        logger.warning("realtime quiz RAG lookup failed material_id=%s err=%s", material_id, type(e).__name__)
        return ""


def _extract_json_text(raw: str) -> Optional[str]:
    if not raw:
        return None
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    obj_start = text.find("{")
    arr_start = text.find("[")
    starts = [i for i in (obj_start, arr_start) if i >= 0]
    if not starts:
        return None
    start = min(starts)
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    end = text.rfind(closer)
    if end <= start:
        return None
    return text[start:end + 1]


def _parse_json_loose(raw: str) -> Optional[Any]:
    extracted = _extract_json_text(raw)
    if not extracted:
        return None
    try:
        return json.loads(extracted)
    except Exception:
        return None


def _call_llm(system: str, user: str, max_tokens: int = 2600, temperature: float = 0.25) -> str:
    try:
        from app.services.llm_engine_router import call_primary_llm
        out = call_primary_llm(system_prompt=system, user_prompt=user, max_tokens=max_tokens, temperature=temperature)
        return out or ""
    except Exception as e:
        logger.warning("realtime quiz primary LLM failed: %s", type(e).__name__)
        return ""


def _repair_json(raw: str, quiz_count: int) -> Optional[Any]:
    if not raw:
        return None
    system = (
        "너는 JSON 복구기다. 입력에서 퀴즈 문항만 추출해 유효한 JSON 객체만 출력한다. "
        "마크다운, 설명문, 주석 없이 JSON만 출력한다."
    )
    user = (
        "아래 텍스트를 다음 스키마로 복구하라. "
        f"questions는 1개 이상 {quiz_count}개 이하로 둔다.\n"
        '{"questions":[{"type":"multiple_choice","question":"...","choices":["A","B","C","D"],'
        '"answer":"A","answer_index":0,"explanation":"...","source":"..."}]}\n\n'
        f"입력:\n{raw[:12000]}"
    )
    repaired = _call_llm(system, user, max_tokens=max(1400, quiz_count * 350), temperature=0.05)
    return _parse_json_loose(repaired)


def _as_questions(parsed: Any) -> List[Dict[str, Any]]:
    if isinstance(parsed, list):
        return [x for x in parsed if isinstance(x, dict)]
    if isinstance(parsed, dict):
        for key in ("questions", "quizzes", "items"):
            value = parsed.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def _fallback_choices(answer: str, keywords: List[str]) -> List[str]:
    pool = [kw for kw in keywords if kw and kw != answer.lower()]
    labels = [answer or "핵심 개념"]
    for kw in pool:
        label = kw[:40]
        if label not in labels:
            labels.append(label)
        if len(labels) >= 4:
            break
    generic = ["문서의 핵심 개념", "부가 설명", "예외 상황", "관련 도구"]
    for item in generic:
        if item not in labels:
            labels.append(item)
        if len(labels) >= 4:
            break
    return labels[:4]


def _document_grounded_fallback(context: str, quiz_count: int, difficulty: str, question_types: List[str]) -> List[Dict[str, Any]]:
    sentences = _sentence_split(context, limit=max(quiz_count * 2, 8))
    keywords = _keywords(context, limit=40)
    if not keywords:
        keywords = ["문서 핵심", "학습 내용", "주요 개념", "활용 방법"]
    questions: List[Dict[str, Any]] = []
    for i in range(quiz_count):
        qtype = question_types[i % len(question_types)]
        source = sentences[i % len(sentences)] if sentences else ""
        answer = keywords[i % len(keywords)]
        if qtype == "true_false":
            questions.append({
                "type": "true_false",
                "question": f"다음 설명은 문서 내용과 일치하는가? {source[:180]}",
                "choices": ["True", "False"],
                "answer": "True",
                "answer_index": 0,
                "explanation": "문서의 근거 문장에 직접 나타나는 내용입니다.",
                "difficulty": difficulty,
                "source": source,
            })
        elif qtype == "short_answer":
            questions.append({
                "type": "short_answer",
                "question": f"문서에서 '{answer}'와 관련해 설명하는 핵심 내용을 한 문장으로 쓰세요.",
                "choices": [],
                "answer": answer,
                "answer_index": None,
                "explanation": source or "문서의 핵심 키워드를 바탕으로 만든 문항입니다.",
                "difficulty": difficulty,
                "source": source,
            })
        else:
            choices = _fallback_choices(answer, keywords)
            questions.append({
                "type": "multiple_choice",
                "question": f"다음 문서 내용과 가장 관련 깊은 핵심 개념은 무엇인가? {source[:160]}",
                "choices": choices,
                "answer": choices[0],
                "answer_index": 0,
                "explanation": source or "문서의 핵심 문장과 키워드를 기반으로 생성했습니다.",
                "difficulty": difficulty,
                "source": source,
            })
    return questions


def _normalize_question(item: Dict[str, Any], idx: int, difficulty: str, fallback: Dict[str, Any], keywords: List[str]) -> Dict[str, Any]:
    qtype = str(item.get("type") or item.get("questionType") or fallback.get("type") or "multiple_choice").strip().lower()
    if qtype not in _ALLOWED_TYPES:
        qtype = "multiple_choice"

    question = str(item.get("question") or item.get("prompt") or fallback.get("question") or "").strip()
    explanation = str(item.get("explanation") or item.get("reason") or fallback.get("explanation") or "").strip()
    source = str(item.get("source") or item.get("evidence") or fallback.get("source") or "").strip()
    choices_raw = item.get("choices", item.get("options", fallback.get("choices", [])))
    choices = [str(c).strip() for c in choices_raw] if isinstance(choices_raw, list) else []
    answer = str(item.get("answer") or item.get("correctAnswer") or item.get("correct_answer") or fallback.get("answer") or "").strip()

    if qtype == "multiple_choice":
        if len(choices) < 4:
            base_answer = answer or str(fallback.get("answer") or "핵심 개념")
            choices = _fallback_choices(base_answer, keywords)
        if answer not in choices:
            answer = choices[0]
        try:
            answer_index = int(item.get("answer_index", item.get("correctAnswer", choices.index(answer))))
        except Exception:
            answer_index = choices.index(answer)
        if answer_index < 0 or answer_index >= len(choices) or choices[answer_index] != answer:
            answer_index = choices.index(answer)
    elif qtype == "true_false":
        choices = choices if len(choices) >= 2 else ["True", "False"]
        normalized = str(answer).strip().lower()
        answer = "False" if normalized in {"false", "거짓", "x", "no", "아니오"} else "True"
        answer_index = 0 if answer == choices[0] else (choices.index(answer) if answer in choices else 0)
    else:
        choices = []
        answer = answer or str(fallback.get("answer") or "문서 핵심 내용")
        answer_index = None

    if not question:
        question = str(fallback.get("question") or f"문서 기반 실시간 퀴즈 {idx}번 문항입니다.")
    if not explanation:
        explanation = str(fallback.get("explanation") or "문서 내용에 근거해 보정된 해설입니다.")

    return {
        "id": idx,
        "type": qtype,
        "question": question,
        "choices": choices,
        "answer": answer,
        "answer_index": answer_index,
        "explanation": explanation,
        "difficulty": difficulty,
        "source": source,
    }


def _similar(a: str, b: str) -> float:
    aw = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", (a or "").lower()))
    bw = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", (b or "").lower()))
    if not aw or not bw:
        return 0.0
    return len(aw & bw) / max(1, len(aw | bw))


def _dedupe_questions(questions: List[Dict[str, Any]], fallback_questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    fallback_iter = iter(fallback_questions)
    for q in questions:
        current = q
        if any(_similar(current.get("question", ""), prev.get("question", "")) >= 0.72 for prev in deduped):
            current = next(fallback_iter, current)
        deduped.append(current)
    return deduped


def _normalize_questions(parsed_questions: List[Dict[str, Any]], context: str, quiz_count: int, difficulty: str, question_types: List[str]) -> List[Dict[str, Any]]:
    fallback_questions = _document_grounded_fallback(context, quiz_count, difficulty, question_types)
    keywords = _keywords(context, limit=40)
    normalized: List[Dict[str, Any]] = []
    parsed_questions = _dedupe_questions(parsed_questions, fallback_questions)
    for i in range(quiz_count):
        raw = parsed_questions[i] if i < len(parsed_questions) else {}
        fallback = fallback_questions[i % len(fallback_questions)]
        normalized.append(_normalize_question(raw, i + 1, difficulty, fallback, keywords))
    return normalized


def _build_prompt(title: str, context: str, quiz_count: int, difficulty: str, question_types: List[str], variant_seed: str) -> Tuple[str, str]:
    types = ", ".join(question_types)
    system = (
        "너는 그룹스터디 실시간 퀴즈 출제자다. 제공된 문서 내용에 근거해서만 한국어 퀴즈를 만든다. "
        "반드시 JSON 객체만 출력한다. 마크다운 코드블록, 설명문, 주석을 출력하지 않는다. "
        "객관식은 choices 4개 이상, answer는 choices 중 하나, answer_index는 0-based로 맞춘다. "
        "문서 근거가 약한 내용을 지어내지 않는다. "
        "같은 자료라도 매번 다른 개념 조합, 질문 표현, 오답 보기, 문항 유형 순서를 사용한다."
    )
    user = (
        f"자료 제목: {title}\n"
        f"난이도: {difficulty}\n"
        f"문항 수: {quiz_count}\n"
        f"허용 문항 유형: {types}\n"
        f"재생성 변형 seed: {variant_seed}\n"
        "출제 다양화 지시: 앞부분 개요 문항만 반복하지 말고 정의/설정/흐름/예외/활용/비교 포인트를 고르게 섞어라. "
        "각 문제의 source는 서로 다른 근거 문장 또는 페이지를 우선 사용하라.\n\n"
        "응답 스키마:\n"
        '{"questions":[{"type":"multiple_choice|true_false|short_answer","question":"문제 내용",'
        '"choices":["A","B","C","D"],"answer":"A","answer_index":0,'
        '"explanation":"정답 해설","source":"근거 문장 또는 페이지"}]}\n\n'
        f"문서 내용:\n{context}"
    )
    return system, user


def generate_realtime_quiz(req: RealtimeQuizGenerateRequest) -> Dict[str, Any]:
    quiz_count = max(1, min(int(req.quiz_count or 5), 20))
    difficulty = normalize_difficulty(req.difficulty)
    question_types = normalize_question_types(req.question_types)
    title = (req.title or "실시간 퀴즈").strip() or "실시간 퀴즈"

    source_text = (req.text or "").strip()
    if not source_text and req.material_id:
        source_text = _retrieve_text_from_rag(req.material_id)

    if not source_text or len(source_text.strip()) < _MIN_TEXT_CHARS:
        raise ValueError("text 또는 RAG에 저장된 material_id 기반 문서 내용이 필요합니다.")

    context, _ = _context_from_text(source_text)
    logger.info(
        "realtime quiz start group_id=%s material_id=%s textLen=%s contextLen=%s count=%s difficulty=%s types=%s",
        req.group_id, req.material_id, len(source_text), len(context), quiz_count, difficulty, question_types,
    )

    variant_seed = uuid.uuid4().hex[:10]
    system, user = _build_prompt(title, context, quiz_count, difficulty, question_types, variant_seed)
    raw = _call_llm(system, user, max_tokens=max(2200, quiz_count * 420), temperature=0.55)
    parsed = _parse_json_loose(raw)
    questions = _as_questions(parsed)

    if not questions:
        repaired = _repair_json(raw, quiz_count)
        questions = _as_questions(repaired)

    normalized = _normalize_questions(questions, context, quiz_count, difficulty, question_types)
    if not normalized:
        normalized = _document_grounded_fallback(context, quiz_count, difficulty, question_types)
        normalized = _normalize_questions(normalized, context, quiz_count, difficulty, question_types)

    return {
        "status": "SUCCESS",
        "quiz_id": f"rtq-{uuid.uuid4().hex[:12]}",
        "group_id": req.group_id,
        "material_id": req.material_id,
        "title": "실시간 퀴즈",
        "quiz_count": len(normalized),
        "questions": normalized,
        "_elapsed_ms": int(time.time() * 1000),
    }
