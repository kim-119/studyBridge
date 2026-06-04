"""
POST /api/ai/predict/study-time — 학습 시간 예측.
Spring Boot 계약 endpoint. camelCase 필드명 유지.
길이 오류(!=7), 음수 입력 → 400 반환.
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException

from app.schemas.prediction_schema import StudyTimePredictRequest, StudyTimePredictResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["Study Time Prediction"])


@router.post(
    "/predict/study-time",
    response_model=StudyTimePredictResponse,
    summary="학습 시간 예측",
    description=(
        "최근 7일간의 학습 시간 데이터를 기반으로 다음 학습 시간을 예측한다. "
        "weeklyStudySeconds는 반드시 7개, 음수 불가. "
        "TF 모델 없으면 가중 평균 기반 예측으로 fallback한다."
    ),
)
async def predict_study_time(request: StudyTimePredictRequest) -> StudyTimePredictResponse:
    # 비즈니스 로직 검증 → 400
    if len(request.weeklyStudySeconds) != 7:
        raise HTTPException(
            status_code=400,
            detail="weeklyStudySeconds는 정확히 7개여야 합니다.",
        )
    if any(v < 0 for v in request.weeklyStudySeconds):
        raise HTTPException(
            status_code=400,
            detail="weeklyStudySeconds 값은 음수일 수 없습니다.",
        )

    try:
        from app.services.study_time_prediction_service import predict_study_time
        from app.core.config import AI_RESPONSE_TIMEOUT_SECONDS
        predicted = await asyncio.wait_for(
            asyncio.to_thread(predict_study_time, list(request.weeklyStudySeconds)),
            timeout=AI_RESPONSE_TIMEOUT_SECONDS,
        )
        return StudyTimePredictResponse(predictedStudySeconds=predicted)
    except asyncio.TimeoutError:
        logger.warning("학습 시간 예측 타임아웃 — 가중 평균 fallback 반환")
        fallback = _weighted_avg_fallback(list(request.weeklyStudySeconds))
        return StudyTimePredictResponse(predictedStudySeconds=fallback)
    except Exception as e:
        logger.error("학습 시간 예측 중 오류: %s", e)
        fallback = _weighted_avg_fallback(list(request.weeklyStudySeconds))
        return StudyTimePredictResponse(predictedStudySeconds=fallback)


def _weighted_avg_fallback(values: list[float]) -> float:
    """모델 없을 때 가중 평균으로 예측 (최근일수록 가중치 높음)."""
    if not values:
        return 0.0
    weights = list(range(1, len(values) + 1))
    total = sum(w * v for w, v in zip(weights, values))
    return round(total / sum(weights), 2)
