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
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

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
    text: Optional[str] = None
    material_id: Optional[int] = None
    difficulty: Optional[str] = "보통"
    questionCount: Optional[int] = 5
    document_title: Optional[str] = None


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
    core_contents = json.dumps(
        [{"title": s.get("title", ""), "description": s.get("content", "")} for s in sections],
        ensure_ascii=False,
    )
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
        "sections": sections,
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
    cache = await get_or_build_chunks(req.material_id, req.text)
    chunks = cache["chunks"]
    context = build_limited_context(chunks, AI_QUIZ_MAX_CHUNKS) or (req.text or "")[:6000]
    try:
        r = await asyncio.wait_for(asyncio.to_thread(
            generate_quiz_json, context, req.difficulty or "보통", req.questionCount or 5,
        ), timeout=_t(QUIZ_TIMEOUT))
    except asyncio.TimeoutError:
        return _fail("AI_TIMEOUT", "AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.",
                     text_status=_text_status(ts, len(chunks)))
    except Exception as e:
        logger.error("quiz 실패: %s", e)
        return _fail("AI_RESPONSE_PARSE_FAILED", "퀴즈 생성에 실패했습니다. 다시 시도해주세요.",
                     text_status=_text_status(ts, len(chunks)))

    questions = r.get("questions", [])
    if not questions:
        return _fail("QUIZ_VALIDATE_FAILED", "퀴즈 형식 검증에 실패했습니다. 다시 생성해주세요.",
                     text_status=_text_status(ts, len(chunks)))

    quiz_data = json.dumps(questions, ensure_ascii=False)  # 프론트 parseQuizQuestions가 파싱
    elapsed = int((time.time() - started) * 1000)
    return {
        "success": True,
        "quizData": quiz_data,           # 하위호환 (Spring이 그대로 저장)
        "quizzes": questions,            # 확장
        "warnings": r.get("warnings", []),
        "textStatus": _text_status(ts, len(chunks)),
        "metadata": {"provider": "openai_gpt", "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
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
    try:
        r = await asyncio.wait_for(asyncio.to_thread(
            generate_roadmap_json, context, req.user_goal or "학습 목표 달성",
        ), timeout=_t(ROADMAP_TIMEOUT))
    except asyncio.TimeoutError:
        return _fail("AI_TIMEOUT", "AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.",
                     text_status=_text_status(ts, len(chunks)))
    except Exception as e:
        logger.error("roadmap 실패: %s", e)
        return _fail("AI_RESPONSE_PARSE_FAILED", "로드맵 생성에 실패했습니다. 다시 시도해주세요.",
                     text_status=_text_status(ts, len(chunks)))

    weeks = r.get("weeks", [])
    if not weeks:
        return _fail("ROADMAP_VALIDATE_FAILED", "로드맵 형식 검증에 실패했습니다. 다시 생성해주세요.",
                     text_status=_text_status(ts, len(chunks)))

    # Spring RoadmapStep/RoadmapTask 계약으로 매핑
    steps = []
    for i, wk in enumerate(weeks):
        tasks = [{"taskOrder": j + 1, "content": t} for j, t in enumerate(wk.get("tasks", []))]
        steps.append({
            "stepOrder": wk.get("weekNumber") or (i + 1),
            "title": wk.get("title") or f"{i + 1}주차",
            "description": wk.get("goal") or "",
            "tasks": tasks,
        })
    elapsed = int((time.time() - started) * 1000)
    return {
        "success": True,
        "roadmap": {"title": r.get("title", "AI 생성 학습 로드맵"), "totalWeeks": len(steps), "steps": steps},
        "warnings": r.get("warnings", []),
        "textStatus": _text_status(ts, len(chunks)),
        "metadata": {"provider": "openai_gpt", "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
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
