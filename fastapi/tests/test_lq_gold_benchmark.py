"""quality-gold.v1 하네스: Wilson CI, 검수 독립성, 출처 라이선스, 그룹 분할/누출, 측정 인정 조건, 경계 안정성."""
import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts.response_quality_v1 import QualityOutput
from app.quality_gate import gold_benchmark as GB

SEED = Path(__file__).parent / "fixtures" / "quality_gold" / "seed_v0_ai_draft.jsonl"


def run(c):
    return asyncio.run(c)


def _item(i, label="ACCEPT", status="HUMAN_REVIEWED", doc=None, **kw):
    rev = {"status": status, "authorId": "author-a", "reviewerIds": ["rev-b", "rev-c"] if status != "AI_DRAFT" else [],
           "expertVerified": status == "EXPERT_VERIFIED"}
    base = {"itemId": f"it-{i:04d}", "domain": "GENERAL", "taskType": "GENERAL_EXPLANATION",
            "request": f"질문 {i} 번 주제 {i * 7919 % 10007}", "proposedOutput": f"주제 {i * 104729 % 1000003} 에 대한 고유 답변 {i}",
            "expectedLabel": label, "answerRationale": "검수 근거 문장", "sourceLicense": "SELF_MADE_CC0",
            "sourceRef": "self-made:test", "documentGroup": doc or f"doc-{i}", "review": rev}
    if label == "REJECT":
        base["errorType"] = "FACTUAL_ERROR"
    base.update(kw)
    return GB.GoldItem.model_validate(base)


def _q(approved, score):
    return QualityOutput(requestId="req-gold-00001", taskType="GENERAL_EXPLANATION", success=approved, verified=approved,
                         qualityStatus="APPROVED" if approved else "REJECTED", score=score, hardFail=False,
                         evaluatorVersion="t")


def test_wilson_matches_reference_values():
    p, lo, hi = GB.wilson(5, 10)
    assert p == 0.5 and abs(lo - 0.2366) < 1e-3 and abs(hi - 0.7634) < 1e-3
    p, lo, hi = GB.wilson(0, 10)
    assert p == 0.0 and lo == 0.0 and abs(hi - 0.2775) < 1e-3
    assert GB.wilson(0, 0) == (None, None, None)


@pytest.mark.parametrize("review", [
    {"status": "HUMAN_REVIEWED", "authorId": "a1", "reviewerIds": ["r1"]},                 # reviewer 1명
    {"status": "HUMAN_REVIEWED", "authorId": "a1", "reviewerIds": ["a1", "r1"]},           # author 가 reviewer
    {"status": "HUMAN_REVIEWED", "authorId": "a1", "reviewerIds": ["r1", "r2"], "disagreement": True},  # 중재자 없음
    {"status": "EXPERT_VERIFIED", "authorId": "a1", "reviewerIds": ["r1", "r2"]},          # 전문가 확인 플래그 없음
])
def test_review_independence_is_enforced(review):
    with pytest.raises(ValidationError):
        _item(1).model_copy(update={}).model_validate({**_item(1).model_dump(), "review": review})


def test_source_license_and_reject_rationale_are_required():
    with pytest.raises(ValidationError):
        GB.GoldItem.model_validate({**_item(1).model_dump(), "sourceLicense": "USER_UPLOAD"})
    d = _item(2, "REJECT").model_dump()
    d["errorType"] = None
    with pytest.raises(ValidationError):
        GB.GoldItem.model_validate(d)


def test_group_split_keeps_documents_and_near_duplicates_together():
    items = [_item(i, doc="same-doc") for i in range(6)] + [_item(100 + i) for i in range(30)]
    items.append(_item(500, proposedOutput=items[10].proposedOutput, request=items[10].request, doc="other-doc"))
    split = GB.group_split(items)
    assert len({split[f"it-{i:04d}"] for i in range(6)}) == 1
    assert split["it-0500"] == split[items[10].itemId]          # 근접/정확 중복은 같은 분할
    assert GB.leakage_report(items, split) == {"sharedDocumentGroups": 0, "sharedUserGroups": 0,
                                               "sharedExactHashes": 0, "nearDuplicatePairs": 0}


def test_ai_draft_seed_is_never_reported_as_measured():
    items = GB.load_items(SEED)
    assert len(items) >= 30 and all(i.review.status == GB.ReviewStatus.AI_DRAFT for i in items)
    from app.quality_gate.evaluator import clear_cache, evaluate
    clear_cache()
    rep = run(GB.run_benchmark(items, evaluate))
    assert rep.measurementStatus == "PREPARED_NOT_MEASURED" and rep.overall["basis"].startswith("smoke")
    assert rep.leakage == {"sharedDocumentGroups": 0, "sharedUserGroups": 0, "sharedExactHashes": 0, "nearDuplicatePairs": 0}
    assert {d for d in GB.DOMAIN_QUOTA} <= {i.domain for i in items}
    # 시드 smoke 가 찾았던 오승인(정중체 부정 '아닙니다') 은 수정 후 0 건이어야 한다
    assert rep.falseApprovals == []


def test_measured_only_with_enough_reviewed_items_and_reports_ci_and_false_approvals():
    items = [_item(i, "ACCEPT" if i % 2 else "REJECT") for i in range(240)]

    async def fake(inp):
        i = int(inp.requestId.split("-")[-1])
        expected_accept = i % 2 == 1
        approved = expected_accept if i % 40 else not expected_accept      # 40개마다 1개 오판
        return _q(approved, 90.0 if approved else 40.0)
    rep = run(GB.run_benchmark(items, fake))
    assert rep.measurementStatus == "MEASURED", rep.reasons
    o = rep.overall
    assert o["basis"].startswith("test") and o["FAR_CI95"][0] <= o["FAR"] <= o["FAR_CI95"][1]
    assert all(fa["itemId"].startswith("it-") for fa in rep.falseApprovals)
    assert set(rep.byDomain) == {"GENERAL"}


def test_boundary_band_items_are_reevaluated_under_perturbation():
    items = [_item(i) for i in range(4)]
    calls = {"n": 0}

    async def fake(inp):
        calls["n"] += 1
        base = isinstance(inp.proposedOutput, str) and not inp.proposedOutput.endswith(("\n", "바랍니다."))
        return _q(base, 80.0 if base else 79.0)                             # 변형하면 79 → 승인 뒤집힘
    rep = run(GB.run_benchmark(items, fake))
    assert rep.boundary["items"] == 4 and rep.boundary["trials"] == 16 and rep.boundary["flips"] >= 8
    assert rep.boundary["flipRate"] is not None and calls["n"] == 4 + 16
