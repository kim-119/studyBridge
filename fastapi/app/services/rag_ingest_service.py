"""
RAG 문서 ingest 서비스.
PDF 텍스트를 받아 청킹 → 임베딩 → pgvector 저장까지 수행한다.

청킹 정책(RAG 정확도 개선):
  - 2,000자 이상 긴 문서: 약 400자 단위 + 100자 overlap 으로 분할(문서 통째 저장 금지).
  - 2,000자 미만 짧은 문서: 기존 RAG_CHUNK_SIZE/RAG_CHUNK_OVERLAP 동작 유지(후방 호환).
  - 두 경로 모두 chunk metadata(chunkId/chunkIndex/charStart/charEnd/tokenEstimate)를
    가능하면 함께 저장한다(metadata 컬럼이 있을 때만, additive).
"""
from app.core.config import (
    RAG_CHUNK_SIZE, RAG_CHUNK_OVERLAP,
    RAG_CHUNK_SIZE_CHARS, RAG_CHUNK_OVERLAP_CHARS, RAG_LONG_DOCUMENT_THRESHOLD_CHARS,
)
from app.services.text_chunker import split_text_into_chunks, split_text_with_metadata
from app.services.embedding_service import embed_passage
from app.services.pgvector_service import replace_document_chunks


def _chunk_id(material_id: int, chunk_index: int) -> str:
    return f"doc{material_id}_chunk_{chunk_index:04d}"


def _build_chunk_records(material_id: int, text: str) -> tuple[list[dict], dict]:
    """문서 길이에 따라 청킹 정책을 적용해 (chunk metadata 포함) 레코드 목록을 만든다."""
    length = len(text)
    is_long = length >= RAG_LONG_DOCUMENT_THRESHOLD_CHARS

    records: list[dict] = []
    if is_long:
        size, overlap = RAG_CHUNK_SIZE_CHARS, RAG_CHUNK_OVERLAP_CHARS
        for c in split_text_with_metadata(text, size, overlap):
            idx = c["chunkIndex"]
            records.append({
                "chunk_index": idx,
                "content": c["text"],
                "metadata": {
                    "chunkId": _chunk_id(material_id, idx),
                    "chunkIndex": idx,
                    "charStart": c["charStart"],
                    "charEnd": c["charEnd"],
                    "tokenEstimate": c["tokenEstimate"],
                    "chunkSizeChars": size,
                    "chunkOverlapChars": overlap,
                },
            })
    else:
        # 짧은 문서: 기존 청킹 동작 유지(청크 경계 변경 없음) + 메타데이터만 부가
        size, overlap = RAG_CHUNK_SIZE, RAG_CHUNK_OVERLAP
        for idx, chunk_text in enumerate(split_text_into_chunks(text, size, overlap)):
            records.append({
                "chunk_index": idx,
                "content": chunk_text,
                "metadata": {
                    "chunkId": _chunk_id(material_id, idx),
                    "chunkIndex": idx,
                    "tokenEstimate": max(1, len(chunk_text) // 2),
                    "chunkSizeChars": size,
                    "chunkOverlapChars": overlap,
                },
            })

    policy = {
        "documentLength": length,
        "longDocument": is_long,
        "chunkSizeChars": size,
        "chunkOverlapChars": overlap,
        "longDocumentThresholdChars": RAG_LONG_DOCUMENT_THRESHOLD_CHARS,
    }
    return records, policy


def ingest_document(
    material_id: int,
    document_title: str,
    text: str,
) -> dict:
    """
    PDF 추출 텍스트를 청킹하고 임베딩하여 pgvector에 저장한다.

    Returns:
        {"material_id", "document_title", "chunk_count", "status", "chunking_policy"}

    Raises:
        ValueError: 텍스트가 비어 있을 때
        RuntimeError: 임베딩 또는 DB 저장 실패 시
    """
    if not text or not text.strip():
        raise ValueError("ingest할 텍스트가 비어 있습니다.")

    # 1. 길이 기반 청킹 (+ metadata)
    records, policy = _build_chunk_records(material_id, text)
    if not records:
        raise ValueError("텍스트 청킹 결과가 비어 있습니다. 입력 텍스트를 확인하세요.")

    # 2. 각 청크 임베딩 생성
    for rec in records:
        try:
            rec["embedding"] = embed_passage(rec["content"])
        except Exception as e:
            raise RuntimeError(f"청크 {rec['chunk_index']} 임베딩 실패: {e}") from e

    # 3. pgvector 저장 (기존 청크 삭제 → 새 청크 삽입, 단일 트랜잭션)
    saved = replace_document_chunks(material_id, document_title, records)

    return {
        "material_id":    material_id,
        "document_title": document_title,
        "chunk_count":    saved,
        "status":         "ingested",
        "chunking_policy": policy,
    }
