-- 학습 루프 이벤트 기록 주체(origin: SERVER/CLIENT) — feature/learning-loop-ec2.
--  - additive 전용(nullable 컬럼 1개). ddl-auto=update 가 기동 시 같은 ALTER 를 자동 실행하므로 **배포 = RDS 스키마 변경**이다.
--    운영 반영은 사용자 승인 + RDS 스냅샷 후에만. 기존 행은 NULL(레거시)로 남고 데이터 변경/삭제 없음.
--  - 롤백: 애플리케이션 롤백만으로 충분(컬럼은 무시됨). 컬럼 제거가 필요하면 ALTER TABLE learning_loop_events DROP COLUMN IF EXISTS origin;
ALTER TABLE learning_loop_events ADD COLUMN IF NOT EXISTS origin varchar(16);
