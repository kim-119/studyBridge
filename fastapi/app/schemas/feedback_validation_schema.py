"""
에이전트 간 피드백 검증 결과 스키마.
"""
from pydantic import BaseModel, Field


class FeedbackValidationResult(BaseModel):
    originalFeedback: str = Field(..., description="원본 피드백")
    toxicityScore: float = Field(0.0, ge=0.0, le=1.0, description="독성 점수 (0=안전, 1=매우독성)")
    personalAttackScore: float = Field(0.0, ge=0.0, le=1.0, description="인신공격 점수")
    mockeryScore: float = Field(0.0, ge=0.0, le=1.0, description="조롱 점수")
    constructivenessScore: float = Field(0.0, ge=0.0, le=1.0, description="건설적 피드백 점수")
    hasImprovementSuggestion: bool = Field(False, description="개선 방향 포함 여부")
    allowed: bool = Field(True, description="그대로 표시 가능 여부")
    rewriteRequired: bool = Field(False, description="재작성 필요 여부")
    finalFeedback: str = Field("", description="최종 표시 피드백 (재작성 또는 원본)")
    wasRewritten: bool = Field(False, description="실제로 재작성이 수행됐는지")
    wasBlocked: bool = Field(False, description="완전 차단 여부 (재작성도 실패)")
