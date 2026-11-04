"""
학습 후보 관리 API.

권한 분리
  - 서비스(Spring) 내부 Bearer:  collect(레거시) / collect-v1(서명 필수) / feedback / correction /
                                 consent-withdrawal / deletion
  - 관리자(내부 Bearer + X-Training-Admin-Token + actor/role/requestId):
        stats(training_reviewer|training_admin), approve·reject(training_reviewer|training_admin),
        export-jsonl(training_admin)
  - 모든 라우트: 본문 크기 제한(라우트 클래스), rate limit, 감사 로그(원문 없음).
상태/자격 규칙은 app.training_pipeline 참고. 자동 학습 승인 경로는 없다.
"""
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.core.audit import AuditWriteFailed, audit_event
from app.core.request_guards import RateLimiter, limited_route_class
from app.core.security import AdminPrincipal, require_role, verify_internal_token, verify_training_admin
from app.schemas.training_candidate_schema import (
    LEGACY_DEFAULT_OUTPUT_PATH,
    CollectCandidateRequest,
    CollectCandidateResponse,
    ConsentWithdrawalRequest,
    CorrectionRequest,
    DeletionRequest,
    ExportJsonlRequest,
    ExportJsonlResponse,
    FeedbackRequest,
    LineageResponse,
    ReviewCandidateRequest,
    ReviewCandidateResponse,
    TrainingPipelineStatsResponse,
)

logger = logging.getLogger(__name__)
class _TrainingRoute(limited_route_class(128 * 1024)):
    """도메인 예외를 안정된 오류 계약으로 바꾼다(예전: InvalidTransition/DB 오류가 500 + 스택)."""

    def get_route_handler(self):
        inner = super().get_route_handler()

        async def handler(request: Request):
            from app.training_pipeline.repository import ConcurrentModification, RepositoryUnavailable
            from app.training_pipeline.states import InvalidTransition
            try:
                return await inner(request)
            except InvalidTransition:
                return JSONResponse(status_code=409, content={"errorCode": "INVALID_STATE_TRANSITION"})
            except ConcurrentModification:
                return JSONResponse(status_code=409, content={"errorCode": "CONCURRENT_MODIFICATION"})
            except RepositoryUnavailable:
                return JSONResponse(status_code=503, content={"errorCode": "TRAINING_REPOSITORY_UNAVAILABLE"})
        return handler


router = APIRouter(
    prefix="/api/training-candidates",
    tags=["Training Candidates"],
    dependencies=[Depends(verify_internal_token)],
    route_class=_TrainingRoute,
)

SERVICE_RATE = RateLimiter(capacity=120, refill_per_sec=10)
# 철회(부정 피드백/동의 철회/삭제)는 '줄이는 방향'이라 수집보다 넉넉한 별도 버킷. 429 시 Spring 은 재시도해야 한다.
REVOCATION_RATE = RateLimiter(capacity=1000, refill_per_sec=100)
# actor id 는 자기 주장이므로 버킷은 서버가 정한 역할 단위로 나눈다.
ADMIN_RATE = RateLimiter(capacity=30, refill_per_sec=0.5)


def _repo():
    from app.training_pipeline.repository import RepositoryUnavailable, get_repository
    try:
        return get_repository()
    except RepositoryUnavailable:
        raise HTTPException(status_code=503, detail={"errorCode": "TRAINING_REPOSITORY_UNAVAILABLE"})


def _actor(p: AdminPrincipal):
    from app.training_pipeline.candidate_service import Actor
    return Actor(p.actor_id, p.role, p.request_id)


def _service_actor(request_id: str | None):
    from app.training_pipeline.candidate_service import Actor
    return Actor("service:spring", "service", (request_id or "")[:128] or None)


def _require_audit(event_type: str, principal: AdminPrincipal, targets=None) -> None:
    """관리 작업(내보내기/검수)은 감사 기록을 먼저 남기고, 남길 수 없으면 실행하지 않는다."""
    try:
        audit_event(event_type, actor=principal.actor_id, role=principal.role, request_id=principal.request_id,
                    outcome="REQUESTED", target_ids=targets, required=True)
    except AuditWriteFailed:
        raise HTTPException(status_code=503, detail={"errorCode": "AUDIT_UNAVAILABLE"})


def _collection_enabled() -> bool:
    from app.training_pipeline.collection_hook import collection_enabled
    return collection_enabled()


@router.get("/stats", response_model=TrainingPipelineStatsResponse, summary="학습 후보 상태별 통계(관리자)")
async def get_stats(principal: AdminPrincipal = Depends(verify_training_admin)) -> TrainingPipelineStatsResponse:
    ADMIN_RATE.check(f"stats:{principal.role}")
    from app.training_pipeline.collection_hook import STATS
    from app.training_pipeline.repository import RepositoryUnavailable
    repo = _repo()
    try:
        states = await repo.counts_by_state()
    except RepositoryUnavailable:
        # 예전처럼 200 + 0 건으로 위장하지 않는다.
        raise HTTPException(status_code=503, detail={"errorCode": "TRAINING_REPOSITORY_UNAVAILABLE"})
    audit_event("training.stats", actor=principal.actor_id, role=principal.role, request_id=principal.request_id,
                outcome="OK")
    return TrainingPipelineStatsResponse(states=states, collection=STATS.snapshot(),
                                         trainEligible=states.get("TRAIN_ELIGIBLE", 0))


@router.post("/export-jsonl", response_model=ExportJsonlResponse, summary="TRAIN_ELIGIBLE 데이터셋 내보내기(관리자)")
async def export_jsonl(request: ExportJsonlRequest,
                       principal: AdminPrincipal = Depends(verify_training_admin)) -> JSONResponse:
    require_role(principal, "training_admin")
    ADMIN_RATE.check(f"export:{principal.role}")
    if request.output_path not in (None, "", LEGACY_DEFAULT_OUTPUT_PATH):
        audit_event("training.export", actor=principal.actor_id, role=principal.role,
                    request_id=principal.request_id, outcome="DENIED", extra={"errorCode": "OUTPUT_PATH_NOT_ALLOWED"})
        raise HTTPException(status_code=400, detail={"errorCode": "OUTPUT_PATH_NOT_ALLOWED"})
    from app.training_pipeline.export_service import export_dataset
    _require_audit("training.export.requested", principal)
    res = await export_dataset(_repo(), actor=principal.actor_id, request_id=principal.request_id)
    audit_event("training.export", actor=principal.actor_id, role=principal.role, request_id=principal.request_id,
                outcome=res.status.upper(), target_ids=[res.dataset_id] if res.dataset_id else [],
                extra={"datasetId": res.dataset_id, "sampleCount": res.total, "manifestSha256": res.manifest_sha256,
                       "errorCode": res.error_code})
    body = ExportJsonlResponse(dataset_version=res.dataset_id, sample_count=res.total,
                               output_file_path=res.relative_path, status=res.status, exported_count=res.total,
                               split_counts=res.sample_counts, excluded=res.excluded,
                               manifest_sha256=res.manifest_sha256, error_code=res.error_code,
                               split_warnings=res.split_warnings)
    code = {"completed": 200, "empty": 200, "busy": 409}.get(res.status, 500)
    return JSONResponse(status_code=code, content=body.model_dump())


@router.post("/collect", response_model=CollectCandidateResponse,
             summary="[레거시] AI 답변 학습 후보 수집 — 동의 정보가 없어 저장하지 않음(부정 피드백 철회만 반영)")
async def collect_candidate_endpoint(request: CollectCandidateRequest,
                                     x_request_id: str | None = Header(default=None, alias="X-Request-Id")
                                     ) -> CollectCandidateResponse:
    SERVICE_RATE.check("collect")
    from app.services.training_candidate_manager import collect_candidate
    result = await collect_candidate(
        question=request.question, answer=request.answer, system_prompt=request.systemPrompt,
        knowledge_level=request.knowledgeLevel, personality=request.personality,
        user_feedback_score=request.userFeedbackScore, user_feedback_text=request.userFeedbackText,
        rag_grounding_score=request.ragGroundingScore, request_id=x_request_id,
    )
    return CollectCandidateResponse(**{k: v for k, v in result.items() if k in CollectCandidateResponse.model_fields})


_CONSENT_FUTURE_TOLERANCE_S = 300


def _lineage_json(status_code: int, res, *, replay: bool = False, extra: dict | None = None) -> JSONResponse:
    body = {"success": status_code < 400 and not res.status.startswith(("REJECTED", "NOT_FOUND", "EVENT_ID", "IN_PROGRESS")),
            "status": res.status, "candidate_uuid": res.candidate_id, "state": res.state, "reasons": res.reasons,
            "invalidated_datasets": res.invalidated_datasets,
            "retirement_required_adapters": res.retirement_required_adapters, "purged_datasets": res.purged_datasets,
            # 이미 학습된 가중치에서 샘플을 지웠다고 주장하지 않는다(어댑터는 폐기/재학습 대상으로만 표시).
            "trainedModelEffect": res.trained_model_effect, "modelWeightsErased": False}
    if extra:
        body.update(extra)
    headers = {"Idempotent-Replay": "true"} if replay else None
    if status_code == 503:
        headers = {**(headers or {}), "Retry-After": "5"}
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def _disposition_status(disp: str, res) -> int:
    if disp == "CONFLICT":
        return 409
    if disp in ("IN_PROGRESS", "NOT_FINAL"):
        return 503                      # 다른 워커 처리 중/저장 보류 → 재시도(409 를 주면 EC2 가 SENT 로 끝낸다)
    return 200


@router.post("/collect-v1", summary="training-sample.v1 수집(본문 서명 + 동의 토큰, 기본 OFF)")
async def collect_v1(request: Request,
                     x_sig: str | None = Header(default=None, alias="X-AI-Contract-Signature"),
                     x_ts: str | None = Header(default=None, alias="X-AI-Contract-Timestamp"),
                     x_consent: str | None = Header(default=None, alias="X-AI-Training-Consent"),
                     x_request_id: str | None = Header(default=None, alias="X-Request-Id")):
    SERVICE_RATE.check("collect-v1")
    if not _collection_enabled():
        return JSONResponse(status_code=503, content={"success": False, "errorCode": "COLLECTION_DISABLED"})
    from datetime import datetime, timedelta, timezone

    from app.contracts.jtypes import ContractJsonError, parse_offset_datetime
    from app.contracts.signing import SignatureError, verify_body, verify_consent_token
    from app.contracts.training_sample_v1 import parse_sample_json
    from app.training_pipeline.candidate_service import collect_sample, run_once
    from app.training_pipeline.control import body_sha256
    raw = await request.body()
    try:
        verify_body(raw, x_sig, x_ts)
    except SignatureError as e:
        return JSONResponse(status_code=401 if e.code not in ("SIGNING_KEY_NOT_CONFIGURED", "SIGNING_KEY_REUSED") else 503,
                            content={"success": False, "errorCode": e.code})
    try:
        sample = parse_sample_json(raw)
    except ValidationError as e:
        return JSONResponse(status_code=422, content={"success": False, "errorCode": "CONTRACT_VALIDATION_FAILED",
                                                      "errors": [{"loc": list(x.get("loc", ())), "type": x.get("type")}
                                                                 for x in e.errors()[:20]]})
    except (ContractJsonError, ValueError):
        return JSONResponse(status_code=422, content={"success": False, "errorCode": "CONTRACT_VALIDATION_FAILED"})
    if not x_request_id or x_request_id != sample.eventId:
        return JSONResponse(status_code=400, content={"success": False, "errorCode": "REQUEST_ID_EVENT_MISMATCH"})
    # 동의 토큰(EC2 가 동의 DB 를 확인한 서명 claim): 용도(typ)·요청(rid=eventId)·주체(sub=가명 키) 바인딩.
    try:
        claim = verify_consent_token(x_consent, expected_request_id=sample.eventId,
                                     expected_sub=sample.pseudonymousUserKey)
    except SignatureError as e:
        return JSONResponse(status_code=503 if e.code in ("SIGNING_KEY_NOT_CONFIGURED", "SIGNING_KEY_REUSED") else 401,
                            content={"success": False, "errorCode": e.code})
    try:
        ct = parse_offset_datetime(claim.consent_timestamp) if claim.consent_timestamp else None
    except ValueError:
        ct = None
    now = datetime.now(timezone.utc)
    mismatch = None
    if "MODEL_TRAINING" not in claim.scope or "MODEL_TRAINING" not in sample.trainingEligibility.consentScope:
        mismatch = "CONSENT_SCOPE_MISSING"
    elif not sample.trainingEligibility.consentGranted or sample.trainingEligibility.consentWithdrawn:
        mismatch = "CONSENT_NOT_GRANTED"
    elif claim.consent_version is None or claim.consent_version != sample.consentVersion:
        mismatch = "CONSENT_VERSION_MISMATCH"
    elif claim.deletion_tracking_id != sample.deletionTrackingId:
        mismatch = "CONSENT_DELETION_ID_MISMATCH"
    elif ct is None or sample.consentTimestamp is None or ct != sample.consentTimestamp:
        mismatch = "CONSENT_TIMESTAMP_MISMATCH"
    elif ct > now + timedelta(seconds=_CONSENT_FUTURE_TOLERANCE_S):
        mismatch = "CONSENT_TIMESTAMP_IN_FUTURE"     # 로컬 시각을 UTC 로 표기하는 오류(C-TIME-3)도 여기서 드러난다
    if mismatch:
        audit_event("training.collect_v1.consent_rejected", actor="service:spring", role="service",
                    request_id=x_request_id, outcome=mismatch)
        return JSONResponse(status_code=422, content={"success": False, "errorCode": mismatch})
    from app.training_pipeline.repository import RepositoryUnavailable
    repo = _repo()

    async def work():
        return await collect_sample(repo, sample)
    from app.training_pipeline.repository import ConcurrentModification
    try:
        disp, res = await run_once(repo, event_id=sample.eventId, message_type="SAMPLE", body_sha256=body_sha256(raw),
                                   work=work)
    except RepositoryUnavailable:
        return JSONResponse(status_code=503, content={"success": False, "errorCode": "TRAINING_REPOSITORY_UNAVAILABLE"})
    except ConcurrentModification:
        return JSONResponse(status_code=503, headers={"Retry-After": "2"},
                            content={"success": False, "errorCode": "CONCURRENT_MODIFICATION_RETRY"})
    code = _disposition_status(disp, res)
    if res.status == "DEFERRED":
        code = 503
    return _lineage_json(code, res, replay=disp == "REPLAY")


async def _control(request: Request, expected, x_sig, x_ts, x_request_id, handle):
    """서명된 training-control.v1 공통 처리: 검증 → DB 원장 1회 처리 → 결과."""
    from app.training_pipeline.candidate_service import run_once
    from app.training_pipeline.control import ControlError, body_sha256, verify_control
    from app.training_pipeline.repository import RepositoryUnavailable
    raw = await request.body()
    try:
        msg = verify_control(raw, signature=x_sig, timestamp=x_ts, request_id=x_request_id, expected=expected)
    except ControlError as e:
        audit_event(f"training.control.{expected.value.lower()}.rejected", actor="service:spring", role="service",
                    request_id=x_request_id, outcome=e.code)
        return JSONResponse(status_code=e.status, content={"success": False, "errorCode": e.code})
    repo = _repo()
    from app.training_pipeline.repository import ConcurrentModification
    try:
        disp, res = await run_once(repo, event_id=msg.eventId, message_type=expected.value,
                                   body_sha256=body_sha256(raw), work=lambda: handle(repo, msg))
    except RepositoryUnavailable:
        return JSONResponse(status_code=503, content={"success": False, "errorCode": "TRAINING_REPOSITORY_UNAVAILABLE"})
    except ConcurrentModification:
        # 409 를 주면 EC2 가 SENT 로 끝내 철회/삭제가 일부만 적용된 채 멈춘다 → 재시도 가능한 503.
        return JSONResponse(status_code=503, headers={"Retry-After": "2"},
                            content={"success": False, "errorCode": "CONCURRENT_MODIFICATION_RETRY"})
    audit_event(f"training.control.{expected.value.lower()}", actor="service:spring", role="service",
                request_id=x_request_id, outcome=f"{disp}:{res.status}",
                extra={"datasets": len(res.invalidated_datasets), "adapters": len(res.retirement_required_adapters)})
    return _lineage_json(_disposition_status(disp, res), res, replay=disp == "REPLAY")


async def _resolve_candidate_id(repo, candidate_id, content_hash):
    if candidate_id:
        return candidate_id
    rec = await repo.find_by_content_hash(content_hash) if content_hash else None
    return rec.candidate_id if rec else None


@router.post("/feedback", summary="사용자 피드백 반영(서명된 training-control.v1, 부정 → 철회 + manifest 무효화)")
async def feedback(request: Request,
                   x_sig: str | None = Header(default=None, alias="X-AI-Contract-Signature"),
                   x_ts: str | None = Header(default=None, alias="X-AI-Contract-Timestamp"),
                   x_request_id: str | None = Header(default=None, alias="X-Request-Id")):
    REVOCATION_RATE.check("feedback")
    from app.training_pipeline.candidate_service import ServiceResult, record_feedback
    from app.training_pipeline.control import MessageType

    async def handle(repo, msg):
        rec = await (repo.find_by_event_id(msg.candidateEventId) if msg.candidateEventId
                     else repo.find_by_content_hash(msg.contentHash))
        if rec is None:
            return ServiceResult(status="NOT_FOUND")
        # 피드백 주체(가명 키)와 후보 소유자가 다르면 '없음'으로 처리(타인 후보 철회 차단)
        return await record_feedback(repo, rec.candidate_id, msg.score, actor=_service_actor(x_request_id),
                                     reason_code=msg.reasonCode, expected_user_key=msg.pseudonymousUserKey)
    return await _control(request, MessageType.FEEDBACK, x_sig, x_ts, x_request_id, handle)


@router.post("/correction", response_model=LineageResponse, summary="사용자 수정 답변 등록(검수 대기)")
async def correction(req: CorrectionRequest, x_request_id: str | None = Header(default=None, alias="X-Request-Id")):
    SERVICE_RATE.check("correction")
    if not _collection_enabled():
        return JSONResponse(status_code=503, content={"success": False, "errorCode": "COLLECTION_DISABLED"})
    from app.training_pipeline.candidate_service import submit_correction
    res = await submit_correction(_repo(), req.candidateId, req.correctedAnswer, actor=_service_actor(x_request_id))
    return LineageResponse(status=res.status, candidate_uuid=req.candidateId, state=res.state, reasons=res.reasons,
                           invalidated_datasets=res.invalidated_datasets)


@router.post("/consent-withdrawal", summary="학습 동의 철회(서명된 training-control.v1) — tombstone + 철회 시각 이전 후보 REVOKED")
async def consent_withdrawal(request: Request,
                             x_sig: str | None = Header(default=None, alias="X-AI-Contract-Signature"),
                             x_ts: str | None = Header(default=None, alias="X-AI-Contract-Timestamp"),
                             x_request_id: str | None = Header(default=None, alias="X-Request-Id")):
    REVOCATION_RATE.check("consent")
    from app.training_pipeline.candidate_service import withdraw_consent
    from app.training_pipeline.control import MessageType

    async def handle(repo, msg):
        return await withdraw_consent(repo, msg.pseudonymousUserKey, actor=_service_actor(x_request_id),
                                      withdrawn_at=msg.issuedAt, event_id=msg.eventId)
    return await _control(request, MessageType.CONSENT_WITHDRAWAL, x_sig, x_ts, x_request_id, handle)


@router.post("/deletion", summary="자료 삭제 반영(서명된 training-control.v1) — tombstone + 내용 파기 + lineage 무효화")
async def deletion(request: Request,
                   x_sig: str | None = Header(default=None, alias="X-AI-Contract-Signature"),
                   x_ts: str | None = Header(default=None, alias="X-AI-Contract-Timestamp"),
                   x_request_id: str | None = Header(default=None, alias="X-Request-Id")):
    REVOCATION_RATE.check("deletion")
    from app.training_pipeline.candidate_service import delete_by_tracking_id
    from app.training_pipeline.control import MessageType

    async def handle(repo, msg):
        return await delete_by_tracking_id(repo, msg.deletionTrackingId, actor=_service_actor(x_request_id),
                                           deleted_at=msg.issuedAt, event_id=msg.eventId)
    return await _control(request, MessageType.DELETION, x_sig, x_ts, x_request_id, handle)


async def _review(request: ReviewCandidateRequest, principal: AdminPrincipal, decision: str) -> ReviewCandidateResponse:
    require_role(principal, "training_reviewer", "training_admin")
    ADMIN_RATE.check(f"review:{principal.role}")
    from app.training_pipeline.candidate_service import review
    _require_audit(f"training.review.{decision.lower()}.requested", principal, [request.candidate_uuid])
    res = await review(_repo(), request.candidate_uuid, decision=decision, actor=_actor(principal), use=request.use,
                       reviewer_answer=request.reviewerAnswer, method=request.method,
                       gold_reference=request.goldReference)
    audit_event(f"training.review.{decision.lower()}", actor=principal.actor_id, role=principal.role,
                request_id=principal.request_id, outcome=res.status, target_ids=[request.candidate_uuid],
                extra={"state": res.state, "reasonCodes": res.reasons})
    if res.status == "NOT_FOUND":
        raise HTTPException(status_code=404, detail={"errorCode": "CANDIDATE_NOT_FOUND"})
    return ReviewCandidateResponse(candidate_uuid=request.candidate_uuid, status=res.status, state=res.state,
                                   reasons=res.reasons, invalidated_datasets=res.invalidated_datasets)


@router.post("/approve", response_model=ReviewCandidateResponse,
             summary="검수자 확인(VERIFY) — 자격 게이트 전부 충족 시에만 TRAIN_ELIGIBLE")
async def approve_candidate(request: ReviewCandidateRequest,
                            principal: AdminPrincipal = Depends(verify_training_admin)):
    return await _review(request, principal, "VERIFY")


@router.post("/reject", response_model=ReviewCandidateResponse, summary="검수자 거절")
async def reject_candidate(request: ReviewCandidateRequest,
                           principal: AdminPrincipal = Depends(verify_training_admin)):
    return await _review(request, principal, "REJECT")
