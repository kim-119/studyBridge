"""
RAG API (신규 구조).
POST /api/materials/{material_id}/rag/ingest — PDF 청크 저장
POST /api/materials/{material_id}/rag/query  — 유사 청크 검색
DELETE /api/materials/{material_id}/rag      — 청크 삭제
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Path

from app.core.security import verify_internal_token
from app.schemas.rag_schema import IngestRequest, IngestResponse, RagSearchRequest, RagSearchResponse, RagDeleteResponse

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/materials",
    tags=["RAG (pgvector)"],
    dependencies=[Depends(verify_internal_token)],
)


@router.post(
    "/{material_id}/rag/ingest",
    response_model=IngestResponse,
    summary="PDF 텍스트 RAG ingest (청킹→임베딩→pgvector 저장)",
)
async def rag_ingest(
    request: IngestRequest,
    material_id: int = Path(..., gt=0),
) -> IngestResponse:
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="text는 비워둘 수 없습니다.")

    from app.services.rag_ingest_service import ingest_document
    try:
        result = await asyncio.to_thread(
            ingest_document,
            material_id=material_id,
            document_title=request.document_title,
            text=request.text,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return IngestResponse(**result)


@router.post(
    "/{material_id}/rag/query",
    response_model=RagSearchResponse,
    summary="pgvector 유사 청크 검색",
)
async def rag_query(
    request: RagSearchRequest,
    material_id: int = Path(..., gt=0),
) -> RagSearchResponse:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question은 비워둘 수 없습니다.")

    from app.services.pdf_rag_service import search_pdf_context
    from app.core.config import RAG_TOP_K
    top_k = request.top_k if request.top_k else RAG_TOP_K
    try:
        results = await asyncio.to_thread(
            search_pdf_context, request.question.strip(), material_id, top_k
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return RagSearchResponse(results=results)


@router.delete(
    "/{material_id}/rag",
    response_model=RagDeleteResponse,
    summary="자료 RAG 청크 삭제",
)
async def rag_delete(
    material_id: int = Path(..., gt=0),
) -> RagDeleteResponse:
    from app.services.pgvector_service import delete_document_chunks
    try:
        deleted = await asyncio.to_thread(delete_document_chunks, material_id)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return RagDeleteResponse(material_id=material_id, deleted_count=deleted, status="deleted")
