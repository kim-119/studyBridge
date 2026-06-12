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
    level: Optional[str] = None


def _fail(error_code: str, message: str, retryable: bool = True,
          text_status: Optional[dict] = None, debug_hint: str = "") -> Dict[str, Any]:
    return {
        "success": False,
        "errorCode": error_code,
        "error_code": error_code,        # snake_case 호환(스펙 F/C)
        "message": message,
        "retryable": retryable,
        "recoverable": retryable,        # 스펙 F: recoverable 포함
        "debug_hint": debug_hint or error_code,
        "questions": [],                 # 실패 시 불합격 퀴즈 누출 방지
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
@router.post("/summary", summary="자료 요약 (구조화 JSON, core 10+/detail 40+)")
async def ai_summary(req: SummaryReq) -> Dict[str, Any]:
    from app.services.material_ai_manager import (
        validate_extracted_text, build_summary_context, ocr_unavailable_status,
    )
    from app.services.material_summary_builder import build_structured_summary
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
            build_structured_summary,
            req.document_title or "자료",
            context,
        ), timeout=_t(SUMMARY_TIMEOUT))
    except asyncio.TimeoutError:
        return _fail("AI_TIMEOUT", "AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.",
                     text_status=_text_status(ts, len(chunks)))
    except Exception as e:
        logger.error("summary 실패: %s", e)
        return _fail("SUMMARY_VALIDATE_FAILED", "요약 생성에 실패했습니다. 다시 시도해주세요.",
                     text_status=_text_status(ts, len(chunks)))

    # 구조화 결과 → 기존 EC2 호환 필드 매핑 (sections/coreContents 문자열은 유지)
    core_contents = r.get("core_contents") or []
    detailed_core_contents = r.get("detailed_core_contents") or []
    keyword_objs = r.get("keywords") or []
    keyword_strings = [k.get("keyword", "") for k in keyword_objs if k.get("keyword")]
    core_items = [
        {"title": c.get("title", ""), "content": c.get("content", ""), "description": c.get("content", "")}
        for c in core_contents
    ]
    legacy_core_string = json.dumps(core_items, ensure_ascii=False)
    # 하위호환 summary 본문 = 마크다운 없는 자연어 섹션 묶음
    legacy_summary = "\n\n".join(
        f"{s['heading']}\n{s['content']}" for s in r.get("detailed_sections", [])
    )

    elapsed = int((time.time() - started) * 1000)
    warnings = [w for w in [r.get("warning")] if w]
    logger.info("summary done provider=%s elapsedMs=%s textLen=%s chunks=%s core=%s detail=%s",
                r.get("provider"), elapsed, ts["textLength"], len(chunks),
                len(core_contents), len(detailed_core_contents))
    return {
        "success": True,
        # ── 하위호환 (기존 EC2/Spring 계약) ─────────────────────────────
        "summary": legacy_summary,
        "key_points": keyword_strings,
        "gpt_raw": "",
        "overview": r.get("overview", ""),
        "coreContents": legacy_core_string,
        "keywords": keyword_strings,
        "sections": core_items,
        "learningPoints": r.get("study_points", []),
        "practicePoints": r.get("practice_points", []),
        "studyQuestions": r.get("study_questions", []),
        # ── 신규 구조화 필드 (마크다운 제거 완료) ────────────────────────
        "title": r.get("title", ""),
        "core_contents": core_contents,
        "detailed_core_contents": detailed_core_contents,
        "keywordsDetailed": keyword_objs,
        "study_points": r.get("study_points", []),
        "practice_points": r.get("practice_points", []),
        "study_questions": r.get("study_questions", []),
        "detailed_sections": r.get("detailed_sections", []),
        "assumption_notice": r.get("assumption_notice"),
        "error_code": r.get("error_code"),
        # ── 공통 ────────────────────────────────────────────────────────
        "warnings": warnings,
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

    # 난이도 정책 강제: hard는 시나리오형 보장(검증 실패 시 OpenAI→Ollama→deterministic repair)
    from app.services.quiz_difficulty_policy import enforce_quiz_difficulty
    from app.services.material_ai_manager import _keywords_from_text
    keywords = _keywords_from_text(context, limit=15)
    try:
        questions, diff_meta = await asyncio.wait_for(
            asyncio.to_thread(enforce_quiz_difficulty, questions, req.difficulty or "보통",
                              context, keywords),
            timeout=_t(QUIZ_TIMEOUT))
    except asyncio.TimeoutError:
        # 타임아웃에도 hard는 검증 미달 문제를 그대로 내려보내지 않는다.
        # LLM repair를 건너뛴 결정적(deterministic) 보정으로 즉시 재구성한다.
        try:
            questions, diff_meta = enforce_quiz_difficulty(
                questions, req.difficulty or "보통", context, keywords, allow_llm_repair=False)
        except Exception as e:  # noqa: BLE001
            logger.error("quiz 난이도 deterministic 보정 실패: %s", e)
            questions, diff_meta = [], {
                "difficulty_requested": req.difficulty or "보통", "difficulty_applied": "hard",
                "difficulty_policy": "문서 기반 + 응용 + 고급 개념",
                "difficulty_validation": {"passed": False, "reason": "난이도 보정 시간 초과 및 복구 실패"},
                "repaired_count": 0,
            }

    # 검증 미통과 시: 불합격 퀴즈를 절대 내려보내지 않는다(빈 배열 + 실패 JSON). 스펙 F.
    diff_val = diff_meta.get("difficulty_validation", {}) if isinstance(diff_meta, dict) else {}
    if not diff_val.get("passed"):
        elapsed = int((time.time() - started) * 1000)
        logger.warning("material quiz validate fail material_id=%s difficulty=%s reason=%s",
                       req.material_id, diff_meta.get("difficulty_requested"), diff_val.get("reason"))
        return {
            "success": False,
            "errorCode": "QUIZ_VALIDATE_FAILED",
            "error_code": "QUIZ_VALIDATE_FAILED",
            "message": "요청한 어려움 난이도가 충분히 반영되지 않았습니다. 다시 생성해 주세요.",
            "recoverable": True,
            "retryable": True,
            "debug_hint": "hard 문제 조건(시나리오/설계 판단/80자 이상) 미충족 + repair 실패",
            "quizData": "[]",
            "quizzes": [],
            "questions": [],
            **{k: v for k, v in diff_meta.items() if k != "difficulty_validation"},
            "difficulty_validation": diff_val or {"passed": False, "reason": "hard 문제 조건을 만족하지 못했습니다."},
            "warnings": r.get("warnings", []),
            "textStatus": _text_status(ts, len(chunks)),
        }

    quiz_data = json.dumps(questions, ensure_ascii=False)  # 프론트 parseQuizQuestions가 파싱
    elapsed = int((time.time() - started) * 1000)
    logger.info("material quiz done material_id=%s requestedCount=%s generatedCount=%s provider=%s difficulty=%s applied=%s repaired=%s elapsedMs=%s", req.material_id, requested_count, len(questions), r.get("provider"), diff_meta.get("difficulty_requested"), diff_meta.get("difficulty_applied"), diff_meta.get("repaired_count"), elapsed)
    return {
        "success": True,
        "error_code": None,
        "quizData": quiz_data,           # 하위호환 (Spring이 그대로 저장)
        "quizzes": questions,            # 확장
        "questions": questions,          # 스펙 F 호환
        **diff_meta,                     # difficulty_requested/applied/policy/difficulty_validation/repaired_count
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
        logger.error(
            "roadmap validate failed material_id=%s field=weeks sample=%s",
            req.material_id,
            str(r.get("raw") or r)[:300],
        )
        return _fail("ROADMAP_VALIDATE_FAILED", "로드맵 형식 검증에 실패했습니다. 다시 생성해주세요.",
                     text_status=_text_status(ts, len(chunks)))

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
@router.post("/feedback", summary="자료 학습 피드백 (장점/권장/우려/다음행동 균형, 마크다운 제거)")
async def ai_feedback(req: FeedbackReq) -> Dict[str, Any]:
    from app.services.material_ai_manager import validate_extracted_text, build_summary_context
    from app.services.feedback_builder import build_balanced_feedback, to_legacy_text
    from app.services.chunk_cache import get_or_build_chunks
    started = time.time()
    ts = validate_extracted_text(req.content)
    if not ts["ok"]:
        return _fail("PDF_TEXT_EMPTY", "분석할 학습 내용이 없습니다.", text_status=_text_status(ts, 0))
    cache = await get_or_build_chunks(None, req.content)
    chunks = cache["chunks"]
    context = build_summary_context(chunks) or (req.content or "")[:6000]
    level = getattr(req, "level", None) or "undergraduate"
    try:
        fb = await asyncio.wait_for(
            asyncio.to_thread(build_balanced_feedback, req.content or context, context, level),
            timeout=_t(SUMMARY_TIMEOUT))
    except asyncio.TimeoutError:
        return _fail("AI_TIMEOUT", "AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.",
                     text_status=_text_status(ts, len(chunks)))
    except Exception as e:
        logger.error("feedback 실패: %s", e)
        return _fail("UNKNOWN_ERROR", "피드백 생성에 실패했습니다.", text_status=_text_status(ts, len(chunks)))
    legacy_text = to_legacy_text(fb)
    return {
        "success": True,
        # ── 하위호환 (기존 EC2/Spring 계약: 문자열 피드백) ──────────────
        "feedbackData": legacy_text,
        "feedback": legacy_text,
        # ── 신규 구조화 피드백 (마크다운 제거, 균형 보장) ──────────────
        **fb,
        "warnings": [w for w in [fb.get("warning")] if w],
        "textStatus": _text_status(ts, len(chunks)),
        "metadata": {"provider": "ollama+openai", "elapsedMs": int((time.time() - started) * 1000)},
    }
