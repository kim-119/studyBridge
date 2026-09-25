"""
학습 시간 예측 API 스키마.
POST /api/ai/predict/study-time — Spring Boot 계약 필드명 유지 (camelCase).
길이/음수 검증은 라우터에서 HTTPException(400)으로 처리한다.
"""
from typing import List, Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class StudyTimePredictRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    userId: Optional[int] = Field(None, validation_alias=AliasChoices("userId", "user_id"), description="사용자 ID")
    weeklyStudySeconds: List[float] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "weeklyStudySeconds",
            "weekly_study_seconds",
            "weeklySeconds",
            "weekly_seconds",
            "studySeconds",
            "values",
        ),
        description="최근 7일 학습 시간 (초 단위)",
    )


class StudyTimePredictResponse(BaseModel):
    predictedStudySeconds: float = Field(..., description="예측된 학습 시간 (초 단위)")
    method: str = Field(
        "weighted_average_fallback",
        description="예측 방식: 'transformer' 또는 'weighted_average_fallback'",
    )
    confidence: float = Field(
        0.5,
        ge=0.0,
        le=1.0,
        description="예측 신뢰도 (0~1). 가중평균 fallback은 최대 0.75 제한.",
    )
    modelAvailable: bool = Field(False, description="TensorFlow 모델 사용 가능 여부")
