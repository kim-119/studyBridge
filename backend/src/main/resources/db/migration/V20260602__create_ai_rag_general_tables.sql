-- 1. 스키마 생성
CREATE SCHEMA IF NOT EXISTS ai;
CREATE SCHEMA IF NOT EXISTS rag;

-- =========================================================================
-- [Schema: ai] AI 대화 및 모델 검증/학습 관리
-- =========================================================================

-- AI 대화 세션 테이블
CREATE TABLE IF NOT EXISTS ai.conversation_session (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id BIGINT NOT NULL,                  -- public.users.user_id 참조 (물리 FK 없음)
    room_id BIGINT,                           -- public.group_studies.group_study_id 참조 (물리 FK 없음)
    material_id BIGINT,                       -- public.materials/group_study_materials.id 참조 (물리 FK 없음)
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 세션별 질문/답변 메시지 테이블
CREATE TABLE IF NOT EXISTS ai.conversation_message (
    message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    sender_role VARCHAR(20) NOT NULL,          -- 'USER', 'ASSISTANT'
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_message_session FOREIGN KEY (session_id) REFERENCES ai.conversation_session(session_id) ON DELETE CASCADE
);

-- 에이전트별 발화 기록 테이블 (Multi-Agent 워크플로우 추적용)
CREATE TABLE IF NOT EXISTS ai.agent_turn (
    turn_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    agent_name VARCHAR(50) NOT NULL,          -- 'SummaryAgent', 'QuizAgent', 'TavilyAgent' 등
    turn_index INT NOT NULL,
    input_data JSONB,
    output_data JSONB,
    latency_ms INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_turn_session FOREIGN KEY (session_id) REFERENCES ai.conversation_session(session_id) ON DELETE CASCADE
);

-- AI 답변 검증 결과 테이블 (RAG 답변 팩트체크 및 할루시네이션 탐지 결과)
CREATE TABLE IF NOT EXISTS ai.validation_job (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL,
    validator_name VARCHAR(50) NOT NULL,      -- 'HallucinationEvaluator', 'FactChecker' 등
    is_valid BOOLEAN NOT NULL,
    score NUMERIC(5, 2),
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_val_job_message FOREIGN KEY (message_id) REFERENCES ai.conversation_message(message_id) ON DELETE CASCADE
);

-- 사용자 Q/A 자동 학습 후보 테이블
CREATE TABLE IF NOT EXISTS ai.training_candidate (
    candidate_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_query TEXT NOT NULL,
    ai_response TEXT NOT NULL,
    feedback_score INT,                       -- +1 (좋음), -1 (나쁨) 등 피드백
    is_exported BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 학습 데이터 Export 이력 테이블
CREATE TABLE IF NOT EXISTS ai.training_export_job (
    export_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exported_count INT NOT NULL,
    file_url VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =========================================================================
-- [Schema: rag] RAG (검색 증강 생성) 및 벡터 청크 메타데이터 관리
-- =========================================================================

-- 자료보관함 문서 청크 메타데이터 테이블 (PDF 파싱 문서 메타 정보)
CREATE TABLE IF NOT EXISTS rag.document_chunk (
    chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    material_id BIGINT NOT NULL,              -- public.materials.material_id 참조 (물리 FK 없음)
    chunk_index INT NOT NULL,
    page_number INT,
    chunk_text TEXT NOT NULL,
    embedding_vector_id VARCHAR(100),         -- pgvector/외부 벡터 DB 고유 키
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- RAG 검색 로그 테이블 (답변 생성 시 어떤 문서 조각들을 참고했는지 로깅)
CREATE TABLE IF NOT EXISTS rag.rag_query_log (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id BIGINT NOT NULL,                  -- public.users.user_id 참조 (물리 FK 없음)
    query_text TEXT NOT NULL,
    retrieved_chunks JSONB,                   -- 검색된 매칭 청크 메타데이터 목록 (JSON Array)
    latency_ms INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =========================================================================
-- 인덱스 설계 (조회 성능 최적화)
-- =========================================================================
CREATE INDEX IF NOT EXISTS idx_conv_sess_user_id ON ai.conversation_session(user_id);
CREATE INDEX IF NOT EXISTS idx_conv_sess_room_id ON ai.conversation_session(room_id);
CREATE INDEX IF NOT EXISTS idx_conv_sess_material_id ON ai.conversation_session(material_id);

CREATE INDEX IF NOT EXISTS idx_conv_msg_session_id ON ai.conversation_message(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_turn_session_id ON ai.agent_turn(session_id);
CREATE INDEX IF NOT EXISTS idx_val_job_message_id ON ai.validation_job(message_id);

CREATE INDEX IF NOT EXISTS idx_doc_chunk_material_id ON rag.document_chunk(material_id);
CREATE INDEX IF NOT EXISTS idx_rag_log_user_id ON rag.rag_query_log(user_id);
