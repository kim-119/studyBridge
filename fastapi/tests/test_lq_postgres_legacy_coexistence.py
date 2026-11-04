"""운영 RDS 와 같은 '레거시 ai 스키마'가 있는 일회용 Postgres 에서 v2 migration/저장소 계약을 검증한다.

운영 RDS 에는 접속하지 않는다(AI_TEST_PG_DSN 이 127.0.0.1/localhost 의 /lq 일 때만). 레거시 구조는 2026-11-04 운영 RDS 의
information_schema 읽기 결과를 그대로 옮겼다:
  ai 스키마 테이블 6개: agent_turn, conversation_message, conversation_session, training_candidate, training_export_job,
  validation_job. 이 중 training_candidate 컬럼은 정확히 재현했다(candidate_id uuid PK, user_query text, ai_response text,
  feedback_score integer, is_exported boolean, created_at timestamptz). 나머지 5개는 컬럼을 조회하지 않았으므로
  '이름 충돌/보존' 확인용 자리표시 테이블이다.
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
LEGACY_TABLES = ("agent_turn", "conversation_message", "conversation_session", "training_candidate",
                 "training_export_job", "validation_job")
V2_TABLES = ("training_sample_v2", "training_sample_event", "training_dataset_manifest", "training_dataset_member",
             "training_model_candidate")


def _sql(stmt: str, fetch: bool = False):
    import psycopg
    with psycopg.connect(DSN, autocommit=True) as c:
        cur = c.execute(stmt)
        return cur.fetchall() if fetch else None


def _apply(name: str):
    _sql((MIG / name).read_text(encoding="utf-8"))


def _fingerprint():
    """레거시 테이블의 컬럼 정의 + 전 행 해시. migration 전후 동일해야 한다."""
    out = {}
    for t in LEGACY_TABLES:
        cols = _sql(f"""SELECT column_name, data_type, is_nullable, coalesce(column_default,'')
                         FROM information_schema.columns WHERE table_schema='ai' AND table_name='{t}'
                         ORDER BY ordinal_position""", fetch=True)
        rows = _sql(f"SELECT md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM ai.{t} x", fetch=True)
        out[t] = (tuple(cols), rows[0][0])
    return out


def _tables():
    return {r[0] for r in _sql("SELECT table_name FROM information_schema.tables WHERE table_schema='ai'", fetch=True)}


@pytest.fixture
def legacy():
    _sql("DROP SCHEMA IF EXISTS ai CASCADE; CREATE SCHEMA ai;")
    _sql("""CREATE TABLE ai.training_candidate (
              candidate_id uuid PRIMARY KEY, user_query text, ai_response text, feedback_score integer,
              is_exported boolean, created_at timestamp with time zone)""")
    for t in LEGACY_TABLES:
        if t != "training_candidate":
            _sql(f"CREATE TABLE ai.{t} (id bigserial PRIMARY KEY, payload text)")          # 자리표시
            _sql(f"INSERT INTO ai.{t} (payload) VALUES ('synthetic-{t}-1'), ('synthetic-{t}-2')")
    _sql("""INSERT INTO ai.training_candidate VALUES
              ('00000000-0000-4000-8000-000000000001','합성 질문 1','합성 답변 1',1,false,'2026-10-01T00:00:00Z'),
              ('00000000-0000-4000-8000-000000000002','합성 질문 2','합성 답변 2',-1,true,'2026-10-02T00:00:00Z'),
              ('00000000-0000-4000-8000-000000000003',NULL,NULL,NULL,NULL,NULL)""")
    return _fingerprint()


def _repo():
    from app.training_pipeline.repository import PostgresTrainingRepository
    return PostgresTrainingRepository(DSN)


def test_forward_migration_is_additive_and_idempotent(legacy):
    _apply("001_training_pipeline_v2.sql")
    _apply("001_training_pipeline_v2.sql")
    assert set(V2_TABLES) | set(LEGACY_TABLES) == _tables()
    assert _fingerprint() == legacy                      # 레거시 컬럼/행 바이트 동일


def test_backward_migration_restores_exact_legacy_state(legacy):
    _apply("001_training_pipeline_v2.sql")
    _apply("002_rollback_training_pipeline_v2.sql")
    assert _tables() == set(LEGACY_TABLES) and _fingerprint() == legacy
    _apply("001_training_pipeline_v2.sql")                # 다시 forward 가능
    assert set(V2_TABLES) <= _tables()


def test_phase_b_migration_order_forward_and_backward_keeps_legacy_exact(legacy):
    """운영 적용 순서: 001 → 003 (롤백: 004 → 002). 레거시 ai.training_candidate 는 컬럼·행 모두 그대로."""
    for m in ("001_training_pipeline_v2.sql", "003_training_control_v1.sql", "003_training_control_v1.sql"):
        _apply(m)
    assert {"training_processed_event", "training_consent_tombstone", "training_deletion_tombstone"} <= _tables()
    assert _fingerprint() == legacy
    _apply("004_rollback_training_control_v1.sql")
    _apply("002_rollback_training_pipeline_v2.sql")
    assert _tables() == set(LEGACY_TABLES) and _fingerprint() == legacy


def test_missing_003_makes_collection_deferred_not_silently_unchecked(legacy):
    """003 을 빠뜨리고 001 만 적용하면 tombstone 확인이 불가 → 저장하지 않고 DEFERRED(fail-closed)."""
    from app.training_pipeline import candidate_service as cs
    from tests.lq_helpers import make_sample
    _apply("001_training_pipeline_v2.sql")
    res = asyncio.run(cs.collect_sample(_repo(), make_sample(7)))
    assert res.status == "DEFERRED" and res.reasons == ["TRAINING_REPOSITORY_UNAVAILABLE"]
    assert asyncio.run(_repo().counts_by_state())["COLLECTED"] == 0


def test_rollback_refused_once_v2_has_data_and_legacy_untouched(legacy):
    import psycopg
    from app.training_pipeline import candidate_service as cs
    from tests.lq_helpers import make_sample
    _apply("001_training_pipeline_v2.sql")
    _apply("003_training_control_v1.sql")
    asyncio.run(cs.collect_sample(_repo(), make_sample(3)))
    with pytest.raises(psycopg.Error):
        _apply("002_rollback_training_pipeline_v2.sql")
    assert set(V2_TABLES) <= _tables() and _fingerprint() == legacy


def test_store_empty_export_revoke_withdraw_delete_on_legacy_db(legacy, tmp_path, monkeypatch):
    from app.training_pipeline import candidate_service as cs
    from app.training_pipeline import export_service as ex
    from app.training_pipeline.records import ModelCandidateRecord
    from tests.lq_helpers import make_sample
    _apply("001_training_pipeline_v2.sql")
    _apply("003_training_control_v1.sql")
    monkeypatch.setenv("AI_TRAINING_DATASET_DIR", str(tmp_path / "ds"))
    repo = _repo()
    rv = cs.Actor("rev-1", "training_reviewer", "req-pgl-0001")
    svc = cs.Actor("svc", "service", "req-pgl-0002")

    async def go():
        # 1) 승인 전에는 export 가 비어 있다(파일/manifest 없음)
        empty = await ex.export_dataset(repo, actor="admin", request_id="req-pgl-empty")
        assert empty.status == "empty" and not list((tmp_path / "ds").glob("train_v*"))
        ids = []
        for i in range(6):
            r = await cs.collect_sample(repo, make_sample(i, user=f"pk_pgluser_{i % 3:09d}"))
            assert r.status == "STORED", r
            assert (await repo.get(r.candidate_id)).state.value == "NEEDS_REVIEW"   # 수집만으로는 학습 대상 아님
            await cs.review(repo, r.candidate_id, decision="VERIFY", actor=rv)
            ids.append(r.candidate_id)
        assert (await repo.counts_by_state())["TRAIN_ELIGIBLE"] == 6
        exp = await ex.export_dataset(repo, actor="admin", request_id="req-pgl-exp1")
        assert exp.status == "completed" and exp.total == 6
        assert (await repo.get_manifest(exp.dataset_id)).status == "ACTIVE"
        await repo.register_model_candidate(ModelCandidateRecord(
            adapter_id="adp-pgl-1", dataset_id=exp.dataset_id, base_model="Qwen/Qwen3-14B", status="REGISTERED",
            candidate_tag="studybridge-qlora-cand-001", notes=[]))
        # 2) 부정 피드백 → 후보 REVOKED + manifest INVALIDATED + 그 manifest 로 학습한 어댑터 RETIREMENT_REQUIRED
        fb = await cs.record_feedback(repo, ids[0], -1, actor=svc, reason_code="WRONG")
        assert fb.status == "REVOKED" and exp.dataset_id in fb.invalidated_datasets
        assert (await repo.get_manifest(exp.dataset_id)).status == "INVALIDATED"
        assert [m.status for m in await repo.models_for_dataset(exp.dataset_id)] == ["RETIREMENT_REQUIRED"]
        # 3) 동의 철회(같은 사용자 키의 나머지 후보 전부) / 4) 자료 삭제(내용 파기, 해시만 보존)
        wd = await cs.withdraw_consent(repo, "pk_pgluser_000000001", actor=svc)
        assert wd.status == "CONSENT_WITHDRAWN"
        for cid in (ids[1], ids[4]):
            assert (await repo.get(cid)).state.value == "REVOKED"
        victim = await repo.get(ids[2])
        de = await cs.delete_by_tracking_id(repo, victim.deletion_tracking_id, actor=svc)
        gone = await repo.get(ids[2])
        assert de.status == "DELETED" and gone.state.value == "DELETED" and gone.question == "" \
            and gone.candidate_answer == "" and gone.content_hash == victim.content_hash
        # 철회/삭제 후 재-export 에는 남은 후보만 들어간다
        exp2 = await ex.export_dataset(repo, actor="admin", request_id="req-pgl-exp2")
        assert exp2.status == "completed" and exp2.total == 2
        counts = await repo.counts_by_state()
        assert counts.get("REVOKED") == 3 and counts.get("DELETED") == 1 and counts.get("TRAIN_ELIGIBLE") == 2
    asyncio.run(go())
    assert _fingerprint() == legacy                      # 전 과정 동안 레거시 테이블 무변경


def test_training_repository_never_falls_back_to_production_dsn(monkeypatch):
    from app.training_pipeline import repository as R
    monkeypatch.setattr(R, "_repo", None)
    monkeypatch.setenv("AI_TRAINING_REPOSITORY", "postgres")
    monkeypatch.setenv("AI_DATABASE_URL", "postgresql://prod:x@rds.example/ai")
    monkeypatch.delenv("AI_TRAINING_DATABASE_URL", raising=False)
    monkeypatch.delenv("AI_TRAINING_ENV", raising=False)
    with pytest.raises(R.RepositoryUnavailable):
        R.get_repository()                                # 예전: 운영 AI_DATABASE_URL 로 조용히 대체
    monkeypatch.setenv("AI_TRAINING_DATABASE_URL", "postgresql://prod:x@rds.example/ai")
    with pytest.raises(R.RepositoryUnavailable):
        R.get_repository()                                # 환경 미지정
    monkeypatch.setenv("AI_TRAINING_ENV", "stage")
    with pytest.raises(R.RepositoryUnavailable):
        R.get_repository()                                # stage 가 운영 DB 를 가리킴
    monkeypatch.setenv("AI_TRAINING_DATABASE_URL", DSN)
    assert isinstance(R.get_repository(), R.PostgresTrainingRepository)
