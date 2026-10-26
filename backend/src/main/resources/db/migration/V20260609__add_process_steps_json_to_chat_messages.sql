-- StudyMate 1차/2차/3차 생성 과정(processSteps) 영속화.
-- chat_messages 에 process_steps_json (TEXT) 컬럼을 추가한다.
--
-- 적용 방식:
--   - 개발/스테이징: spring.jpa.hibernate.ddl-auto=update 가 켜져 있으면 앱 기동 시 자동 추가됨.
--   - 운영(RDS): ddl-auto 를 validate/none 로 운영하는 경우, 배포 전 이 스크립트를 수동 적용한다.
--
-- 안전성:
--   - 기존 데이터 손상 없음(추가 전용, nullable).
--   - IF NOT EXISTS 로 재실행 안전(idempotent). PostgreSQL 9.6+ 지원.
--   - 과거 메시지는 NULL → 프론트는 processSteps 없으면 생성과정 아코디언을 표시하지 않음(기존 동작 유지).

ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS process_steps_json TEXT;
