"""
PDF RAG 검색 서비스.
질문을 임베딩하고 pgvector에서 유사 청크를 검색한다.

이전 더미 구현에서 실제 pgvector 검색으로 교체됨.
"""
from typing import Optional

from app.core.config import RAG_TOP_K, RAG_MIN_SCORE
from app.services.embedding_service import embed_query
from app.services.pgvector_service import search_similar_chunks


def search_pdf_context(
    question: str,
    material_id: Optional[int] = None,
    top_k: int = RAG_TOP_K,
) -> list[dict]:
    """
    질문과 유사한 PDF 청크를 pgvector에서 검색한다.

    Args:
        question:    사용자 질문
        material_id: 특정 PDF만 검색할 경우 지정 (None이면 전체 검색)
        top_k:       반환할 최대 청크 수

    Returns:
        [
            {
                "source":         "pdf_rag",
                "material_id":    int,
                "document_title": str,
                "chunk_index":    int,
                "content":        str,
                "similarity":     float,
            },
            ...
        ]
        RAG_MIN_SCORE 미만 결과는 제외됨.
    """
    # 1. 질문 임베딩
    try:
        query_vec = embed_query(question)
    except Exception as e:
        raise RuntimeError(f"질문 임베딩 실패: {e}") from e

    # 2. pgvector 유사 청크 검색
    try:
        raw_results = search_similar_chunks(
            query_embedding=query_vec,
            material_id=material_id,
            top_k=top_k,
        )
    except Exception as e:
        raise RuntimeError(f"pgvector 검색 실패: {e}") from e

    # 3. 유사도 필터링 및 반환 형식 정규화
    results = []
    for row in raw_results:
        similarity = float(row.get("similarity", 0.0))
        if similarity < RAG_MIN_SCORE:
            continue

        results.append({
            "source":         "pdf_rag",
            "material_id":    row.get("material_id"),
            "document_title": row.get("document_title", ""),
            "chunk_index":    row.get("chunk_index", -1),
            "content":        row.get("content", ""),
            "similarity":     round(similarity, 4),
        })

    return results
