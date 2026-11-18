"""
AI DB / pgvector 연결 상태 점검 스크립트.

실행 방법:
  python scripts/check_ai_db_connection.py

종료 코드:
  0 — 모든 핵심 체크 통과
  1 — 하나 이상 실패
"""
import os
import sys

DB_URL = os.environ.get("AI_DATABASE_URL") or os.environ.get("VECTOR_DATABASE_URL")
AUTO_MIGRATE = os.environ.get("AUTO_RUN_AI_MIGRATIONS", "false").lower() == "true"


def _ok(label: str, msg: str = "") -> None:
    suffix = f": {msg}" if msg else ""
    print(f"  [OK]  {label}{suffix}")


def _fail(label: str, msg: str = "") -> None:
    suffix = f": {msg}" if msg else ""
    print(f"  [FAIL] {label}{suffix}")


def check_all() -> bool:
    if not DB_URL:
        print("[FAIL] AI_DATABASE_URL / VECTOR_DATABASE_URL 환경변수가 설정되지 않았습니다.")
        return False

    all_ok = True

    try:
        import psycopg
        conn = psycopg.connect(DB_URL, connect_timeout=5)
    except Exception as e:
        _fail("PostgreSQL 연결", str(e))
        return False

    _ok("PostgreSQL 연결")

    with conn:
        with conn.cursor() as cur:

            # pgvector extension
            try:
                cur.execute("SELECT installed_version FROM pg_available_extensions WHERE name='vector'")
                row = cur.fetchone()
                if row and row[0]:
                    _ok("pgvector extension", f"v{row[0]}")
                else:
                    _fail("pgvector extension", "미설치 — CREATE EXTENSION IF NOT EXISTS vector; 필요")
                    all_ok = False
            except Exception as e:
                _fail("pgvector extension", str(e))
                all_ok = False

            # ai schema
            try:
                cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name='ai'")
                if cur.fetchone():
                    _ok("ai schema")
                else:
                    _fail("ai schema", "없음 — CREATE SCHEMA IF NOT EXISTS ai; 필요")
                    all_ok = False
            except Exception as e:
                _fail("ai schema", str(e))
                all_ok = False

            # ai.document_chunks
            try:
                cur.execute("SELECT to_regclass('ai.document_chunks')")
                row = cur.fetchone()
                if row and row[0]:
                    _ok("ai.document_chunks 테이블")
                else:
                    _fail("ai.document_chunks 테이블", "없음")
                    all_ok = False
            except Exception as e:
                _fail("ai.document_chunks 테이블", str(e))
                all_ok = False

            # ai.training_candidate
            try:
                cur.execute("SELECT to_regclass('ai.training_candidate')")
                row = cur.fetchone()
                if row and row[0]:
                    _ok("ai.training_candidate 테이블")
                else:
                    _fail("ai.training_candidate 테이블", "없음")
                    all_ok = False
            except Exception as e:
                _fail("ai.training_candidate 테이블", str(e))
                all_ok = False

    conn.close()
    return all_ok


if __name__ == "__main__":
    print("=" * 50)
    print("AI DB 연결 점검")
    print("=" * 50)
    passed = check_all()
    print("=" * 50)

    if AUTO_MIGRATE and not passed:
        print("[INFO] AUTO_RUN_AI_MIGRATIONS=true — 마이그레이션 스크립트를 실행합니다.")
        import subprocess
        result = subprocess.run(
            [sys.executable, "scripts/run_ai_migrations.py"],
            capture_output=False,
        )
        sys.exit(result.returncode)

    if passed:
        print("[PASS] 모든 AI DB 체크 통과")
        sys.exit(0)
    else:
        print("[FAIL] 일부 체크 실패 — run_ai_migrations.py 실행을 검토하세요.")
        sys.exit(1)
