"""데이터셋 export 보안(경로/덮어쓰기/권한/원자성/manifest/동시성/크기) + 그룹 분할 누출 방지."""
import asyncio
import hashlib
import json
import os
import stat

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.training_pipeline import candidate_service as cs
from app.training_pipeline import export_service as ex
from app.training_pipeline.dataset_builder import (TRAINING_SYSTEM_PROMPT_V1, LeakageError, build_dataset,
                                                   verify_no_leakage)
from app.training_pipeline.repository import InMemoryTrainingRepository, set_repository
from tests.lq_helpers import ADMIN_TOKEN, INTERNAL_KEY, admin_headers, make_sample

REVIEWER = cs.Actor("reviewer-01", "training_reviewer", "req-review-0001")


def run(c):
    return asyncio.run(c)


async def _eligible_repo(n=12, users=6):
    repo = InMemoryTrainingRepository()
    for i in range(n):
        s = make_sample(i, user=f"pk_user_{i % users:012d}")
        r = await cs.collect_sample(repo, s)
        await cs.review(repo, r.candidate_id, decision="VERIFY", actor=REVIEWER)
    return repo


@pytest.fixture
def droot(tmp_path, monkeypatch):
    d = tmp_path / "datasets"
    monkeypatch.setenv("AI_TRAINING_DATASET_DIR", str(d))
    monkeypatch.setenv("AI_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("AI_CODE_REVISION", "test-rev-abc")
    return d


def test_export_completed_with_manifest_and_permissions(droot):
    repo = run(_eligible_repo())
    res = run(ex.export_dataset(repo, actor="admin-1", request_id="req-exp-0001"))
    assert res.status == "completed" and ex.DATASET_ID_RE.match(res.dataset_id)
    d = droot / res.dataset_id
    assert stat.S_IMODE(os.stat(droot).st_mode) == 0o700 and stat.S_IMODE(os.stat(d).st_mode) == 0o700
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    for name, sha in manifest["files"].items():
        assert hashlib.sha256((d / name).read_bytes()).hexdigest() == sha
        assert stat.S_IMODE(os.stat(d / name).st_mode) == 0o400
    assert hashlib.sha256((d / "manifest.json").read_bytes()).hexdigest() == res.manifest_sha256
    assert manifest["codeRevision"] == "test-rev-abc" and manifest["status"] == "ACTIVE"
    assert sum(v["count"] for v in manifest["splits"].values()) == res.total == 12
    assert manifest["baseModelReference"]["id"] == "Qwen/Qwen3-14B"
    assert not [p for p in d.iterdir() if p.name.startswith(".")]   # 임시파일 잔여 없음
    line = json.loads((d / "train.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert line["messages"][0] == {"role": "system", "content": TRAINING_SYSTEM_PROMPT_V1}
    assert run(repo.get_manifest(res.dataset_id)).status == "ACTIVE"


def test_same_day_exports_get_unique_ids(droot):
    repo = run(_eligible_repo(4, 4))
    a = run(ex.export_dataset(repo, actor="a", request_id="req-exp-0002"))
    b = run(ex.export_dataset(repo, actor="a", request_id="req-exp-0003"))
    assert a.dataset_id != b.dataset_id and a.dataset_id[:16] == b.dataset_id[:16]
    assert b.dataset_id.split("_")[2] == "002"


def test_empty_is_distinct_from_completed_and_writes_nothing(droot):
    res = run(ex.export_dataset(InMemoryTrainingRepository(), actor="a", request_id="req-exp-0004"))
    assert res.status == "empty" and res.dataset_id is None
    assert [p.name for p in droot.iterdir() if not p.name.startswith(".")] == []


def test_no_clobber_write_refuses_existing(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    ex._write_no_clobber(d, "a.jsonl", b"1")
    with pytest.raises(FileExistsError):
        ex._write_no_clobber(d, "a.jsonl", b"2")
    with pytest.raises(ValueError):
        ex._write_no_clobber(d, "../evil", b"x")


def test_symlink_root_refused(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.setenv("AI_TRAINING_DATASET_DIR", str(link))
    with pytest.raises(ValueError):
        ex.datasets_root()
    monkeypatch.setenv("AI_TRAINING_DATASET_DIR", "relative/dir")
    with pytest.raises(ValueError):
        ex.datasets_root()


def test_size_limit_rolls_back(droot, monkeypatch):
    repo = run(_eligible_repo(6, 6))
    monkeypatch.setenv("AI_TRAINING_EXPORT_MAX_BYTES", "200")
    res = run(ex.export_dataset(repo, actor="a", request_id="req-exp-0005"))
    assert res.status == "failed" and res.error_code == "EXPORT_TOO_LARGE"
    assert [p for p in droot.iterdir() if p.name.startswith("train_v")] == []


def test_manifest_registration_failure_rolls_back(droot):
    repo = run(_eligible_repo(4, 4))

    async def boom(m):
        raise RuntimeError("db")
    repo.save_manifest = boom
    res = run(ex.export_dataset(repo, actor="a", request_id="req-exp-0006"))
    assert res.status == "failed"
    assert [p for p in droot.iterdir() if p.name.startswith("train_v")] == []


def test_concurrent_export_is_busy(droot):
    repo = run(_eligible_repo(4, 4))
    orig = repo.list_by

    async def slow_list_by(**kw):      # 실제 DB 처럼 I/O 대기 중 다른 요청이 끼어들게 한다
        await asyncio.sleep(0.05)
        return await orig(**kw)
    repo.list_by = slow_list_by

    async def both():
        return await asyncio.gather(ex.export_dataset(repo, actor="a", request_id="req-exp-0007"),
                                    ex.export_dataset(repo, actor="b", request_id="req-exp-0008"))
    r = run(both())
    assert sorted(x.status for x in r) == ["busy", "completed"]


def test_revoked_member_is_excluded_from_next_export(droot):
    repo = run(_eligible_repo(4, 4))
    first = run(ex.export_dataset(repo, actor="a", request_id="req-exp-0009"))
    victim = run(repo.list_by())[0]
    res = run(cs.record_feedback(repo, victim.candidate_id, -1, actor=cs.Actor("service:spring", "service")))
    assert first.dataset_id in res.invalidated_datasets
    assert run(repo.get_manifest(first.dataset_id)).status == "INVALIDATED"
    second = run(ex.export_dataset(repo, actor="a", request_id="req-exp-0010"))
    m2 = json.loads((droot / second.dataset_id / "manifest.json").read_text(encoding="utf-8"))
    assert victim.content_hash not in m2["memberContentHashes"] and second.total == 3


def test_route_rejects_output_path_and_hides_absolute_path(droot, monkeypatch):
    monkeypatch.setenv("AI_SERVER_API_KEY", INTERNAL_KEY)
    monkeypatch.setenv("TRAINING_ADMIN_TOKEN", ADMIN_TOKEN)
    set_repository(run(_eligible_repo(4, 4)))
    from app.api import training_candidate_routes as r
    r.ADMIN_RATE.reset()
    app = FastAPI()
    app.include_router(r.router)
    c = TestClient(app)
    for bad in ("/tmp/x.jsonl", "../../etc/cron.d/x", "/home/ai07/capstoneLLM/fastapi/main.py"):
        assert c.post("/api/training-candidates/export-jsonl", json={"output_path": bad}, headers=admin_headers()).status_code == 400
    ok = c.post("/api/training-candidates/export-jsonl", json={"output_path": "exported_training_data.jsonl"},
                headers=admin_headers())
    assert ok.status_code == 200 and ok.json()["status"] == "completed"
    assert not ok.json()["output_file_path"].startswith("/")
    set_repository(None)


# ── 그룹 분할 누출 방지 ──────────────────────────────────────────────────────────
def test_group_split_keeps_user_document_and_near_dups_together():
    async def build():
        repo = InMemoryTrainingRepository()
        recs = []
        for i in range(40):
            s = make_sample(i, user=f"pk_user_{i % 10:012d}")
            r = await cs.collect_sample(repo, s)
            await cs.review(repo, r.candidate_id, decision="VERIFY", actor=REVIEWER)
            recs.append(await repo.get(r.candidate_id))
        return recs
    recs = run(build())
    b = build_dataset(recs)
    verify_no_leakage(b.splits)
    owner = {}
    for split, items in b.splits.items():
        for s in items:
            assert owner.setdefault(s.user_key, split) == split


def test_leakage_detector_catches_shared_user():
    async def build():
        repo = InMemoryTrainingRepository()
        out = []
        for i in range(2):
            r = await cs.collect_sample(repo, make_sample(i))
            await cs.review(repo, r.candidate_id, decision="VERIFY", actor=REVIEWER)
            out.append(await repo.get(r.candidate_id))
        return out
    a, c = run(build())
    from app.training_pipeline.dataset_builder import DatasetSample, to_messages
    mk = lambda r: DatasetSample(r.candidate_id, r.content_hash, r.pseudonymous_user_key, set(), r.simhash, to_messages(r), r)
    with pytest.raises(LeakageError):
        verify_no_leakage({"train": [mk(a)], "validation": [], "test": [mk(c)]})


def test_frozen_test_set_stays_in_test():
    async def build():
        repo = InMemoryTrainingRepository()
        out = []
        for i in range(10):
            r = await cs.collect_sample(repo, make_sample(i, user=f"pk_user_{i:012d}"))
            await cs.review(repo, r.candidate_id, decision="VERIFY", actor=REVIEWER)
            out.append(await repo.get(r.candidate_id))
        return out
    recs = run(build())
    frozen = {recs[0].content_hash, recs[1].content_hash}
    b = build_dataset(recs, frozen_test_hashes=frozen)
    assert frozen <= {s.content_hash for s in b.splits["test"]}


def test_training_target_is_verified_answer_not_runtime_prompt():
    async def build():
        repo = InMemoryTrainingRepository()
        r = await cs.collect_sample(repo, make_sample(1, feedback=-1))
        await cs.submit_correction(repo, r.candidate_id, "검증된 정답: O(log n).", actor=cs.Actor("s", "service"))
        await cs.review(repo, r.candidate_id, decision="VERIFY", actor=REVIEWER, use="correction")
        return await repo.get(r.candidate_id)
    rec = run(build())
    msgs = build_dataset([rec]).splits
    m = next(s for v in msgs.values() for s in v).messages
    assert m[-1] == {"role": "assistant", "content": "검증된 정답: O(log n)."}
    assert rec.candidate_answer not in json.dumps(m, ensure_ascii=False)
