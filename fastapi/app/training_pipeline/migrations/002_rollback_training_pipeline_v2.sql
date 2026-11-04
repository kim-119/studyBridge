-- 001_training_pipeline_v2 롤백. 학습 후보 데이터가 있으면 중단한다(데이터 삭제 금지 원칙).
BEGIN;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM ai.training_sample_v2 LIMIT 1) THEN
        RAISE EXCEPTION 'training_sample_v2 has rows — rollback refused (export/archive first, with approval)';
    END IF;
END $$;
DROP TABLE IF EXISTS ai.training_model_candidate;
DROP TABLE IF EXISTS ai.training_dataset_member;
DROP TABLE IF EXISTS ai.training_dataset_manifest;
DROP TRIGGER IF EXISTS training_sample_event_no_update ON ai.training_sample_event;
DROP TABLE IF EXISTS ai.training_sample_event;
DROP FUNCTION IF EXISTS ai.training_sample_event_immutable();
DROP TABLE IF EXISTS ai.training_sample_v2;
COMMIT;
