"""
RAG ingest / search API 요청·응답 스키마.
"""
from typing import Optional
from pydantic import BaseModel, Field


# ── Ingest ──────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    """PDF 텍스트 ingest 요청 DTO"""
    material_id:    int = Field(..., description="자료 ID (Spring Boot material_id와 일치)")
    document_title: str = Field(..., description="문서 제목")
    text:           str = Field(..., description="PDF에서 추출한 전체 텍스트", min_length=1)


class IngestResponse(BaseModel):
    """ingest 완료 응답 DTO"""
    material_id:    int
    document_title: str
    chunk_count:    int   = Field(..., description="저장된 청크 수")
    status:         str   = Field(..., description="처리 결과 상태 (ingested)")


# ── Search ──────────────────────────────────────────────────────────

class RagSearchRequest(BaseModel):
    """RAG 유사 청크 검색 요청 DTO"""
    question:    str             = Field(..., description="검색 질문", min_length=1)
    material_id: Optional[int]   = Field(None, description="특정 PDF만 검색 (None이면 전체)")
    top_k:       Optional[int]   = Field(None, description="반환할 최대 청크 수 (None이면 기본값 사용)")


class RagSearchResponse(BaseModel):
    """RAG 유사 청크 검색 응답 DTO"""
    results: list[dict] = Field(..., description="유사 청크 목록 (similarity 내림차순)")


# ── Delete ──────────────────────────────────────────────────────────

class RagDeleteResponse(BaseModel):
    """RAG 청크 삭제 응답 DTO"""
    material_id:   int = Field(..., description="삭제 대상 자료 ID")
    deleted_count: int = Field(..., description="삭제된 청크 수")
    status:        str = Field(..., description="처리 결과 상태 (deleted)")
