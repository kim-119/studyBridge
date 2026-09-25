"""
자동 재학습 파이프라인 API.

GET  /api/ai/training/auto-retrain/status   — 스케줄러 + 파이프라인 상태
POST /api/ai/training/auto-retrain/run-dry  — dry-run (dataset 생성까지만)
POST /api/ai/training/auto-retrain/enable   — autoRetrainEnabled=true 설정
POST /api/ai/training/auto-retrain/disable  — autoRetrainEnabled=false 설정

중요:
  - 실제 QLoRA 학습은 AUTO_TRAIN_ENABLED=true + autoTrain=true일 때만 실행된다.
  - production 모델 자동 배포는 autoDeploy=true일 때만 실행된다.
  - 기본값은 autoTrain=false, autoDeploy=false이다.
"""
import dataclasses
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security import verify_internal_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai/training", tags=["Auto Retrain"])


class RunDryRequest(BaseModel):
    note: str = Field("", description="실행 메모 (선택)")


# ── 엔드포인트 ─────────────────────────────────────────────────────────────────

@router.get(
    "/auto-retrain/status",
    summary="자동 재학습 스케줄러 + 파이프라인 현황 조회",
)
async def get_auto_retrain_status():
    """
    자동 재학습 스케줄러 상태와 마지막 실행 결과를 반환한다.

    autoRetrainEnabled=false이면 학습이 자동 실행되지 않는다.
    autoTrain=false이면 dataset 생성까지만 수행한다.
    autoDeploy=false이면 production에 자동 반영되지 않는다.
    """
    try:
        from app.training.auto_retrain_scheduler import get_scheduler
        scheduler = get_scheduler()
        status = scheduler.get_status()
        return dataclasses.asdict(status)
    except Exception as e:
        logger.error("auto-retrain status 조회 실패: %s", e)
        return {
            "enabled": False,
            "has_apscheduler": False,
            "running": False,
            "message": f"상태 조회 오류: {e}",
        }


@router.post(
    "/auto-retrain/run-dry",
    summary="자동 재학습 dry-run (실제 학습/배포 없음)",
    dependencies=[Depends(verify_internal_token)],
)
async def run_auto_retrain_dry(request: RunDryRequest, background_tasks: BackgroundTasks):
    """
    자동 재학습 파이프라인을 dry-run으로 실행한다.

    dry-run: DB 수집 → 검증 → dataset version 생성 → readiness check까지만 수행.
    실제 QLoRA 학습과 배포는 실행하지 않는다.

    결과가 즉시 반환되지 않을 수 있으므로 background 실행 후 status API로 확인하세요.
    """
    try:
        from app.training.auto_retrain_scheduler import get_scheduler
        scheduler = get_scheduler()
        result = await scheduler.run_once(dry_run=True)
        return {
            "message": "dry-run 실행 완료",
            "note": request.note,
            "result": result,
        }
    except Exception as e:
        logger.error("run-dry 실패: %s", e)
        raise HTTPException(status_code=500, detail=f"dry-run 실패: {e}")


@router.post(
    "/auto-retrain/enable",
    summary="자동 재학습 활성화 (autoRetrainEnabled=true)",
    dependencies=[Depends(verify_internal_token)],
)
async def enable_auto_retrain():
    """
    auto_retrain_config.json에서 autoRetrainEnabled를 true로 변경한다.

    주의: autoTrain / autoDeploy는 별도로 설정해야 한다.
    이 API는 스케줄러만 활성화한다.
    """
    try:
        from app.training.auto_retrain_scheduler import get_scheduler
        scheduler = get_scheduler()
        success = scheduler.enable()
        if success:
            return {"message": "autoRetrainEnabled=true 설정 완료.", "status": "enabled"}
        raise HTTPException(status_code=500, detail="설정 파일 업데이트 실패")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/auto-retrain/disable",
    summary="자동 재학습 비활성화 (autoRetrainEnabled=false)",
    dependencies=[Depends(verify_internal_token)],
)
async def disable_auto_retrain():
    """autoRetrainEnabled를 false로 변경한다."""
    try:
        from app.training.auto_retrain_scheduler import get_scheduler
        scheduler = get_scheduler()
        success = scheduler.disable()
        if success:
            return {"message": "autoRetrainEnabled=false 설정 완료.", "status": "disabled"}
        raise HTTPException(status_code=500, detail="설정 파일 업데이트 실패")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
