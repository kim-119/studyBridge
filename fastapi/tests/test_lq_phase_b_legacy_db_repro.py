"""Phase B7 — 운영 레거시 학습 후보 저장 경로가 왜 한 번도 성공할 수 없었는지 격리 DB 에서 재현한다.

운영 RDS 에는 접속하지 않는다(AI_TEST_PG_DSN 이 127.0.0.1/localhost 의 /lq 일 때만). 레거시 테이블 구조는
2026-11-04 운영 RDS information_schema 읽기 결과(test_lq_postgres_legacy_coexistence 와 같은 DDL).

재현 1: 운영 venv 에는 asyncpg 가 없다 → app/db/postgres.init_pool 이 ImportError 를 삼키고 풀 없음(=DB 기능 비활성).
재현 2: asyncpg 가 있어도 레거시 코드가 쓰는 컬럼(quality_status, candidate_uuid)이 운영 테이블에 없다 → UndefinedColumn.
v2 저장소(psycopg3, 운영 venv 에 설치됨)는 별도 테이블(001/003)을 쓰므로 레거시 테이블을 건드리지 않는다.
"""
import asyncio
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest

DSN = os.getenv("AI_TEST_PG_DSN", "")
_u = urlparse(DSN) if DSN else None
pg = pytest.mark.skipif(not DSN or _u.hostname not in ("127.0.0.1", "localhost") or _u.path != "/lq",
                        reason="ephemeral local test DB only")
PROD_VENV_PY = Path("/home/ai07/capstoneLLM/fastapi/.venv/bin/python")


def _sql(stmt):
    import psycopg
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(stmt)


@pytest.mark.skipif(not PROD_VENV_PY.exists(), reason="ai07 운영 venv 없음(CI)")
def test_prod_venv_has_psycopg_but_not_asyncpg():
    """읽기 전용: 운영 venv 의 드라이버 상태(설치/수정하지 않는다)."""
    def has(mod):
        return subprocess.run([str(PROD_VENV_PY), "-I", "-c", f"import {mod}"], capture_output=True).returncode == 0
    assert has("psycopg") and not has("asyncpg")


@pg
def test_legacy_repository_cannot_work_against_production_shaped_table(monkeypatch):
    pytest.importorskip("asyncpg")
    _sql("DROP SCHEMA IF EXISTS ai CASCADE; CREATE SCHEMA ai;")
    _sql("""CREATE TABLE ai.training_candidate (
              candidate_id uuid PRIMARY KEY, user_query text, ai_response text, feedback_score integer,
              is_exported boolean, created_at timestamp with time zone)""")
    import asyncpg
    import app.core.config as cfg
    import app.db.postgres as P
    from app.repositories import training_candidate_repository as legacy
    monkeypatch.setattr(cfg, "AI_DATABASE_URL", DSN, raising=False)
    monkeypatch.setattr(P, "_pool", None)

    async def go():
        await P.init_pool()
        try:
            with pytest.raises(asyncpg.exceptions.UndefinedColumnError):
                await legacy.get_stats()                                   # quality_status 없음
            with pytest.raises(asyncpg.exceptions.UndefinedColumnError):
                await legacy.update_status("00000000-0000-4000-8000-000000000001", "manual_approved")  # candidate_uuid 없음
        finally:
            await P.close_pool()
    asyncio.run(go())


@pg
def test_v2_store_does_not_touch_legacy_table_and_needs_001_then_003():
    from app.training_pipeline import candidate_service as cs
    from app.training_pipeline.repository import PostgresTrainingRepository
    from tests.lq_helpers import make_sample
    mig = Path(__file__).resolve().parents[1] / "app" / "training_pipeline" / "migrations"
    _sql("DROP SCHEMA IF EXISTS ai CASCADE; CREATE SCHEMA ai;")
    _sql("CREATE TABLE ai.training_candidate (candidate_id uuid PRIMARY KEY, user_query text, ai_response text)")
    for m in ("001_training_pipeline_v2.sql", "003_training_control_v1.sql"):
        _sql((mig / m).read_text(encoding="utf-8"))
    res = asyncio.run(cs.collect_sample(PostgresTrainingRepository(DSN), make_sample(1)))
    assert res.status == "STORED"
    import psycopg
    with psycopg.connect(DSN) as c:
        assert c.execute("SELECT count(*) FROM ai.training_candidate").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM ai.training_sample_v2").fetchone()[0] == 1
