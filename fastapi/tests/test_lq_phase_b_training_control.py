"""Phase B3 — 동의·삭제·피드백 보안: 본문 서명·동의 토큰·scope/typ·재전송·tombstone·멀티 워커 멱등.

- InMemory 저장소: 라우트 계약(서명/토큰/바인딩/재전송/철회 효과)
- Postgres(일회용 로컬 DB, AI_TEST_PG_DSN): 동시 워커(별도 프로세스 포함)에서 같은 eventId 1회 처리, 철회·수집 경합
"""
import asyncio
import json
import multiprocessing as mp
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts import signing as S
from tests.lq_helpers import INTERNAL_KEY, PK, make_sample

SAMPLE_KEY = "s" * 40
CONSENT_KEY = "c" * 40
SCOPE_KEY = "o" * 40
OTHER_PK = "pk_someone_else_0001"
H = {"Authorization": f"Bearer {INTERNAL_KEY}"}
CT = datetime(2026, 11, 1, tzinfo=timezone.utc)                # make_sample 의 동의 시각


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("AI_SERVER_API_KEY", INTERNAL_KEY)
    monkeypatch.setenv("AI_TRAINING_SAMPLE_SIGNING_KEY", SAMPLE_KEY)
    monkeypatch.setenv("AI_TRAINING_CONSENT_SIGNING_KEY", CONSENT_KEY)
    monkeypatch.setenv("AI_SCOPE_SIGNING_KEY", SCOPE_KEY)
    monkeypatch.setenv("AI_TRAINING_COLLECTION_ENABLED", "true")
    monkeypatch.setenv("AI_TRAINING_DATASET_DIR", "/tmp/lq-phaseb-ds-unused")


def run(c):
    return asyncio.run(c)


def _client():
    from app.api.training_candidate_routes import ADMIN_RATE, REVOCATION_RATE, SERVICE_RATE, router
    for b in (ADMIN_RATE, REVOCATION_RATE, SERVICE_RATE):
        b.reset()
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def _mem():
    from app.training_pipeline.repository import InMemoryTrainingRepository, set_repository
    r = InMemoryTrainingRepository()
    set_repository(r)
    return r


def _signed(body: bytes, *, ts=None, key=SAMPLE_KEY, rid=None):
    ts = int(time.time()) if ts is None else ts
    h = {**H, "Content-Type": "application/json", "X-AI-Contract-Timestamp": str(ts),
         "X-AI-Contract-Signature": S.sign_body_with_key(key.encode(), body, ts)}
    if rid:
        h["X-Request-Id"] = rid
    return h


def _sample_body(i=0, **kw):
    s = make_sample(i, **kw)
    return s, s.model_dump_json().encode()


def _consent(s, *, rid=None, sub=None, cv=None, ct=None, dtid=None, scope=("MODEL_TRAINING",), typ_scope=False):
    if typ_scope:
        return S.issue_scope_token(sub or s.pseudonymousUserKey, [], [], request_id=rid or s.eventId)
    return S.issue_consent_token(sub or s.pseudonymousUserKey, consent_version=cv or s.consentVersion,
                                 consent_timestamp=ct or s.consentTimestamp.isoformat().replace("+00:00", "Z"),
                                 scope=list(scope), rights={}, deletion_tracking_id=dtid or s.deletionTrackingId,
                                 request_id=rid or s.eventId)


def _collect(c, s, body, **tok):
    h = _signed(body, rid=tok.pop("rid_header", s.eventId))
    token = tok.pop("token", None)
    h["X-AI-Training-Consent"] = token if token is not None else _consent(s, **tok)
    return c.post("/api/training-candidates/collect-v1", content=body, headers=h)


def _control(c, route, msg: dict, *, rid=None, ts=None, key=SAMPLE_KEY, raw=None):
    body = raw if raw is not None else json.dumps(msg).encode()
    return c.post(f"/api/training-candidates/{route}", content=body,
                  headers=_signed(body, ts=ts, key=key, rid=rid or msg.get("eventId")))


def _withdrawal(eid="rv-unit-000001", pk=PK, at=None, **kw):
    return {"schemaVersion": "training-control.v1", "typ": "training-control", "messageType": "CONSENT_WITHDRAWAL",
            "eventId": eid, "issuedAt": (at or datetime.now(timezone.utc)).isoformat(), "pseudonymousUserKey": pk,
            "scope": ["MODEL_TRAINING"], **kw}


def _deletion(eid="dl-unit-000001", dtid="del-pk_7f3a9c2-0000", **kw):
    return {"schemaVersion": "training-control.v1", "typ": "training-control", "messageType": "DELETION",
            "eventId": eid, "issuedAt": datetime.now(timezone.utc).isoformat(), "deletionTrackingId": dtid, **kw}


def _feedback(eid, cand_event, pk=PK, score=-1):
    return {"schemaVersion": "training-control.v1", "typ": "training-control", "messageType": "FEEDBACK",
            "eventId": eid, "issuedAt": datetime.now(timezone.utc).isoformat(), "pseudonymousUserKey": pk,
            "candidateEventId": cand_event, "score": score}


# ── collect-v1: 본문 서명 + 동의 토큰 ─────────────────────────────────────────────────
def test_collect_v1_requires_consent_token_bound_to_event_subject_and_purpose():
    repo = _mem()
    c = _client()
    s, body = _sample_body(0)
    assert _collect(c, s, body, token="").json()["errorCode"] == "CONSENT_TOKEN_MISSING"
    assert _collect(c, s, body, rid="evt-other-000001").json()["errorCode"] == "CONSENT_REQUEST_MISMATCH"
    assert _collect(c, s, body, sub=OTHER_PK).json()["errorCode"] == "CONSENT_SUBJECT_MISMATCH"
    assert _collect(c, s, body, token=_consent(s, typ_scope=True)).json()["errorCode"] in (
        "CONSENT_TOKEN_INVALID", "CONSENT_TOKEN_TYPE_INVALID")        # scope 키로 서명 → 서명 불일치가 먼저
    r = _collect(c, s, body, cv="tc-2099-01")
    assert r.status_code == 422 and r.json()["errorCode"] == "CONSENT_VERSION_MISMATCH"
    assert _collect(c, s, body, dtid="del-xxxxxxxx-9999").json()["errorCode"] == "CONSENT_DELETION_ID_MISMATCH"
    assert _collect(c, s, body, ct="2026-10-01T00:00:00Z").json()["errorCode"] == "CONSENT_TIMESTAMP_MISMATCH"
    assert _collect(c, s, body, scope=("ANALYTICS",)).json()["errorCode"] == "CONSENT_SCOPE_MISSING"
    r = _collect(c, s, body, rid_header="evt-other-000001")
    assert r.status_code == 400 and r.json()["errorCode"] == "REQUEST_ID_EVENT_MISMATCH"
    assert run(repo.counts_by_state())["NEEDS_REVIEW"] == 0          # 위 어떤 거절도 저장하지 않았다
    ok = _collect(c, s, body)
    assert ok.status_code == 200 and ok.json()["status"] == "STORED", ok.json()


def test_collect_v1_consent_token_of_wrong_type_signed_with_consent_key_is_type_invalid(monkeypatch):
    _mem()
    c = _client()
    s, body = _sample_body(1)
    monkeypatch.setenv("AI_SCOPE_SIGNING_KEY", CONSENT_KEY + "x")          # 키 재사용 검사 회피용 다른 값
    p = {"v": 1, "typ": "ai-scope", "sub": s.pseudonymousUserKey, "rid": s.eventId, "iat": int(time.time()),
         "exp": int(time.time()) + 60}
    tok = S._token(CONSENT_KEY.encode(), p)                              # consent 키로 서명했지만 용도는 scope
    assert _collect(c, s, body, token=tok).json()["errorCode"] == "CONSENT_TOKEN_TYPE_INVALID"   # C-SIG-1


def test_collect_v1_rejects_tampered_body_and_future_consent(monkeypatch):
    _mem()
    c = _client()
    s, body = _sample_body(2)
    h = _signed(body, rid=s.eventId)
    h["X-AI-Training-Consent"] = _consent(s)
    tampered = body.replace(b'"qwen3:14b"', b'"qwen3:15b"')
    assert c.post("/api/training-candidates/collect-v1", content=tampered, headers=h).json()["errorCode"] == "SIGNATURE_INVALID"
    future = datetime.now(timezone.utc) + timedelta(hours=9)             # C-TIME-3: KST 벽시계를 UTC 로 표기한 경우
    s2 = make_sample(3)
    d = json.loads(s2.model_dump_json())
    d["consentTimestamp"] = future.isoformat()
    b2 = json.dumps(d).encode()
    from app.contracts.training_sample_v1 import parse_sample_json
    s2 = parse_sample_json(b2)
    r = _collect(c, s2, b2, ct=future.isoformat())
    assert r.status_code == 422 and r.json()["errorCode"] == "CONSENT_TIMESTAMP_IN_FUTURE"


def test_collect_v1_replay_is_idempotent_and_conflicting_body_is_409():
    repo = _mem()
    c = _client()
    s, body = _sample_body(4)
    assert _collect(c, s, body).json()["status"] == "STORED"
    again = _collect(c, s, body)
    assert again.status_code == 200 and again.headers.get("Idempotent-Replay") == "true"
    other = json.loads(body)
    other["retentionPolicy"] = "TRAINING_CANDIDATE_30D"                  # 같은 eventId, 다른 본문
    ob = json.dumps(other).encode()
    from app.contracts.training_sample_v1 import parse_sample_json
    r = _collect(c, parse_sample_json(ob), ob)
    assert r.status_code == 409 and r.json()["status"] == "EVENT_ID_CONFLICT"
    assert run(repo.counts_by_state())["NEEDS_REVIEW"] == 1


# ── 철회/삭제/피드백: Bearer 만으로는 거부, 서명된 training-control.v1 만 ───────────────
def test_control_routes_reject_bearer_only_and_contract_violations():
    _mem()
    c = _client()
    legacy = c.post("/api/training-candidates/consent-withdrawal", json={"pseudonymousUserKey": PK}, headers=H)
    assert legacy.status_code == 401 and legacy.json()["errorCode"] == "SIGNATURE_MISSING"
    assert c.post("/api/training-candidates/deletion", json={"deletionTrackingId": "del-x-00000001"},
                  headers=H).status_code == 401
    assert c.post("/api/training-candidates/feedback", json={"contentHash": "0" * 64, "score": -1},
                  headers=H).status_code == 401
    cases = [
        ("consent-withdrawal", _withdrawal(typ="ai-scope"), 422, "CONTROL_CONTRACT_INVALID"),
        ("consent-withdrawal", _withdrawal(scope=["MODEL_TRAINING", "ANALYTICS"]), 422, "CONTROL_CONTRACT_INVALID"),
        ("consent-withdrawal", _withdrawal(scope=[]), 422, "CONTROL_CONTRACT_INVALID"),
        ("consent-withdrawal", _withdrawal(pk="12345678901234567"), 422, "CONTROL_CONTRACT_INVALID"),
        ("consent-withdrawal", _withdrawal(at=datetime.now(timezone.utc) + timedelta(hours=1)), 422,
         "CONTROL_ISSUED_IN_FUTURE"),
        ("consent-withdrawal", {**_withdrawal(), "issuedAt": "2026-11-04T10:00:00"}, 422, "CONTROL_CONTRACT_INVALID"),
        ("deletion", _withdrawal(eid="rv-unit-000009"), 422, "CONTROL_MESSAGE_TYPE_MISMATCH"),   # 용도 간 재사용
        ("consent-withdrawal", {**_withdrawal(), "extra": 1}, 422, "CONTROL_CONTRACT_INVALID"),
    ]
    for route, msg, status, code in cases:
        r = _control(c, route, msg)
        assert (r.status_code, r.json()["errorCode"]) == (status, code), (route, msg)
    r = _control(c, "consent-withdrawal", _withdrawal(), rid="rv-other-000001")
    assert r.status_code == 400 and r.json()["errorCode"] == "REQUEST_ID_EVENT_MISMATCH"
    r = _control(c, "consent-withdrawal", _withdrawal(), ts=int(time.time()) - 301)
    assert r.status_code == 401 and r.json()["errorCode"] == "SIGNATURE_EXPIRED"
    r = _control(c, "consent-withdrawal", _withdrawal(), key=CONSENT_KEY)           # 다른 키 서명
    assert r.status_code == 401 and r.json()["errorCode"] == "SIGNATURE_INVALID"


def test_withdrawal_revokes_prior_consent_blocks_late_samples_and_keeps_reconsent():
    repo = _mem()
    c = _client()
    s0, b0 = _sample_body(10)
    assert _collect(c, s0, b0).json()["status"] == "STORED"
    w = _control(c, "consent-withdrawal", _withdrawal(at=CT + timedelta(days=2)))
    j = w.json()
    assert w.status_code == 200 and j["status"] == "CONSENT_WITHDRAWN"
    assert j["modelWeightsErased"] is False and j["trainedModelEffect"] == "NO_TRAINED_ADAPTER_AFFECTED"
    assert run(repo.find_by_event_id(s0.eventId)).state.value == "REVOKED"
    # 철회 이전 동의로 만든 샘플이 늦게 도착(재전송/경합) → 저장 거부
    s1, b1 = _sample_body(11)
    r = _collect(c, s1, b1)
    assert r.status_code == 200 and r.json()["status"] == "REJECTED_CONSENT_WITHDRAWN"
    assert run(repo.find_by_event_id(s1.eventId)) is None
    # 재동의(철회 이후 동의 시각) 샘플은 허용, 같은 철회 재전송은 재동의 후보를 철회하지 않는다
    d = json.loads(make_sample(12).model_dump_json())
    d["consentTimestamp"] = d["trainingEligibility"]["decidedAt"] = (CT + timedelta(days=3)).isoformat()
    b2 = json.dumps(d).encode()
    from app.contracts.training_sample_v1 import parse_sample_json
    s2 = parse_sample_json(b2)
    assert _collect(c, s2, b2, ct=s2.consentTimestamp.isoformat()).json()["status"] == "STORED"
    replay = _control(c, "consent-withdrawal", _withdrawal(at=CT + timedelta(days=2)))
    assert replay.status_code == 200 and replay.headers.get("Idempotent-Replay") == "true"
    older = _control(c, "consent-withdrawal", _withdrawal(eid="rv-unit-000002", at=CT + timedelta(days=1)))
    assert older.status_code == 200
    assert run(repo.find_by_event_id(s2.eventId)).state.value == "NEEDS_REVIEW"


def test_withdrawal_invalidates_manifest_and_marks_adapter_without_claiming_erasure(tmp_path, monkeypatch):
    from app.training_pipeline.records import ManifestRecord, ModelCandidateRecord
    repo = _mem()
    c = _client()
    s, b = _sample_body(20)
    _collect(c, s, b)
    rec = run(repo.find_by_event_id(s.eventId))
    run(repo.save_manifest(ManifestRecord(dataset_id="train_v20261104_001_deadbeef", status="ACTIVE",
                                          manifest_sha256="0" * 64, member_hashes=[rec.content_hash], created_at=CT)))
    run(repo.register_model_candidate(ModelCandidateRecord(adapter_id="adp-1", dataset_id="train_v20261104_001_deadbeef",
                                                           base_model="qwen3:14b", status="REGISTERED")))
    monkeypatch.setattr("app.training_pipeline.export_service.purge_dataset_files", lambda d: False)
    j = _control(c, "consent-withdrawal", _withdrawal(eid="rv-unit-000020", at=CT + timedelta(days=2))).json()
    assert j["invalidated_datasets"] == ["train_v20261104_001_deadbeef"] and j["retirement_required_adapters"] == ["adp-1"]
    assert j["trainedModelEffect"] == "RETIREMENT_REQUIRED_WEIGHTS_NOT_ERASED" and j["modelWeightsErased"] is False
    assert run(repo.get_manifest("train_v20261104_001_deadbeef")).status == "INVALIDATED"
    assert run(repo.models_for_dataset("train_v20261104_001_deadbeef"))[0].status == "RETIREMENT_REQUIRED"


def test_deletion_destroys_content_and_tombstone_blocks_future_samples():
    repo = _mem()
    c = _client()
    s, b = _sample_body(30)
    _collect(c, s, b)
    j = _control(c, "deletion", _deletion(dtid=s.deletionTrackingId)).json()
    assert j["status"] == "DELETED"
    rec = run(repo.find_by_event_id(s.eventId))
    assert rec.state.value == "DELETED" and rec.question == "" and rec.candidate_answer == ""
    d = json.loads(make_sample(31).model_dump_json())
    d["deletionTrackingId"] = s.deletionTrackingId
    b2 = json.dumps(d).encode()
    from app.contracts.training_sample_v1 import parse_sample_json
    s2 = parse_sample_json(b2)
    assert _collect(c, s2, b2).json()["status"] == "REJECTED_SOURCE_DELETED"


def test_feedback_is_bound_to_candidate_owner():
    repo = _mem()
    c = _client()
    s, b = _sample_body(40)
    _collect(c, s, b)
    r = _control(c, "feedback", _feedback("fb-unit-000001", s.eventId, pk=OTHER_PK))
    assert r.json()["status"] == "NOT_FOUND"
    assert run(repo.find_by_event_id(s.eventId)).state.value == "NEEDS_REVIEW"     # 타인 피드백은 무효
    msg = _feedback("fb-unit-000002", s.eventId)
    r = _control(c, "feedback", msg)
    assert r.json()["status"] == "REVOKED"
    again = _control(c, "feedback", msg)                                   # 같은 본문 재전송(서명 시각만 새로)
    assert again.status_code == 200 and again.headers.get("Idempotent-Replay") == "true"
    changed = _control(c, "feedback", {**msg, "score": 1})                 # 같은 eventId, 다른 본문
    assert changed.status_code == 409
    assert run(repo.find_by_event_id(s.eventId)).feedback_history == [-1]          # 재전송으로 두 번 적용되지 않음


# ── Postgres: 동시 워커 ─────────────────────────────────────────────────────────────
DSN = os.getenv("AI_TEST_PG_DSN", "")
_u = urlparse(DSN) if DSN else None
pg = pytest.mark.skipif(not DSN or _u.hostname not in ("127.0.0.1", "localhost") or _u.path != "/lq",
                        reason="ephemeral local test DB only")
MIG = Path(__file__).resolve().parents[1] / "app" / "training_pipeline" / "migrations"


def _sql(stmt):
    import psycopg
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(stmt)


@pytest.fixture
def pgrepo():
    _sql("DROP SCHEMA IF EXISTS ai CASCADE; CREATE SCHEMA ai;")
    for m in ("001_training_pipeline_v2.sql", "003_training_control_v1.sql", "003_training_control_v1.sql"):
        _sql((MIG / m).read_text(encoding="utf-8"))                     # 003 멱등 재적용
    from app.training_pipeline.repository import PostgresTrainingRepository, set_repository
    r = PostgresTrainingRepository(DSN)
    set_repository(r)
    return r


@pg
def test_pg_same_event_from_many_concurrent_workers_is_processed_once(pgrepo):
    from app.training_pipeline import candidate_service as cs
    from app.training_pipeline.repository import PostgresTrainingRepository
    s = make_sample(50, feedback=-1)
    body = s.model_dump_json().encode()
    calls = {"n": 0}

    async def one():
        repo = PostgresTrainingRepository(DSN)                          # 워커마다 별도 저장소/연결

        async def work():
            calls["n"] += 1
            return await cs.collect_sample(repo, s)
        return await cs.run_once(repo, event_id=s.eventId, message_type="SAMPLE", body_sha256="a" * 64, work=work)

    async def go():
        return await asyncio.gather(*(one() for _ in range(12)))
    outs = run(go())
    disps = [d for d, _ in outs]
    assert calls["n"] == 1 and disps.count("PROCESSED") == 1
    assert set(disps) <= {"PROCESSED", "IN_PROGRESS", "REPLAY"}
    assert run(pgrepo.counts_by_state())["NEEDS_REVIEW"] + run(pgrepo.counts_by_state())["REVOKED"] == 1


def _proc_worker(dsn, event_id, q):
    os.environ["AI_TEST_PG_DSN"] = dsn
    from app.training_pipeline import candidate_service as cs
    from app.training_pipeline.repository import PostgresTrainingRepository

    async def main():
        repo = PostgresTrainingRepository(dsn)

        async def work():
            return await cs.withdraw_consent(repo, PK, actor=cs.SYSTEM_ACTOR,
                                             withdrawn_at=datetime(2026, 11, 3, tzinfo=timezone.utc), event_id=event_id)
        d, _ = await cs.run_once(repo, event_id=event_id, message_type="CONSENT_WITHDRAWAL", body_sha256="b" * 64,
                                 work=work)
        return d
    q.put(asyncio.run(main()))


@pg
def test_pg_withdrawal_delivered_to_separate_processes_is_applied_once(pgrepo):
    from app.training_pipeline import candidate_service as cs
    for i in range(3):
        run(cs.collect_sample(pgrepo, make_sample(60 + i)))
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    procs = [ctx.Process(target=_proc_worker, args=(DSN, "rv-proc-000001", q)) for _ in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
    results = [q.get(timeout=5) for _ in procs]
    assert results.count("PROCESSED") == 1 and set(results) <= {"PROCESSED", "IN_PROGRESS", "REPLAY"}, results
    counts = run(pgrepo.counts_by_state())
    assert counts["REVOKED"] == 3 and counts["NEEDS_REVIEW"] == 0


@pg
def test_pg_withdrawal_racing_collection_never_leaves_prior_consent_candidate(pgrepo):
    """수집과 철회를 동시에 여러 번 돌려도 '철회 이전 동의' 후보가 살아남지 않는다(저장 후 tombstone 재확인)."""
    from app.training_pipeline import candidate_service as cs
    from app.training_pipeline.repository import PostgresTrainingRepository

    async def go(k):
        user = f"pk_race_user_{k:06d}"
        a, b = PostgresTrainingRepository(DSN), PostgresTrainingRepository(DSN)
        await asyncio.gather(
            cs.collect_sample(a, make_sample(100 + k, user=user)),
            cs.withdraw_consent(b, user, actor=cs.SYSTEM_ACTOR, withdrawn_at=CT + timedelta(days=1),
                                event_id=f"rv-race-{k:06d}"))
        return [r.state.value for r in await a.list_by(pseudonymous_user_key=user)]

    async def all_():
        return [await go(k) for k in range(20)]
    for states in run(all_()):
        assert all(st == "REVOKED" for st in states), states


@pg
def test_pg_rollback_refuses_when_tombstones_exist(pgrepo):
    from app.training_pipeline import candidate_service as cs
    run(cs.delete_by_tracking_id(pgrepo, "del-rollback-0001", actor=cs.SYSTEM_ACTOR, event_id="dl-rb-000001"))
    import psycopg
    with pytest.raises(psycopg.Error):
        _sql((MIG / "004_rollback_training_control_v1.sql").read_text(encoding="utf-8"))
    assert run(pgrepo.get_deletion_tombstone("del-rollback-0001")) is not None
