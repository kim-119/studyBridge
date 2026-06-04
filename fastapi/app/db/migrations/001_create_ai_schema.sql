-- ============================================================
-- Migration 001: AI 스키마 + 대화/검증/학습 후보 테이블 생성
-- 대상: AI 전용 DB (studybridge_ai) — capstone DB 적용 금지
-- ============================================================

-- ── AI 전용 스키마 ────────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS ai;

-- ── 대화 세션 ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai.conversation_session (
    id              BIGSERIAL    PRIMARY KEY,
    session_uuid    UUID         NOT NULL DEFAULT gen_random_uuid(),
    user_id         BIGINT,                          -- Spring Boot users.id (참조용, 외래키 없음)
    agent_id        BIGINT,                          -- Spring Boot agents.id (참조용)
    knowledge_level VARCHAR(20)  NOT NULL DEFAULT '학사',
    personality     VARCHAR(50)  NOT NULL DEFAULT '친절_설명형',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    metadata        JSONB        DEFAULT '{}'::jsonb,
    UNIQUE (session_uuid)
);

-- ── 대화 메시지 ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai.conversation_message (
    id              BIGSERIAL    PRIMARY KEY,
    session_id      BIGINT       NOT NULL REFERENCES ai.conversation_session(id) ON DELETE CASCADE,
    role            VARCHAR(20)  NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content         TEXT         NOT NULL,
    model_used      VARCHAR(100),                    -- 'qwen2.5:7b', 'gpt-4o-mini' 등
    tokens_used     INTEGER,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── 에이전트 발화 (티키타카) ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai.agent_turn (
    id              BIGSERIAL    PRIMARY KEY,
    session_id      BIGINT       NOT NULL REFERENCES ai.conversation_session(id) ON DELETE CASCADE,
    turn_number     INTEGER      NOT NULL,           -- 발화 순서 (0부터)
    agent_role      VARCHAR(50)  NOT NULL,           -- 'A', 'B', 'C', 'moderator'
    agent_name      VARCHAR(100),
    content         TEXT         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── GPT 검증 작업 ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai.validation_job (
    id              BIGSERIAL    PRIMARY KEY,
    job_uuid        UUID         NOT NULL DEFAULT gen_random_uuid(),
    session_id      BIGINT       REFERENCES ai.conversation_session(id) ON DELETE SET NULL,
    question        TEXT         NOT NULL,
    answer          TEXT         NOT NULL,
    knowledge_level VARCHAR(20),
    personality     VARCHAR(50),
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending'
                                 CHECK (status IN ('pending','running','completed','failed')),
    score           NUMERIC(4,2),                   -- 0.00~1.00
    is_valid        BOOLEAN,
    issues          JSONB        DEFAULT '[]'::jsonb,
    correction_needed BOOLEAN    DEFAULT FALSE,
    suggestion      TEXT,
    corrected_answer TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    UNIQUE (job_uuid)
);

-- ── 학습 후보 데이터 ──────────────────────────────────────────────────────────
-- 사용자 Q/A에서 자동 수집된 학습 후보를 저장한다.
-- 민감정보 필터링, 중복 검사, GPT 자동 검수 결과를 포함한다.
CREATE TABLE IF NOT EXISTS ai.training_candidate (
    id              BIGSERIAL    PRIMARY KEY,
    candidate_uuid  UUID         NOT NULL DEFAULT gen_random_uuid(),
    session_id      BIGINT       REFERENCES ai.conversation_session(id) ON DELETE SET NULL,
    question        TEXT         NOT NULL,
    answer          TEXT         NOT NULL,
    system_prompt   TEXT,
    knowledge_level VARCHAR(20),
    personality     VARCHAR(50),
    quality_score   SMALLINT,                       -- 0~100
    quality_status  VARCHAR(30)  NOT NULL DEFAULT 'pending'
                                 CHECK (quality_status IN (
                                     'pending','auto_approved','holdout',
                                     'auto_rejected','duplicate','unsafe','reviewed','rejected'
                                 )),
    is_duplicate    BOOLEAN      NOT NULL DEFAULT FALSE,
    content_hash    VARCHAR(64),                    -- SHA-256 해시 (중복 검사용)
    is_unsafe       BOOLEAN      NOT NULL DEFAULT FALSE,
    unsafe_reason   TEXT,
    review_notes    TEXT,
    reviewed_by     VARCHAR(100),
    reviewed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (candidate_uuid)
);

-- ── 학습 데이터 내보내기 작업 ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai.training_export_job (
    id              BIGSERIAL    PRIMARY KEY,
    export_uuid     UUID         NOT NULL DEFAULT gen_random_uuid(),
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending'
                                 CHECK (status IN ('pending','running','completed','failed')),
    filter_status   VARCHAR(30)  DEFAULT 'auto_approved',
    sample_count    INTEGER,
    file_path       TEXT,
    error_message   TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    UNIQUE (export_uuid)
);

COMMENT ON SCHEMA ai IS 'StudyBridge AI 전용 스키마 — capstone 서비스 DB와 분리';
COMMENT ON TABLE ai.conversation_session IS '에이전트 대화 세션';
COMMENT ON TABLE ai.conversation_message IS '대화 메시지 (user/assistant/system)';
COMMENT ON TABLE ai.agent_turn IS '티키타카 멀티 에이전트 발화';
COMMENT ON TABLE ai.validation_job IS 'GPT 답변 품질 검증 작업';
COMMENT ON TABLE ai.training_candidate IS '학습 후보 데이터 (자동 수집 + 검수)';
COMMENT ON TABLE ai.training_export_job IS 'JSONL 내보내기 작업';
