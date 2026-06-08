"""
sentence-transformers 기반 임베딩 서비스.
모델은 최초 1회만 로드하고 이후 재사용한다.

multilingual-e5 계열 모델은 입력 앞에 접두사가 필요하다.
  - 질문(쿼리):  "query: {텍스트}"
  - 문서 청크:   "passage: {텍스트}"
"""
from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer

from app.core.config import EMBEDDING_MODEL_NAME, EMBEDDING_DIM

# 모듈 수준 캐시 — 프로세스당 한 번만 로드
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    """임베딩 모델을 로드하고 캐싱한다."""
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


def _embed(text: str) -> list[float]:
    """단일 텍스트를 임베딩 벡터로 변환하고 list[float]로 반환한다."""
    model = _get_model()
    vec: np.ndarray = model.encode(text, normalize_embeddings=True)

    if len(vec) != EMBEDDING_DIM:
        raise ValueError(
            f"임베딩 차원 불일치: 모델 출력={len(vec)}, 설정값={EMBEDDING_DIM}. "
            f"EMBEDDING_DIM 환경변수를 확인하세요."
        )

    return vec.tolist()


def embed_query(text: str) -> list[float]:
    """
    사용자 질문(쿼리)을 임베딩한다.
    multilingual-e5 계열은 "query: " 접두사를 붙인다.

    Args:
        text: 질문 원문

    Returns:
        768차원 float 리스트
    """
    return _embed(f"query: {text}")


def embed_passage(text: str) -> list[float]:
    """
    PDF 청크(문서 패시지)를 임베딩한다.
    multilingual-e5 계열은 "passage: " 접두사를 붙인다.

    Args:
        text: 청크 원문

    Returns:
        768차원 float 리스트
    """
    return _embed(f"passage: {text}")
