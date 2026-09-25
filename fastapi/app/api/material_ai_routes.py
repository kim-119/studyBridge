"""
자료보관함 AI API.
POST /api/materials/{material_id}/ai/analyze — 요약/퀴즈/로드맵/문서분석/QA

모델 라우팅: 요약→Ollama/Qwen, 로드맵/퀴즈→GPT, QA→Qwen+GPT.
모든 작업에 hard timeout과 추출 텍스트 검증, 정규화된 실패 응답을 적용한다.
"""
import asyncio
import logging
import os
import time

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

# 기능별 hard timeout (전체 120초 예산 내)
_GLOBAL_TIMEOUT = int(os.getenv("AI_GLOBAL_TIMEOUT_SECONDS", "120"))
_TIMEOUTS = {
    "summary": int(os.getenv("AI_SUMMARY_TIMEOUT_SECONDS", "90")),
    "roadmap": int(os.getenv("AI_ROADMAP_TIMEOUT_SECONDS", "110")),
    "quiz": int(os.getenv("AI_QUIZ_TIMEOUT_SECONDS", "90")),
    "question_answer": int(os.getenv("AI_QA_TIMEOUT_SECONDS", "115")),
    "document_analysis": int(os.getenv("AI_QA_TIMEOUT_SECONDS", "115")),
}
# 텍스트 기반(추출 검증 필요) 작업
_TEXT_BASED = {"summary", "quiz", "roadmap"}


def _timeout_for(t: str) -> int:
    return min(_TIMEOUTS.get(t, 90), _GLOBAL_TIMEOUT - 5)


def _fail_response(material_id: int, t: str, error_code: str, message: str,
                   retryable: bool = True, text_status: dict | None = None) -> "MaterialAnalyzeResponse":
    """정규화된 실패 응답 (500 대신 200 + metadata.success=false)."""
    meta = {
        "success": False,
        "errorCode": error_code,
        "message": message,
        "retryable": retryable,
    }
    if text_status is not None:
        meta["textStatus"] = text_status
    return MaterialAnalyzeResponse(
        material_id=material_id, analyze_type=t, result=message, metadata=meta,
    )


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

    # 플래너/로드맵은 PDF 가 아니라 구조화 데이터다 — PDF 분석 파이프라인 진입 차단.
    if (request.material_type or "").strip().upper() in {"PLANNER", "ROADMAP", "PLAN"}:
        raise HTTPException(
            status_code=400,
            detail="플래너/로드맵은 구조화된 데이터이며 PDF 자료가 아닙니다. "
                   "별도의 구조화 분석 경로를 사용하세요.",
        )

    from app.services.material_ai_manager import (
        summarize_document,
        generate_quiz,
        generate_roadmap,
        answer_from_pdf,
        validate_extracted_text,
        validate_qa_result,
    )
    from app.services.pdf_rag_service import search_pdf_context

    t = request.analyze_type
    started = time.time()

    # 1) 텍스트 기반 작업은 추출 텍스트 검증 — 실패 시 모두 같은 원인 메시지 공유
    text_status = None
    if t in _TEXT_BASED:
        ts = validate_extracted_text(request.text)
        text_status = {"hasText": ts["ok"] and ts["status"] != "empty",
                       "textLength": ts["textLength"], "status": ts["status"]}
        if not ts["ok"]:
            return _fail_response(
                material_id, t, "PDF_TEXT_EMPTY",
                "PDF에서 추출된 텍스트가 없습니다. PDF 텍스트 추출을 다시 시도해주세요.",
                retryable=True, text_status=text_status,
            )

    timeout_s = _timeout_for(t)

    try:
        if t == "summary":
            r = await asyncio.wait_for(asyncio.to_thread(
                summarize_document,
                document_title=request.document_title or f"자료 {material_id}",
                text=request.text or "",
                personality=request.personality,
                agent_name=request.agent_name,
            ), timeout=timeout_s)
            result_text = r["summary"]
            metadata = {
                "success": True, "taskType": t, "provider": r.get("provider", "ollama_qwen"),
                "usedFallback": r.get("usedFallback", False),
                "key_points": r["key_points"],
                "overview": r.get("overview", ""),
                "keywords": r.get("keywords", []),
                "sections": r.get("sections", []),
                "warnings": r.get("warnings", []),
                "textStatus": text_status,
            }

        elif t == "quiz":
            r = await asyncio.wait_for(asyncio.to_thread(
                generate_quiz,
                document_title=request.document_title or f"자료 {material_id}",
                context=request.text or "",
                num_questions=request.num_questions or 5,
                knowledge_level=request.knowledge_level,
            ), timeout=timeout_s)
            result_text = r["quiz"]
            metadata = {
                "success": True, "taskType": t, "provider": "openai_gpt",
                "question_count": r["question_count"], "textStatus": text_status,
            }

        elif t == "roadmap":
            r = await asyncio.wait_for(asyncio.to_thread(
                generate_roadmap,
                document_title=request.document_title or f"자료 {material_id}",
                context=request.text or "",
                knowledge_level=request.knowledge_level,
            ), timeout=timeout_s)
            result_text = r["roadmap"]
            metadata = {
                "success": True, "taskType": t, "provider": "openai_gpt",
                "textStatus": text_status,
            }

        else:  # document_analysis | question_answer
            question = request.question or "이 문서의 핵심 내용을 분석해 주세요."
            chunks = await asyncio.wait_for(
                asyncio.to_thread(search_pdf_context, question, material_id), timeout=20)
            r = await asyncio.wait_for(asyncio.to_thread(
                answer_from_pdf,
                question=question,
                rag_chunks=chunks,
                personality=request.personality,
                agent_name=request.agent_name,
                knowledge_level=request.knowledge_level,
            ), timeout=timeout_s)
            qa = validate_qa_result(r["answer"], question, " ".join(c.get("content", "") for c in chunks))
            result_text = qa["answer"]
            metadata = {
                "success": True, "taskType": t, "provider": "ollama_qwen+openai_gpt",
                "chunk_count": len(r.get("sources", [])),
                "warnings": qa.get("warnings", []),
            }

    except asyncio.TimeoutError:
        logger.warning("자료 분석 타임아웃 material_id=%s type=%s timeout=%ss", material_id, t, timeout_s)
        return _fail_response(
            material_id, t, "AI_TIMEOUT",
            "AI 응답 시간이 초과되었습니다. 다시 시도해주세요.",
            retryable=True, text_status=text_status,
        )
    except Exception as e:
        logger.error("자료 분석 실패 material_id=%s type=%s: %s", material_id, t, e)
        return _fail_response(
            material_id, t, "AI_GENERATION_FAILED",
            "AI 결과 생성에 실패했습니다. 잠시 후 다시 시도해주세요.",
            retryable=True, text_status=text_status,
        )

    metadata["elapsedMs"] = int((time.time() - started) * 1000)
    logger.info("자료 분석 완료 material_id=%s type=%s provider=%s elapsedMs=%s textLen=%s",
                material_id, t, metadata.get("provider"), metadata["elapsedMs"],
                (text_status or {}).get("textLength"))

    return MaterialAnalyzeResponse(
        material_id=material_id,
        analyze_type=t,
        result=result_text,
        metadata=metadata,
    )
