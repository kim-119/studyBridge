-- StudyBridge AI RAG 전용 초기화 SQL
-- pgvector/pgvector:pg16 컨테이너 최초 시작 시 자동으로 실행된다.
-- 기존 서비스 테이블이 있는 PostgreSQL에 직접 적용할 경우
-- fastapi/db/migration/V1__create_ai_schema_and_document_chunks.sql 을 사용한다.

-- ── pgvector extension 활성화 ──────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS vector;

-- ── AI 전용 schema 생성 ────────────────────────────────────────────────
-- 기존 서비스 테이블과 충돌 방지를 위해 ai 스키마 아래에 분리한다.
CREATE SCHEMA IF NOT EXISTS ai;

-- ── PDF 청크 + 임베딩 저장 테이블 ─────────────────────────────────────
-- material_id: Spring Boot 자료보관함의 PDF ID (외래키 없이 참조용으로만 사용)
-- chunk_index: 같은 문서 내 청크 순서 (0부터 시작)
-- content:     청크 원문
-- metadata:    추가 정보 (페이지 번호, 섹션명 등 — 자유 형식 JSONB)
-- embedding:   multilingual-e5-base 기준 768차원 벡터
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

-- ── 인덱스 ────────────────────────────────────────────────────────────

-- material_id 필터링 인덱스 (특정 PDF 내 검색 시 사용)
CREATE INDEX IF NOT EXISTS idx_ai_document_chunks_material_id
    ON ai.document_chunks (material_id);

-- HNSW 인덱스: cosine distance 기반 근사 최근접 이웃 검색
-- ef_construction=64, m=16 은 품질↔속도 균형이 잘 맞는 기본값
CREATE INDEX IF NOT EXISTS idx_ai_document_chunks_embedding_hnsw
    ON ai.document_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
