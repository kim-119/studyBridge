"""학습 후보 수집·검수·철회 서비스.

핵심 규칙
- 수집은 학습이 아니다. 새 후보는 항상 COLLECTED → (QUARANTINED | NEEDS_REVIEW) 로만 간다.
- 중복이어도 '부정 피드백'은 반드시 기존 후보에 반영된다(예전 코드는 중복 조기 반환으로 철회가 누락됨).
- 부정 피드백/동의 철회/자료 삭제 → 후보 상태 전이 + 그 후보가 포함된 데이터셋 manifest INVALIDATED
  + 해당 manifest 로 학습한 어댑터 후보 RETIREMENT_REQUIRED (가중치에서 '완전 삭제됨'이라고 주장하지 않음).
- 사용자 수정 답변은 정답으로 바로 쓰지 않고 검수 대기(NEEDS_REVIEW). 검수자가 확인해야 verified_answer 가 된다.
- (Phase B3) 동의 철회/자료 삭제는 먼저 DB tombstone 을 남긴다 → 이후(또는 경합 중) 도착한 샘플은 저장 거부·즉시 철회.
  철회는 '철회 시각 이전 동의'로 만든 후보에만 적용한다(재동의 이후 후보는 유지, 소급 확장/소급 철회 없음).
- 같은 eventId 의 중복 처리는 DB 원장(repo.claim_event)이 막는다 — 프로세스 메모리 캐시에 의존하지 않는다(다중 워커 안전).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from app.contracts.training_sample_v1 import TrainingSampleV1, VerificationMethod
from app.training_pipeline import eligibility as elig
from app.training_pipeline.records import CandidateEvent, CandidateRecord, utcnow
from app.training_pipeline.states import CandidateState, check_transition
from app.utils import duplicate_checker as dup
from app.utils.pii_filter import mask_pii, scan_pii

logger = logging.getLogger(__name__)
S = CandidateState


@dataclass
class ServiceResult:
    status: str
    candidate_id: Optional[str] = None
    state: Optional[str] = None
    reasons: List[str] = field(default_factory=list)
    invalidated_datasets: List[str] = field(default_factory=list)
    retirement_required_adapters: List[str] = field(default_factory=list)
    purged_datasets: List[str] = field(default_factory=list)

    @property
    def trained_model_effect(self) -> str:
        # 학습된 가중치에서 샘플을 지웠다고 주장하지 않는다: 영향받은 어댑터는 '폐기/재학습 필요'로만 표시된다.
        return "RETIREMENT_REQUIRED_WEIGHTS_NOT_ERASED" if self.retirement_required_adapters else "NO_TRAINED_ADAPTER_AFFECTED"


def result_to_dict(r: ServiceResult) -> Dict[str, Any]:
    d = asdict(r)
    d["trained_model_effect"] = r.trained_model_effect
    return d


def result_from_dict(d: Dict[str, Any]) -> ServiceResult:
    keys = {f for f in ServiceResult.__dataclass_fields__}
    return ServiceResult(**{k: v for k, v in (d or {}).items() if k in keys})


async def run_once(repo, *, event_id: str, message_type: str, body_sha256: str,
                   work: Callable[[], Awaitable[ServiceResult]]) -> Tuple[str, ServiceResult]:
    """eventId 단위 1회 처리(DB 원장). 반환 (disposition, result):
    PROCESSED | REPLAY(이전 결과) | CONFLICT(같은 id 다른 본문) | IN_PROGRESS(다른 워커 처리 중) | NOT_FINAL(DEFERRED, 재시도 가능)."""
    state, prior = await repo.claim_event(event_id, message_type, body_sha256)
    if state == "DONE":
        r = result_from_dict(prior)
        return "REPLAY", ServiceResult(status="IDEMPOTENT_REPLAY", candidate_id=r.candidate_id, state=r.state,
                                       reasons=list(r.reasons), invalidated_datasets=r.invalidated_datasets,
                                       retirement_required_adapters=r.retirement_required_adapters,
                                       purged_datasets=r.purged_datasets)
    if state == "CONFLICT":
        return "CONFLICT", ServiceResult(status="EVENT_ID_CONFLICT", reasons=["EVENT_ID_REUSED_WITH_DIFFERENT_BODY"])
    if state == "IN_PROGRESS":
        return "IN_PROGRESS", ServiceResult(status="IN_PROGRESS", reasons=["EVENT_BEING_PROCESSED"])
    try:
        res = await work()
    except BaseException:
        await repo.release_event(event_id)      # 실패한 선점은 풀어 다음 재시도가 다시 처리하게 한다
        raise
    if res.status == "DEFERRED":
        await repo.release_event(event_id)
        return "NOT_FINAL", res
    await repo.complete_event(event_id, result_to_dict(res))
    return "PROCESSED", res


@dataclass(frozen=True)
class Actor:
    actor_id: str
    role: str
    request_id: Optional[str] = None


SYSTEM_ACTOR = Actor("system:ai07", "system")


async def _transition(repo, rec: CandidateRecord, dst: CandidateState, actor: Actor, event_type: str,
                      reasons: List[str]) -> CandidateRecord:
    src = rec.state
    if src != dst:
        check_transition(src, dst)
    rec.state = dst
    expected = rec.version
    saved = await repo.update(rec, expected)
    await _event(repo, saved.candidate_id, event_type, src.value, dst.value, actor, reasons)
    return saved


async def _event(repo, candidate_id: str, event_type: str, src: Optional[str], dst: Optional[str],
                 actor: Actor, reasons: List[str]) -> None:
    ev = CandidateEvent.build(event_id=str(uuid.uuid4()), candidate_id=candidate_id, event_type=event_type,
                              from_state=src, to_state=dst, actor=actor.actor_id, actor_role=actor.role,
                              request_id=actor.request_id, reason_codes=reasons,
                              prev_hash=await repo.last_event_hash())
    await repo.append_event(ev)


# 원문 자체를 더 이상 보관하면 안 되는 사유 → 이미 export 된 JSONL 파일도 파기한다.
# (예전: DB 내용만 지우고 0400 train.jsonl 에는 원문이 남았다 — 2026-11-04 재현)
_PURGE_REASONS = frozenset({"SOURCE_DELETED", "CONSENT_WITHDRAWN"})


async def _invalidate_lineage(repo, content_hash: str, reason: str, result: ServiceResult) -> None:
    for m in await repo.manifests_containing(content_hash):
        await repo.invalidate_manifest(m.dataset_id, reason)
        result.invalidated_datasets.append(m.dataset_id)
        if reason in _PURGE_REASONS:
            from app.training_pipeline.export_service import purge_dataset_files
            try:
                if purge_dataset_files(m.dataset_id):
                    result.purged_datasets.append(m.dataset_id)
                    await repo.invalidate_manifest(m.dataset_id, "FILES_PURGED")
            except (OSError, ValueError) as e:
                # 파기 실패는 숨기지 않는다: 호출자가 재시도하도록 예외를 올린다(멱등).
                raise RuntimeError(f"DATASET_PURGE_FAILED:{type(e).__name__}") from e
        for model in await repo.models_for_dataset(m.dataset_id):
            if model.status != "RETIREMENT_REQUIRED":
                await repo.set_model_status(model.adapter_id, "RETIREMENT_REQUIRED",
                                            f"{reason}: dataset {m.dataset_id} member withdrawn — "
                                            "weights are NOT erased; retire or retrain without the sample")
            result.retirement_required_adapters.append(model.adapter_id)


def _scan_all(*texts: Optional[str]):
    worst = None
    cats: List[str] = []
    for t in texts:
        if not t:
            continue
        r = scan_pii(t)
        if not r.clean:
            cats.extend(r.categories or ("SCAN_ERROR",))
            worst = r if (worst is None or r.blocking) else worst
    return worst, sorted(set(cats))


def _record_from_sample(sample: TrainingSampleV1, *, task_type: Optional[str],
                        display_quality: Optional[Dict[str, Any]]) -> CandidateRecord:
    claim = sample.trainingEligibility
    return CandidateRecord(
        candidate_id=str(uuid.uuid4()), event_id=sample.eventId,
        pseudonymous_user_key=sample.pseudonymousUserKey, state=S.COLLECTED,
        source_kind=sample.sourceKind.value, task_type=task_type,
        question=sample.question, candidate_answer=sample.candidateAnswer,
        verified_answer=None,                      # 수집 시점의 verifiedAnswer 는 검수 전 '주장'으로만 보관
        verification=sample.verification.model_dump(mode="json") if sample.verification else None,
        user_correction=sample.verifiedAnswer if (sample.verifiedAnswer and sample.verifiedAnswer != sample.candidateAnswer) else None,
        evidence=[e.model_dump(mode="json") for e in sample.evidence],
        content_hash=sample.contentHash, simhash=dup.simhash64(sample.question + "\n" + sample.candidateAnswer),
        deletion_tracking_id=sample.deletionTrackingId, retention_policy=sample.retentionPolicy,
        model_name=sample.modelName, model_digest=sample.modelDigest,
        prompt_template_version=sample.promptTemplateVersion, rights_status=sample.rightsStatus.value,
        source_revision_hash=sample.sourceRevisionHash, consent_version=sample.consentVersion,
        consent_timestamp=sample.consentTimestamp, consent_granted=claim.consentGranted,
        consent_scope=list(claim.consentScope), consent_withdrawn=claim.consentWithdrawn,
        quality_label=sample.qualityLabel.value, quality_evaluator_version=sample.qualityEvaluatorVersion,
        display_quality_score=(display_quality or {}).get("score"),
        display_quality_status=(display_quality or {}).get("qualityStatus"),
        feedback_score=sample.feedback.score if sample.feedback else None,
        feedback_history=list(sample.feedback.history) if sample.feedback else [],
    )


async def collect_sample(repo, sample: TrainingSampleV1, *, actor: Actor = SYSTEM_ACTOR,
                         task_type: Optional[str] = None,
                         display_quality: Optional[Dict[str, Any]] = None) -> ServiceResult:
    """training-sample.v1 → 후보 저장. TRAIN_ELIGIBLE 로 직접 가지 않는다. 저장소 장애 → DEFERRED(저장 안 함)."""
    from app.training_pipeline.repository import RepositoryUnavailable
    try:
        return await _collect_sample(repo, sample, actor=actor, task_type=task_type, display_quality=display_quality)
    except RepositoryUnavailable:
        return ServiceResult(status="DEFERRED", reasons=["TRAINING_REPOSITORY_UNAVAILABLE"])


async def _tombstone_reason(repo, sample: TrainingSampleV1) -> Optional[str]:
    """이 샘플이 철회/삭제된 대상인가(저장 전·후 모두 확인 — 동시 철회 경합 대비)."""
    if await repo.get_deletion_tombstone(sample.deletionTrackingId) is not None:
        return "SOURCE_DELETED"
    t = await repo.get_consent_tombstone(sample.pseudonymousUserKey)
    if t is not None and (sample.consentTimestamp is None or sample.consentTimestamp <= t):
        return "CONSENT_WITHDRAWN"
    return None


async def _collect_sample(repo, sample: TrainingSampleV1, *, actor: Actor, task_type: Optional[str],
                          display_quality: Optional[Dict[str, Any]]) -> ServiceResult:
    # 멱등: 같은 eventId 재전송은 기존 결과를 돌려준다.
    prior = await repo.find_by_event_id(sample.eventId)
    if prior is not None:
        return ServiceResult(status="IDEMPOTENT_REPLAY", candidate_id=prior.candidate_id, state=prior.state.value)
    blocked = await _tombstone_reason(repo, sample)
    if blocked is not None:
        # 철회/삭제 이후 도착한 샘플(재전송·전송 중 경합 포함)은 저장하지 않는다.
        return ServiceResult(status="REJECTED_" + blocked, reasons=[blocked])

    # 1) 중복 검사 — 실패하면 저장 보류(fail-closed)
    d = await dup.check_duplicate(sample.contentHash, sample.question + "\n" + sample.candidateAnswer, repo)
    if d.status == dup.UNKNOWN:
        return ServiceResult(status="DEFERRED", reasons=["DUPLICATE_CHECK_UNAVAILABLE"])
    negative = bool(sample.feedback and sample.feedback.score < 0)
    if d.status == dup.EXACT_DUPLICATE:
        res = ServiceResult(status="DUPLICATE", candidate_id=d.matched_id, reasons=["EXACT_DUPLICATE"])
        if sample.feedback is not None:
            # 중복이라도 최신 피드백은 반영한다(부정이면 철회까지).
            fb = await record_feedback(repo, d.matched_id, sample.feedback.score, actor=actor,
                                       reason_code=sample.feedback.reasonCode)
            res.state, res.reasons = fb.state, res.reasons + fb.reasons
            res.invalidated_datasets, res.retirement_required_adapters = fb.invalidated_datasets, fb.retirement_required_adapters
        return res
    if d.status == dup.NEAR_DUPLICATE:
        res = ServiceResult(status="NEAR_DUPLICATE", candidate_id=d.matched_id, reasons=["NEAR_DUPLICATE"])
        if negative:
            other = await repo.get(d.matched_id)
            if other and other.state in (S.VERIFIED, S.TRAIN_ELIGIBLE):
                await _transition(repo, other, S.NEEDS_REVIEW, actor, "NEAR_DUP_NEGATIVE_FEEDBACK",
                                  ["NEAR_DUP_NEGATIVE_FEEDBACK"])
                await _invalidate_lineage(repo, other.content_hash, "NEAR_DUP_NEGATIVE_FEEDBACK", res)
                res.state = S.NEEDS_REVIEW.value
        return res

    rec = _record_from_sample(sample, task_type=task_type, display_quality=display_quality)

    # 2) PII/비밀 검사 — 감지/오류면 마스킹 사본만 저장하고 격리
    worst, cats = _scan_all(sample.question, sample.candidateAnswer, sample.verifiedAnswer,
                            *[e.quote for e in sample.evidence])
    target_state = S.NEEDS_REVIEW
    reasons: List[str] = []
    if worst is not None:
        rec.question = mask_pii(rec.question)
        rec.candidate_answer = mask_pii(rec.candidate_answer)
        rec.user_correction = mask_pii(rec.user_correction) if rec.user_correction else None
        for e in rec.evidence:
            if e.get("quote"):
                e["quote"] = mask_pii(e["quote"])
        rec.content_masked = True
        rec.pii_status = "ERROR" if worst.status == "ERROR" else "DETECTED"
        rec.pii_categories = cats
        target_state = S.QUARANTINED
        reasons.append("PII_SCAN_ERROR" if worst.status == "ERROR" else "PII_DETECTED")
    else:
        rec.pii_status = "CLEAN"

    if not await repo.insert_candidate(rec):
        # 동시 수집 race: 유니크 제약이 막았다 → 중복으로 처리
        return ServiceResult(status="DUPLICATE", reasons=["CONCURRENT_DUPLICATE"])
    await _event(repo, rec.candidate_id, "COLLECTED", None, S.COLLECTED.value, actor, [])
    saved = await repo.get(rec.candidate_id)
    if negative and not rec.user_correction:
        reasons.append("NEGATIVE_FEEDBACK_AT_COLLECTION")
    saved = await _transition(repo, saved, target_state, actor, "TRIAGED", reasons or ["AWAITING_VERIFICATION"])
    # 저장 뒤 재확인: 저장과 동시에 철회/삭제가 처리됐다면(철회 쪽 스캔이 이 행을 못 봤을 수 있음) 여기서 정리한다.
    late = await _tombstone_reason(repo, sample)
    if late is not None:
        res = ServiceResult(status="REJECTED_" + late, candidate_id=saved.candidate_id, reasons=[late, "LATE_TOMBSTONE"])
        if late == "SOURCE_DELETED":
            await _destroy(repo, saved, actor, res)
        else:
            saved.consent_withdrawn = True
            saved = await _transition(repo, saved, S.REVOKED, actor, "CONSENT_WITHDRAWN", ["CONSENT_WITHDRAWN"])
            res.state = saved.state.value
        return res
    return ServiceResult(status="QUARANTINED" if target_state == S.QUARANTINED else "STORED",
                         candidate_id=saved.candidate_id, state=saved.state.value, reasons=reasons)


async def record_feedback(repo, candidate_id: str, score: int, *, actor: Actor,
                          reason_code: Optional[str] = None, expected_user_key: Optional[str] = None) -> ServiceResult:
    rec = await repo.get(candidate_id)
    if rec is None or (expected_user_key is not None and rec.pseudonymous_user_key != expected_user_key):
        # 다른 사용자의 후보는 '없음'과 같게 응답한다(존재 여부 노출·타인 후보 철회 방지).
        return ServiceResult(status="NOT_FOUND")
    rec.feedback_history = (rec.feedback_history or []) + [int(score)]
    rec.feedback_score = int(score)
    res = ServiceResult(status="FEEDBACK_RECORDED", candidate_id=candidate_id)
    if rec.state in (S.REVOKED, S.DELETED) and score < 0:
        # 이미 철회된 후보: 이전 시도가 lineage 무효화 중 실패했을 수 있으므로 무효화를 다시 수행(멱등).
        saved = await repo.update(rec, rec.version)
        await _invalidate_lineage(repo, rec.content_hash, "NEGATIVE_FEEDBACK", res)
        res.state = saved.state.value
        return res
    if score >= 0 or rec.state in (S.REVOKED, S.DELETED):
        saved = await repo.update(rec, rec.version)
        await _event(repo, candidate_id, "FEEDBACK", saved.state.value, saved.state.value, actor,
                     [f"SCORE_{score}"] + ([reason_code] if reason_code else []))
        res.state = saved.state.value
        return res
    # 부정 피드백: 학습 타깃이 원 AI 답변이면 철회, 검증된 별도 수정 답변이면 재검수.
    distinct_target = bool(rec.verified_answer and rec.verified_answer.strip() != rec.candidate_answer.strip())
    dst = S.NEEDS_REVIEW if distinct_target else S.REVOKED
    if rec.state == S.REJECTED and dst == S.NEEDS_REVIEW:
        dst = S.REJECTED
    saved = await _transition(repo, rec, dst, actor, "NEGATIVE_FEEDBACK",
                              ["NEGATIVE_FEEDBACK"] + ([reason_code] if reason_code else []))
    await _invalidate_lineage(repo, rec.content_hash, "NEGATIVE_FEEDBACK", res)
    res.status, res.state, res.reasons = "REVOKED" if dst == S.REVOKED else "REREVIEW", saved.state.value, ["NEGATIVE_FEEDBACK"]
    return res


async def submit_correction(repo, candidate_id: str, corrected_answer: str, *, actor: Actor) -> ServiceResult:
    """사용자 수정 답변 → 검수 대기. 수정 답변도 사람이 틀릴 수 있으므로 정답으로 자동 채택하지 않는다."""
    rec = await repo.get(candidate_id)
    if rec is None:
        return ServiceResult(status="NOT_FOUND")
    if rec.state in (S.REVOKED, S.DELETED):
        return ServiceResult(status="NOT_ALLOWED", state=rec.state.value, reasons=[f"STATE_{rec.state.value}"])
    r = scan_pii(corrected_answer)
    rec.user_correction = corrected_answer if r.clean else mask_pii(corrected_answer)
    if not r.clean:
        rec.content_masked = True
    rec.verified_answer = None
    rec.verification = None
    dst = S.QUARANTINED if not r.clean else S.NEEDS_REVIEW
    if rec.state == dst:
        saved = await repo.update(rec, rec.version)
        await _event(repo, candidate_id, "USER_CORRECTION", dst.value, dst.value, actor, ["USER_CORRECTION"])
    else:
        saved = await _transition(repo, rec, dst, actor, "USER_CORRECTION", ["USER_CORRECTION"])
    res = ServiceResult(status="CORRECTION_PENDING_REVIEW", candidate_id=candidate_id, state=saved.state.value)
    await _invalidate_lineage(repo, rec.content_hash, "USER_CORRECTION", res)
    return res


async def review(repo, candidate_id: str, *, decision: str, actor: Actor, use: str = "candidate",
                 reviewer_answer: Optional[str] = None,
                 method: str = VerificationMethod.HUMAN_REVIEW.value,
                 gold_reference: Optional[str] = None) -> ServiceResult:
    """검수자 결정. decision=VERIFY|REJECT. VERIFY 후 자격을 즉시 재평가해 충족 시에만 TRAIN_ELIGIBLE.

    use: candidate(원 답변 확인) | correction(사용자 수정 답변 확인) | reviewer(검수자 작성 답변)
    """
    rec = await repo.get(candidate_id)
    if rec is None:
        return ServiceResult(status="NOT_FOUND")
    if decision == "REJECT":
        if rec.state in (S.REVOKED, S.DELETED):
            return ServiceResult(status="NOT_ALLOWED", state=rec.state.value, reasons=[f"STATE_{rec.state.value}"])
        if rec.state == S.REJECTED:                       # 재시도 멱등(예전: REJECTED→REJECTED 전이 예외 → 500)
            return ServiceResult(status="REJECTED", candidate_id=candidate_id, state=rec.state.value)
        saved = await _transition(repo, rec, S.REJECTED, actor, "REVIEW_REJECT", ["REVIEWER_REJECTED"])
        res = ServiceResult(status="REJECTED", candidate_id=candidate_id, state=saved.state.value)
        await _invalidate_lineage(repo, rec.content_hash, "REVIEWER_REJECTED", res)
        return res
    if decision != "VERIFY":
        return ServiceResult(status="INVALID_DECISION")
    if method == VerificationMethod.LLM_JUDGE.value or method == VerificationMethod.NONE.value:
        return ServiceResult(status="NOT_ALLOWED", reasons=["VERIFICATION_INSUFFICIENT"])
    if rec.content_masked:
        return ServiceResult(status="NOT_ALLOWED", reasons=["CONTENT_MASKED"])
    answer = {"candidate": rec.candidate_answer, "correction": rec.user_correction, "reviewer": reviewer_answer}.get(use)
    if not answer or not answer.strip():
        return ServiceResult(status="NOT_ALLOWED", reasons=["VERIFIED_ANSWER_MISSING"])
    if not scan_pii(answer).clean:
        return ServiceResult(status="NOT_ALLOWED", reasons=["PII_NOT_CLEAR"])
    if rec.state not in (S.NEEDS_REVIEW, S.VERIFIED):
        return ServiceResult(status="NOT_ALLOWED", state=rec.state.value, reasons=[f"STATE_{rec.state.value}"])
    rec.verified_answer = answer
    rec.verification = {"method": method, "reviewerId": actor.actor_id,   # 누가 확인했는지 항상 기록
                        "goldReference": gold_reference, "basis": use}
    rec.quality_label = "REVIEWER_VERIFIED" if method == "HUMAN_REVIEW" else "DETERMINISTIC_GOLD"
    saved = await _transition(repo, rec, S.VERIFIED, actor, "REVIEW_VERIFY", [f"BASIS_{use.upper()}"])
    return await promote_if_eligible(repo, saved.candidate_id, actor=actor)


async def promote_if_eligible(repo, candidate_id: str, *, actor: Actor) -> ServiceResult:
    rec = await repo.get(candidate_id)
    if rec is None:
        return ServiceResult(status="NOT_FOUND")
    result = elig.evaluate_eligibility(rec)
    rec.eligibility_reasons = result.reasons
    if result.eligible and rec.state == S.VERIFIED:
        saved = await _transition(repo, rec, S.TRAIN_ELIGIBLE, actor, "PROMOTED", ["ALL_GATES_PASSED"])
        return ServiceResult(status="TRAIN_ELIGIBLE", candidate_id=candidate_id, state=saved.state.value)
    if not result.eligible and rec.state == S.TRAIN_ELIGIBLE:
        saved = await _transition(repo, rec, S.NEEDS_REVIEW, actor, "DEMOTED", result.reasons)
        return ServiceResult(status="DEMOTED", candidate_id=candidate_id, state=saved.state.value, reasons=result.reasons)
    saved = await repo.update(rec, rec.version)
    return ServiceResult(status="VERIFIED_NOT_ELIGIBLE" if not result.eligible else "UNCHANGED",
                         candidate_id=candidate_id, state=saved.state.value, reasons=result.reasons)


async def withdraw_consent(repo, pseudonymous_user_key: str, *, actor: Actor,
                           withdrawn_at: Optional[datetime] = None, event_id: Optional[str] = None) -> ServiceResult:
    """tombstone(철회 시각) 먼저 → 그 시각 이전 동의로 만든 후보 전부 REVOKED + lineage 무효화.
    재동의 이후(consentTimestamp > 철회 시각) 후보는 건드리지 않는다. 동의 시각이 없는 후보는 보수적으로 철회."""
    res = ServiceResult(status="CONSENT_WITHDRAWN")
    effective = await repo.put_consent_tombstone(pseudonymous_user_key, withdrawn_at or utcnow(),
                                                 event_id or (actor.request_id or "direct"))
    for rec in await repo.list_by(pseudonymous_user_key=pseudonymous_user_key):
        if rec.consent_timestamp is not None and rec.consent_timestamp > effective:
            continue
        if rec.state in (S.REVOKED, S.DELETED):
            await _invalidate_lineage(repo, rec.content_hash, "CONSENT_WITHDRAWN", res)   # 재시도 멱등
            continue
        rec.consent_withdrawn = True
        await _transition(repo, rec, S.REVOKED, actor, "CONSENT_WITHDRAWN", ["CONSENT_WITHDRAWN"])
        await _invalidate_lineage(repo, rec.content_hash, "CONSENT_WITHDRAWN", res)
    return res


async def _destroy(repo, rec: CandidateRecord, actor: Actor, res: ServiceResult) -> None:
    if rec.state == S.DELETED:
        await _invalidate_lineage(repo, rec.content_hash, "SOURCE_DELETED", res)      # 재시도 멱등
        return
    rec.question = rec.candidate_answer = ""
    rec.verified_answer = rec.user_correction = None
    rec.evidence = []
    rec.content_destroyed = True
    saved = await _transition(repo, rec, S.DELETED, actor, "SOURCE_DELETED", ["SOURCE_DELETED"])
    res.state = saved.state.value
    await _invalidate_lineage(repo, rec.content_hash, "SOURCE_DELETED", res)


async def delete_by_tracking_id(repo, deletion_tracking_id: str, *, actor: Actor,
                                deleted_at: Optional[datetime] = None, event_id: Optional[str] = None) -> ServiceResult:
    """사용자 자료 삭제: tombstone 먼저 → 내용 파기(해시/lineage 만 보존) + manifest 무효화 + 어댑터 retirement 표시."""
    res = ServiceResult(status="DELETED")
    await repo.put_deletion_tombstone(deletion_tracking_id, deleted_at or utcnow(),
                                      event_id or (actor.request_id or "direct"))
    for rec in await repo.list_by(deletion_tracking_id=deletion_tracking_id):
        await _destroy(repo, rec, actor, res)
    res.state = None
    return res
