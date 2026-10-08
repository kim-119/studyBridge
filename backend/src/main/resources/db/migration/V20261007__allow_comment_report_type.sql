-- ReportType already supports COMMENT. Hibernate ddl-auto=update does not update old CHECK constraints.
-- Apply atomically; preserve every report and existing status/type policy.
BEGIN;
ALTER TABLE reports DROP CONSTRAINT IF EXISTS reports_report_type_check;
ALTER TABLE reports ADD CONSTRAINT reports_report_type_check CHECK (report_type IN ('USER', 'POST', 'COMMENT'));
COMMIT;
