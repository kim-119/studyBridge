-- materials.material_type CHECK 제약에 PLANNER 추가.
--  - @Enumerated(STRING) MaterialType 에 PLANNER 를 추가했으나,
--    ddl-auto=update 는 기존 CHECK 제약(STUDY_LOG/SYLLABUS/PDF)을 갱신하지 않으므로 수동 적용한다.
--  - 운영(RDS)에는 2026-06-11 적용 완료. 신규 DB(ddl-auto=update 최초 생성)는 PLANNER 포함되어 생성되므로 무해(idempotent).
ALTER TABLE materials DROP CONSTRAINT IF EXISTS materials_material_type_check;
ALTER TABLE materials ADD CONSTRAINT materials_material_type_check
    CHECK (material_type IN ('STUDY_LOG', 'SYLLABUS', 'PDF', 'PLANNER'));
