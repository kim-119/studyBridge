"""
학습 후보 관리 API.
GET  /api/training-candidates/stats       — 상태별 통계
POST /api/training-candidates/export-jsonl — auto_approved 데이터 JSONL 내보내기
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import verify_internal_token
from app.schemas.training_candidate_schema import (
    TrainingCandidateStatsResponse,
    ExportJsonlRequest,
    ExportJsonlResponse,
    CollectCandidateRequest,
    CollectCandidateResponse,
    ReviewCandidateRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/training-candidates",
    tags=["Training Candidates"],
    dependencies=[Depends(verify_internal_token)],
)


@router.get(
    "/stats",
    response_model=TrainingCandidateStatsResponse,
    summary="학습 후보 상태별 통계",
)
async def get_stats() -> TrainingCandidateStatsResponse:
    try:
        from app.repositories.training_candidate_repository import get_stats
        stats = await get_stats()
        return TrainingCandidateStatsResponse(**stats)
    except Exception as e:
        logger.warning("통계 조회 실패 (DB 연결 확인): %s", e)
        # DB 연결 실패 시 0으로 반환 (서버 죽이지 않음)
        return TrainingCandidateStatsResponse(
            auto_collected=0, auto_approved=0, auto_rejected=0,
            holdout=0, duplicate=0, unsafe=0,
            error=str(e),
        )


@router.post(
    "/export-jsonl",
    response_model=ExportJsonlResponse,
    summary="auto_approved 데이터 JSONL 내보내기",
    description="quality_status=auto_approved인 샘플만 messages 구조로 JSONL 파일에 저장한다.",
)
async def export_jsonl(request: ExportJsonlRequest) -> ExportJsonlResponse:
    from datetime import datetime
    try:
        from app.services.jsonl_export_service import export_approved_candidates
        result = await export_approved_candidates(
            output_path=request.output_path,
            min_score=request.min_score,
        )
        # 서비스 반환값을 Spring 계약 스키마로 변환
        version_date = datetime.now().strftime("%Y%m%d")
        return ExportJsonlResponse(
            dataset_version=f"train_v{version_date}_001",
            sample_count=result.get("exported_count", 0),
            output_file_path=result.get("output_path", request.output_path),
            status=result.get("status", "completed"),
            exported_count=result.get("exported_count", 0),
        )
    except Exception as e:
        logger.error("JSONL 내보내기 실패: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/collect",
    response_model=CollectCandidateResponse,
    summary="AI 답변을 학습 후보로 수집 (즉시 학습 아님 · 검수 게이트)",
    description=(
        "Spring/Frontend가 AI 답변 생성 후 호출한다. 답변을 즉시 학습하지 않고 "
        "PII/중복/품질/사용자 피드백 게이트를 거쳐 ai.training_candidate에 후보로만 저장한다. "
        "사용자가 싫어요/오류 신고(userFeedbackScore<0)한 답변은 auto_approved되지 않는다."
    ),
)
async def collect_candidate_endpoint(request: CollectCandidateRequest) -> CollectCandidateResponse:
    try:
        from app.services.training_candidate_manager import collect_candidate
        result = await collect_candidate(
            question=request.question,
            answer=request.answer,
            system_prompt=request.systemPrompt,
            knowledge_level=request.knowledgeLevel,
            personality=request.personality,
            user_feedback_score=request.userFeedbackScore,
            user_feedback_text=request.userFeedbackText,
            rag_grounding_score=request.ragGroundingScore,
        )
        return CollectCandidateResponse(
            candidate_uuid=result.get("candidate_uuid"),
            quality_status=result.get("quality_status", "unknown"),
            quality_score=int(result.get("quality_score", 0) or 0),
            stored=bool(result.get("stored", False)),
            auto_approved=bool(result.get("auto_approved", result.get("quality_status") == "auto_approved")),
            safety_status=result.get("safety_status", "safe"),
            duplicate_status=result.get("duplicate_status", "unique"),
            reason=result.get("reason"),
        )
    except Exception as e:
        logger.warning("학습 후보 수집 실패 (서버는 유지): %s", e)
        # 수집 실패가 채팅 흐름을 막지 않도록 200으로 상태만 반환
        return CollectCandidateResponse(
            quality_status="error", stored=False, reason=str(e),
        )


@router.post(
    "/approve",
    summary="학습 후보 수동 승인 (검수자)",
    description="holdout 등 후보를 검수자가 manual_approved로 승격한다.",
)
async def approve_candidate(request: ReviewCandidateRequest):
    try:
        from app.repositories.training_candidate_repository import update_status
        ok = await update_status(request.candidate_uuid, "manual_approved")
        if not ok:
            raise HTTPException(status_code=404, detail="해당 candidate_uuid를 찾을 수 없습니다.")
        return {"candidate_uuid": request.candidate_uuid, "quality_status": "manual_approved", "updated": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("후보 승인 실패: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/reject",
    summary="학습 후보 수동 거절 (검수자)",
    description="부적합 후보를 검수자가 rejected로 강등한다(학습 데이터에서 제외).",
)
async def reject_candidate(request: ReviewCandidateRequest):
    try:
        from app.repositories.training_candidate_repository import update_status
        ok = await update_status(request.candidate_uuid, "rejected")
        if not ok:
            raise HTTPException(status_code=404, detail="해당 candidate_uuid를 찾을 수 없습니다.")
        return {"candidate_uuid": request.candidate_uuid, "quality_status": "rejected", "updated": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("후보 거절 실패: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
