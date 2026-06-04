-- ============================================================
-- Migration 002: RAG 스키마 + pgvector 테이블 생성
-- 대상: AI 전용 DB (studybridge_ai) — capstone DB 적용 금지
--
-- embedding dimension: 1536 (OpenAI text-embedding-3-small)
-- sentence-transformers(multilingual-e5-base) 사용 시 768로 변경할 것.
-- ============================================================

-- ── pgvector extension 활성화 ────────────────────────────────────────────────
-- pgvector/pgvector:pg16 이미지는 이미 빌드에 포함되어 있다.
CREATE EXTENSION IF NOT EXISTS vector;

-- ── RAG 전용 스키마 ───────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS rag;

-- ── PDF 청크 + 임베딩 저장 ────────────────────────────────────────────────────
-- material_id: Spring Boot 자료보관함 materials.id (참조용, FK 없음)
-- embedding:   OpenAI text-embedding-3-small → 1536차원
--              sentence-transformers 사용 시 vector(768) 으로 변경
CREATE TABLE IF NOT EXISTS rag.document_chunk (
    id              BIGSERIAL    PRIMARY KEY,
    material_id     BIGINT       NOT NULL,
    document_title  TEXT,
    chunk_index     INTEGER      NOT NULL,
    content         TEXT         NOT NULL,
    content_hash    VARCHAR(64)  NOT NULL,           -- SHA-256 (중복 ingest 방지)
    token_count     INTEGER,
    page_number     INTEGER,
    metadata        JSONB        DEFAULT '{}'::jsonb,
    embedding       VECTOR(1536) NOT NULL,           -- OpenAI 1536차원
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (material_id, chunk_index)
);

-- ── RAG 검색 로그 ─────────────────────────────────────────────────────────────
-- 검색 품질 모니터링 및 임베딩 drift 감지용
CREATE TABLE IF NOT EXISTS rag.rag_query_log (
    id              BIGSERIAL    PRIMARY KEY,
    session_id      BIGINT,                          -- ai.conversation_session.id (참조용)
    material_id     BIGINT,
    query_text      TEXT         NOT NULL,
    query_embedding VECTOR(1536),                    -- OpenAI 1536차원
    top_k           INTEGER      NOT NULL DEFAULT 5,
    similarity_threshold NUMERIC(4,3) DEFAULT 0.25,
    result_count    INTEGER,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

COMMENT ON SCHEMA rag IS 'StudyBridge RAG 전용 스키마 — pgvector PDF 청크 저장';
COMMENT ON TABLE rag.document_chunk IS 'PDF 청크 + 임베딩 (OpenAI 1536차원)';
COMMENT ON TABLE rag.rag_query_log IS 'RAG 검색 로그 (품질 모니터링)';
COMMENT ON COLUMN rag.document_chunk.embedding IS 'OpenAI text-embedding-3-small (1536차원). sentence-transformers 전환 시 vector(768) 변경 필요';
COMMENT ON COLUMN rag.document_chunk.content_hash IS 'SHA-256 해시 — 중복 청크 ingest 방지';
