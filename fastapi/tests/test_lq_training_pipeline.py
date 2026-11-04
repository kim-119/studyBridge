"""학습 후보 상태/자격/철회/수정/삭제 — '수집 ≠ 학습 자격' 을 증명한다."""
import asyncio

import pytest

from app.training_pipeline import candidate_service as cs
from app.training_pipeline.eligibility import evaluate_eligibility
from app.training_pipeline.records import ManifestRecord, ModelCandidateRecord, utcnow
from app.training_pipeline.repository import InMemoryTrainingRepository
from app.training_pipeline.states import CandidateState as S
from app.training_pipeline.states import InvalidTransition, check_transition, from_legacy
from tests.lq_helpers import make_sample

REVIEWER = cs.Actor("reviewer-01", "training_reviewer", "req-review-0001")
EVID = [{"sourceType": "PDF_ORIGINAL", "materialId": 42, "sourceRevisionHash": "rev-1", "page": 3, "chunkId": "m42-c1",
         "quote": "이진 탐색은 정렬된 배열에서 O(log n) 시간에 동작한다. 1946년에 처음 언급되었다."}]


def run(c):
    return asyncio.run(c)


@pytest.fixture
def repo():
    return InMemoryTrainingRepository()


def test_legacy_approvals_never_promote_to_train_eligible():
    for legacy in ("auto_approved", "manual_approved", "holdout"):
        assert from_legacy(legacy) == S.NEEDS_REVIEW
    assert from_legacy("unsafe") == S.QUARANTINED
    with pytest.raises(InvalidTransition):
        check_transition(S.COLLECTED, S.TRAIN_ELIGIBLE)
    with pytest.raises(InvalidTransition):
        check_transition(S.REVOKED, S.TRAIN_ELIGIBLE)


def test_collect_goes_to_needs_review_not_eligible(repo):
    res = run(cs.collect_sample(repo, make_sample(1, feedback=1)))   # '좋아요'
    assert res.status == "STORED" and res.state == "NEEDS_REVIEW"
    rec = run(repo.get(res.candidate_id))
    assert rec.verified_answer is None
    assert not evaluate_eligibility(rec).eligible


def test_high_display_score_and_like_are_not_training_approval(repo):
    res = run(cs.collect_sample(repo, make_sample(2, feedback=1),
                                display_quality={"score": 99.0, "qualityStatus": "APPROVED"}))
    rec = run(repo.get(res.candidate_id))
    e = evaluate_eligibility(rec)
    assert not e.eligible and "VERIFIED_ANSWER_MISSING" in e.reasons and "STATE_NOT_VERIFIED" in e.reasons


def test_review_promotes_only_when_all_gates_pass(repo):
    res = run(cs.collect_sample(repo, make_sample(3)))
    out = run(cs.review(repo, res.candidate_id, decision="VERIFY", actor=REVIEWER))
    assert out.status == "TRAIN_ELIGIBLE" and out.state == "TRAIN_ELIGIBLE"
    events = run(repo.events_for(res.candidate_id))
    assert [e.to_state for e in events] == ["COLLECTED", "NEEDS_REVIEW", "VERIFIED", "TRAIN_ELIGIBLE"]
    assert all(e.prev_hash for e in events) and len({e.event_hash for e in events}) == 4


@pytest.mark.parametrize("kw,reason", [
    ({"consent": False}, "CONSENT_NOT_GRANTED"),
    ({"scope": ("ANALYTICS",)}, "CONSENT_SCOPE_MISSING"),
    ({"rights": "THIRD_PARTY_UNVERIFIED"}, "RIGHTS_UNVERIFIED"),
    ({"kind": "PDF_QA"}, "EVIDENCE_PROVENANCE_MISSING"),
])
def test_eligibility_requires_every_condition(repo, kw, reason):
    res = run(cs.collect_sample(repo, make_sample(10 + len(reason), **kw)))
    out = run(cs.review(repo, res.candidate_id, decision="VERIFY", actor=REVIEWER))
    assert out.status == "VERIFIED_NOT_ELIGIBLE" and reason in out.reasons


def test_llm_judge_or_none_cannot_verify(repo):
    res = run(cs.collect_sample(repo, make_sample(20)))
    for m in ("LLM_JUDGE", "NONE"):
        out = run(cs.review(repo, res.candidate_id, decision="VERIFY", actor=REVIEWER, method=m))
        assert out.status == "NOT_ALLOWED" and "VERIFICATION_INSUFFICIENT" in out.reasons


def test_pdf_summary_must_match_source(repo):
    bad = "이진 탐색은 정렬된 배열에서 O(log n) 시간에 동작한다. 1972년에 처음 언급되었다."
    res = run(cs.collect_sample(repo, make_sample(21, kind="PDF_SUMMARY", rights="USER_OWNED_VERIFIED",
                                                  evidence=EVID, revision="rev-1", answer=bad)))
    out = run(cs.review(repo, res.candidate_id, decision="VERIFY", actor=REVIEWER))
    assert "NOT_SOURCE_FAITHFUL" in out.reasons
    good = "이진 탐색은 정렬된 배열에서 O(log n) 시간에 동작한다. 1946년에 처음 언급되었다."
    res2 = run(cs.collect_sample(repo, make_sample(22, kind="PDF_SUMMARY", rights="USER_OWNED_VERIFIED",
                                                   evidence=EVID, revision="rev-1", answer=good)))
    assert run(cs.review(repo, res2.candidate_id, decision="VERIFY", actor=REVIEWER)).status == "TRAIN_ELIGIBLE"


def test_duplicate_negative_feedback_revokes_existing_and_invalidates_lineage(repo):
    first = run(cs.collect_sample(repo, make_sample(30)))
    run(cs.review(repo, first.candidate_id, decision="VERIFY", actor=REVIEWER))
    rec = run(repo.get(first.candidate_id))
    run(repo.save_manifest(ManifestRecord("train_v20261104_001_deadbeef", "ACTIVE", "0" * 64, [rec.content_hash], utcnow())))
    run(repo.register_model_candidate(ModelCandidateRecord("adapter-x", "train_v20261104_001_deadbeef",
                                                           "Qwen/Qwen3-14B", "REGISTERED", "sb-cand-x")))
    # 같은 Q/A + 부정 피드백(새 eventId) — 예전 코드는 중복이라 조기 반환하고 아무것도 철회하지 않았다.
    again = make_sample(30, feedback=-1).model_copy(update={"eventId": "evt-test-dup-neg-1"})
    res = run(cs.collect_sample(repo, again))
    assert res.status == "DUPLICATE" and res.state == "REVOKED"
    assert res.invalidated_datasets == ["train_v20261104_001_deadbeef"]
    assert res.retirement_required_adapters == ["adapter-x"]
    m = run(repo.get_manifest("train_v20261104_001_deadbeef"))
    assert m.status == "INVALIDATED" and "NEGATIVE_FEEDBACK" in m.invalidated_reasons
    assert (run(repo.models_for_dataset("train_v20261104_001_deadbeef"))[0]).status == "RETIREMENT_REQUIRED"
    assert run(repo.get(first.candidate_id)).state == S.REVOKED


def test_user_correction_requires_review_then_can_train(repo):
    res = run(cs.collect_sample(repo, make_sample(40, feedback=-1)))
    rec = run(repo.get(res.candidate_id))
    assert "NEGATIVE_FEEDBACK" in evaluate_eligibility(rec).reasons
    corr = run(cs.submit_correction(repo, res.candidate_id, "이진 탐색의 시간 복잡도는 O(log n) 이며 정렬이 전제다.",
                                    actor=cs.Actor("service:spring", "service")))
    assert corr.status == "CORRECTION_PENDING_REVIEW" and corr.state == "NEEDS_REVIEW"
    assert run(repo.get(res.candidate_id)).verified_answer is None   # 수정 답변도 자동 채택 안 함
    out = run(cs.review(repo, res.candidate_id, decision="VERIFY", actor=REVIEWER, use="correction"))
    assert out.status == "TRAIN_ELIGIBLE"
    final = run(repo.get(res.candidate_id))
    assert final.verified_answer.startswith("이진 탐색의 시간 복잡도는") and final.verification["basis"] == "correction"


def test_pii_is_quarantined_with_masked_copy(repo):
    s = make_sample(50, question="제 이메일 hong@example.com 로 답 보내주세요. 이진 탐색이 뭔가요?")
    res = run(cs.collect_sample(repo, s))
    assert res.status == "QUARANTINED"
    rec = run(repo.get(res.candidate_id))
    assert "hong@example.com" not in rec.question and rec.content_masked
    assert run(cs.review(repo, res.candidate_id, decision="VERIFY", actor=REVIEWER)).status == "NOT_ALLOWED"


def test_duplicate_check_unavailable_defers(repo):
    repo.fail_reads = True
    assert run(cs.collect_sample(repo, make_sample(60))).status in ("DEFERRED",)


def test_consent_withdrawal_and_deletion(repo):
    a = run(cs.collect_sample(repo, make_sample(70)))
    run(cs.review(repo, a.candidate_id, decision="VERIFY", actor=REVIEWER))
    w = run(cs.withdraw_consent(repo, make_sample(70).pseudonymousUserKey, actor=cs.Actor("service:spring", "service")))
    assert w.status == "CONSENT_WITHDRAWN"
    assert run(repo.get(a.candidate_id)).state == S.REVOKED
    b = run(cs.collect_sample(repo, make_sample(71, user="pk_other_user_000001")))
    d = run(cs.delete_by_tracking_id(repo, make_sample(71, user="pk_other_user_000001").deletionTrackingId,
                                     actor=cs.Actor("service:spring", "service")))
    rec = run(repo.get(b.candidate_id))
    assert d.status == "DELETED" and rec.state == S.DELETED and rec.question == "" and rec.content_destroyed


def test_idempotent_replay(repo):
    s = make_sample(80)
    r1 = run(cs.collect_sample(repo, s))
    r2 = run(cs.collect_sample(repo, s))
    assert r2.status == "IDEMPOTENT_REPLAY" and r2.candidate_id == r1.candidate_id
