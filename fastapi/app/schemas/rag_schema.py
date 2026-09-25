"""
RAG ingest / search / delete API 요청·응답 스키마.

기존 라우터: /api/materials/{material_id}/rag/* (하위 호환 유지)
Spring 계약 라우터: /api/rag/* (material_id를 body에 포함)
"""
from typing import List, Optional
from pydantic import BaseModel, Field


# ── Ingest ──────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    """PDF 텍스트 ingest 요청 DTO (기존 + Spring 계약 공통)"""
    material_id:    int = Field(..., description="자료 ID (Spring Boot material_id와 일치)")
    document_title: str = Field(..., description="문서 제목")
    # text 가 비어 있어도(이미지-only PDF) s3Key 가 있으면 서버가 VL 정규화로 텍스트를 만든다.
    text:           str = Field("", description="PDF에서 추출한 전체 텍스트(없으면 s3Key로 서버 추출)")
    s3Key:          str | None = Field(None, description="이미지 PDF용: text 미제공 시 S3에서 직접 로드+VL 정규화")


class IngestResponse(BaseModel):
    """ingest 완료 응답 DTO"""
    material_id:    int
    document_title: str
    chunk_count:    int = Field(..., description="저장된 청크 수")
    status:         str = Field(..., description="처리 결과 상태 (success | ingested)")


# ── Search ──────────────────────────────────────────────────────────

class RagSearchRequest(BaseModel):
    """기존 RAG 유사 청크 검색 요청 DTO (URL 경로에 material_id 포함)"""
    question:    str           = Field(..., description="검색 질문", min_length=1)
    material_id: Optional[int] = Field(None, description="특정 PDF만 검색 (None이면 전체)")
    top_k:       Optional[int] = Field(None, description="반환할 최대 청크 수")


class RagSearchResponse(BaseModel):
    """기존 RAG 유사 청크 검색 응답 DTO"""
    results: list[dict] = Field(..., description="유사 청크 목록 (similarity 내림차순)")


# ── Spring 계약 RAG 스키마 (/api/rag/query) ──────────────────────────

class RagQueryRequest(BaseModel):
    """Spring 계약: POST /api/rag/query — body에 material_id 포함"""
    material_id: int           = Field(..., description="자료 ID")
    question:    str           = Field(..., min_length=1, description="검색 질문")
    top_k:       int           = Field(5, ge=1, le=20, description="반환할 최대 청크 수")


class RagChunk(BaseModel):
    chunk_id:   int   = Field(..., description="청크 ID")
    content:    str   = Field(..., description="청크 내용")
    similarity: float = Field(..., description="코사인 유사도 (0~1)")


class RagQueryResponse(BaseModel):
    """Spring 계약: POST /api/rag/query 응답"""
    material_id: int          = Field(..., description="자료 ID")
    question:    str          = Field(..., description="검색 질문")
    chunks:      List[RagChunk] = Field(default_factory=list, description="유사 청크 목록")


# ── Delete ──────────────────────────────────────────────────────────

class RagDeleteResponse(BaseModel):
    """RAG 청크 삭제 응답 DTO"""
    material_id:   int = Field(..., description="삭제 대상 자료 ID")
    deleted_count: int = Field(..., description="삭제된 청크 수")
    status:        str = Field(..., description="처리 결과 상태 (deleted)")
