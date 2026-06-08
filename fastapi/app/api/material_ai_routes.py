"""
자료보관함 AI API.
POST /api/materials/{material_id}/ai/analyze — 요약/퀴즈/로드맵/문서분석/QA
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Path

from app.core.security import verify_internal_token
from app.schemas.material_ai_schema import MaterialAnalyzeRequest, MaterialAnalyzeResponse

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/materials",
    tags=["Material AI"],
    dependencies=[Depends(verify_internal_token)],
)

ALLOWED_TYPES = {"summary", "quiz", "roadmap", "document_analysis", "question_answer"}


@router.post(
    "/{material_id}/ai/analyze",
    response_model=MaterialAnalyzeResponse,
    summary="자료 AI 분석 (GPT 70% + Qwen 30%)",
)
async def analyze_material(
    request: MaterialAnalyzeRequest,
    material_id: int = Path(..., gt=0),
) -> MaterialAnalyzeResponse:
    """
    analyze_type에 따라 PDF 자료를 분석한다.
    - summary: 요약
    - quiz: 퀴즈 생성
    - roadmap: 학습 로드맵
    - document_analysis: 문서 분석
    - question_answer: RAG 기반 Q&A
    """
    if request.analyze_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"analyze_type은 {ALLOWED_TYPES} 중 하나여야 합니다.",
        )

    from app.services.material_ai_manager import (
        summarize_document,
        generate_quiz,
        generate_roadmap,
        answer_from_pdf,
    )
    from app.services.pdf_rag_service import search_pdf_context

    t = request.analyze_type
    result_text = ""
    metadata: dict = {}

    try:
        if t == "summary":
            r = await asyncio.to_thread(
                summarize_document,
                document_title=request.document_title or f"자료 {material_id}",
                text=request.text or "",
                personality=request.personality,
                agent_name=request.agent_name,
            )
            result_text = r["summary"]
            metadata = {"key_points": r["key_points"]}

        elif t == "quiz":
            r = await asyncio.to_thread(
                generate_quiz,
                document_title=request.document_title or f"자료 {material_id}",
                context=request.text or "",
                num_questions=request.num_questions or 5,
                knowledge_level=request.knowledge_level,
            )
            result_text = r["quiz"]
            metadata = {"question_count": r["question_count"]}

        elif t == "roadmap":
            r = await asyncio.to_thread(
                generate_roadmap,
                document_title=request.document_title or f"자료 {material_id}",
                context=request.text or "",
                knowledge_level=request.knowledge_level,
            )
            result_text = r["roadmap"]

        elif t in ("document_analysis", "question_answer"):
            question = request.question or "이 문서의 핵심 내용을 분석해 주세요."
            chunks = await asyncio.to_thread(search_pdf_context, question, material_id)
            r = await asyncio.to_thread(
                answer_from_pdf,
                question=question,
                rag_chunks=chunks,
                personality=request.personality,
                agent_name=request.agent_name,
                knowledge_level=request.knowledge_level,
            )
            result_text = r["answer"]
            metadata = {"chunk_count": len(r.get("sources", []))}

    except Exception as e:
        logger.error("자료 분석 실패 material_id=%s type=%s: %s", material_id, t, e)
        raise HTTPException(status_code=500, detail=f"자료 분석 실패: {e}")

    return MaterialAnalyzeResponse(
        material_id=material_id,
        analyze_type=t,
        result=result_text,
        metadata=metadata,
    )
