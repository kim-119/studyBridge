"""
PostgreSQL + pgvector 연결 및 벡터 검색 서비스.

연결 방식: psycopg v3 (동기)
벡터 타입: pgvector Python 패키지로 등록
테이블:   rag.document_chunk  (ai 스키마 분리)
거리 함수: cosine distance (<=>), similarity = 1 - distance
"""
from __future__ import annotations

import psycopg
from pgvector.psycopg import register_vector

from app.core.config import VECTOR_DATABASE_URL, RAG_TOP_K

# 테이블 이름 상수 — 스키마 포함 (변경 시 이 곳만 수정)
_TABLE = "rag.document_chunk"


def _get_connection() -> psycopg.Connection:
    """
    pgvector DB에 새 커넥션을 생성하고 vector 타입을 등록한다.

    Returns:
        psycopg.Connection 객체

    Raises:
        RuntimeError: VECTOR_DATABASE_URL 미설정 또는 연결 실패 시
    """
    if not VECTOR_DATABASE_URL:
        raise RuntimeError(
            "VECTOR_DATABASE_URL 환경변수가 설정되지 않았습니다. "
            ".env 파일에 VECTOR_DATABASE_URL=postgresql://... 를 추가하세요."
        )

    try:
        conn = psycopg.connect(VECTOR_DATABASE_URL)
        register_vector(conn)
        return conn
    except Exception as e:
        raise RuntimeError(f"pgvector DB 연결 실패: {e}") from e


def replace_document_chunks(
    material_id: int,
    document_title: str,
    chunks_with_embeddings: list[dict],
) -> int:
    """
    같은 material_id의 기존 청크를 모두 삭제하고 새 청크로 교체한다.
    하나의 트랜잭션 안에서 DELETE → INSERT 순서로 처리해 일관성을 보장한다.

    Args:
        material_id:            자료 ID
        document_title:         문서 제목
        chunks_with_embeddings: [{"chunk_index": int, "content": str, "embedding": list[float]}, ...]

    Returns:
        저장된 청크 수
    """
    if not chunks_with_embeddings:
        return 0

    delete_sql = f"DELETE FROM {_TABLE} WHERE material_id = %s"

    insert_sql = f"""
        INSERT INTO {_TABLE}
            (material_id, document_title, chunk_index, content, embedding)
        VALUES (%s, %s, %s, %s, %s)
    """

    saved = 0
    # autocommit=False (psycopg 기본값) → 명시적 commit/rollback
    with _get_connection() as conn:
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                # 기존 청크 전체 삭제
                cur.execute(delete_sql, (material_id,))

                # 새 청크 일괄 삽입
                for item in chunks_with_embeddings:
                    cur.execute(
                        insert_sql,
                        (
                            material_id,
                            document_title,
                            item["chunk_index"],
                            item["content"],
                            item["embedding"],
                        ),
                    )
                    saved += 1

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return saved


def delete_document_chunks(material_id: int) -> int:
    """
    특정 material_id에 해당하는 모든 청크를 삭제한다.
    자료보관함에서 PDF가 삭제될 때 Spring Boot가 호출하는 용도.

    Args:
        material_id: 삭제할 자료 ID

    Returns:
        삭제된 행 수
    """
    sql = f"DELETE FROM {_TABLE} WHERE material_id = %s"

    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (material_id,))
            deleted = cur.rowcount
        conn.commit()

    return deleted


def search_similar_chunks(
    query_embedding: list[float],
    material_id: int | None = None,
    top_k: int = RAG_TOP_K,
) -> list[dict]:
    """
    질문 임베딩과 유사한 PDF 청크를 pgvector에서 검색한다.

    Args:
        query_embedding: 질문 임베딩 벡터 (list[float])
        material_id:     특정 PDF만 검색할 경우 지정 (None이면 전체 검색)
        top_k:           반환할 최대 청크 수

    Returns:
        [{"id": int, "material_id": int, "document_title": str,
          "chunk_index": int, "content": str, "similarity": float}, ...]
    """
    sql = f"""
        SELECT
            id,
            material_id,
            document_title,
            chunk_index,
            content,
            1 - (embedding <=> %s::vector) AS similarity
        FROM {_TABLE}
        WHERE (%s IS NULL OR material_id = %s)
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """

    results = []
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    query_embedding,
                    material_id,
                    material_id,
                    query_embedding,
                    top_k,
                ),
            )
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description]

    for row in rows:
        results.append(dict(zip(cols, row)))

    return results
