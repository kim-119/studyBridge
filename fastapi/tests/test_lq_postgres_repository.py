"""Postgres v2 저장소 + 마이그레이션 통합 테스트 — 일회용 DB 에서만 실행(AI_TEST_PG_DSN 미설정 시 skip).

운영 RDS 에는 절대 실행하지 않는다: DSN 호스트가 127.0.0.1/localhost 이고 DB 이름이 'lq' 일 때만 동작.
  docker run -d --rm --name sb-lq-pgtest -e POSTGRES_PASSWORD=lqtest -e POSTGRES_USER=lq -e POSTGRES_DB=lq \\
      -p 127.0.0.1:55432:5432 pgvector/pgvector:pg16
  AI_TEST_PG_DSN=postgresql://lq:lqtest@127.0.0.1:55432/lq pytest tests/test_lq_postgres_repository.py
"""
import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

DSN = os.getenv("AI_TEST_PG_DSN", "")
_u = urlparse(DSN) if DSN else None
pytestmark = pytest.mark.skipif(not DSN or _u.hostname not in ("127.0.0.1", "localhost") or _u.path != "/lq",
                                reason="ephemeral local test DB only")
MIG = Path(__file__).resolve().parents[1] / "app" / "training_pipeline" / "migrations"


def _sql(stmt: str):
    import psycopg
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(stmt)


@pytest.fixture
def repo():
    _sql("DROP SCHEMA IF EXISTS ai CASCADE; CREATE SCHEMA ai;")
    _sql((MIG / "001_training_pipeline_v2.sql").read_text(encoding="utf-8"))
    _sql((MIG / "001_training_pipeline_v2.sql").read_text(encoding="utf-8"))   # 멱등 재적용
    from app.training_pipeline.repository import PostgresTrainingRepository
    return PostgresTrainingRepository(DSN)


def test_full_lifecycle_on_postgres(repo, tmp_path, monkeypatch):
    from app.training_pipeline import candidate_service as cs
    from app.training_pipeline import export_service as ex
    from tests.lq_helpers import make_sample
    monkeypatch.setenv("AI_TRAINING_DATASET_DIR", str(tmp_path / "ds"))
    rv = cs.Actor("rev-1", "training_reviewer", "req-pg-0001")

    async def go():
        ids = []
        for i in range(6):
            r = await cs.collect_sample(repo, make_sample(i, user=f"pk_pguser_{i % 3:010d}"))
            assert r.status == "STORED"
            await cs.review(repo, r.candidate_id, decision="VERIFY", actor=rv)
            ids.append(r.candidate_id)
        counts = await repo.counts_by_state()
        assert counts["TRAIN_ELIGIBLE"] == 6
        exp = await ex.export_dataset(repo, actor="admin", request_id="req-pg-exp1")
        assert exp.status == "completed" and exp.total == 6
        victim = await repo.get(ids[0])
        again = make_sample(0, user="pk_pguser_0000000000", feedback=-1).model_copy(update={"eventId": "evt-pg-dupneg"})
        res = await cs.collect_sample(repo, again)
        assert res.status == "DUPLICATE" and res.state == "REVOKED" and exp.dataset_id in res.invalidated_datasets
        m = await repo.get_manifest(exp.dataset_id)
        assert m.status == "INVALIDATED" and len(m.member_hashes) == 6
        evs = await repo.events_for(victim.candidate_id)
        assert [e.to_state for e in evs][-1] == "REVOKED"
    asyncio.run(go())


def test_event_log_is_append_only(repo):
    import psycopg
    from app.training_pipeline import candidate_service as cs
    from tests.lq_helpers import make_sample
    asyncio.run(cs.collect_sample(repo, make_sample(1)))
    with pytest.raises(psycopg.Error):
        _sql("UPDATE ai.training_sample_event SET actor='x'")
    with pytest.raises(psycopg.Error):
        _sql("DELETE FROM ai.training_sample_event")


def test_unique_constraint_blocks_concurrent_duplicates(repo):
    from app.training_pipeline import candidate_service as cs
    from tests.lq_helpers import make_sample
    s = make_sample(5)

    async def go():
        a = s.model_copy(update={"eventId": "evt-race-aaaa"})
        b = s.model_copy(update={"eventId": "evt-race-bbbb"})
        return await asyncio.gather(cs.collect_sample(repo, a), cs.collect_sample(repo, b))
    r = asyncio.run(go())
    assert sorted(x.status for x in r) == ["DUPLICATE", "STORED"]
    import psycopg
    with psycopg.connect(DSN) as c:
        assert c.execute("SELECT count(*) FROM ai.training_sample_v2").fetchone()[0] == 1


def test_rollback_refuses_when_rows_exist(repo):
    import psycopg
    from app.training_pipeline import candidate_service as cs
    from tests.lq_helpers import make_sample
    asyncio.run(cs.collect_sample(repo, make_sample(9)))
    with pytest.raises(psycopg.Error):
        _sql((MIG / "002_rollback_training_pipeline_v2.sql").read_text(encoding="utf-8"))


def test_production_tag_cannot_be_registered_as_candidate(repo):
    import psycopg
    _sql("INSERT INTO ai.training_dataset_manifest VALUES ('train_v20261104_001_abcdef01','ACTIVE','" + "0" * 64 + "',now(),'{}')")
    with pytest.raises(psycopg.Error):
        _sql("INSERT INTO ai.training_model_candidate (adapter_id,dataset_id,base_model,status,candidate_tag) "
             "VALUES ('a1','train_v20261104_001_abcdef01','Qwen/Qwen3-14B','REGISTERED','qwen3:14b')")
