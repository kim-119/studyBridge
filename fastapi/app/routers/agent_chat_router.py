"""
AI 에이전트 채팅 라우터.

엔드포인트:
  POST   /api/ai/chat                         — 에이전트 채팅 (즉시 답변 + 비동기 검증)
  GET    /api/ai/chat/validation/{job_id}     — GPT 검증 상태 폴링
  POST   /api/ai/material/summary             — PDF 요약 (GPT 중심)
  POST   /api/ai/material/quiz                — 퀴즈 생성
  POST   /api/ai/material/roadmap             — 학습 로드맵 생성
  POST   /api/ai/material/qa                  — PDF RAG Q&A
"""
import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path
from fastapi.responses import JSONResponse

from app.core.security import verify_internal_token
from app.schemas.agent_chat_schema import (
    AgentChatRequest,
    AgentChatResponse,
    TikiTakaTurnDTO,
    ValidationStatusResponse,
    MaterialSummaryRequest,
    MaterialSummaryResponse,
    MaterialQuizRequest,
    MaterialQuizResponse,
    MaterialRoadmapRequest,
    MaterialRoadmapResponse,
    MaterialQARequest,
)
from app.services.agent_chat_manager import run_agent_chat
from app.services.material_ai_manager import (
    answer_from_pdf,
    summarize_document,
    generate_quiz,
    generate_roadmap,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/ai",
    tags=["AI Chat & Material"],
    dependencies=[Depends(verify_internal_token)],
)

# ── 인메모리 검증 작업 저장소 ─────────────────────────────────────────────────
# 데모용: 실제 운영 시 Redis 교체 권장
_validation_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = asyncio.Lock()


async def _run_validation_job(
    job_id: str,
    question: str,
    answer: str,
    knowledge_level: str,
    personality: str,
) -> None:
    """Background task: GPT로 답변을 검증하고 결과를 저장한다."""
    async with _jobs_lock:
        _validation_jobs[job_id]["status"] = "running"

    try:
        from app.services.gpt_verifier import (
            verify_answer_async,
            generate_corrected_answer_async,
        )
        result = await verify_answer_async(question, answer, knowledge_level, personality)

        corrected = None
        if result.get("correction_needed") and result.get("suggestion"):
            corrected = await generate_corrected_answer_async(
                question, answer, result["suggestion"], knowledge_level, personality
            )

        async with _jobs_lock:
            _validation_jobs[job_id].update({
                "status":           "completed",
                "result":           result,
                "corrected_answer": corrected,
            })
        logger.info("검증 완료 job_id=%s score=%.2f", job_id, result.get("score", 0))

    except Exception as e:
        logger.error("검증 실패 job_id=%s: %s", job_id, e)
        async with _jobs_lock:
            _validation_jobs[job_id].update({
                "status": "failed",
                "result": {"error": str(e)},
            })


# ── POST /api/ai/chat ──────────────────────────────────────────────────────

@router.post(
    "/chat",
    response_model=AgentChatResponse,
    summary="에이전트 채팅",
    description=(
        "지식수준·성격 기반 에이전트 채팅. "
        "Qwen 1차 답변을 즉시 반환하고, GPT 검증은 백그라운드에서 비동기 실행한다. "
        "티키타카 활성화 시 멀티 에이전트 대화를 함께 반환한다."
    ),
)
async def agent_chat(
    request: AgentChatRequest,
    background_tasks: BackgroundTasks,
) -> AgentChatResponse:
    question = (request.question or "").strip()
    context = (request.context or "").strip()

    _EMPTY_FALLBACK = {
        "success": False,
        "answer": "현재 자료 기반 답변을 생성하지 못했습니다. 자료가 비어 있거나 AI 서버 응답이 지연되고 있습니다.",
        "message": "현재 자료 기반 답변을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        "sourceRefs": [],
    }

    # question/message 둘 다 비어도 422로 막지 않고 명확한 JSON을 반환한다.
    if not question:
        return JSONResponse(status_code=200, content={
            **_EMPTY_FALLBACK,
            "message": "질문(question 또는 message)이 비어 있습니다.",
        })

    # 자료 맥락(context/materialContext/sourceText)이 있으면 질문 앞에 근거로 주입한다.
    effective_question = f"[참고 자료]\n{context}\n\n[질문]\n{question}" if context else question

    # 동기 파이프라인 실행 (to_thread로 블로킹 방지). 예외는 raw 노출 대신 success=false JSON.
    try:
        result = await asyncio.to_thread(
            run_agent_chat,
            question=effective_question,
            knowledge_level=request.knowledge_level,
            personality=request.personality,
            agent_name=request.agent_name,
            custom_instruction=request.custom_instruction,
            material_id=request.material_id,
            enable_tiki_taka=request.enable_tiki_taka,
            enable_round2=request.enable_round2,
        )
    except Exception as e:  # noqa: BLE001 — traceback/raw exception 사용자 비노출
        logger.error("agent_chat 실행 실패: %s", e)
        return JSONResponse(status_code=200, content=_EMPTY_FALLBACK)

    # 빈 응답 방어: answer가 비면 success=false JSON (빈 답변 노출 금지).
    if not (result.get("answer") or "").strip():
        return JSONResponse(status_code=200, content=_EMPTY_FALLBACK)

    # GPT 검증 job 등록 (선택)
    job_id: str | None = None
    chat_status = "no_validation"

    if request.use_gpt_validation:
        job_id = str(uuid.uuid4())
        async with _jobs_lock:
            _validation_jobs[job_id] = {
                "status":           "pending",
                "result":           None,
                "corrected_answer": None,
            }
        background_tasks.add_task(
            _run_validation_job,
            job_id,
            request.question.strip(),
            result["answer"],
            request.knowledge_level,
            request.personality,
        )
        chat_status = "pending_validation"
    else:
        chat_status = "complete"

    return AgentChatResponse(
        answer=result["answer"],
        tiki_taka_dialogue=[
            TikiTakaTurnDTO(**t) for t in result.get("tiki_taka_dialogue", [])
        ],
        validation_job_id=job_id,
        status=chat_status,
        knowledge_level=result["knowledge_level"],
        personality=result["personality"],
        process_logs=result["process_logs"],
    )


# ── GET /api/ai/chat/validation/{job_id} ──────────────────────────────────

@router.get(
    "/chat/validation/{job_id}",
    response_model=ValidationStatusResponse,
    summary="GPT 검증 상태 폴링",
    description="백그라운드 GPT 검증 작업의 상태를 조회한다.",
)
async def get_validation_status(
    job_id: str = Path(..., description="검증 작업 ID"),
) -> ValidationStatusResponse:
    async with _jobs_lock:
        job = _validation_jobs.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail=f"job_id={job_id}를 찾을 수 없습니다.")

    return ValidationStatusResponse(
        job_id=job_id,
        status=job["status"],
        result=job.get("result"),
        corrected_answer=job.get("corrected_answer"),
    )


# ── POST /api/ai/material/summary ─────────────────────────────────────────

@router.post(
    "/material/summary",
    response_model=MaterialSummaryResponse,
    summary="PDF 요약 (GPT 중심)",
)
async def material_summary(request: MaterialSummaryRequest) -> MaterialSummaryResponse:
    result = await asyncio.to_thread(
        summarize_document,
        document_title=request.document_title,
        text=request.text,
        personality=request.personality,
        agent_name=request.agent_name,
    )
    return MaterialSummaryResponse(
        summary=result["summary"],
        key_points=result["key_points"],
    )


# ── POST /api/ai/material/quiz ─────────────────────────────────────────────

@router.post(
    "/material/quiz",
    response_model=MaterialQuizResponse,
    summary="퀴즈 생성 (GPT 전담)",
)
async def material_quiz(request: MaterialQuizRequest) -> MaterialQuizResponse:
    result = await asyncio.to_thread(
        generate_quiz,
        document_title=request.document_title,
        context=request.context,
        num_questions=request.num_questions,
        knowledge_level=request.knowledge_level,
    )
    return MaterialQuizResponse(
        quiz=result["quiz"],
        question_count=result["question_count"],
    )


# ── POST /api/ai/material/roadmap ─────────────────────────────────────────

@router.post(
    "/material/roadmap",
    response_model=MaterialRoadmapResponse,
    summary="학습 로드맵 생성 (GPT 전담)",
)
async def material_roadmap(request: MaterialRoadmapRequest) -> MaterialRoadmapResponse:
    result = await asyncio.to_thread(
        generate_roadmap,
        document_title=request.document_title,
        context=request.context,
        knowledge_level=request.knowledge_level,
    )
    return MaterialRoadmapResponse(roadmap=result["roadmap"])


# ── POST /api/ai/material/qa ───────────────────────────────────────────────

@router.post(
    "/material/qa",
    summary="PDF RAG Q&A (GPT 70% + Qwen 30%)",
    response_model=dict,
)
async def material_qa(request: MaterialQARequest) -> dict:
    # RAG 검색
    try:
        from app.services.pdf_rag_service import search_pdf_context
        chunks = await asyncio.to_thread(
            search_pdf_context,
            request.question,
            request.material_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG 검색 실패: {e}")

    result = await asyncio.to_thread(
        answer_from_pdf,
        question=request.question,
        rag_chunks=chunks,
        personality=request.personality,
        agent_name=request.agent_name,
        knowledge_level=request.knowledge_level,
    )
    return {
        "answer":  result["answer"],
        "sources": result["sources"],
    }
