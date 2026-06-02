"""
GET /api/ai/validation/{job_id} — GPT 검증 작업 상태 조회.
Redis 우선 조회 → ai-db fallback.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Path

from app.core.security import verify_internal_token
from app.schemas.validation_schema import ValidationStatusResponse

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/ai",
    tags=["Validation"],
    dependencies=[Depends(verify_internal_token)],
)


@router.get(
    "/validation/{job_id}",
    response_model=ValidationStatusResponse,
    summary="GPT 검증 작업 상태 폴링",
    description="Redis 우선 조회 → ai-db fallback. job_id는 /api/ai/chat 응답에서 반환된다.",
)
async def get_validation_status(
    job_id: str = Path(..., description="검증 작업 UUID"),
) -> ValidationStatusResponse:
    # ── Redis 우선 조회 ───────────────────────────────────────────────
    from app.db.redis_client import get_validation_job
    job = await get_validation_job(job_id)

    if job is not None:
        return ValidationStatusResponse(
            job_id=job_id,
            status=job.get("status", "unknown"),
            result=job.get("result"),
            corrected_answer=job.get("corrected_answer"),
        )

    # ── ai-db fallback ────────────────────────────────────────────────
    try:
        from app.repositories.validation_job_repository import get_job_by_uuid
        db_job = await get_job_by_uuid(job_id)
        if db_job is not None:
            return ValidationStatusResponse(
                job_id=job_id,
                status=db_job.get("status", "unknown"),
                result={
                    "is_valid":          db_job.get("is_valid"),
                    "score":             float(db_job["score"]) if db_job.get("score") else None,
                    "issues":            db_job.get("issues", []),
                    "correction_needed": db_job.get("correction_needed"),
                    "suggestion":        db_job.get("suggestion"),
                },
                corrected_answer=db_job.get("corrected_answer"),
            )
    except Exception as e:
        logger.warning("ai-db validation_job 조회 실패: %s", e)

    raise HTTPException(status_code=404, detail=f"job_id={job_id}를 찾을 수 없습니다.")
