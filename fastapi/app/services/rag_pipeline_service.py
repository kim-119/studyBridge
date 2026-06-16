"""
Grounded RAG 파이프라인.

질문 → vector search(후보 넉넉히, top_k=30) → cross-encoder rerank → 상위 3개 chunk만
LLM context 로 구성 → 근거 안에서만 답변 생성 → retrieval/usedContext/citations 반환.

원칙:
  - 문서 전체/후보 전체를 LLM 에 넣지 않는다. rerank 상위 N개만 넣는다.
  - 근거에 없는 교수명/연도/강의명을 만들지 않는다(환각 방지). 근거 부족이면 부족하다고 말한다.
  - reranker 실패/timeout 은 vectorScore fallback + warnings 로 처리(서버 죽이지 않음).
  - materialId/documentId scope 밖으로 임의 확장하지 않는다(권한은 Spring 책임).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.core.config import (
    RAG_VECTOR_TOP_K, RAG_RERANK_TOP_N, RAG_MIN_SCORE, RAG_MAX_CONTEXT_CHARS,
    RAG_CHUNK_SIZE_CHARS, RAG_CHUNK_OVERLAP_CHARS,
)

logger = logging.getLogger(__name__)


def _resolve_material_id(material_id: Optional[Any], document_id: Optional[Any]) -> Optional[int]:
    if material_id is not None:
        try:
            return int(material_id)
        except (TypeError, ValueError):
            return None
    if document_id is not None:
        m = re.fullmatch(r"(?:doc[_-])?(\d+)", str(document_id).strip())
        if m:
            return int(m.group(1))
    return None


def _chunk_id_of(row: dict, material_id: Optional[int]) -> str:
    meta = row.get("metadata") or {}
    if isinstance(meta, dict) and meta.get("chunkId"):
        return str(meta["chunkId"])
    mid = row.get("material_id", material_id)
    idx = row.get("chunk_index", 0)
    try:
        return f"doc{int(mid)}_chunk_{int(idx):04d}"
    except (TypeError, ValueError):
        return f"doc{mid}_chunk_{idx}"


def _normalize_candidate(row: dict, material_id: Optional[int]) -> dict:
    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return {
        "chunkId": _chunk_id_of(row, material_id),
        "chunkIndex": row.get("chunk_index"),
        "text": row.get("content") or "",
        "vectorScore": round(float(row.get("similarity", 0.0)), 4),
        "pageStart": row.get("page_start") if row.get("page_start") is not None else meta.get("pageStart"),
        "pageEnd": row.get("page_end") if row.get("page_end") is not None else meta.get("pageEnd"),
        "metadata": meta,
    }


def _vector_candidates(question: str, material_id: Optional[int], top_k: int) -> list[dict]:
    """vector 후보 검색. 실패 시 빈 리스트(파이프라인은 근거 없음으로 진행)."""
    try:
        from app.services.embedding_service import embed_query
        from app.services.pgvector_service import search_candidate_chunks
        emb = embed_query(question)
        rows = search_candidate_chunks(emb, material_id, top_k)
    except Exception as e:  # noqa: BLE001
        logger.warning("[rag_pipeline] vector 후보 검색 실패: %s", type(e).__name__)
        return []
    cands = [_normalize_candidate(r, material_id) for r in rows]
    # RAG_MIN_SCORE 미만은 후보에서 제외(reranker 입력 품질 보호). 단 결과가 0이면 완화.
    filtered = [c for c in cands if c["vectorScore"] >= RAG_MIN_SCORE]
    return filtered if filtered else cands


def _build_context(question: str, selected: list[dict]) -> str:
    parts = ["[질문]", question.strip(), ""]
    budget = RAG_MAX_CONTEXT_CHARS
    for i, c in enumerate(selected, start=1):
        page = c.get("pageStart")
        head = f"[근거 Chunk {i}] source={c['chunkId']}" + (f", page={page}" if page is not None else "")
        body = (c.get("text") or "")[:max(0, budget)]
        budget -= len(body)
        parts.append(head)
        parts.append(body)
        parts.append("")
        if budget <= 0:
            break
    parts.append(
        "[지시]\n"
        "- 위 근거 안에서만 답변한다.\n"
        "- 근거에 없으면 '자료에서 근거를 찾지 못했다'고 말한다.\n"
        "- 추측해서 교수명, 연도, 강의명, 사람 이름을 만들지 않는다.\n"
        "- 한국어로 간결하게, 마크다운 강조 없이 답한다."
    )
    return "\n".join(parts)


_GROUNDED_SYSTEM = (
    "너는 학습 자료 기반 질의응답 도우미다. 반드시 제공된 근거 chunk 안에서만 답한다.\n"
    "근거에 없는 내용(교수명/연도/강의명/사람 이름/정의)을 지어내지 않는다.\n"
    "근거가 부족하면 솔직히 부족하다고 말한다. 일반 개념 보충이 필요하면 '일반적으로는'이라고 구분한다.\n"
    "한국어로 간결하게 답한다."
)


def _generate_answer(context: str) -> Optional[str]:
    try:
        from app.services.llm_engine_router import call_primary_llm
        raw = call_primary_llm(_GROUNDED_SYSTEM, context, max_tokens=700, temperature=0.2)
    except Exception as e:  # noqa: BLE001
        logger.info("[rag_pipeline] LLM 답변 생성 실패: %s", e)
        return None
    if not raw or raw.strip().startswith("["):
        return None
    text = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE)
    return re.sub(r"</?think>", "", text).strip() or None


def grounded_rag_query(
    question: str,
    material_id: Optional[Any] = None,
    document_id: Optional[Any] = None,
    *,
    vector_top_k: Optional[int] = None,
    rerank_top_n: Optional[int] = None,
    generate_answer: bool = True,
) -> dict:
    """grounded RAG: 후보검색 → rerank → top-N → grounded 답변. 항상 안전 응답을 반환한다."""
    from app.services.rag_rerank_service import rerank, clamp_top_n

    warnings: list[str] = []
    mid = _resolve_material_id(material_id, document_id)
    top_k = int(vector_top_k) if vector_top_k else RAG_VECTOR_TOP_K
    top_n = clamp_top_n(rerank_top_n)

    candidates = _vector_candidates(question, mid, top_k)

    if not candidates:
        warnings.append("자료에서 관련 근거 chunk를 찾지 못했습니다.")
        return {
            "success": True,
            "answer": "이 질문에 대한 근거를 자료에서 찾지 못했습니다. 자료 범위나 질문을 확인해 주세요.",
            "citations": [],
            "retrieval": {
                "chunkingPolicy": {"chunkSizeChars": RAG_CHUNK_SIZE_CHARS,
                                   "chunkOverlapChars": RAG_CHUNK_OVERLAP_CHARS},
                "vectorTopK": top_k,
                "rerankTopN": top_n,
                "candidates": [],
                "selectedChunks": [],
            },
            "usedContext": {"ragUsed": False, "rerankerUsed": False,
                            "fallbackUsed": False, "selectedChunkCount": 0},
            "warnings": warnings,
        }

    selected, info = rerank(question, candidates, top_n)
    if info.get("reason"):
        warnings.append(info["reason"])

    answer = ""
    if generate_answer:
        answer = _generate_answer(_build_context(question, selected)) or ""
        if not answer:
            warnings.append("LLM 답변 생성에 실패하여 근거 chunk만 반환합니다.")

    citations = [{
        "chunkId": c["chunkId"],
        "pageStart": c.get("pageStart"),
        "pageEnd": c.get("pageEnd"),
        "reason": "질문과 관련도가 높아 근거로 사용됨",
    } for c in selected]

    candidate_view = [{
        "chunkId": c["chunkId"],
        "vectorScore": c.get("vectorScore"),
        "rerankScore": c.get("rerankScore"),
        "pageStart": c.get("pageStart"),
        "pageEnd": c.get("pageEnd"),
    } for c in candidates]

    selected_view = [{
        "chunkId": c["chunkId"],
        "rerankScore": c.get("rerankScore"),
        "vectorScore": c.get("vectorScore"),
        "pageStart": c.get("pageStart"),
        "pageEnd": c.get("pageEnd"),
    } for c in selected]

    return {
        "success": True,
        "answer": answer,
        "citations": citations,
        "retrieval": {
            "chunkingPolicy": {"chunkSizeChars": RAG_CHUNK_SIZE_CHARS,
                               "chunkOverlapChars": RAG_CHUNK_OVERLAP_CHARS},
            "vectorTopK": top_k,
            "rerankTopN": top_n,
            "candidates": candidate_view,
            "selectedChunks": selected_view,
        },
        "usedContext": {
            "ragUsed": True,
            "rerankerUsed": info.get("rerankerUsed", False),
            "fallbackUsed": info.get("fallbackUsed", False),
            "selectedChunkCount": len(selected),
        },
        "warnings": warnings,
    }
