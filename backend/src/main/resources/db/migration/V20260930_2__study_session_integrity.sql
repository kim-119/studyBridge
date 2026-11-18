-- 공부 세션 무결성(2026-09-30 #2): 서버 시각 source of truth + heartbeat fallback + 활성 세션 1개 보장.
--  - additive/backward-compatible. DROP/TRUNCATE/데이터 삭제 없음.
--  - 개발/스테이징: ddl-auto=update 가 컬럼/일반 인덱스는 자동 추가. partial unique index 는 JPA 로 표현할 수 없어 여기서만 만든다.
--  - 운영(RDS): 배포 전 수동 적용(멱등).
ALTER TABLE timers ADD COLUMN IF NOT EXISTS last_heartbeat_at timestamp(6) without time zone;
ALTER TABLE timers ADD COLUMN IF NOT EXISTS end_reason varchar(30);
ALTER TABLE group_study_attendances ADD COLUMN IF NOT EXISTS last_active_at timestamp(6) without time zone;

-- 사용자당 활성(STARTED) 세션 1개 — 애플리케이션 잠금(사용자 행 FOR UPDATE)의 최후 방어선.
--  ※ 적용 전 중복 활성 세션이 있으면 실패한다(2026-09-30 운영 확인: 중복 0건).
CREATE UNIQUE INDEX IF NOT EXISTS ux_timers_user_active ON timers (user_id) WHERE status = 'STARTED';

-- 통계/reaper 조회 인덱스(기존: pkey 만 존재)
CREATE INDEX IF NOT EXISTS ix_timers_user_status ON timers (user_id, status);
CREATE INDEX IF NOT EXISTS ix_timers_group_start ON timers (group_study_id, start_time);
