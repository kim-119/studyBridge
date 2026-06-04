"""
학습 시간 예측 API 스키마.
POST /api/ai/predict/study-time — Spring Boot 계약 필드명 유지 (camelCase).
길이/음수 검증은 라우터에서 HTTPException(400)으로 처리한다.
"""
from typing import List
from pydantic import BaseModel, Field


class StudyTimePredictRequest(BaseModel):
    userId: int = Field(..., description="사용자 ID")
    weeklyStudySeconds: List[float] = Field(
        ..., description="최근 7일 학습 시간 (초 단위)"
    )


class StudyTimePredictResponse(BaseModel):
    predictedStudySeconds: float = Field(..., description="예측된 학습 시간 (초 단위)")
