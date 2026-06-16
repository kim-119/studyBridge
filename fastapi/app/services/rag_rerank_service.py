"""
Cross-Encoder Reranker 서비스 (RAG 2차 정밀 검색).

vector search 가 찾은 후보군(top_k)을 (query, chunk) 쌍으로 직접 채점해 관련도를 재산정하고
상위 N개만 선별한다. 모델 로딩/예측은 lazy + timeout + fallback 으로 보호해, 모델이 없거나
느려도 RAG 가 죽지 않게 한다.

fallback 순서:
  1. cross-encoder reranker 사용
  2. 로딩 실패/timeout/예측 실패 → vectorScore 기준 top_n
  3. fallback 사용 사실을 호출부가 warnings 에 명시

상태(_STATE): "untried" → 최초 1회 로드 시도 → "ready" 또는 "failed".
한 번 실패하면 이후에는 즉시 fallback(반복 다운로드/지연 방지).
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Optional

from app.core.config import (
    RAG_RERANK_ENABLED, RAG_RERANK_MODEL, RAG_RERANK_TOP_N,
    RAG_RERANK_TOP_N_MAX, RAG_RERANK_TIMEOUT_SEC, RAG_MAX_CONTEXT_CHARS,
)

logger = logging.getLogger(__name__)

_STATE = "untried"   # untried | ready | failed
_MODEL: Any = None
_LOCK = threading.Lock()
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-rerank")


def _load_model() -> bool:
    """CrossEncoder lazy 로드. 성공 True / 실패 False(이후 영구 fallback)."""
    global _STATE, _MODEL
    if _STATE == "ready":
        return True
    if _STATE == "failed":
        return False
    with _LOCK:
        if _STATE == "ready":
            return True
        if _STATE == "failed":
            return False
        try:
            from sentence_transformers import CrossEncoder
            _MODEL = CrossEncoder(RAG_RERANK_MODEL)
            _STATE = "ready"
            logger.info("[rag_rerank] CrossEncoder 로드 완료: %s", RAG_RERANK_MODEL)
            return True
        except Exception as e:  # noqa: BLE001
            _STATE = "failed"
            logger.warning("[rag_rerank] CrossEncoder 로드 실패 → vectorScore fallback 고정: %s",
                           type(e).__name__)
            return False


def _predict(pairs: list[list[str]]) -> list[float]:
    scores = _MODEL.predict(pairs)
    return [float(s) for s in scores]


def clamp_top_n(requested: Optional[int]) -> int:
    """rerank_top_n 을 [1, RAG_RERANK_TOP_N_MAX] 로 제한. None 이면 기본값."""
    n = RAG_RERANK_TOP_N if requested is None else int(requested)
    return max(1, min(n, RAG_RERANK_TOP_N_MAX))


def rerank(
    query: str,
    candidates: list[dict],
    top_n: Optional[int] = None,
    *,
    timeout_sec: Optional[float] = None,
) -> tuple[list[dict], dict]:
    """
    후보 chunk 를 재채점해 상위 top_n 선별.

    Args:
        query:      사용자 질문
        candidates: [{"chunkId","text","vectorScore", ...}, ...] (vectorScore 내림차순 가정)
        top_n:      최종 선별 개수(없으면 RAG_RERANK_TOP_N)

    Returns:
        (selected, info)
        selected: 각 dict 에 rerankScore 추가됨(상위 top_n)
        info: {"rerankerUsed": bool, "fallbackUsed": bool, "reason": Optional[str]}
    """
    n = clamp_top_n(top_n)
    info = {"rerankerUsed": False, "fallbackUsed": False, "reason": None}

    if not candidates:
        return [], info

    def _vector_fallback(reason: Optional[str]) -> tuple[list[dict], dict]:
        ranked = sorted(candidates, key=lambda c: c.get("vectorScore", 0.0), reverse=True)
        sel = ranked[:n]
        for c in sel:
            c.setdefault("rerankScore", None)
        return sel, {"rerankerUsed": False,
                     "fallbackUsed": reason is not None,
                     "reason": reason}

    if not RAG_RERANK_ENABLED:
        # rerank 비활성 — 정상 동작(fallback 아님)
        return _vector_fallback(None)

    if not _load_model():
        return _vector_fallback(
            "Cross-encoder reranker 로딩 실패로 vectorScore 기반 top-N fallback을 사용했습니다.")

    pairs = [[query, (c.get("text") or "")[:RAG_MAX_CONTEXT_CHARS]] for c in candidates]
    to = RAG_RERANK_TIMEOUT_SEC if timeout_sec is None else timeout_sec
    try:
        future = _EXECUTOR.submit(_predict, pairs)
        scores = future.result(timeout=to)
    except FutureTimeout:
        return _vector_fallback(
            f"Cross-encoder reranker timeout({to}s)으로 vectorScore 기반 top-N fallback을 사용했습니다.")
    except Exception as e:  # noqa: BLE001
        logger.warning("[rag_rerank] 예측 실패: %s", type(e).__name__)
        return _vector_fallback(
            "Cross-encoder reranker 예측 실패로 vectorScore 기반 top-N fallback을 사용했습니다.")

    for c, s in zip(candidates, scores):
        c["rerankScore"] = round(float(s), 4)
    ranked = sorted(candidates, key=lambda c: c.get("rerankScore", float("-inf")), reverse=True)
    return ranked[:n], {"rerankerUsed": True, "fallbackUsed": False, "reason": None}
