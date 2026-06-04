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
