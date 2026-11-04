-- training control v1 (Phase B3) — 동의 철회/자료 삭제 tombstone + 처리 이벤트 원장(멀티 워커 멱등·재전송 판정).
-- 선행: 001_training_pipeline_v2.sql. 적용은 EC2/DB 담당 승인 후(운영 RDS 직접 적용 금지). 롤백: 004_rollback_training_control_v1.sql
-- 프로세스 메모리 캐시로 정확성을 보장하지 않는다: 아래 PK/UNIQUE 제약이 동시 워커 간 중복 처리를 막는다.
BEGIN;

-- 수신한 모든 학습 채널 메시지(SAMPLE/CONSENT_WITHDRAWAL/DELETION/FEEDBACK)의 eventId 원장.
-- status: PROCESSING(선점, lease) → DONE. 같은 eventId + 다른 본문 해시 = CONFLICT(409).
CREATE TABLE IF NOT EXISTS ai.training_processed_event (
    event_id     text PRIMARY KEY CHECK (event_id ~ '^[A-Za-z0-9._:-]{8,128}$'),
    message_type text NOT NULL CHECK (message_type IN ('SAMPLE','CONSENT_WITHDRAWAL','DELETION','FEEDBACK')),
    body_sha256  char(64) NOT NULL CHECK (body_sha256 ~ '^[0-9a-f]{64}$'),
    status       text NOT NULL CHECK (status IN ('PROCESSING','DONE')),
    result       jsonb NOT NULL DEFAULT '{}'::jsonb,
    claimed_at   timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);
CREATE INDEX IF NOT EXISTS training_processed_event_type_idx ON ai.training_processed_event (message_type, claimed_at);

-- 가명 사용자 단위 동의 철회. withdrawn_at = EC2 가 서명한 철회 시각(issuedAt). 여러 번 철회되면 가장 늦은 시각을 유지.
-- 이 시각 이전에 받은 동의로 만든 샘플은 저장 거부/REVOKED, 이후 재동의로 만든 샘플만 허용(소급 확장 없음).
CREATE TABLE IF NOT EXISTS ai.training_consent_tombstone (
    pseudonymous_user_key text PRIMARY KEY CHECK (pseudonymous_user_key ~ '^[A-Za-z0-9_-]{16,128}$'),
    withdrawn_at          timestamptz NOT NULL,
    event_id              text NOT NULL,
    updated_at            timestamptz NOT NULL DEFAULT now()
);

-- 자료(또는 사용자) 단위 삭제. 이 deletionTrackingId 를 가진 샘플은 이후 영구히 저장 거부.
CREATE TABLE IF NOT EXISTS ai.training_deletion_tombstone (
    deletion_tracking_id text PRIMARY KEY CHECK (deletion_tracking_id ~ '^[A-Za-z0-9._:-]{8,128}$'),
    deleted_at           timestamptz NOT NULL,
    event_id             text NOT NULL
);

COMMIT;
