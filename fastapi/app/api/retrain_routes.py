"""
QLoRA 재학습 파이프라인 API (관리자 전용).

POST /api/training/retrain/check-readiness — 재학습 준비 상태 점검 + training_status.json 갱신
POST /api/training/retrain/run            — 재학습 실행 (관리자 토큰 필수, 게이트 통과 시에만)

원칙
----
- '실시간 재학습'이 아니다. 후보 수집 → 검수 → export → 학습 → 평가 → 배포의 배치 흐름이다.
- 실제 학습이 끝나지 않았는데 finetuning_status를 'trained'로 표시하지 않는다.
- auto_retrain_config.json의 autoRetrainEnabled가 false면 명시적 force + 관리자 토큰 없이는 실행하지 않는다.
- 관리자 토큰(TRAINING_ADMIN_TOKEN)이 설정/일치할 때만 run을 허용한다(미설정이면 차단).
"""
import json
import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.core.security import verify_internal_token
from app.core.config import TRAINING_ADMIN_TOKEN

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/training", tags=["QLoRA Retrain"])

_BASE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_STATUS_FILE = os.path.join(_BASE_DIR, "training_status.json")
_CONFIG_FILE = os.path.join(_BASE_DIR, "auto_retrain_config.json")


class RetrainRunRequest(BaseModel):
    force: bool = Field(False, description="autoRetrainEnabled=false여도 강제 실행 시도 (관리자 한정)")
    dry_run: bool = Field(True, description="True(기본)면 실제 학습을 실행하지 않고 준비 상태/계획만 반환")


# ── 헬퍼 ───────────────────────────────────────────────────────────────────────

def _load_json(path: str, default: dict) -> dict:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("%s 읽기 실패: %s", path, e)
    return default


def _write_status(patch: dict) -> None:
    """training_status.json을 부분 갱신한다. 'trained'는 실제 학습 결과가 있을 때만 외부에서 설정한다."""
    data = _load_json(_STATUS_FILE, {})
    data.update(patch)
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    try:
        with open(_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("training_status.json 쓰기 실패: %s", e)


async def _refresh_status_from_db() -> dict:
    """DB 실시간 집계 + readiness를 training_status.json에 반영하고, 집계 dict를 반환한다."""
    info: dict = {}
    try:
        from app.training.db_training_data_collector import count_candidates, fetch_recent_export_info
        counts = await count_candidates()
        export_info = await fetch_recent_export_info()
        qualified = counts.get("qualified", 0)
        info = {
            "totalCandidates": counts.get("total", 0),
            "qualified": qualified,
            "autoApproved": counts.get("auto_approved", 0),
            "lastExportedFile": export_info.get("last_exported_file"),
            "lastExportCount": export_info.get("last_export_count", 0),
        }
        base = _load_json(_STATUS_FILE, {})
        min_required = base.get("readiness_check", {}).get("minimum_samples_required", 300)
        rc = dict(base.get("readiness_check", {}))
        rc["current_sample_count"] = qualified
        rc["training_data_sufficient"] = qualified >= min_required
        _write_status({
            "readiness_check": rc,
            "lastExportedFile": info["lastExportedFile"],
            "lastExportCount": info["lastExportCount"],
        })
    except Exception as e:
        logger.debug("DB 집계 실패(상태 파일 갱신 생략): %s", e)
        info = {"error": "DB 연결 불가 — 실시간 집계 불가"}
    return info


def _require_admin(token: Optional[str]) -> None:
    """관리자 토큰 검증. TRAINING_ADMIN_TOKEN 미설정이면 학습 실행 자체를 차단한다."""
    if not TRAINING_ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="학습 실행 API가 비활성화되어 있습니다(TRAINING_ADMIN_TOKEN 미설정).",
        )
    if not token or token != TRAINING_ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 토큰이 올바르지 않습니다. (X-Admin-Token)",
        )


# ── 엔드포인트 ─────────────────────────────────────────────────────────────────

@router.post(
    "/retrain/check-readiness",
    summary="재학습 준비 상태 점검 (+ training_status.json 실시간 갱신)",
    dependencies=[Depends(verify_internal_token)],
)
async def check_readiness():
    """
    QLoRA 재학습을 실행할 수 있는 상태인지 점검하고 training_status.json을 실제 수치로 갱신한다.
    절대 'trained'로 표시하지 않는다.
    """
    live = await _refresh_status_from_db()
    try:
        from app.training.qlora_readiness_checker import check_readiness as _check, report_to_dict
        report = report_to_dict(await _check())
    except Exception as e:
        logger.error("readiness check 실패: %s", e)
        report = {"status": "not_ready", "message": f"점검 오류: {type(e).__name__}", "error": str(e)}
    return {"readiness": report, "liveStats": live}


@router.post(
    "/retrain/run",
    summary="QLoRA 재학습 실행 (관리자 토큰 필수)",
    dependencies=[Depends(verify_internal_token)],
)
async def run_retrain(
    request: RetrainRunRequest,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
):
    """
    재학습 실행. 관리자 토큰 + 준비 게이트 + auto_retrain_config(autoRetrainEnabled/force)를 모두 만족해야 한다.
    이 API는 실제 학습 완료를 보장하지 않으며, 완료 시까지 'trained'로 표시하지 않는다.
    dry_run=True(기본)면 학습을 시작하지 않고 게이트 결과/계획만 반환한다.
    """
    _require_admin(x_admin_token)

    cfg = _load_json(_CONFIG_FILE, {})
    auto_enabled = bool(cfg.get("autoRetrainEnabled", False))
    if not auto_enabled and not request.force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="autoRetrainEnabled=false 입니다. 실행하려면 force=true(관리자)로 명시하세요.",
        )

    # 준비 게이트 점검
    live = await _refresh_status_from_db()
    try:
        from app.training.qlora_readiness_checker import check_readiness as _check, report_to_dict
        report = report_to_dict(await _check())
    except Exception as e:
        report = {"status": "not_ready", "message": str(e)}

    if report.get("status") != "ready":
        # 준비 안 됨 → 학습하지 않고 정직하게 not_ready 반환
        _write_status({"finetuning_status": "not_ready", "current_status": "not_ready"})
        return {
            "started": False,
            "status": "not_ready",
            "reason": report.get("message", "학습 준비 기준 미달"),
            "readiness": report,
            "liveStats": live,
        }

    if request.dry_run:
        return {
            "started": False,
            "status": "ready",
            "dryRun": True,
            "message": "준비 완료. dry_run=false로 호출하면 학습 배치를 시작합니다.",
            "plannedSteps": [
                "export JSONL (validate_sft_dataset.py)",
                "train_lora_adapter.py (QLoRA)",
                "compare_base_vs_finetuned.py",
                "evaluationGate 통과 시 canary deploy, 실패 시 rollback",
            ],
            "readiness": report,
        }

    # 실제 실행: 학습 진행 상태로만 표시하고, 완료(trained)는 학습 스크립트 결과로만 갱신한다.
    _write_status({
        "finetuning_status": "training_in_progress",
        "current_status": "training_in_progress",
        "training_started_at": datetime.now().isoformat(),
    })
    logger.info("[QLoRA] 재학습 실행 요청 수락 (관리자). 실제 학습은 배치/CLI에서 수행됩니다.")
    return {
        "started": True,
        "status": "training_in_progress",
        "message": (
            "재학습이 큐에 등록되었습니다. 실제 학습은 GPU 배치(train_lora_adapter.py)에서 수행되며, "
            "평가 게이트 통과 후에만 배포되고 그때 finetuning_status가 'trained'로 갱신됩니다."
        ),
        "readiness": report,
    }
