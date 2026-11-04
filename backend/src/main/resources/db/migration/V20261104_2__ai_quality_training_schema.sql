-- [승인 요청서] feature/learning-loop-ec2(PR #117) 운영 스키마 변경 — 적용 금지(승인·RDS 스냅샷 전).
-- 이 저장소에는 Flyway 가 없다. 운영 반영 경로는 배포 후 Spring ddl-auto=update 이며, 아래 DDL 은 그때 Hibernate 가 실행할 문장과 같다.
-- 근거(2026-11-04 dry-run 2회 — Phase C 와 Phase D 병합 후, 운영 RDS 미접속): 운영 schema-only 스냅샷(rds_schema_raw.sql, 2026-08-29, 44 테이블)을 일회용 PG16 에 올리고
--   SchemaDdlDryRunTest(hbm2ddl scripts.action=update, DB 미적용)로 받은 스크립트에서 이 PR 의 테이블/컬럼만 발췌했다.
--   스냅샷 이후 운영에 이미 반영된 다른 변경(chat_messages.event_id 등)은 제외. 실제 운영 상태와 다르면 배포 직전 같은 절차로 다시 뽑는다.
-- 성격: 전부 nullable 컬럼 추가 또는 신규 테이블. 기존 행 변경·삭제 없음. 잠금: ADD COLUMN(기본값 없음)은 메타데이터 변경(짧은 ACCESS EXCLUSIVE).
-- 사전 조건: ① 사용자 승인 ② RDS 스냅샷 ③ 피크 외 시간 ④ 롤백 담당자 지정. 플래그(AI_RESPONSE_QUALITY_GATE_ENABLED, AI_TRAINING_*)는 OFF 유지.

-- 1) 학습 루프 이벤트 기록 주체(V20261104__learning_loop_event_origin.sql 과 같은 컬럼 + Hibernate enum CHECK)
ALTER TABLE IF EXISTS public.learning_loop_events ADD COLUMN IF NOT EXISTS origin varchar(16);
-- Hibernate 는 enum 값 CHECK 를 함께 만든다. 이후 LearningEventOrigin 에 값을 추가하면 이 CHECK 를 수동 ALTER 해야 한다(MaterialType 선례).
ALTER TABLE IF EXISTS public.learning_loop_events DROP CONSTRAINT IF EXISTS learning_loop_events_origin_check;
ALTER TABLE IF EXISTS public.learning_loop_events ADD CONSTRAINT learning_loop_events_origin_check CHECK (origin IN ('SERVER', 'CLIENT'));

-- 2) 품질 게이트 판정(APPROVED 만 기록, NULL = 레거시/게이트 OFF) — Phase C·D 전체(2026-11-04 dry-run 재추출)
ALTER TABLE IF EXISTS public.chat_messages ADD COLUMN IF NOT EXISTS quality_status varchar(24);
ALTER TABLE IF EXISTS public.group_chat_messages ADD COLUMN IF NOT EXISTS quality_status varchar(24);
ALTER TABLE IF EXISTS public.material_summaries ADD COLUMN IF NOT EXISTS quality_status varchar(24);
ALTER TABLE IF EXISTS public.material_summaries ADD COLUMN IF NOT EXISTS quality_score float(53);
ALTER TABLE IF EXISTS public.material_feedbacks ADD COLUMN IF NOT EXISTS quality_status varchar(24);
ALTER TABLE IF EXISTS public.material_feedbacks ADD COLUMN IF NOT EXISTS quality_score float(53);
ALTER TABLE IF EXISTS public.material_questions ADD COLUMN IF NOT EXISTS quality_status varchar(24);
ALTER TABLE IF EXISTS public.material_quizzes ADD COLUMN IF NOT EXISTS quality_status varchar(24);
ALTER TABLE IF EXISTS public.material_quizzes ADD COLUMN IF NOT EXISTS quality_score float(53);
ALTER TABLE IF EXISTS public.group_study_quizzes ADD COLUMN IF NOT EXISTS quality_status varchar(24);
ALTER TABLE IF EXISTS public.group_study_quizzes ADD COLUMN IF NOT EXISTS quality_score float(53);
ALTER TABLE IF EXISTS public.review_notes ADD COLUMN IF NOT EXISTS quality_status varchar(24);
ALTER TABLE IF EXISTS public.review_notes ADD COLUMN IF NOT EXISTS review_needed_quality_status varchar(24);
ALTER TABLE IF EXISTS public.material_study_note_analysis ADD COLUMN IF NOT EXISTS quality_status varchar(24);
ALTER TABLE IF EXISTS public.study_journals ADD COLUMN IF NOT EXISTS quality_status varchar(24);
ALTER TABLE IF EXISTS public.roadmaps ADD COLUMN IF NOT EXISTS quality_status varchar(24);
ALTER TABLE IF EXISTS public.roadmaps ADD COLUMN IF NOT EXISTS quality_checksum varchar(64);
ALTER TABLE IF EXISTS public.plan_analysis ADD COLUMN IF NOT EXISTS quality_status varchar(24);
ALTER TABLE IF EXISTS public.planners ADD COLUMN IF NOT EXISTS plan_analysis_quality_status varchar(24);
ALTER TABLE IF EXISTS public.planner_ai_result ADD COLUMN IF NOT EXISTS quality_status varchar(24);
ALTER TABLE IF EXISTS public.planner_ai_result ADD COLUMN IF NOT EXISTS used_fallback boolean;
-- learning_recommendations 는 2026-10-12 운영 배포 테이블(스냅샷 2026-08-29 에는 없음) — 이 PR 은 컬럼 1개만 추가한다.
ALTER TABLE IF EXISTS public.learning_recommendations ADD COLUMN IF NOT EXISTS quality_status varchar(24);

-- 3) MODEL_TRAINING 동의 이력(append-only). created_at = 실제 UTC 순간(timestamptz) — C-TIME-3
CREATE TABLE IF NOT EXISTS public.ai_training_consents (
    id bigserial NOT NULL,
    age_confirmed_14_plus boolean,
    consent_text_sha256 varchar(64),
    consent_version varchar(32) NOT NULL,
    created_at timestamp(6) with time zone NOT NULL,
    purpose varchar(32) NOT NULL,
    source varchar(16),
    status varchar(16) NOT NULL,
    user_id bigint NOT NULL,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS idx_atc_user_purpose_created ON public.ai_training_consents (user_id, purpose, created_at);

-- 4) 학습 후보·제어 메시지 outbox(at-least-once, event_id 멱등). kind: SAMPLE | CONSENT_WITHDRAWAL | DELETION | FEEDBACK
CREATE TABLE IF NOT EXISTS public.ai_training_outbox (
    id bigserial NOT NULL,
    attempts integer NOT NULL,
    consent_id bigint,
    consent_version varchar(32),
    content_hash varchar(64),
    created_at timestamp(6) with time zone,
    deletion_tracking_id varchar(128),
    event_id varchar(128) NOT NULL,
    kind varchar(32) NOT NULL,
    last_error_code varchar(64),
    lease_until timestamp(6) with time zone,
    material_id bigint,
    next_attempt_at timestamp(6) with time zone,
    payload_json text,
    result_status varchar(64),
    sent_at timestamp(6) with time zone,
    status varchar(16) NOT NULL,
    updated_at timestamp(6) with time zone,
    user_id bigint NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_ato_event_id UNIQUE (event_id)
);
CREATE INDEX IF NOT EXISTS idx_ato_status_next ON public.ai_training_outbox (status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_ato_user_material ON public.ai_training_outbox (user_id, material_id);

-- 검증(적용 후, 읽기 전용):
--   SELECT column_name, data_type FROM information_schema.columns WHERE table_name IN ('ai_training_consents','ai_training_outbox') ORDER BY 1;
--   SELECT count(*) FROM ai_training_consents;  -- 0 이어야 한다(기능 OFF)

-- 롤백(승인 후에만, 역순). 1순위는 앱 롤백(새 컬럼은 무시된다) + 플래그 OFF.
--   신규 테이블에 행이 있으면(동의·철회 = 감사 근거) DROP 금지 — 먼저 보존/파기 정책 결정.
--   DROP TABLE IF EXISTS public.ai_training_outbox;
--   DROP TABLE IF EXISTS public.ai_training_consents;
--   ALTER TABLE IF EXISTS public.learning_recommendations DROP COLUMN IF EXISTS quality_status;
--   ALTER TABLE IF EXISTS public.planner_ai_result DROP COLUMN IF EXISTS used_fallback, DROP COLUMN IF EXISTS quality_status;
--   ALTER TABLE IF EXISTS public.planners DROP COLUMN IF EXISTS plan_analysis_quality_status;
--   ALTER TABLE IF EXISTS public.plan_analysis DROP COLUMN IF EXISTS quality_status;
--   ALTER TABLE IF EXISTS public.roadmaps DROP COLUMN IF EXISTS quality_checksum, DROP COLUMN IF EXISTS quality_status;
--   ALTER TABLE IF EXISTS public.study_journals DROP COLUMN IF EXISTS quality_status;
--   ALTER TABLE IF EXISTS public.material_study_note_analysis DROP COLUMN IF EXISTS quality_status;
--   ALTER TABLE IF EXISTS public.review_notes DROP COLUMN IF EXISTS review_needed_quality_status, DROP COLUMN IF EXISTS quality_status;
--   ALTER TABLE IF EXISTS public.group_study_quizzes DROP COLUMN IF EXISTS quality_score, DROP COLUMN IF EXISTS quality_status;
--   ALTER TABLE IF EXISTS public.material_quizzes DROP COLUMN IF EXISTS quality_score, DROP COLUMN IF EXISTS quality_status;
--   ALTER TABLE IF EXISTS public.material_questions DROP COLUMN IF EXISTS quality_status;
--   ALTER TABLE IF EXISTS public.group_chat_messages DROP COLUMN IF EXISTS quality_status;
--   ALTER TABLE IF EXISTS public.material_feedbacks DROP COLUMN IF EXISTS quality_score, DROP COLUMN IF EXISTS quality_status;
--   ALTER TABLE IF EXISTS public.material_summaries DROP COLUMN IF EXISTS quality_score, DROP COLUMN IF EXISTS quality_status;
--   ALTER TABLE IF EXISTS public.chat_messages DROP COLUMN IF EXISTS quality_status;
--   ALTER TABLE IF EXISTS public.learning_loop_events DROP CONSTRAINT IF EXISTS learning_loop_events_origin_check, DROP COLUMN IF EXISTS origin;
