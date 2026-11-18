"""
학습 시간 예측 서비스.

TensorFlow 모델이 있으면 모델 기반 예측, 없으면 7일 가중 평균 기반 예측.
[FastAPI 내부 안전장치] Spring Boot에도 별도 fallback이 있음.
TensorFlow import 실패 시 서버 전체가 죽지 않도록 graceful degradation.

응답에 method와 confidence를 포함하여 예측 방식을 명확히 구분한다.
실제 학습된 Transformer 모델이 없으면 "transformer" method를 반환하지 않는다.
"""
import logging
import math
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
        import tensorflow as tf
    except Exception as e:
        logger.warning("TensorFlow를 import할 수 없습니다: %s. 가중평균 기반 예측으로 fallback합니다.", e)
        return False

    if not os.path.exists(model_path):
        logger.warning(
            "TF 모델 경로를 찾을 수 없습니다: %s. 가중평균 기반 예측으로 fallback합니다.", model_path
        )
        return False

    try:
        if os.path.isfile(model_path) or os.path.exists(os.path.join(model_path, "config.json")):
            _tf_model = tf.keras.models.load_model(model_path)
        elif os.path.exists(os.path.join(model_path, "saved_model.pb")):
            try:
                _tf_model = tf.keras.models.load_model(model_path)
            except Exception:
                _tf_model = tf.saved_model.load(model_path)
        else:
            logger.warning("TF 모델 파일이 없습니다: %s. 가중평균 기반 예측으로 fallback합니다.", model_path)
            return False
        _tf_available = True
        logger.info("TensorFlow 학습 시간 예측 모델 로드 완료: %s", model_path)
        return True
    except Exception as e:
        _tf_available = False
        _tf_model = None
        logger.error("TF 모델 로드 실패: %s. 가중평균 기반 예측으로 fallback합니다.", e)
        return False


def _compute_weighted_avg(weekly_seconds: List[float]) -> float:
    """7일 데이터의 가중 평균 (최근 3일 가중치 증가) 기반 예측."""
    weights = [0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.22]
    total = sum(w * v for w, v in zip(weights, weekly_seconds))
    return round(total, 1)


def _compute_fallback_confidence(weekly_seconds: List[float]) -> float:
    """
    가중평균 fallback의 신뢰도를 데이터 분산 기반으로 추정한다.
    분산이 낮을수록(패턴이 일정할수록) 신뢰도가 높다.
    최대 0.75 (실제 모델이 아니므로 상한 제한).
    """
    if not weekly_seconds:
        return 0.3
    mean = sum(weekly_seconds) / len(weekly_seconds)
    if mean == 0:
        return 0.3
    variance = sum((v - mean) ** 2 for v in weekly_seconds) / len(weekly_seconds)
    cv = math.sqrt(variance) / (mean + 1e-9)  # 변동계수 (0에 가까울수록 안정)
    # cv 0 → confidence 0.75, cv 1+ → confidence 0.35
    confidence = max(0.35, min(0.75, 0.75 - cv * 0.4))
    return round(confidence, 2)


def _model_predict(weekly_seconds: List[float]) -> float:
    """TensorFlow 모델 기반 예측."""
    import numpy as np

    input_arr = np.array([weekly_seconds], dtype=np.float32)
    if hasattr(_tf_model, "predict"):
        result = _tf_model.predict(input_arr, verbose=0)
    else:
        result = _tf_model(input_arr)
    if isinstance(result, dict):
        result = next(iter(result.values()))
    if hasattr(result, "numpy"):
        result = result.numpy()
    return float(np.asarray(result).reshape(-1)[0])


def predict_study_time(weekly_seconds: List[float]) -> dict:
    """
    학습 시간 예측 진입점.

    Args:
        weekly_seconds: 최근 7일 학습 시간 (초 단위). 길이 검증은 호출 전에 완료.

    Returns:
        {
            "predicted_seconds": float,
            "method": "transformer" | "weighted_average_fallback",
            "confidence": float,  # 0~1
        }
    """
    from app.core.config import STUDY_TIME_MODEL_PATH

    model_available = _try_load_tf_model(STUDY_TIME_MODEL_PATH)

    if model_available and _tf_model is not None:
        try:
            result = _model_predict(weekly_seconds)
            logger.info("TF 모델 예측 완료: %.1f초", result)
            return {
                "predicted_seconds": result,
                "method": "tensorflow",
                "confidence": 0.82,
            }
        except Exception as e:
            logger.error("TF 모델 예측 중 오류, 가중평균 fallback: %s", e)

    result = _compute_weighted_avg(weekly_seconds)
    confidence = _compute_fallback_confidence(weekly_seconds)
    logger.info("가중평균 예측 (fallback) 완료: %.1f초, confidence=%.2f", result, confidence)
    return {
        "predicted_seconds": result,
        "method": "weighted_average_fallback",
        "confidence": confidence,
    }
