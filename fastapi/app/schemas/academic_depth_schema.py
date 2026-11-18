"""
학문적 깊이 검증 스키마.
academic_depth_verifier.py 결과를 담는 Pydantic DTO.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class DepthVerificationResult(BaseModel):
    domain: str = Field(..., description="검증 대상 도메인")
    knowledge_level: str = Field(..., description="지식수준")

    definition_score: float = Field(0.0, ge=0.0, le=1.0, description="개념 정의 완성도")
    theory_score: float = Field(0.0, ge=0.0, le=1.0, description="이론적 배경 완성도")
    methodology_score: float = Field(0.0, ge=0.0, le=1.0, description="방법론 완성도")
    evidence_score: float = Field(0.0, ge=0.0, le=1.0, description="근거 완성도")
    limitation_score: float = Field(0.0, ge=0.0, le=1.0, description="한계/예외 완성도")
    counterargument_score: float = Field(0.0, ge=0.0, le=1.0, description="반론/대안 관점 완성도")
    domain_depth_coverage: float = Field(0.0, ge=0.0, le=1.0, description="도메인 depth axis 커버리지")

    source_leakage_detected: bool = Field(False, description="출처 노출 여부")
    rewrite_required: bool = Field(False, description="재작성 필요 여부")

    missing_requirements: List[str] = Field(
        default_factory=list, description="부족한 항목 목록"
    )
    warning_message: Optional[str] = Field(None, description="재작성 후에도 기준 미달 시 경고")


class DepthRewriteResult(BaseModel):
    original_answer: str
    rewritten_answer: str
    rewrite_applied: bool = False
    rewrite_reason: Optional[str] = None
    verification_after_rewrite: Optional[DepthVerificationResult] = None
