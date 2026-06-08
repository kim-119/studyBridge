"""
RAG 문서 ingest 서비스.
PDF 텍스트를 받아 청킹 → 임베딩 → pgvector 저장까지 수행한다.
"""
from app.core.config import RAG_CHUNK_SIZE, RAG_CHUNK_OVERLAP
from app.services.text_chunker import split_text_into_chunks
from app.services.embedding_service import embed_passage
from app.services.pgvector_service import replace_document_chunks


def ingest_document(
    material_id: int,
    document_title: str,
    text: str,
) -> dict:
    """
    PDF 추출 텍스트를 청킹하고 임베딩하여 pgvector에 저장한다.

    Args:
        material_id:    자료 ID (Spring Boot material_id 와 일치시킨다)
        document_title: 문서 제목
        text:           PDF에서 추출한 전체 텍스트

    Returns:
        {
            "material_id": int,
            "document_title": str,
            "chunk_count": int,
            "status": "ingested"
        }

    Raises:
        ValueError: 텍스트가 비어 있을 때
        RuntimeError: 임베딩 또는 DB 저장 실패 시
    """
    if not text or not text.strip():
        raise ValueError("ingest할 텍스트가 비어 있습니다.")

    # 1. 청크 분리
    chunks = split_text_into_chunks(text, RAG_CHUNK_SIZE, RAG_CHUNK_OVERLAP)
    if not chunks:
        raise ValueError("텍스트 청킹 결과가 비어 있습니다. 입력 텍스트를 확인하세요.")

    # 2. 각 청크 임베딩 생성
    chunks_with_embeddings = []
    for idx, chunk_text in enumerate(chunks):
        try:
            embedding = embed_passage(chunk_text)
        except Exception as e:
            raise RuntimeError(f"청크 {idx} 임베딩 실패: {e}") from e

        chunks_with_embeddings.append({
            "chunk_index": idx,
            "content":     chunk_text,
            "embedding":   embedding,
        })

    # 3. pgvector 저장 (기존 청크 삭제 → 새 청크 삽입, 단일 트랜잭션)
    saved = replace_document_chunks(material_id, document_title, chunks_with_embeddings)

    return {
        "material_id":    material_id,
        "document_title": document_title,
        "chunk_count":    saved,
        "status":         "ingested",
    }
