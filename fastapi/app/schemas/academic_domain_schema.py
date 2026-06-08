"""
학문 도메인 분류 스키마.
academic_domain_classifier.py 결과를 담는 Pydantic DTO.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class AcademicDomainResult(BaseModel):
    domain: str = Field(..., description="분류된 학문 도메인")
    confidence: float = Field(..., ge=0.0, le=1.0, description="분류 신뢰도 (0~1)")
    subdomain: Optional[str] = Field(None, description="세부 분야 (선택)")
    is_high_stakes: bool = Field(False, description="의료/법률 등 고위험 도메인 여부")
    requires_recent_sources: bool = Field(False, description="최신 자료가 필요한지 여부")
    recommended_sources: List[str] = Field(
        default_factory=lambda: ["rag", "wikipedia"],
        description="권장 소스 목록",
    )
    used_llm_fallback: bool = Field(False, description="LLM fallback 분류 사용 여부")
