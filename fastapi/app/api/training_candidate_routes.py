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

from app.core.audit import audit_event
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
router = APIRouter(
    prefix="/api/training-candidates",
    tags=["Training Candidates"],
    dependencies=[Depends(verify_internal_token)],
    route_class=limited_route_class(128 * 1024),
)

SERVICE_RATE = RateLimiter(capacity=120, refill_per_sec=10)
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


def _collection_enabled() -> bool:
    from app.training_pipeline.collection_hook import collection_enabled
    return collection_enabled()


@router.get("/stats", response_model=TrainingPipelineStatsResponse, summary="학습 후보 상태별 통계(관리자)")
async def get_stats(principal: AdminPrincipal = Depends(verify_training_admin)) -> TrainingPipelineStatsResponse:
    ADMIN_RATE.check(f"stats:{principal.actor_id}")
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
    ADMIN_RATE.check(f"export:{principal.actor_id}")
    if request.output_path not in (None, "", LEGACY_DEFAULT_OUTPUT_PATH):
        audit_event("training.export", actor=principal.actor_id, role=principal.role,
                    request_id=principal.request_id, outcome="DENIED", extra={"errorCode": "OUTPUT_PATH_NOT_ALLOWED"})
        raise HTTPException(status_code=400, detail={"errorCode": "OUTPUT_PATH_NOT_ALLOWED"})
    from app.training_pipeline.export_service import export_dataset
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


@router.post("/collect-v1", summary="training-sample.v1 수집(서명된 내부 계약, 기본 OFF)")
async def collect_v1(request: Request,
                     x_sig: str | None = Header(default=None, alias="X-AI-Contract-Signature"),
                     x_ts: str | None = Header(default=None, alias="X-AI-Contract-Timestamp")):
    SERVICE_RATE.check("collect-v1")
    if not _collection_enabled():
        return JSONResponse(status_code=503, content={"success": False, "errorCode": "COLLECTION_DISABLED"})
    from app.contracts.signing import SignatureError, verify_body
    from app.contracts.training_sample_v1 import TrainingSampleV1
    from app.training_pipeline.candidate_service import collect_sample
    raw = await request.body()
    try:
        verify_body(raw, x_sig, x_ts)
    except SignatureError as e:
        return JSONResponse(status_code=401 if e.code != "SIGNING_KEY_NOT_CONFIGURED" else 503,
                            content={"success": False, "errorCode": e.code})
    try:
        sample = TrainingSampleV1.model_validate_json(raw)
    except ValidationError as e:
        return JSONResponse(status_code=422, content={"success": False, "errorCode": "CONTRACT_VALIDATION_FAILED",
                                                      "errors": [{"loc": list(x.get("loc", ())), "type": x.get("type")}
                                                                 for x in e.errors()[:20]]})
    from app.training_pipeline.repository import RepositoryUnavailable
    try:
        res = await collect_sample(_repo(), sample)
    except RepositoryUnavailable:
        return JSONResponse(status_code=503, content={"success": False, "errorCode": "TRAINING_REPOSITORY_UNAVAILABLE"})
    code = 503 if res.status == "DEFERRED" else 200
    return JSONResponse(status_code=code, content={"success": res.status not in ("DEFERRED",), "status": res.status,
                                                   "candidateId": res.candidate_id, "state": res.state,
                                                   "reasons": res.reasons,
                                                   "invalidatedDatasets": res.invalidated_datasets})


async def _resolve_candidate_id(repo, candidate_id, content_hash):
    if candidate_id:
        return candidate_id
    rec = await repo.find_by_content_hash(content_hash) if content_hash else None
    return rec.candidate_id if rec else None


@router.post("/feedback", response_model=LineageResponse, summary="사용자 피드백 반영(부정 → 철회 + manifest 무효화)")
async def feedback(req: FeedbackRequest, x_request_id: str | None = Header(default=None, alias="X-Request-Id")):
    SERVICE_RATE.check("feedback")
    from app.training_pipeline.candidate_service import record_feedback
    repo = _repo()
    cid = await _resolve_candidate_id(repo, req.candidateId, req.contentHash)
    if not cid:
        return LineageResponse(status="NOT_FOUND")
    res = await record_feedback(repo, cid, req.score, actor=_service_actor(x_request_id), reason_code=req.reasonCode)
    return LineageResponse(status=res.status, candidate_uuid=cid, state=res.state, reasons=res.reasons,
                           invalidated_datasets=res.invalidated_datasets,
                           retirement_required_adapters=res.retirement_required_adapters)


@router.post("/correction", response_model=LineageResponse, summary="사용자 수정 답변 등록(검수 대기)")
async def correction(req: CorrectionRequest, x_request_id: str | None = Header(default=None, alias="X-Request-Id")):
    SERVICE_RATE.check("correction")
    if not _collection_enabled():
        return JSONResponse(status_code=503, content={"success": False, "errorCode": "COLLECTION_DISABLED"})
    from app.training_pipeline.candidate_service import submit_correction
    res = await submit_correction(_repo(), req.candidateId, req.correctedAnswer, actor=_service_actor(x_request_id))
    return LineageResponse(status=res.status, candidate_uuid=req.candidateId, state=res.state, reasons=res.reasons,
                           invalidated_datasets=res.invalidated_datasets)


@router.post("/consent-withdrawal", response_model=LineageResponse, summary="학습 동의 철회(사용자 전체 후보 REVOKED)")
async def consent_withdrawal(req: ConsentWithdrawalRequest,
                             x_request_id: str | None = Header(default=None, alias="X-Request-Id")):
    SERVICE_RATE.check("consent")
    from app.training_pipeline.candidate_service import withdraw_consent
    res = await withdraw_consent(_repo(), req.pseudonymousUserKey, actor=_service_actor(x_request_id))
    audit_event("training.consent_withdrawal", actor="service:spring", role="service", request_id=x_request_id,
                outcome=res.status, extra={"count": len(res.invalidated_datasets)})
    return LineageResponse(status=res.status, invalidated_datasets=res.invalidated_datasets,
                           retirement_required_adapters=res.retirement_required_adapters)


@router.post("/deletion", response_model=LineageResponse, summary="자료 삭제 반영(내용 파기 + lineage 무효화)")
async def deletion(req: DeletionRequest, x_request_id: str | None = Header(default=None, alias="X-Request-Id")):
    SERVICE_RATE.check("deletion")
    from app.training_pipeline.candidate_service import delete_by_tracking_id
    res = await delete_by_tracking_id(_repo(), req.deletionTrackingId, actor=_service_actor(x_request_id))
    audit_event("training.deletion", actor="service:spring", role="service", request_id=x_request_id,
                outcome=res.status, extra={"count": len(res.invalidated_datasets)})
    return LineageResponse(status=res.status, invalidated_datasets=res.invalidated_datasets,
                           retirement_required_adapters=res.retirement_required_adapters)


async def _review(request: ReviewCandidateRequest, principal: AdminPrincipal, decision: str) -> ReviewCandidateResponse:
    require_role(principal, "training_reviewer", "training_admin")
    ADMIN_RATE.check(f"review:{principal.actor_id}")
    from app.training_pipeline.candidate_service import review
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
