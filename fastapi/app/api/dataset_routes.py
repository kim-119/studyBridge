"""
Dataset version 관리 API.

GET  /api/ai/training/datasets                           — 전체 active dataset 목록
GET  /api/ai/training/datasets/{dataset_version}        — 특정 version manifest
POST /api/ai/training/datasets/export                   — 새 versioned dataset 생성
POST /api/ai/training/datasets/{dataset_version}/archive — version archive 처리
POST /api/ai/training/datasets/{dataset_version}/block  — version blocked 처리
"""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security import verify_internal_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai/training", tags=["Dataset Management"])


class ExportDatasetRequest(BaseModel):
    note: str = Field("", description="버전 생성 메모")
    min_db_score: int = Field(70, ge=0, le=100)
    max_train_samples: int = Field(5000, ge=10)
    max_valid_samples: int = Field(500, ge=5)
    max_test_samples: int = Field(500, ge=5)


class BlockDatasetRequest(BaseModel):
    reason: str = Field(..., description="차단 이유 (필수)")


# ── 엔드포인트 ─────────────────────────────────────────────────────────────────

@router.get(
    "/datasets",
    summary="active dataset version 목록 조회",
)
async def list_datasets():
    """
    training_exports/active/ 에 있는 dataset version 목록과 각 manifest를 반환한다.
    """
    try:
        from app.training.dataset_version_manager import list_dataset_versions
        versions = list_dataset_versions()
        return {
            "activeVersions": versions,
            "count": len(versions),
        }
    except Exception as e:
        logger.error("dataset 목록 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/datasets/{dataset_version}",
    summary="특정 dataset version manifest 조회",
)
async def get_dataset(dataset_version: str):
    """dataset_version(예: sft_v001)에 해당하는 manifest를 반환한다."""
    try:
        from app.training.dataset_version_manager import get_dataset_version
        manifest = get_dataset_version(dataset_version)
        if manifest is None:
            raise HTTPException(
                status_code=404,
                detail=f"dataset version '{dataset_version}'을 찾을 수 없습니다.",
            )
        return manifest
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/datasets/export",
    summary="새 versioned dataset 생성 (DB → 검증 → split → JSONL)",
    dependencies=[Depends(verify_internal_token)],
)
async def export_dataset_version(request: ExportDatasetRequest):
    """
    DB 후보 데이터를 수집·검증·중복제거·분리하여 새 dataset version을 생성한다.

    하나의 JSONL 파일에 무한 append하지 않는다.
    각 학습 시점마다 독립적인 dataset version(sft_v001, sft_v002, ...)을 생성한다.
    각 version은 train/valid/test.jsonl + dataset_manifest.json을 포함한다.
    """
    try:
        from app.training.dataset_version_manager import (
            create_dataset_version,
            DatasetVersionConfig,
        )
        import dataclasses

        config = DatasetVersionConfig(
            min_db_score=request.min_db_score,
            max_train_samples=request.max_train_samples,
            max_valid_samples=request.max_valid_samples,
            max_test_samples=request.max_test_samples,
        )
        result = await create_dataset_version(config)
        resp = dataclasses.asdict(result)
        resp["note"] = request.note
        return resp
    except Exception as e:
        logger.error("dataset export 실패: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/datasets/{dataset_version}/archive",
    summary="dataset version archive 처리",
    dependencies=[Depends(verify_internal_token)],
)
async def archive_dataset(dataset_version: str):
    """
    지정한 dataset version을 archive/ 로 압축 이동한다.
    실제 학습에 사용된 version (used_for_training=true)은 보호된다.
    """
    try:
        from app.training.dataset_version_manager import _DEFAULT_EXPORT_ROOT
        from app.training.dataset_cleanup_policy import _archive_version, read_manifest

        export_root = Path(_DEFAULT_EXPORT_ROOT)
        version_dir = export_root / "active" / dataset_version
        archive_dir = export_root / "archive"

        if not version_dir.exists():
            raise HTTPException(
                status_code=404,
                detail=f"'{dataset_version}'를 active에서 찾을 수 없습니다.",
            )

        # 학습에 사용된 version은 보호
        m = read_manifest(version_dir)
        if m and m.get("used_for_training"):
            raise HTTPException(
                status_code=409,
                detail=f"'{dataset_version}'는 학습에 사용된 version으로 보호됩니다.",
            )

        archive_dir.mkdir(parents=True, exist_ok=True)
        _archive_version(version_dir, archive_dir)
        return {"message": f"'{dataset_version}' archive 완료.", "status": "archived"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/datasets/{dataset_version}/block",
    summary="dataset version blocked 처리 (품질/안전 문제)",
    dependencies=[Depends(verify_internal_token)],
)
async def block_dataset(dataset_version: str, request: BlockDatasetRequest):
    """
    문제가 있는 dataset version을 blocked/ 로 격리한다.
    blocked version은 자동 재학습 파이프라인에서 사용되지 않는다.
    """
    try:
        from app.training.dataset_version_manager import _DEFAULT_EXPORT_ROOT
        from app.training.dataset_cleanup_policy import block_dataset_version

        export_root = Path(_DEFAULT_EXPORT_ROOT)
        version_dir = export_root / "active" / dataset_version
        blocked_dir = export_root / "blocked"

        if not version_dir.exists():
            raise HTTPException(
                status_code=404,
                detail=f"'{dataset_version}'를 active에서 찾을 수 없습니다.",
            )

        block_dataset_version(version_dir, blocked_dir, request.reason)
        return {
            "message": f"'{dataset_version}' blocked 처리 완료.",
            "status": "blocked",
            "reason": request.reason,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
