-- ============================================================
-- Migration 003: 인덱스 생성
-- 대상: AI 전용 DB (studybridge_ai) — capstone DB 적용 금지
--
-- 주의:
--   HNSW 인덱스는 대용량 데이터에서 생성 시간이 길다.
--   인덱스 생성 실패 시 테이블 자체는 정상 동작한다 (검색만 느려짐).
--   CREATE INDEX CONCURRENTLY는 트랜잭션 밖에서 실행해야 한다.
-- ============================================================

-- ── ai 스키마 인덱스 ──────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_ai_conversation_session_user_id
    ON ai.conversation_session (user_id)
    WHERE user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ai_conversation_session_agent_id
    ON ai.conversation_session (agent_id)
    WHERE agent_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ai_conversation_message_session_id
    ON ai.conversation_message (session_id);

CREATE INDEX IF NOT EXISTS idx_ai_agent_turn_session_id
    ON ai.agent_turn (session_id);

CREATE INDEX IF NOT EXISTS idx_ai_validation_job_uuid
    ON ai.validation_job (job_uuid);

CREATE INDEX IF NOT EXISTS idx_ai_validation_job_status
    ON ai.validation_job (status);

CREATE INDEX IF NOT EXISTS idx_ai_training_candidate_status
    ON ai.training_candidate (quality_status);

CREATE INDEX IF NOT EXISTS idx_ai_training_candidate_hash
    ON ai.training_candidate (content_hash)
    WHERE content_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ai_training_candidate_duplicate
    ON ai.training_candidate (is_duplicate)
    WHERE is_duplicate = TRUE;

-- ── rag 스키마 인덱스 ─────────────────────────────────────────────────────────

-- material_id 필터 인덱스 (특정 PDF 내 검색)
CREATE INDEX IF NOT EXISTS idx_rag_document_chunk_material_id
    ON rag.document_chunk (material_id);

CREATE INDEX IF NOT EXISTS idx_rag_document_chunk_content_hash
    ON rag.document_chunk (content_hash);

-- HNSW 인덱스: pgvector cosine distance 기반 근사 최근접 이웃 검색
-- m=16, ef_construction=64 → 품질↔속도 균형 기본값
-- 데이터가 10만 건 이상이면 ef_construction=128 권장
CREATE INDEX IF NOT EXISTS idx_rag_document_chunk_embedding_hnsw
    ON rag.document_chunk
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- rag_query_log 인덱스
CREATE INDEX IF NOT EXISTS idx_rag_query_log_material_id
    ON rag.rag_query_log (material_id)
    WHERE material_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_rag_query_log_created_at
    ON rag.rag_query_log (created_at DESC);

-- ── 확인 쿼리 (수동 실행용, 주석 처리됨) ────────────────────────────────────
-- SELECT schemaname, tablename, indexname FROM pg_indexes
--   WHERE schemaname IN ('ai', 'rag') ORDER BY schemaname, tablename;
