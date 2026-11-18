-- 그룹스터디 운영 정책(스터디 타입·하루 목표시간·가입 질문·닉네임 규칙·아이콘) + 가입 답변/그룹 닉네임.
--  - 모두 additive/backward-compatible. 기존 row 는 DEFAULT 로 채워진다(GENERAL / 240분 / OFF).
--  - 개발/스테이징: spring.jpa.hibernate.ddl-auto=update 가 켜져 있으면 앱 기동 시 자동 추가됨(columnDefinition 에 default 포함).
--  - 운영(RDS): ddl-auto 를 validate/none 로 운영하는 경우 배포 전 이 스크립트를 수동 적용한다. 멱등(IF NOT EXISTS).
--  - DROP/TRUNCATE/데이터 삭제 없음.
ALTER TABLE group_studies ADD COLUMN IF NOT EXISTS study_type varchar(20) DEFAULT 'GENERAL' NOT NULL;
ALTER TABLE group_studies ADD COLUMN IF NOT EXISTS target_study_minutes integer DEFAULT 240 NOT NULL;
ALTER TABLE group_studies ADD COLUMN IF NOT EXISTS join_question_enabled boolean DEFAULT false NOT NULL;
ALTER TABLE group_studies ADD COLUMN IF NOT EXISTS join_question varchar(200);
ALTER TABLE group_studies ADD COLUMN IF NOT EXISTS nickname_rule_enabled boolean DEFAULT false NOT NULL;
ALTER TABLE group_studies ADD COLUMN IF NOT EXISTS nickname_rule varchar(100);
ALTER TABLE group_studies ADD COLUMN IF NOT EXISTS study_icon_id varchar(50);

ALTER TABLE group_study_join_applications ADD COLUMN IF NOT EXISTS join_answer text;
ALTER TABLE group_study_join_applications ADD COLUMN IF NOT EXISTS nickname varchar(30);

ALTER TABLE group_study_members ADD COLUMN IF NOT EXISTS nickname varchar(30);

-- 서버(GroupStudySettingsPolicy)가 enum 을 검증하지만, DB 차원 방어도 함께 둔다(멱등).
ALTER TABLE group_studies DROP CONSTRAINT IF EXISTS group_studies_study_type_check;
ALTER TABLE group_studies ADD CONSTRAINT group_studies_study_type_check CHECK (study_type IN ('GENERAL', 'CAM'));
