"""
자료보관함 라이브 AI 엔드포인트 — Spring AiIntegrationService 계약.

실제 사용자 화면(ArchiveDetail) → Spring AiIntegrationService → 아래 엔드포인트.
직전까지 FastAPI 측에 이 경로들이 정의되어 있지 않아 자료보관함 요약/질문/로드맵/퀴즈가
연결되지 않았다(이 라우터가 그 미연결을 해소한다).

  POST /api/ai/summary   {text}                              -> {overview, coreContents, ...}
  POST /api/ai/quiz      {text, difficulty, questionCount}   -> {quizData, ...}
  POST /api/ai/question  {text, question}                    -> {answer, ...}
  POST /api/ai/roadmap   {material_id, pdf_text, user_goal}  -> {roadmap:{title,steps}, ...}
  POST /api/ai/feedback  {content}                           -> {feedbackData, ...}

모델 라우팅: 요약=Ollama/Qwen 우선(GPT fallback), 로드맵/퀴즈=GPT, 질문=Ollama+GPT fallback.
PDF 텍스트는 chunk 단위로 처리하며, 전체 endpoint hard timeout은 115초.
응답은 success/errorCode/textStatus/warnings/metadata + 기존 하위호환 필드를 함께 싣는다.
"""
import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["Material AI (live)"])

# 기능별 hard timeout (전체 2분 예산 내)
SUMMARY_TIMEOUT = int(os.getenv("AI_SUMMARY_TIMEOUT_SECONDS", "90"))
ROADMAP_TIMEOUT = int(os.getenv("AI_ROADMAP_TIMEOUT_SECONDS", "110"))
QUIZ_TIMEOUT = int(os.getenv("AI_QUIZ_TIMEOUT_SECONDS", "90"))
QA_TIMEOUT = int(os.getenv("AI_QA_TIMEOUT_SECONDS", "115"))
HARD_CAP = int(os.getenv("AI_GLOBAL_TIMEOUT_SECONDS", "120")) - 5


def _t(v: int) -> int:
    return min(v, HARD_CAP)


# ── 요청 모델 (관대하게 — 누락 필드 허용) ─────────────────────────────────────
class SummaryReq(BaseModel):
    text: Optional[str] = None
    document_title: Optional[str] = None
    material_id: Optional[int] = None


class QuizReq(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    text: Optional[str] = None
    material_id: Optional[int] = Field(None, validation_alias=AliasChoices("material_id", "materialId"))
    difficulty: Optional[str] = "보통"
    questionCount: Optional[int] = Field(5, validation_alias=AliasChoices("questionCount", "quizCount", "count", "numQuestions", "question_count"))
    document_title: Optional[str] = Field(None, validation_alias=AliasChoices("document_title", "documentTitle", "title"))


class QuestionReq(BaseModel):
    text: Optional[str] = None
    question: Optional[str] = None
    material_id: Optional[int] = None


class RoadmapReq(BaseModel):
    material_id: Optional[int] = None
    pdf_text: Optional[str] = None
    user_goal: Optional[str] = None
    text: Optional[str] = None  # 하위호환


class FeedbackReq(BaseModel):
    content: Optional[str] = None


def _fail(error_code: str, message: str, retryable: bool = True,
          text_status: Optional[dict] = None) -> Dict[str, Any]:
    return {
        "success": False,
        "errorCode": error_code,
        "message": message,
        "retryable": retryable,
        "textStatus": text_status or {"hasText": False, "textLength": 0, "chunkCount": 0, "status": "EMPTY"},
        "warnings": [],
    }


def _text_status(ts: dict, chunk_count: int) -> dict:
    return {
        "hasText": ts["ok"] and ts["status"] != "empty",
        "textLength": ts["textLength"],
        "chunkCount": chunk_count,
        "status": "READY" if ts["status"] == "ok" else (
            "TOO_SHORT" if ts["status"] == "too_short" else "EMPTY"),
        "warnings": ts.get("warnings", []),
    }


def _quiz_fallback_payload(context: str, difficulty: str, count: int,
                           ts: dict, chunk_count: int, reason: str) -> Dict[str, Any]:
    """AI 퀴즈 생성 실패(timeout/parse/검증 실패/빈 응답) 시에도 문서 기반 기본 문제를
    항상 반환한다. 빈 결과나 에러만 돌려주지 않는다(사용자 요구: 무조건 문제 노출)."""
    count = max(3, min(int(count or 5), 20))
    raw: List[Dict[str, Any]] = []
    try:
        from app.services.realtime_quiz_service import _document_grounded_fallback
        raw = _document_grounded_fallback(context or "", count, difficulty or "보통", ["multiple_choice"])
    except Exception as e:  # noqa: BLE001
        logger.warning("quiz 문서기반 fallback 생성 실패(generic 사용): %s", e)
    questions: List[Dict[str, Any]] = []
    for q in raw:
        opts = q.get("choices") or []
        ai = q.get("answer_index")
        ai = ai if isinstance(ai, int) and 0 <= ai < len(opts) else 0
        questions.append({
            "question": (q.get("question") or "").strip(),
            "options": opts,
            "answer": ai,            # 프론트 parseQuizQuestions는 숫자 인덱스를 기대
            "answerIndex": ai,
            "explanation": (q.get("explanation") or "").strip(),
            "difficulty": q.get("difficulty") or difficulty or "보통",
            "source": "FALLBACK",
        })
    if not questions:  # 문서 기반도 비면 안내형 generic 으로 최종 보장
        for i in range(count):
            questions.append({
                "question": f"학습 자료 복습 문항 {i + 1}: 이 자료의 핵심 개념을 가장 잘 설명한 것은?",
                "options": ["자료의 핵심 개념", "관련 없는 내용", "부분적으로만 맞는 설명", "반대되는 설명"],
                "answer": 0, "answerIndex": 0,
                "explanation": "AI 생성이 일시적으로 어려워 기본 복습 문항으로 대체했습니다. 자료를 다시 확인해 보세요.",
                "difficulty": difficulty or "보통", "source": "FALLBACK",
            })
    logger.warning("material quiz fallback 사용 reason=%s count=%s", reason, len(questions))
    return {
        "success": True,
        "quizData": json.dumps(questions, ensure_ascii=False),  # 하위호환 (Spring이 그대로 저장)
        "quizzes": questions,
        "warnings": ["AI 퀴즈 생성에 실패하여 문서 기반 기본 문제로 대체했습니다."],
        "textStatus": _text_status(ts, chunk_count),
        "metadata": {"provider": "fallback", "usedFallback": True,
                     "fallbackReason": reason, "chunkCount": chunk_count},
    }


def _roadmap_fallback_payload(document_title: str, ts: dict, chunk_count: int,
                              reason: str) -> Dict[str, Any]:
    """AI 로드맵 생성 실패(timeout/parse/검증 실패/빈 weeks) 시에도 기본 로드맵을 항상
    반환한다. UNKNOWN_ERROR/빈 weeks/500 으로 끝내지 않는다(success 구조 동일 유지)."""
    title = (document_title or "").strip() or "학습 자료"
    try:
        from app.services.roadmap_service import build_fallback_roadmap
        fb = build_fallback_roadmap(0, title, reason)
        fb_weeks = fb.get("weeks", []) if isinstance(fb, dict) else []
    except Exception as e:  # noqa: BLE001
        logger.warning("roadmap 기본 fallback 생성 실패(generic 사용): %s", e)
        fb, fb_weeks = {}, []
    steps: List[Dict[str, Any]] = []
    for i, wk in enumerate(fb_weeks):
        task_values = wk.get("tasks") if isinstance(wk.get("tasks"), list) else []
        tasks = [{"taskOrder": j + 1, "content": str(t).strip()}
                 for j, t in enumerate(task_values) if str(t).strip()]
        if not tasks:
            tasks = [
                {"taskOrder": 1, "content": "문서 핵심 내용을 읽고 요약하기"},
                {"taskOrder": 2, "content": "이해가 부족한 개념을 질문 목록으로 정리하기"},
            ]
        steps.append({
            "stepOrder": wk.get("week") or (i + 1),
            "title": wk.get("title") or f"{i + 1}주차",
            "description": f"학습 목표: {wk.get('goal', '')}".strip() or "학습 목표 정리",
            "tasks": tasks,
            "goal": wk.get("goal") or "",
            "keyConcepts": [],
            "deliverable": "",
            "estimatedHours": 3,
        })
    if not steps:  # roadmap_service 도 비면 최소 4주 generic 보장
        for i, (t, g) in enumerate([
            ("기초 개념 이해", "핵심 개념과 용어를 파악한다."),
            ("심화 학습", "주요 개념의 원리와 구조를 이해한다."),
            ("응용 및 정리", "학습 내용을 실제 문제에 적용한다."),
            ("복습 및 완성", "전체 내용을 통합하고 부족한 부분을 보완한다."),
        ]):
            steps.append({
                "stepOrder": i + 1, "title": f"{i + 1}주차 {t}",
                "description": f"학습 목표: {g}",
                "tasks": [{"taskOrder": 1, "content": "문서 핵심 내용을 읽고 요약하기"},
                          {"taskOrder": 2, "content": "핵심 개념 정리 및 자기 점검"}],
                "goal": g, "keyConcepts": [], "deliverable": "", "estimatedHours": 3,
            })
    logger.warning("material roadmap fallback 사용 reason=%s weeks=%s", reason, len(steps))
    return {
        "success": True,
        "roadmap": {"title": (fb.get("title") if isinstance(fb, dict) else None) or f"{title} 학습 로드맵 (기본 구성)",
                    "totalWeeks": len(steps), "steps": steps},
        "warnings": ["AI 로드맵 생성에 실패하여 기본 로드맵으로 대체했습니다."],
        "fallbackUsed": True,
        "message": "AI 로드맵 생성이 불안정하여 기본 로드맵을 생성했습니다.",
        "textStatus": _text_status(ts, chunk_count),
        "metadata": {"provider": "fallback", "usedFallback": True,
                     "fallbackReason": reason, "chunkCount": chunk_count},
    }


# ── POST /api/ai/summary ──────────────────────────────────────────────────────
@router.post("/summary", summary="자료 요약 (Ollama/Qwen 우선)")
async def ai_summary(req: SummaryReq) -> Dict[str, Any]:
    from app.services.material_ai_manager import (
        validate_extracted_text, build_summary_context, summarize_document, ocr_unavailable_status,
    )
    from app.services.chunk_cache import get_or_build_chunks
    started = time.time()
    ts = validate_extracted_text(req.text)
    if not ts["ok"]:
        return {**_fail("PDF_OCR_REQUIRED",
                     "이미지 기반 PDF라 텍스트 추출이 필요합니다. OCR 설정을 켠 뒤 다시 시도해주세요.",
                     text_status=_text_status(ts, 0)), "metadata": {"ocr": ocr_unavailable_status()}}
    cache = await get_or_build_chunks(req.material_id, req.text)
    chunks = cache["chunks"]
    context = build_summary_context(chunks) or (req.text or "")[:6000]
    try:
        r = await asyncio.wait_for(asyncio.to_thread(
            summarize_document,
            document_title=req.document_title or "자료",
            text=context,
        ), timeout=_t(SUMMARY_TIMEOUT))
    except asyncio.TimeoutError:
        return _fail("AI_TIMEOUT", "AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.",
                     text_status=_text_status(ts, len(chunks)))
    except Exception as e:
        logger.error("summary 실패: %s", e)
        return _fail("SUMMARY_VALIDATE_FAILED", "요약 생성에 실패했습니다. 다시 시도해주세요.",
                     text_status=_text_status(ts, len(chunks)))

    sections = r.get("sections") or []
    core_items = [
        {
            "title": s.get("title", ""),
            "content": s.get("content", s.get("description", "")),
            "description": s.get("description", s.get("content", "")),
        }
        for s in sections
    ]
    core_contents = json.dumps(core_items, ensure_ascii=False)
    elapsed = int((time.time() - started) * 1000)
    logger.info("summary done provider=%s elapsedMs=%s textLen=%s chunks=%s",
                r.get("provider"), elapsed, ts["textLength"], len(chunks))
    return {
        "success": True,
        # 하위호환
        "summary": r.get("summary", ""),
        "key_points": r.get("key_points", []),
        "gpt_raw": r.get("gpt_raw", ""),
        "overview": r.get("overview", ""),
        "coreContents": core_contents,
        # 확장
        "keywords": r.get("keywords", []),
        "sections": core_items,
        "learningPoints": r.get("learningPoints", []),
        "practicePoints": r.get("practicePoints", []),
        "studyQuestions": r.get("studyQuestions", []),
        "warnings": r.get("warnings", []),
        "textStatus": _text_status(ts, len(chunks)),
        "metadata": {
            "provider": r.get("provider", "ollama"),
            "model": os.getenv("OLLAMA_SUMMARY_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5:14b")),
            "elapsedMs": elapsed,
            "usedFallback": r.get("usedFallback", False),
            "cacheHit": cache["cacheHit"],
            "cacheBackend": cache["cacheBackend"],
            "chunkCount": len(chunks),
            "extractedTextHash": cache.get("extractedTextHash"),
        },
    }


# ── POST /api/ai/quiz ─────────────────────────────────────────────────────────
@router.post("/quiz", summary="자료 퀴즈 생성 (GPT, 구조화 JSON)")
async def ai_quiz(req: QuizReq) -> Dict[str, Any]:
    from app.services.material_ai_manager import (
        validate_extracted_text, build_limited_context, generate_quiz_json, AI_QUIZ_MAX_CHUNKS, ocr_unavailable_status,
    )
    from app.services.chunk_cache import get_or_build_chunks
    started = time.time()
    ts = validate_extracted_text(req.text)
    if not ts["ok"]:
        return {**_fail("PDF_OCR_REQUIRED",
                     "이미지 기반 PDF라 텍스트 추출이 필요합니다. OCR 설정을 켠 뒤 다시 시도해주세요.",
                     text_status=_text_status(ts, 0)), "metadata": {"ocr": ocr_unavailable_status()}}
    requested_count = max(1, min(int(req.questionCount or 5), 20))
    logger.info("material quiz start material_id=%s requestedCount=%s difficulty=%s textLen=%s", req.material_id, requested_count, req.difficulty, ts["textLength"])
    cache = await get_or_build_chunks(req.material_id, req.text)
    chunks = cache["chunks"]
    context = build_limited_context(chunks, AI_QUIZ_MAX_CHUNKS) or (req.text or "")[:6000]
    try:
        r = await asyncio.wait_for(asyncio.to_thread(
            generate_quiz_json, context, req.difficulty or "보통", requested_count,
        ), timeout=_t(QUIZ_TIMEOUT))
    except asyncio.TimeoutError:
        # 빈 결과/에러만 반환하지 않고 문서 기반 fallback 문제를 보장한다.
        return _quiz_fallback_payload(context, req.difficulty or "보통", requested_count,
                                      ts, len(chunks), "AI_TIMEOUT")
    except Exception as e:
        logger.error("quiz 실패: %s", e)
        return _quiz_fallback_payload(context, req.difficulty or "보통", requested_count,
                                      ts, len(chunks), "AI_RESPONSE_PARSE_FAILED")

    questions = r.get("questions", [])
    if not questions:
        # schema 검증 실패로 전체를 폐기하지 않고 fallback 으로 복구한다.
        return _quiz_fallback_payload(context, req.difficulty or "보통", requested_count,
                                      ts, len(chunks), "QUIZ_VALIDATE_FAILED")

    quiz_data = json.dumps(questions, ensure_ascii=False)  # 프론트 parseQuizQuestions가 파싱
    elapsed = int((time.time() - started) * 1000)
    logger.info("material quiz done material_id=%s requestedCount=%s generatedCount=%s provider=%s elapsedMs=%s", req.material_id, requested_count, len(questions), r.get("provider"), elapsed)
    return {
        "success": True,
        "quizData": quiz_data,           # 하위호환 (Spring이 그대로 저장)
        "quizzes": questions,            # 확장
        "warnings": r.get("warnings", []),
        "textStatus": _text_status(ts, len(chunks)),
        "metadata": {"provider": r.get("provider", "ollama_qwen"), "model": os.getenv("OLLAMA_MODEL", "qwen2.5:14b"),
                     "elapsedMs": elapsed, "chunkCount": len(chunks),
                     "cacheHit": cache["cacheHit"], "cacheBackend": cache["cacheBackend"],
                     "extractedTextHash": cache.get("extractedTextHash")},
    }


# ── POST /api/ai/question ─────────────────────────────────────────────────────
@router.post("/question", summary="자료 기반 질문 (Ollama+GPT fallback, chunk Top-K)")
async def ai_question(req: QuestionReq) -> Dict[str, Any]:
    from app.services.material_ai_manager import (
        validate_extracted_text, select_relevant_chunks, validate_qa_result, ocr_unavailable_status,
    )
    from app.services.chunk_cache import get_or_build_chunks
    started = time.time()
    ts = validate_extracted_text(req.text)
    if not ts["ok"]:
        return {
            **_fail("PDF_OCR_REQUIRED",
                    "이미지 기반 PDF라 텍스트 추출이 필요합니다. OCR 설정을 켠 뒤 다시 시도해주세요.",
                    text_status=_text_status(ts, 0)),
            "answer": "이미지 기반 PDF라 텍스트 추출이 필요합니다. OCR 설정을 켠 뒤 다시 시도해주세요.",
            "metadata": {"ocr": ocr_unavailable_status()},
        }
    question = (req.question or "").strip() or "이 문서의 핵심을 알려주세요."
    cache = await get_or_build_chunks(req.material_id, req.text)
    chunks = cache["chunks"]
    relevant = select_relevant_chunks(question, chunks)
    context = "\n\n".join(f"[chunk {c['chunkIndex']}] {c['content']}" for c in relevant)

    system = (
        "너는 PDF 문서 기반 Q&A 전문가다. 제공된 문맥에 근거해서만 한국어로 답한다. "
        "문맥에 없는 내용은 '문서 기준으로는 확인되지 않습니다.'라고 명시한다."
    )
    user = f"## 문맥\n{context[:6000]}\n\n## 질문\n{question}\n\n위 문맥을 근거로 답하라."

    def _answer() -> str:
        # 1순위 Ollama/Qwen (내부 GPT fallback 포함)
        try:
            from app.services.llm_engine_router import call_primary_llm
            out = call_primary_llm(system_prompt=system, user_prompt=user, max_tokens=1200, temperature=0.3)
            if out and not out.strip().startswith("["):
                return out
        except Exception as e:
            logger.warning("question Ollama 실패: %s", e)
        # GPT fallback
        try:
            from app.services.openai_client import chat_sync, is_enabled
            if is_enabled():
                return chat_sync(system=system, user=user, temperature=0.3, max_tokens=1200)
        except Exception as e:
            logger.warning("question GPT 실패: %s", e)
        return ""

    try:
        raw_answer = await asyncio.wait_for(asyncio.to_thread(_answer), timeout=_t(QA_TIMEOUT))
    except asyncio.TimeoutError:
        return {**_fail("AI_TIMEOUT", "AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.",
                        text_status=_text_status(ts, len(chunks))),
                "answer": "AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요."}

    qa = validate_qa_result(raw_answer, question, context)
    if qa["answer"].strip().startswith("문서 기준으로는 확인되지 않습니다") and context.strip():
        context_lower = context.lower()
        q_terms = [t for t in re.findall(r"[가-힣A-Za-z0-9+_.#-]{2,}", question) if t.lower() in context_lower]
        if q_terms:
            evidence = re.sub(r"\s+", " ", context).strip()
            evidence = re.sub(r"\[chunk \d+\]", "", evidence).strip()
            qa["answer"] = f"자료 기준으로는 {evidence[:700]}"
            qa.setdefault("warnings", []).append("LLM이 근거 없음으로 응답해 자료 문맥 기반 답변으로 보정했습니다.")
    elapsed = int((time.time() - started) * 1000)
    return {
        "success": True,
        "answer": qa["answer"],          # 하위호환 (Spring이 읽음)
        "usedChunks": [c["chunkIndex"] for c in relevant],
        "warnings": qa.get("warnings", []),
        "textStatus": _text_status(ts, len(chunks)),
        "metadata": {"provider": "ollama+gpt", "elapsedMs": elapsed, "chunkCount": len(chunks),
                     "cacheHit": cache["cacheHit"], "cacheBackend": cache["cacheBackend"],
                     "extractedTextHash": cache.get("extractedTextHash")},
    }


# ── POST /api/ai/roadmap ──────────────────────────────────────────────────────
@router.post("/roadmap", summary="자료 학습 로드맵 (GPT, 구조화 JSON)")
async def ai_roadmap(req: RoadmapReq) -> Dict[str, Any]:
    from app.services.material_ai_manager import (
        validate_extracted_text, build_limited_context, generate_roadmap_json, AI_ROADMAP_MAX_CHUNKS, ocr_unavailable_status,
    )
    from app.services.chunk_cache import get_or_build_chunks
    started = time.time()
    text = req.pdf_text or req.text
    ts = validate_extracted_text(text)
    if not ts["ok"]:
        return {**_fail("PDF_OCR_REQUIRED",
                     "이미지 기반 PDF라 텍스트 추출이 필요합니다. OCR 설정을 켠 뒤 다시 시도해주세요.",
                     text_status=_text_status(ts, 0)), "metadata": {"ocr": ocr_unavailable_status()}}
    cache = await get_or_build_chunks(req.material_id, text)
    chunks = cache["chunks"]
    context = build_limited_context(chunks, AI_ROADMAP_MAX_CHUNKS) or (text or "")[:6000]
    _rm_title = (req.user_goal or req.document_title or "학습 자료") if hasattr(req, "document_title") else (req.user_goal or "학습 자료")
    try:
        r = await asyncio.wait_for(asyncio.to_thread(
            generate_roadmap_json, context, req.user_goal or "학습 목표 달성",
        ), timeout=_t(ROADMAP_TIMEOUT))
    except asyncio.TimeoutError:
        # UNKNOWN_ERROR/빈 결과로 끝내지 않고 기본 로드맵 fallback 을 보장한다.
        return _roadmap_fallback_payload(_rm_title, ts, len(chunks), "AI_TIMEOUT")
    except Exception as e:
        logger.error("roadmap 실패: %s", e)
        return _roadmap_fallback_payload(_rm_title, ts, len(chunks), "AI_RESPONSE_PARSE_FAILED")

    weeks = r.get("weeks", [])
    if not weeks:
        logger.error(
            "roadmap validate failed material_id=%s field=weeks sample=%s",
            req.material_id,
            str(r.get("raw") or r)[:300],
        )
        # schema 검증 실패로 전체를 폐기하지 않고 fallback 으로 복구한다.
        return _roadmap_fallback_payload(_rm_title, ts, len(chunks), "ROADMAP_VALIDATE_FAILED")

    # Spring RoadmapStep/RoadmapTask 계약으로 매핑. description에 확장 정보를 포함해 기존 DTO를 유지한다.
    steps = []
    for i, wk in enumerate(weeks):
        task_values = wk.get("tasks") if isinstance(wk.get("tasks"), list) else []
        tasks = []
        for j, task in enumerate(task_values):
            content = task if isinstance(task, str) else str(task.get("content") or task.get("title") or task.get("task") or "")
            content = content.strip()
            if content:
                tasks.append({"taskOrder": j + 1, "content": content})
        if not tasks:
            logger.warning("roadmap task normalized material_id=%s week=%s reason=empty_tasks", req.material_id, i + 1)
            tasks = [
                {"taskOrder": 1, "content": "문서 핵심 내용을 읽고 요약하기"},
                {"taskOrder": 2, "content": "이해가 부족한 개념을 질문 목록으로 정리하기"},
            ]
        concepts = wk.get("keyConcepts") if isinstance(wk.get("keyConcepts"), list) else []
        description_parts = []
        if wk.get("goal"):
            description_parts.append(f"학습 목표: {wk.get('goal')}")
        if concepts:
            description_parts.append("핵심 개념: " + ", ".join(str(c) for c in concepts if c))
        if wk.get("deliverable"):
            description_parts.append(f"산출물/자기점검: {wk.get('deliverable')}")
        if wk.get("estimatedHours"):
            description_parts.append(f"예상 학습 시간: {wk.get('estimatedHours')}시간")
        steps.append({
            "stepOrder": wk.get("weekNumber") or (i + 1),
            "title": wk.get("title") or f"{i + 1}주차",
            "description": "\n".join(description_parts) or (wk.get("goal") or "학습 목표 정리"),
            "tasks": tasks,
            "goal": wk.get("goal") or "",
            "keyConcepts": concepts,
            "deliverable": wk.get("deliverable") or "",
            "estimatedHours": wk.get("estimatedHours") or 3,
        })
    elapsed = int((time.time() - started) * 1000)
    return {
        "success": True,
        "roadmap": {"title": r.get("title", "AI 생성 학습 로드맵"), "totalWeeks": len(steps), "steps": steps},
        "warnings": r.get("warnings", []),
        "textStatus": _text_status(ts, len(chunks)),
        "metadata": {"provider": r.get("provider", "ollama_qwen"), "model": os.getenv("OLLAMA_MODEL", "qwen2.5:14b"),
                     "elapsedMs": elapsed, "chunkCount": len(chunks),
                     "cacheHit": cache["cacheHit"], "cacheBackend": cache["cacheBackend"],
                     "extractedTextHash": cache.get("extractedTextHash")},
    }


# ── POST /api/ai/feedback ─────────────────────────────────────────────────────
@router.post("/feedback", summary="자료 학습 피드백 (GPT)")
async def ai_feedback(req: FeedbackReq) -> Dict[str, Any]:
    from app.services.material_ai_manager import validate_extracted_text, build_summary_context, _call_gpt
    from app.services.chunk_cache import get_or_build_chunks
    started = time.time()
    ts = validate_extracted_text(req.content)
    if not ts["ok"]:
        return _fail("PDF_TEXT_EMPTY", "분석할 학습 내용이 없습니다.", text_status=_text_status(ts, 0))
    cache = await get_or_build_chunks(None, req.content)
    chunks = cache["chunks"]
    context = build_summary_context(chunks) or (req.content or "")[:6000]
    system = "너는 학습 코치다. 제공된 학습 내용에 근거해 한국어로 간결한 학습 피드백을 제공한다."
    user = f"## 학습 내용\n{context[:5000]}\n\n학습자에게 도움이 되는 피드백을 작성하라."
    try:
        feedback = await asyncio.wait_for(asyncio.to_thread(_call_gpt, system, user), timeout=_t(SUMMARY_TIMEOUT))
    except asyncio.TimeoutError:
        return _fail("AI_TIMEOUT", "AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.",
                     text_status=_text_status(ts, len(chunks)))
    except Exception as e:
        logger.error("feedback 실패: %s", e)
        return _fail("UNKNOWN_ERROR", "피드백 생성에 실패했습니다.", text_status=_text_status(ts, len(chunks)))
    return {
        "success": True,
        "feedbackData": feedback,
        "feedback": feedback,
        "warnings": [],
        "textStatus": _text_status(ts, len(chunks)),
        "metadata": {"provider": "openai_gpt", "elapsedMs": int((time.time() - started) * 1000)},
    }
