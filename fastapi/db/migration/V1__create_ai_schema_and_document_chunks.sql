-- ============================================================
-- StudyBridge RAG 마이그레이션 V1
-- 목적: 기존 팀플 PostgreSQL DB에 AI 전용 schema/table 추가
-- 실행 방법 (수동):
--   psql -h <host> -p <port> -U <user> -d <dbname> -f V1__create_ai_schema_and_document_chunks.sql
-- Flyway 사용 시:
--   파일명 V1__create_ai_schema_and_document_chunks.sql 그대로 migrations 폴더에 배치
-- ============================================================

-- ── 1. pgvector extension 확인 및 활성화 ─────────────────────────────
-- RDS PostgreSQL인 경우 먼저 다음으로 지원 여부 확인:
--   SELECT * FROM pg_available_extensions WHERE name = 'vector';
-- 지원 안 되면 RDS 인스턴스 파라미터 또는 버전 업그레이드 필요.
CREATE EXTENSION IF NOT EXISTS vector;

-- ── 2. AI 전용 schema 생성 ────────────────────────────────────────────
-- 기존 서비스 테이블(public schema)과 완전 분리한다.
CREATE SCHEMA IF NOT EXISTS ai;

-- ── 3. PDF 청크 저장 테이블 ────────────────────────────────────────────
-- material_id는 자료보관함 테이블의 PK를 참조하지만
-- 서비스 DB 직접 외래키 제약을 걸지 않는다.
-- (FastAPI DB가 별도일 경우 제약 불가, 서비스 DB 공유 시 추후 추가 가능)
CREATE TABLE IF NOT EXISTS ai.document_chunks (
    id             BIGSERIAL    PRIMARY KEY,
    material_id    BIGINT       NOT NULL,
    document_title TEXT,
    chunk_index    INTEGER      NOT NULL,
    content        TEXT         NOT NULL,
    metadata       JSONB        DEFAULT '{}'::jsonb,
    embedding      vector(768)  NOT NULL,
    created_at     TIMESTAMPTZ  DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (material_id, chunk_index)
);

COMMENT ON TABLE  ai.document_chunks                IS 'StudyBridge RAG PDF 청크 + 임베딩 저장 테이블';
COMMENT ON COLUMN ai.document_chunks.material_id    IS '자료보관함 material PK (참조용, 외래키 없음)';
COMMENT ON COLUMN ai.document_chunks.chunk_index    IS '문서 내 청크 순서 (0부터 시작)';
COMMENT ON COLUMN ai.document_chunks.embedding      IS 'multilingual-e5-base 768차원 벡터';

-- ── 4. 인덱스 ─────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_ai_document_chunks_material_id
    ON ai.document_chunks (material_id);

-- HNSW 인덱스: cosine distance 근사 최근접 이웃 검색
CREATE INDEX IF NOT EXISTS idx_ai_document_chunks_embedding_hnsw
    ON ai.document_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ── 5. 확인 쿼리 (실행 후 수동 확인용) ──────────────────────────────────
-- SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema = 'ai';
-- \d ai.document_chunks
