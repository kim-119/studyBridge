"""
학습 시간 예측 서비스.

TensorFlow 모델이 있으면 모델 기반 예측, 없으면 7일 가중 평균 기반 예측.
[FastAPI 내부 안전장치] Spring Boot에도 별도 fallback이 있음.
TensorFlow import 실패 시 서버 전체가 죽지 않도록 graceful degradation.
"""
import logging
import os
from typing import List

logger = logging.getLogger(__name__)

_tf_model = None
_tf_available = False
_model_loaded = False


def _try_load_tf_model(model_path: str) -> bool:
    global _tf_model, _tf_available, _model_loaded
    if _model_loaded:
        return _tf_available

    _model_loaded = True
    try:
        import tensorflow as tf  # noqa: F401
        _tf_available = True
    except ImportError:
        logger.warning("TensorFlow를 import할 수 없습니다. 평균 기반 예측으로 fallback합니다.")
        return False

    if not os.path.exists(model_path):
        logger.warning("TF 모델 파일을 찾을 수 없습니다: %s. 평균 기반 예측으로 fallback합니다.", model_path)
        return False

    try:
        import tensorflow as tf
        _tf_model = tf.saved_model.load(model_path)
        logger.info("TensorFlow 학습 시간 예측 모델 로드 완료: %s", model_path)
        return True
    except Exception as e:
        logger.error("TF 모델 로드 실패: %s. 평균 기반 예측으로 fallback합니다.", e)
        return False


def _average_fallback(weekly_seconds: List[float]) -> float:
    """7일 데이터의 가중 평균 (최근 3일 가중치 증가) 기반 예측."""
    weights = [0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.22]
    total = sum(w * v for w, v in zip(weights, weekly_seconds))
    return round(total, 1)


def _model_predict(weekly_seconds: List[float]) -> float:
    """TensorFlow 모델 기반 예측."""
    import numpy as np
    import tensorflow as tf

    input_arr = np.array([weekly_seconds], dtype=np.float32)
    result = _tf_model(input_arr)
    return float(result.numpy()[0][0])


def predict_study_time(weekly_seconds: List[float]) -> float:
    """
    학습 시간 예측 진입점.

    Args:
        weekly_seconds: 최근 7일 학습 시간 (초 단위). 길이 검증은 호출 전에 완료.

    Returns:
        예측된 학습 시간 (초 단위, float)
    """
    from app.core.config import STUDY_TIME_MODEL_PATH

    model_available = _try_load_tf_model(STUDY_TIME_MODEL_PATH)

    if model_available and _tf_model is not None:
        try:
            result = _model_predict(weekly_seconds)
            logger.info("TF 모델 예측 완료: %.1f초", result)
            return result
        except Exception as e:
            logger.error("TF 모델 예측 중 오류, 평균 기반으로 fallback: %s", e)

    result = _average_fallback(weekly_seconds)
    logger.info("평균 기반 예측 (fallback) 완료: %.1f초", result)
    return result
