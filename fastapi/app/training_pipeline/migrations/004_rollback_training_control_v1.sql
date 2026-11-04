-- 003_training_control_v1.sql 롤백. tombstone 을 지우면 철회/삭제된 사용자의 샘플이 다시 수집될 수 있다 →
-- 수집(AI_TRAINING_COLLECTION_ENABLED)이 꺼져 있고 tombstone 이 0행일 때만 실행한다(아래 가드).
BEGIN;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM ai.training_consent_tombstone) OR EXISTS (SELECT 1 FROM ai.training_deletion_tombstone) THEN
        RAISE EXCEPTION 'tombstones present — refusing rollback (would re-enable withdrawn/deleted data)';
    END IF;
END $$;
DROP TABLE IF EXISTS ai.training_deletion_tombstone;
DROP TABLE IF EXISTS ai.training_consent_tombstone;
DROP TABLE IF EXISTS ai.training_processed_event;
COMMIT;
