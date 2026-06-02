# pgvector 스키마 가이드

> **중요: 이 스키마는 AI 전용 DB(studybridge_ai)에만 적용한다. capstone-db에 적용 금지.**

---

## 1. 스키마 구조

```
studybridge_ai
├── ai.*          — 대화/검증/학습후보 테이블
└── rag.*         — PDF 청크 + 임베딩 테이블
```

## 2. 임베딩 차원

| 모델 | 차원 | 설정 |
|---|---|---|
| OpenAI text-embedding-3-small | **1536** | OPENAI_EMBEDDING_DIM=1536 (기본값) |
| multilingual-e5-base | 768 | EMBEDDING_DIM=768 (sentence-transformers) |

> 마이그레이션 SQL의 `VECTOR(1536)`은 OpenAI 기준.
> sentence-transformers 사용 시 `VECTOR(768)`으로 변경 후 migration 재실행 필요.

## 3. rag.document_chunk 테이블

```sql
CREATE TABLE rag.document_chunk (
    id              BIGSERIAL    PRIMARY KEY,
    material_id     BIGINT       NOT NULL,       -- Spring Boot materials.id (참조용)
    document_title  TEXT,
    chunk_index     INTEGER      NOT NULL,
    content         TEXT         NOT NULL,
    content_hash    VARCHAR(64)  NOT NULL,       -- SHA-256 (중복 방지)
    token_count     INTEGER,
    page_number     INTEGER,
    metadata        JSONB        DEFAULT '{}',
    embedding       VECTOR(1536) NOT NULL,       -- OpenAI 임베딩
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (material_id, chunk_index)
);
```

## 4. Similarity Search SQL

```sql
-- material_id 기준 상위 5개 청크 검색 (cosine distance)
SELECT
    id,
    material_id,
    document_title,
    chunk_index,
    content,
    1 - (embedding <=> $1::vector) AS similarity
FROM rag.document_chunk
WHERE material_id = $2
  AND 1 - (embedding <=> $1::vector) >= 0.25   -- RAG_MIN_SCORE
ORDER BY embedding <=> $1::vector
LIMIT 5;                                         -- RAG_TOP_K
```

## 5. HNSW 인덱스

```sql
CREATE INDEX idx_rag_document_chunk_embedding_hnsw
    ON rag.document_chunk
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

- `m=16`: 연결 수. 높을수록 검색 품질↑, 인덱스 크기↑
- `ef_construction=64`: 구축 품질. 높을수록 정확도↑, 빌드 시간↑
- 데이터 10만 건 이상: `ef_construction=128` 권장

## 6. 자료 삭제 연동

자료보관함에서 PDF 삭제 시 Spring Boot가 FastAPI를 호출:
```
DELETE /api/materials/{material_id}/rag
→ DELETE FROM rag.document_chunk WHERE material_id = $1
```
