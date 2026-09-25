"""
Deep Search API 요청/응답 스키마 정의.
"""
from typing import Optional
from pydantic import BaseModel, Field


class DeepSearchRequest(BaseModel):
    """Deep Search 요청 DTO"""
    question: str = Field(..., description="사용자 질문", min_length=1)
    material_id: Optional[int] = Field(
        None,
        description="PDF 자료 ID (없으면 PDF RAG 검색 생략)"
    )


class DeepSearchResponse(BaseModel):
    """Deep Search 응답 DTO"""
    answer: str = Field(..., description="Qwen2.5가 생성한 1차 답변")
    route: dict = Field(..., description="질문 유형 분류 결과 (use_pdf, use_tavily, use_wikipedia)")
    sources: dict = Field(..., description="수집된 자료 목록 (pdf, tavily, wikipedia)")
    process_logs: list[str] = Field(..., description="파이프라인 처리 단계 로그")
