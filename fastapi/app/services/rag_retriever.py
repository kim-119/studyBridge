"""
RAG 청크 검색 서비스.
pgvector cosine similarity 기반 유사 청크를 조회한다.
DB 연결 실패 시 빈 결과를 반환하고 서버를 죽이지 않는다.
기존 pdf_rag_service.py의 인터페이스를 통합/위임한다.
"""
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


def retrieve_similar_chunks(
    question: str,
    material_id: Optional[int] = None,
    top_k: int = 5,
) -> List[dict]:
    """
    pgvector에서 질문과 유사한 청크를 검색한다.

    Args:
        question:    검색 질문
        material_id: 특정 자료로 필터 (None이면 전체)
        top_k:       반환할 최대 청크 수

    Returns:
        [{"id": int, "content": str, "similarity": float, "chunk_index": int, ...}, ...]
        DB 연결 실패 시 빈 리스트 반환.
    """
    try:
        from app.services.pdf_rag_service import search_pdf_context
        results = search_pdf_context(question, material_id, top_k)
        return results if results else []
    except ImportError:
        logger.warning("pdf_rag_service를 import할 수 없습니다.")
        return []
    except RuntimeError as e:
        logger.error("RAG 검색 실패 (DB 연결 확인): %s", e)
        return []
    except Exception as e:
        logger.error("RAG 검색 중 예상치 못한 오류: %s", e)
        return []


def is_result_sufficient(chunks: List[dict], min_count: int = 1) -> bool:
    """RAG 결과가 답변 생성에 충분한지 확인한다."""
    return len(chunks) >= min_count
