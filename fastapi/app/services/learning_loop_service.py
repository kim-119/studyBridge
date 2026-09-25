"""
StudyBridge 학습 왕복 루프(Learning Loop) 서비스.

Spring 이 검증한 요청(taskType + learningLoopContext)을 받아
RAG 본문 근거 + 최근 학습 이력(요약/오답/퀴즈/메모/플래너/대화/에이전트 피드백)을
결합해 구조화 JSON 을 생성한다. DB 저장은 Spring 책임이고, FastAPI 는 생성·검증만 한다.

설계 원칙(반드시 유지):
  - 기존 라우터/서비스(multi-chat, summary, quiz, roadmap, rag, review-note 등)를
    import 하더라도 그 동작을 바꾸지 않는다. 이 모듈은 additive 진입점이다.
  - learningLoopContext 의 어떤 필드가 없거나 잘못돼도 요청이 실패하면 안 된다.
  - RAG 본문 근거가 있으면 최우선. 사용자 오답/메모는 보조. 모르면 모른다고 한다.
  - 컨텍스트에 없는 교수명/연도/강의명/사람 이름을 임의 생성하지 않는다.
  - LLM 실패에도 deterministic fallback 으로 기능이 죽지 않게 하고, fallback 사용은
    warnings 에 반드시 명시한다.
  - 모든 응답은 success / taskType / usedContext / warnings 를 포함한다.

LLM: 운영 주력은 Ollama(qwen2.5/qwen3). ai07 은 OpenAI 보강이 비활성일 수 있으므로
     ai_pipeline.generate_structured(Ollama 우선 → OpenAI 보강 fallback) 를 그대로 쓴다.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# usedContext 표준 키 (Spring 파서 계약) ────────────────────────────────────────
_USED_KEYS = (
    "ragUsed", "summaryUsed", "wrongNotesUsed", "quizResultsUsed",
    "plannerReviewsUsed", "userMemosUsed", "recentChatUsed",
)

_RAG_TOP_K = 5
_RAG_CHUNK_CHARS = 600
_SOURCE_TEXT_CHARS = 2200
_HISTORY_ITEMS = 6
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[가-힣]{2,}")


# ── 공통 헬퍼 ────────────────────────────────────────────────────────────────
def _clean(value: Any) -> str:
    from app.utils.sanitize import sanitize_markdown_text
    return sanitize_markdown_text(value)


def _strip_think(text: Optional[str]) -> str:
    if not text:
        return ""
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    if "</think>" in text.lower():
        text = text[text.lower().rfind("</think>") + len("</think>"):]
    return re.sub(r"</?think>", "", text, flags=re.IGNORECASE).strip()


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _str_items(values: Any, limit: int) -> List[str]:
    out = [_clean(v) for v in _as_list(values) if str(v).strip()]
    return out[:limit]


def _keywords(text: str) -> set:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) >= 2}


def _new_used() -> Dict[str, bool]:
    return {k: False for k in _USED_KEYS}


def resolve_material_id(material_id: Optional[Any], document_id: Optional[Any]) -> Optional[int]:
    """materialId/documentId 를 내부 material_id(int)로 매핑. 실패하면 None(전체 검색 X 의도지만
    학습루프는 grounding 없이도 동작해야 하므로 raise 하지 않는다)."""
    if material_id is not None:
        try:
            return int(material_id)
        except (TypeError, ValueError):
            return None
    if document_id is not None:
        m = re.fullmatch(r"(?:doc[_-])?(\d+)", str(document_id).strip())
        if m:
            return int(m.group(1))
    return None


# ── LLM 호출(Ollama 우선) ─────────────────────────────────────────────────────
def _llm_text(system: str, user: str, *, max_tokens: int = 900,
              temperature: float = 0.4) -> Optional[str]:
    """자유형 텍스트 응답(채팅 등). Ollama → OpenAI fallback. 실패 시 None."""
    try:
        from app.services.llm_engine_router import call_primary_llm
        raw = call_primary_llm(system, user, max_tokens=max_tokens, temperature=temperature)
    except Exception as e:  # noqa: BLE001
        logger.info("[learning_loop] _llm_text 실패: %s", e)
        return None
    if not raw or raw.strip().startswith("["):
        return None
    cleaned = _strip_think(raw)
    return cleaned or None


def _llm_struct(*, draft_system: str, draft_user: str, validator: Callable[[Dict[str, Any]], bool],
                max_tokens: int = 1100) -> Optional[Dict[str, Any]]:
    """구조화 JSON 생성: ai_pipeline(Ollama 초안 → OpenAI 보강 → repair) 재사용."""
    from app.services.ai_pipeline import generate_structured, repair_to_valid

    refine_system = draft_system + "\n반드시 같은 JSON 스키마로만 응답한다. 마크다운/설명 금지."

    def _refine_user(draft: Dict[str, Any]) -> str:
        import json as _json
        txt = _json.dumps(draft, ensure_ascii=False) if draft else "(초안 없음 — 직접 생성)"
        return draft_user + f"\n\n## 1차 초안\n{txt}\n위 초안을 보강해 같은 JSON 으로만 응답하라."

    parsed = generate_structured(
        draft_system=draft_system, draft_user=draft_user,
        refine_system=refine_system, refine_user_builder=_refine_user,
        validator=validator, max_tokens=max_tokens,
    )
    if isinstance(parsed, dict) and validator(parsed):
        return parsed
    repaired = repair_to_valid(
        repair_system=refine_system, repair_user=_refine_user(parsed or {}),
        validator=validator, max_tokens=max_tokens,
    )
    if isinstance(repaired, dict) and validator(repaired):
        return repaired
    return parsed if isinstance(parsed, dict) else None


# ── 컨텍스트 결합 ─────────────────────────────────────────────────────────────
def _gather_rag(question: str, material_id: Optional[int]) -> List[dict]:
    try:
        from app.services.rag_retriever import retrieve_similar_chunks
        chunks = retrieve_similar_chunks(question or "", material_id, _RAG_TOP_K)
        return chunks or []
    except Exception as e:  # noqa: BLE001
        logger.info("[learning_loop] RAG 검색 실패(무시): %s", type(e).__name__)
        return []


def assemble_context(req: "LearningLoopRequest") -> Tuple[str, Dict[str, bool], List[dict]]:
    """우선순위(RAG > sourceText > 요약 > 오답 > 퀴즈 > 메모 > 플래너 > 대화 > 에이전트피드백)대로
    프롬프트 컨텍스트 문자열과 usedContext 플래그를 만든다."""
    ctx = req.learningLoopContext
    used = _new_used()
    blocks: List[str] = []

    mid = resolve_material_id(req.materialId, req.documentId)
    search_q = (req.userQuestion or req.title or "").strip()

    # 1. RAG 본문 근거 (질문 또는 자료 식별자가 있을 때만)
    chunks: List[dict] = []
    if search_q or mid is not None:
        chunks = _gather_rag(search_q or "핵심 개념", mid)
    if chunks:
        used["ragUsed"] = True
        body = "\n---\n".join((c.get("content") or "")[:_RAG_CHUNK_CHARS] for c in chunks[:_RAG_TOP_K])
        blocks.append("## 자료 본문 근거(RAG, 최우선)\n" + body)

    # 2. 사용자가 직접 선택한 sourceText
    if (req.sourceText or "").strip():
        if not chunks:
            used["ragUsed"] = True  # 본문 근거가 sourceText 형태로 제공된 경우
        blocks.append("## 사용자가 선택한 본문(sourceText)\n" + req.sourceText.strip()[:_SOURCE_TEXT_CHARS])

    if ctx is None:
        return "\n\n".join(blocks), used, chunks

    # 3. 최근 요약
    summaries = _as_list(ctx.summaries)
    if summaries:
        used["summaryUsed"] = True
        lines = []
        for s in summaries[:_HISTORY_ITEMS]:
            if isinstance(s, dict):
                t = _clean(s.get("title") or "")
                c = _clean(s.get("content") or s.get("summary") or "")
                lines.append(f"- {t}: {c}" if t else f"- {c}")
            else:
                lines.append(f"- {_clean(s)}")
        blocks.append("## 최근 요약(보조)\n" + "\n".join(l for l in lines if l.strip()))

    # 4. 최근 오답노트
    wrong = _as_list(ctx.wrongNotes)
    if wrong:
        used["wrongNotesUsed"] = True
        lines = []
        for w in wrong[:_HISTORY_ITEMS]:
            if isinstance(w, dict):
                q = _clean(w.get("question") or w.get("questionText") or "")
                ua = _clean(w.get("userAnswer") or "")
                ca = _clean(w.get("correctAnswer") or "")
                ex = _clean(w.get("explanation") or "")
                lines.append(f"- 문제: {q} / 내가 고른 답: {ua} / 정답: {ca} / 해설: {ex}")
            else:
                lines.append(f"- {_clean(w)}")
        blocks.append("## 최근 오답노트(이전에 헷갈렸던 부분)\n" + "\n".join(lines))

    # 5. 최근 퀴즈 결과
    quizzes = _as_list(ctx.quizResults)
    if quizzes:
        used["quizResultsUsed"] = True
        lines = []
        for q in quizzes[:_HISTORY_ITEMS]:
            if isinstance(q, dict):
                tot, cor, wr = q.get("total"), q.get("correct"), q.get("wrong")
                concept = _clean(q.get("concept") or "")
                lines.append(f"- 총 {tot} / 정답 {cor} / 오답 {wr}" + (f" (개념: {concept})" if concept else ""))
            else:
                lines.append(f"- {_clean(q)}")
        blocks.append("## 최근 퀴즈 결과\n" + "\n".join(lines))

    # 6. 사용자 메모
    memos = _as_list(ctx.userMemos)
    if memos:
        used["userMemosUsed"] = True
        lines = []
        for m in memos[:_HISTORY_ITEMS]:
            txt = _clean(m.get("content") if isinstance(m, dict) else m)
            if txt:
                lines.append(f"- {txt}")
        if lines:
            blocks.append("## 사용자 메모(사용자가 헷갈린 지점)\n" + "\n".join(lines))
        else:
            used["userMemosUsed"] = False

    # 7. 플래너 복습 일정
    planners = _as_list(ctx.plannerReviews)
    if planners:
        used["plannerReviewsUsed"] = True
        lines = []
        for p in planners[:_HISTORY_ITEMS]:
            if isinstance(p, dict):
                title = _clean(p.get("title") or p.get("task") or "")
                due = _clean(p.get("reviewDate") or p.get("dueDate") or "")
                lines.append(f"- {title} ({due})" if due else f"- {title}")
            else:
                lines.append(f"- {_clean(p)}")
        blocks.append("## 플래너 복습 일정\n" + "\n".join(l for l in lines if l.strip()))

    # 8. 최근 대화
    chats = _as_list(ctx.recentChatHistory)
    if chats:
        used["recentChatUsed"] = True
        lines = []
        for c in chats[-_HISTORY_ITEMS:]:
            if isinstance(c, dict):
                role = _clean(c.get("role") or c.get("sender") or "")
                content = _clean(c.get("content") or c.get("message") or "")
                lines.append(f"- {role}: {content}" if role else f"- {content}")
            else:
                lines.append(f"- {_clean(c)}")
        blocks.append("## 최근 대화\n" + "\n".join(l for l in lines if l.strip()))

    return "\n\n".join(b for b in blocks if b.strip()), used, chunks


def _has_grounding(used: Dict[str, bool], context_text: str) -> bool:
    return used["ragUsed"] or bool(context_text.strip())


# ── 복습 추천일 계산 ──────────────────────────────────────────────────────────
def _review_date(days: int) -> str:
    return (date.today() + timedelta(days=max(0, int(days)))).isoformat()


def _clamp_days(value: Any, default: int) -> int:
    try:
        d = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(30, d))


# ════════════════════════════════════════════════════════════════════════════
# taskType 핸들러
# ════════════════════════════════════════════════════════════════════════════
def handle_chat(req: "LearningLoopRequest") -> Dict[str, Any]:
    context_text, used, _chunks = assemble_context(req)
    warnings: List[str] = []
    question = (req.userQuestion or "").strip() or "이 자료의 핵심 개념을 설명해줘"

    system = (
        "너는 StudyBridge 학습 도우미다. 학습자가 올린 자료와 학습 이력을 바탕으로 질문에 답한다.\n"
        "규칙:\n"
        "1. 자료 본문 근거(RAG/sourceText)가 있으면 그것을 최우선으로 답한다.\n"
        "2. 근거에 없는 내용은 지어내지 않는다. 모르면 모른다고 말한다.\n"
        "3. 컨텍스트에 없는 교수명/연도/강의명/사람 이름을 임의로 만들지 않는다.\n"
        "4. 오답노트가 있으면 '이전에 헷갈렸던 부분'으로, 사용자 메모가 있으면 '사용자가 헷갈린 지점'으로 반영한다.\n"
        "5. 과도하게 길게 쓰지 말고 학습용으로 구조화해 답한다. 한국어.\n"
        "6. 마크다운 강조(별표/해시)는 쓰지 않는다."
    )
    user = (
        (f"## 학습 컨텍스트\n{context_text}\n\n" if context_text.strip() else "")
        + f"## 학습자 질문\n{question}\n\n위 컨텍스트를 근거로 답하라."
    )
    answer = _llm_text(system, user, max_tokens=900, temperature=0.4)

    if not answer:
        warnings.append("LLM 응답을 생성하지 못해 fallback 안내를 반환했습니다.")
        if context_text.strip():
            answer = ("현재 AI 응답 생성이 지연되어 자료 근거를 충분히 풀어 설명하지 못했습니다. "
                      "잠시 후 다시 질문해 주세요. 자료의 핵심 키워드를 중심으로 먼저 살펴보면 도움이 됩니다.")
        else:
            answer = ("이 질문에 답하려면 자료 본문이나 학습 컨텍스트가 필요합니다. "
                      "자료를 선택했는지 확인하거나 질문을 더 구체적으로 적어 주세요.")

    follow_ups = ["이 개념을 예제로 풀어볼까요?"]
    if used["wrongNotesUsed"]:
        follow_ups.append("관련 오답노트를 복습할까요?")
    else:
        follow_ups.append("핵심 개념으로 짧은 퀴즈를 만들어볼까요?")

    return {
        "answer": answer,
        "usedContext": used,
        "followUpQuestions": follow_ups,
        "warnings": warnings,
    }


def handle_summary(req: "LearningLoopRequest") -> Dict[str, Any]:
    context_text, used, _chunks = assemble_context(req)
    warnings: List[str] = []

    def _valid(d: Dict[str, Any]) -> bool:
        return (bool((d.get("summary") or "").strip())
                and isinstance(d.get("keyPoints"), list) and len(d.get("keyPoints")) >= 1)

    draft_system = (
        "너는 학습 자료 요약기다. 자료 본문 근거를 바탕으로 학습자가 바로 복습할 수 있게 요약한다.\n"
        "원문에 없는 교수명/날짜/과목명을 지어내지 않는다. 제목이 없으면 내용 기반으로 자연스럽게 만든다.\n"
        "반드시 한국어, 마크다운 없이 JSON 한 개로만 응답한다.\n"
        '{ "title":"내용 기반 제목", "summary":"전체 요약 3~5문장", '
        '"keyPoints":["핵심 개념1","핵심 개념2","핵심 개념3"], '
        '"keywords":["키워드1","키워드2"], '
        '"recommendedReviewInDays": 3, "recommendedReviewReason":"복습 주기 권장 사유" }'
    )
    draft_user = (
        (f"## 자료/학습 컨텍스트\n{context_text}\n\n" if context_text.strip() else "## 자료\n(본문 근거 없음)\n\n")
        + (f"## 자료 제목 힌트\n{req.title}\n\n" if (req.title or '').strip() else "")
        + "위 내용을 학습 복습용으로 요약해 JSON 으로만 응답하라."
    )

    result = None
    if _has_grounding(used, context_text):
        result = _llm_struct(draft_system=draft_system, draft_user=draft_user, validator=_valid, max_tokens=1200)

    if result and _valid(result):
        days = _clamp_days(result.get("recommendedReviewInDays"), 3)
        return {
            "title": _clean(result.get("title")) or (req.title or "학습 자료 요약"),
            "summary": _clean(result.get("summary")),
            "keyPoints": _str_items(result.get("keyPoints"), 8),
            "keywords": _str_items(result.get("keywords"), 12),
            "recommendedReviewInDays": days,
            "recommendedReviewDate": _review_date(days),
            "recommendedReviewReason": _clean(result.get("recommendedReviewReason")) or "핵심 개념 정착을 위해 단기 복습을 권장합니다.",
            "usedContext": used,
            "warnings": warnings,
        }

    # deterministic fallback (근거 텍스트에서 키워드/문장 추출)
    warnings.append("LLM 요약 생성에 실패하여 컨텍스트 기반 fallback 요약을 반환했습니다.")
    sents = [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n", context_text) if len(s.strip()) >= 12]
    key_points = sents[:5] or ["자료의 핵심 내용을 다시 확인해 주세요."]
    kw_counts: Dict[str, int] = {}
    for k in _keywords(context_text):
        if len(k) >= 3:
            kw_counts[k] = kw_counts.get(k, 0) + 1
    keywords = [w for w, _ in sorted(kw_counts.items(), key=lambda kv: kv[1], reverse=True)][:8]
    return {
        "title": req.title or "학습 자료 요약",
        "summary": (" ".join(key_points[:3]))[:600] or "자료 요약을 생성하지 못했습니다.",
        "keyPoints": key_points,
        "keywords": keywords,
        "recommendedReviewInDays": 3,
        "recommendedReviewDate": _review_date(3),
        "recommendedReviewReason": "기초 개념 정착을 위해 단기 복습을 권장합니다.",
        "usedContext": used,
        "warnings": warnings,
    }


def _normalize_quiz_item(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    choices = [_clean(c) for c in _as_list(raw.get("choices") or raw.get("options")) if str(c).strip()]
    if len(choices) != 4 or len(set(choices)) != 4:
        return None
    question = _clean(raw.get("question") or raw.get("questionText"))
    if not question:
        return None
    answer = _clean(raw.get("answer") or raw.get("correctAnswer"))
    idx = raw.get("answerIndex")
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        idx = -1
    if answer and answer in choices:
        idx = choices.index(answer)
    elif 0 <= idx < 4:
        answer = choices[idx]
    else:
        return None
    explanation = _clean(raw.get("explanation"))
    if not explanation:
        return None
    return {
        "question": question,
        "choices": choices,
        "answerIndex": idx,
        "answer": answer,
        "explanation": explanation,
        "sourceHint": _clean(raw.get("sourceHint")),
        "concept": _clean(raw.get("concept")),
    }


def handle_quiz(req: "LearningLoopRequest") -> Dict[str, Any]:
    context_text, used, _chunks = assemble_context(req)
    warnings: List[str] = []
    want = max(1, min(10, req.count or 5))

    def _valid(d: Dict[str, Any]) -> bool:
        items = [_normalize_quiz_item(it) for it in _as_list(d.get("items"))]
        return any(it is not None for it in items)

    draft_system = (
        "너는 학습 퀴즈 출제기다. 자료 본문 근거를 바탕으로 4지선다 문제를 만든다.\n"
        "규칙: 선택지는 정확히 4개, answerIndex 는 0부터 시작, 정답과 해설은 반드시 포함.\n"
        "오답노트가 있으면 같은 개념을 다른 맥락으로 다시 점검하는 문제를 일부 포함하되, "
        "원본 문제를 복붙하지 말고 변형한다. 본문에 없는 내용을 지어내지 않는다.\n"
        "반드시 한국어, 마크다운 없이 JSON 한 개로만 응답한다.\n"
        '{ "quizTitle":"제목", "difficulty":"중", "items":[ '
        '{ "question":"...", "choices":["A","B","C","D"], "answerIndex":0, '
        '"answer":"choices 중 하나와 동일", "explanation":"왜 정답인지", '
        '"sourceHint":"근거 위치", "concept":"개념명" } ] }'
    )
    draft_user = (
        (f"## 자료/학습 컨텍스트\n{context_text}\n\n" if context_text.strip() else "## 자료\n(본문 근거 없음)\n\n")
        + f"## 요청 문항 수\n{want}\n\n위 내용으로 4지선다 퀴즈를 JSON 으로만 만들어라."
    )

    items: List[Dict[str, Any]] = []
    title = req.title or "학습 자료 퀴즈"
    difficulty = req.difficulty or "중"
    if _has_grounding(used, context_text):
        result = _llm_struct(draft_system=draft_system, draft_user=draft_user, validator=_valid,
                             max_tokens=1100 + 350 * want)
        if isinstance(result, dict):
            title = _clean(result.get("quizTitle")) or title
            difficulty = _clean(result.get("difficulty")) or difficulty
            for it in _as_list(result.get("items")):
                norm = _normalize_quiz_item(it)
                if norm:
                    items.append(norm)
                if len(items) >= want:
                    break

    if not items:
        warnings.append("LLM 퀴즈 생성에 실패하여 빈 items 를 반환했습니다(자료 근거 부족 또는 응답 지연).")

    return {
        "quizTitle": title,
        "difficulty": difficulty,
        "items": items,
        "usedContext": used,
        "warnings": warnings,
    }


def handle_roadmap(req: "LearningLoopRequest") -> Dict[str, Any]:
    context_text, used, _chunks = assemble_context(req)
    warnings: List[str] = []

    def _valid(d: Dict[str, Any]) -> bool:
        items = _as_list(d.get("items"))
        return any(isinstance(it, dict) and (it.get("theme") or it.get("goals") or it.get("tasks")) for it in items)

    draft_system = (
        "너는 학습 로드맵 설계기다. 자료 본문 근거를 바탕으로 주차별 학습 계획을 만든다.\n"
        "오답/약점이 있으면 앞 주차에 보강 학습을 배치한다. 본문에 없는 내용을 지어내지 않는다.\n"
        "반드시 한국어, 마크다운 없이 JSON 한 개로만 응답한다.\n"
        '{ "title":"로드맵 제목", "items":[ '
        '{ "week":1, "theme":"주차 주제", "goals":["학습 목표"], "tasks":["할 일"] } ], '
        '"recommendedReviewInDays": 7, "recommendedReviewReason":"사유" }'
    )
    draft_user = (
        (f"## 자료/학습 컨텍스트\n{context_text}\n\n" if context_text.strip() else "## 자료\n(본문 근거 없음)\n\n")
        + (f"## 자료 제목 힌트\n{req.title}\n\n" if (req.title or '').strip() else "")
        + "위 내용으로 주차별 학습 로드맵을 JSON 으로만 만들어라."
    )

    items: List[Dict[str, Any]] = []
    title = req.title or "학습 로드맵"
    days = 7
    reason = "주차별 학습 후 복습 주기를 권장합니다."
    if _has_grounding(used, context_text):
        result = _llm_struct(draft_system=draft_system, draft_user=draft_user, validator=_valid, max_tokens=1600)
        if isinstance(result, dict):
            title = _clean(result.get("title")) or title
            days = _clamp_days(result.get("recommendedReviewInDays"), 7)
            reason = _clean(result.get("recommendedReviewReason")) or reason
            for i, it in enumerate(_as_list(result.get("items"))[:12], start=1):
                if not isinstance(it, dict):
                    continue
                try:
                    week = int(it.get("week", i))
                except (TypeError, ValueError):
                    week = i
                items.append({
                    "week": week,
                    "theme": _clean(it.get("theme") or it.get("focus")),
                    "goals": _str_items(it.get("goals"), 6),
                    "tasks": _str_items(it.get("tasks"), 8),
                })

    if not items:
        warnings.append("LLM 로드맵 생성에 실패하여 빈 items 를 반환했습니다.")

    return {
        "title": title,
        "items": items,
        "recommendedReviewInDays": days,
        "recommendedReviewDate": _review_date(days),
        "recommendedReviewReason": reason,
        "usedContext": used,
        "warnings": warnings,
    }


_EXPL_FIELDS = ("answer", "whyWrong", "correctConcept", "memoryTip")


def handle_wrong_note_explanation(req: "LearningLoopRequest") -> Dict[str, Any]:
    context_text, used, _chunks = assemble_context(req)
    warnings: List[str] = []

    def _valid(d: Dict[str, Any]) -> bool:
        return all((d.get(f) or "").strip() for f in _EXPL_FIELDS)

    draft_system = (
        "너는 오답 분석 코치다. 단순 정답 설명이 아니라 왜 틀렸는지/정확한 개념/암기 팁/유사 개념을 분석한다.\n"
        "자료 근거가 있으면 그 개념과 연결한다. 본문에 없는 내용을 지어내지 않는다.\n"
        "반드시 한국어, 마크다운 없이 JSON 한 개로만 응답한다.\n"
        '{ "answer":"AI 해설 본문", "whyWrong":"사용자가 헷갈린 이유", '
        '"correctConcept":"정확한 개념", "memoryTip":"암기 팁", '
        '"similarConcepts":["관련 개념1","관련 개념2"], '
        '"recommendReviewInDays":2, "recommendedReviewReason":"사유" }'
    )
    draft_user = (
        (f"## 자료/학습 컨텍스트\n{context_text}\n\n" if context_text.strip() else "")
        + (f"## 질문/오답 내용\n{req.userQuestion}\n\n" if (req.userQuestion or '').strip() else "")
        + "위 오답을 분석해 JSON 으로만 응답하라."
    )

    result = _llm_struct(draft_system=draft_system, draft_user=draft_user, validator=_valid, max_tokens=1300)
    if result and _valid(result):
        days = _clamp_days(result.get("recommendReviewInDays"), 2)
        return {
            "answer": _clean(result.get("answer")),
            "whyWrong": _clean(result.get("whyWrong")),
            "correctConcept": _clean(result.get("correctConcept")),
            "memoryTip": _clean(result.get("memoryTip")),
            "similarConcepts": _str_items(result.get("similarConcepts"), 6),
            "recommendReviewInDays": days,
            "recommendedReviewDate": _review_date(days),
            "recommendedReviewReason": _clean(result.get("recommendedReviewReason")) or "개념 혼동형 오답이므로 짧은 주기 복습이 적합합니다.",
            "usedContext": used,
            "warnings": warnings,
        }

    warnings.append("LLM 오답 해설 생성에 실패하여 fallback 안내를 반환했습니다.")
    return {
        "answer": "현재 AI 해설 생성이 지연되었습니다. 오답노트의 정답과 해설을 먼저 다시 확인해 주세요.",
        "whyWrong": "헷갈린 지점을 자동 분석하지 못했습니다.",
        "correctConcept": "자료의 정답 개념을 다시 확인해 주세요.",
        "memoryTip": "정답 개념과 자신이 고른 답의 차이를 한 문장으로 정리해 보세요.",
        "similarConcepts": [],
        "recommendReviewInDays": 2,
        "recommendedReviewDate": _review_date(2),
        "recommendedReviewReason": "개념 혼동형 오답이므로 짧은 주기 복습이 적합합니다.",
        "usedContext": used,
        "warnings": warnings,
    }


def handle_similar_question(req: "LearningLoopRequest") -> Dict[str, Any]:
    context_text, used, _chunks = assemble_context(req)
    warnings: List[str] = []
    want = max(1, min(5, req.count or 1))

    def _valid(d: Dict[str, Any]) -> bool:
        return any(_normalize_quiz_item(it) is not None for it in _as_list(d.get("items")))

    draft_system = (
        "너는 오답 복습용 유사문제 출제기다. 원본 오답과 같은 핵심 개념을 다른 맥락으로 묻는 "
        "4지선다 문제를 만든다. 원본 문제를 복붙하지 말고 변형한다. choices 는 정확히 4개, "
        "answerIndex 는 0부터, 정답·해설 포함. 본문/오답 근거에 없는 내용은 지어내지 않는다.\n"
        "반드시 한국어, 마크다운 없이 JSON 한 개로만 응답한다.\n"
        '{ "items":[ { "question":"...", "choices":["A","B","C","D"], "answerIndex":0, '
        '"answer":"choices 중 하나", "explanation":"왜 정답인지", '
        '"originalWrongConcept":"원본 오개념", "variationType":"개념 변형" } ] }'
    )
    draft_user = (
        (f"## 자료/오답 컨텍스트\n{context_text}\n\n" if context_text.strip() else "")
        + (f"## 원본 오답/질문\n{req.userQuestion}\n\n" if (req.userQuestion or '').strip() else "")
        + f"## 생성할 문항 수\n{want}\n\n위 오답과 같은 개념의 유사문제를 JSON 으로만 만들어라."
    )

    items: List[Dict[str, Any]] = []
    result = _llm_struct(draft_system=draft_system, draft_user=draft_user, validator=_valid,
                         max_tokens=1100 + 400 * want)
    if isinstance(result, dict):
        for it in _as_list(result.get("items")):
            norm = _normalize_quiz_item(it)
            if norm:
                if isinstance(it, dict):
                    norm["originalWrongConcept"] = _clean(it.get("originalWrongConcept"))
                    norm["variationType"] = _clean(it.get("variationType")) or "개념 변형"
                items.append(norm)
            if len(items) >= want:
                break

    if not items:
        warnings.append("LLM 유사문제 생성에 실패하여 빈 items 를 반환했습니다.")

    return {
        "items": items,
        "recommendReviewInDays": 2,
        "recommendedReviewDate": _review_date(2),
        "recommendedReviewReason": "동일 개념의 변형 문제로 오답 패턴을 교정하세요.",
        "usedContext": used,
        "warnings": warnings,
    }


def handle_review_recommendation(req: "LearningLoopRequest") -> Dict[str, Any]:
    context_text, used, _chunks = assemble_context(req)
    warnings: List[str] = []

    def _valid(d: Dict[str, Any]) -> bool:
        return (bool((d.get("reviewTitle") or "").strip())
                and bool((d.get("reviewReason") or "").strip()))

    draft_system = (
        "너는 학습 복습 추천기다. 최근 오답/퀴즈/요약/메모를 종합해 언제 무엇을 복습할지 추천한다.\n"
        "본문에 없는 내용을 지어내지 않는다. 반드시 한국어, 마크다운 없이 JSON 한 개로만 응답한다.\n"
        '{ "recommendReviewInDays":3, "reviewTitle":"복습 제목", "reviewReason":"권장 사유", '
        '"suggestedTasks":["오답노트 다시 풀기","유사문제 풀이","핵심 요약 복습"] }'
    )
    draft_user = (
        (f"## 학습 컨텍스트\n{context_text}\n\n" if context_text.strip() else "## 학습 컨텍스트\n(이력 없음)\n\n")
        + "위 이력을 종합해 복습 추천을 JSON 으로만 만들어라."
    )

    result = _llm_struct(draft_system=draft_system, draft_user=draft_user, validator=_valid, max_tokens=900)
    if result and _valid(result):
        days = _clamp_days(result.get("recommendReviewInDays"), 3)
        tasks = _str_items(result.get("suggestedTasks"), 6) or ["오답노트 다시 풀기", "유사문제 풀이", "핵심 요약 복습"]
        return {
            "recommendReviewInDays": days,
            "recommendedReviewDate": _review_date(days),
            "reviewTitle": _clean(result.get("reviewTitle")),
            "reviewReason": _clean(result.get("reviewReason")),
            "suggestedTasks": tasks,
            "usedContext": used,
            "warnings": warnings,
        }

    warnings.append("LLM 복습 추천 생성에 실패하여 기본 추천을 반환했습니다.")
    days = 3 if (used["wrongNotesUsed"] or used["quizResultsUsed"]) else 5
    return {
        "recommendReviewInDays": days,
        "recommendedReviewDate": _review_date(days),
        "reviewTitle": (req.title or "학습 복습") + " 복습",
        "reviewReason": ("최근 오답/퀴즈 이력이 있어 단기 복습을 권장합니다."
                         if days == 3 else "학습 정착을 위해 정기 복습을 권장합니다."),
        "suggestedTasks": ["오답노트 다시 풀기", "유사문제 3개 풀이", "핵심 요약 5분 복습"],
        "usedContext": used,
        "warnings": warnings,
    }


_MODE_GUIDE = {
    "SOCRATIC": ("너는 소크라테스식 튜터다. 정답을 바로 다 말하지 말고 꼬리질문과 사고 유도 중심으로 "
                 "답한다. 단, 학습자가 너무 막히면 힌트를 제공한다."),
    "DEBATE": ("너는 토론 진행자다. 찬성/반대/중립 등 관점별로 구분해 제시하고, 한쪽 결론으로 "
               "자동 합성하지 않는다."),
    "ROLEPLAY": ("너는 상황극 파트너다. 역할과 상황을 유지하되, 학습 목적에서 벗어난 과도한 연극식 "
                 "장문은 피한다."),
}


def handle_agent_chat_feedback(req: "LearningLoopRequest") -> Dict[str, Any]:
    """멀티에이전트 구조(FIRST_ANSWER/VALIDATION/PEER_FEEDBACK)를 유지한다.
    이 비스트리밍 진입점은 FIRST_ANSWER 단계만 생성하며 자동 최종합성을 하지 않는다.
    VALIDATION/PEER_FEEDBACK 은 기존 SSE 멀티에이전트 경로에서 수행된다."""
    context_text, used, _chunks = assemble_context(req)
    warnings: List[str] = []
    mode = (req.mode or "").strip().upper()
    mode_guide = _MODE_GUIDE.get(mode, "너는 학습 도우미다. 학습자의 질문에 근거 기반으로 답한다.")

    # 최근 사용자 피드백 반영 (현재 요청 mode/personality/level > 최근 피드백 > 기본값)
    feedback_note = ""
    if req.learningLoopContext and _as_list(req.learningLoopContext.agentFeedback):
        fbs = []
        for fb in _as_list(req.learningLoopContext.agentFeedback)[-3:]:
            txt = _clean(fb.get("feedback") if isinstance(fb, dict) else fb)
            if txt:
                fbs.append(txt)
        if fbs:
            feedback_note = "## 최근 사용자 피드백(반영)\n" + "\n".join(f"- {f}" for f in fbs) + "\n\n"

    system = (
        f"{mode_guide}\n"
        f"성격: {req.personality or '기본'} / 지식수준: {req.knowledgeLevel or '기본'}.\n"
        "자료 근거가 있으면 우선하고 없는 내용은 지어내지 않는다. 한국어. 마크다운 강조 금지.\n"
        "이것은 1차 답변(FIRST_ANSWER)이다. 최종 결론으로 단정 합성하지 않는다."
    )
    user = (
        (f"## 학습 컨텍스트\n{context_text}\n\n" if context_text.strip() else "")
        + feedback_note
        + f"## 질문\n{(req.userQuestion or '').strip() or '학습 주제를 설명해줘'}\n\n"
        "위 지시(mode/성격/지식수준/피드백)에 맞춰 1차 답변을 작성하라."
    )
    answer = _llm_text(system, user, max_tokens=1000, temperature=0.5)
    if not answer:
        warnings.append("LLM 응답 생성에 실패하여 fallback 안내를 반환했습니다.")
        answer = "현재 AI 응답이 지연되고 있습니다. 잠시 후 다시 시도하거나 질문을 더 구체적으로 적어 주세요."

    return {
        "answer": answer,
        "stage": "FIRST_ANSWER",
        "stages": ["FIRST_ANSWER", "VALIDATION", "PEER_FEEDBACK"],
        "autoSynthesized": False,
        "mode": mode or None,
        "personality": req.personality,
        "knowledgeLevel": req.knowledgeLevel,
        "usedContext": used,
        "warnings": warnings,
    }


# ── 디스패치 ──────────────────────────────────────────────────────────────────
_HANDLERS: Dict[str, Callable[["LearningLoopRequest"], Dict[str, Any]]] = {
    "AI_CHAT_WITH_LEARNING_LOOP": handle_chat,
    "SUMMARY_WITH_LEARNING_LOOP": handle_summary,
    "QUIZ_WITH_LEARNING_LOOP": handle_quiz,
    "ROADMAP_WITH_LEARNING_LOOP": handle_roadmap,
    "WRONG_NOTE_EXPLANATION": handle_wrong_note_explanation,
    "SIMILAR_QUESTION_FROM_WRONG_NOTE": handle_similar_question,
    "REVIEW_RECOMMENDATION": handle_review_recommendation,
    "AGENT_CHAT_WITH_FEEDBACK": handle_agent_chat_feedback,
}

SUPPORTED_TASK_TYPES = tuple(_HANDLERS.keys())


def run_learning_loop(req: "LearningLoopRequest") -> Dict[str, Any]:
    """taskType 디스패치. 미지원/예외도 success:false 또는 안전 응답으로 반환하고 서버를 죽이지 않는다."""
    task_type = (req.taskType or "").strip().upper()
    handler = _HANDLERS.get(task_type)
    if handler is None:
        return {
            "success": False,
            "taskType": task_type or "UNKNOWN",
            "errorCode": "UNSUPPORTED_TASK_TYPE",
            "usedContext": _new_used(),
            "warnings": [f"지원하지 않는 taskType 입니다: {task_type or '(빈 값)'}"],
        }
    try:
        result = handler(req)
    except Exception as e:  # noqa: BLE001
        logger.error("[learning_loop] %s 처리 실패: %s", task_type, e, exc_info=True)
        return {
            "success": False,
            "taskType": task_type,
            "errorCode": "LEARNING_LOOP_FAILED",
            "usedContext": _new_used(),
            "warnings": [f"처리 중 오류가 발생했습니다: {type(e).__name__}"],
        }
    result.setdefault("usedContext", _new_used())
    result.setdefault("warnings", [])
    return {"success": True, "taskType": task_type, **result}
