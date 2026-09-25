"""
RAG 라우터.
  POST   /api/rag/ingest               — PDF 텍스트 청킹·임베딩·저장
  POST   /api/rag/search               — 유사 청크 검색
  DELETE /api/rag/materials/{material_id} — 자료 삭제 시 청크 제거

모든 엔드포인트는 내부 인증 헤더(Authorization: Bearer ...)를 검사한다.
"""
from fastapi import APIRouter, Depends, HTTPException, Path

from app.core.security import verify_internal_token
from app.schemas.rag_schema import (
    IngestRequest,
    IngestResponse,
    RagSearchRequest,
    RagSearchResponse,
    RagDeleteResponse,
)
from app.services.rag_ingest_service import ingest_document
from app.services.pdf_rag_service import search_pdf_context
from app.services.pgvector_service import delete_document_chunks
from app.core.config import RAG_TOP_K

router = APIRouter(
    prefix="/api/rag",
    tags=["RAG (pgvector)"],
    dependencies=[Depends(verify_internal_token)],  # 모든 엔드포인트에 인증 적용
)


@router.post(
    "/ingest",
    response_model=IngestResponse,
    summary="PDF 텍스트 ingest",
    description=(
        "PDF에서 추출한 텍스트를 청킹 → 임베딩 → pgvector 저장한다. "
        "같은 material_id가 이미 있으면 기존 청크를 삭제하고 새 청크로 교체한다 (트랜잭션)."
    ),
)
async def rag_ingest(request: IngestRequest):
    """
    PDF 텍스트를 받아 RAG 파이프라인(청킹 → 임베딩 → pgvector 저장)을 실행한다.
    재업로드 시 기존 청크를 삭제 후 새 청크로 교체한다.
    """
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="text는 비워둘 수 없습니다.")

    try:
        result = ingest_document(
            material_id=request.material_id,
            document_title=request.document_title,
            text=request.text,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return IngestResponse(**result)


@router.post(
    "/search",
    response_model=RagSearchResponse,
    summary="pgvector 유사 청크 검색",
    description=(
        "질문을 임베딩하여 pgvector에서 유사한 PDF 청크를 검색한다. "
        "material_id를 지정하면 해당 PDF 안에서만 검색한다."
    ),
)
async def rag_search(request: RagSearchRequest):
    """
    질문과 유사한 PDF 청크를 pgvector에서 검색하고 similarity와 함께 반환한다.
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question은 비워둘 수 없습니다.")

    top_k = request.top_k if request.top_k is not None else RAG_TOP_K

    try:
        results = search_pdf_context(
            question=request.question.strip(),
            material_id=request.material_id,
            top_k=top_k,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return RagSearchResponse(results=results)


@router.delete(
    "/materials/{material_id}",
    response_model=RagDeleteResponse,
    summary="자료 RAG 청크 삭제",
    description=(
        "자료보관함에서 PDF가 삭제될 때 Spring Boot가 호출한다. "
        "해당 material_id의 모든 청크를 ai.document_chunks에서 제거한다."
    ),
)
async def rag_delete_material(
    material_id: int = Path(..., description="삭제할 자료 ID", gt=0),
):
    """
    material_id에 해당하는 모든 pgvector 청크를 삭제한다.
    """
    try:
        deleted = delete_document_chunks(material_id)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return RagDeleteResponse(
        material_id=material_id,
        deleted_count=deleted,
        status="deleted",
    )
