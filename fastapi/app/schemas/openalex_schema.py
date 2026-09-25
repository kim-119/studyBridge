"""
OpenAlex 응답 스키마.
openalex_service.py 내부 결과를 담는 Pydantic DTO.
이 스키마는 내부 컨텍스트 보강에만 사용하며 최종 사용자에게 노출하지 않는다.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class OpenAlexWork(BaseModel):
    """OpenAlex 논문 단건 (내부 사용)."""
    title: str = Field(..., description="논문 제목")
    publication_year: Optional[int] = Field(None, description="발행 연도")
    cited_by_count: Optional[int] = Field(None, description="인용 수 (내부 참고용)")
    abstract: Optional[str] = Field(None, description="요약 (내부 컨텍스트 보강용)")
    doi: Optional[str] = Field(None, description="DOI (내부 참고용, 사용자 노출 금지)")


class OpenAlexSearchResult(BaseModel):
    """OpenAlex 검색 결과 집합 (내부 사용)."""
    query: str
    works: List[OpenAlexWork] = Field(default_factory=list)
    total_count: int = 0
    min_publication_date: str = "2020-01-01"
    error: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None

    def to_context_text(self) -> str:
        """최종 답변에 삽입할 내부 컨텍스트 텍스트. 출처 표현 없이 내용만 반환."""
        if self.skipped or not self.works:
            return ""
        parts = []
        for w in self.works:
            if w.abstract:
                parts.append(w.abstract[:300])
        return "\n\n".join(parts)
