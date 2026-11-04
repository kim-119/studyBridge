-- training pipeline v2 (ai07 학습 후보) — 기존 ai.training_candidate(레거시, 0행) 는 건드리지 않는다.
-- 적용은 EC2/DB 담당 승인 후. 롤백: 002_rollback_training_pipeline_v2.sql (데이터가 0행일 때만).
BEGIN;

CREATE TABLE IF NOT EXISTS ai.training_sample_v2 (
    candidate_id          uuid PRIMARY KEY,
    event_id              text NOT NULL UNIQUE,
    content_hash          char(64) NOT NULL UNIQUE,          -- 정확 중복/동시 수집 race 를 DB 가 막는다
    state                 text NOT NULL CHECK (state IN ('COLLECTED','QUARANTINED','NEEDS_REVIEW','VERIFIED',
                                                         'TRAIN_ELIGIBLE','REJECTED','REVOKED','DELETED')),
    simhash               bigint NOT NULL,
    pseudonymous_user_key text NOT NULL,
    deletion_tracking_id  text NOT NULL,
    version               integer NOT NULL DEFAULT 0,          -- 낙관적 동시성(CAS)
    record                jsonb NOT NULL,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    CHECK (content_hash ~ '^[0-9a-f]{64}$')
);
CREATE INDEX IF NOT EXISTS training_sample_v2_state_idx ON ai.training_sample_v2 (state);
CREATE INDEX IF NOT EXISTS training_sample_v2_user_idx ON ai.training_sample_v2 (pseudonymous_user_key);
CREATE INDEX IF NOT EXISTS training_sample_v2_deletion_idx ON ai.training_sample_v2 (deletion_tracking_id);

-- 불변 이벤트 로그(해시 체인). UPDATE/DELETE 금지 트리거.
CREATE TABLE IF NOT EXISTS ai.training_sample_event (
    seq          bigserial PRIMARY KEY,
    event_id     uuid NOT NULL UNIQUE,
    candidate_id uuid NOT NULL,
    event_type   text NOT NULL,
    from_state   text,
    to_state     text,
    actor        text NOT NULL,
    actor_role   text NOT NULL,
    request_id   text,
    reason_codes text[] NOT NULL DEFAULT '{}',
    at           timestamptz NOT NULL,
    prev_hash    text NOT NULL,
    event_hash   char(64) NOT NULL
);
CREATE INDEX IF NOT EXISTS training_sample_event_candidate_idx ON ai.training_sample_event (candidate_id);

CREATE OR REPLACE FUNCTION ai.training_sample_event_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ai.training_sample_event is append-only';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS training_sample_event_no_update ON ai.training_sample_event;
CREATE TRIGGER training_sample_event_no_update BEFORE UPDATE OR DELETE ON ai.training_sample_event
    FOR EACH ROW EXECUTE FUNCTION ai.training_sample_event_immutable();

CREATE TABLE IF NOT EXISTS ai.training_dataset_manifest (
    dataset_id          text PRIMARY KEY CHECK (dataset_id ~ '^train_v[0-9]{8}_[0-9]{3}_[0-9a-f]{8}$'),
    status              text NOT NULL CHECK (status IN ('PENDING','ACTIVE','INVALIDATED')),  -- PENDING: 파일 기록 중
    manifest_sha256     char(64) NOT NULL,
    created_at          timestamptz NOT NULL,
    invalidated_reasons text[] NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS ai.training_dataset_member (
    dataset_id   text NOT NULL REFERENCES ai.training_dataset_manifest(dataset_id),
    content_hash char(64) NOT NULL,
    PRIMARY KEY (dataset_id, content_hash)
);
CREATE INDEX IF NOT EXISTS training_dataset_member_hash_idx ON ai.training_dataset_member (content_hash);

CREATE TABLE IF NOT EXISTS ai.training_model_candidate (
    adapter_id    text PRIMARY KEY,
    dataset_id    text NOT NULL REFERENCES ai.training_dataset_manifest(dataset_id),
    base_model    text NOT NULL,
    status        text NOT NULL CHECK (status IN ('REGISTERED','EVALUATING','REJECTED','APPROVED_FOR_CANARY',
                                                  'RETIREMENT_REQUIRED')),
    candidate_tag text,                                         -- 운영 태그(qwen3:14b)와 분리된 후보 태그만
    notes         text[] NOT NULL DEFAULT '{}',
    CHECK (candidate_tag IS NULL OR candidate_tag NOT IN ('qwen3:14b','qwen3:latest'))
);

COMMIT;
