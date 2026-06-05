"""
학습 파이프라인 관련 API.

GET  /api/ai/training/status           — 파인튜닝 상태 + DB 기반 실시간 집계
POST /api/ai/training/readiness-check  — QLoRA 학습 준비 상태 상세 점검
POST /api/ai/training/validate-candidates — 후보 데이터 검증 (샘플 기반)
POST /api/ai/training/export-jsonl     — 검증 통과 데이터 JSONL 내보내기

절대 "파인튜닝 완료"라고 반환하지 않는다.
QLoRA 학습 실행 API는 이 파일에 포함하지 않는다 (관리자 CLI로만 실행).
"""
import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from app.core.security import verify_internal_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["Training Pipeline"])

_STATUS_FILE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "training_status.json")
)

# ── 스키마 ─────────────────────────────────────────────────────────────────────

class ExportJsonlRequest(BaseModel):
    output_filename: Optional[str] = Field(None, description="저장할 파일명 (없으면 자동 생성)")
    min_db_score: int = Field(70, ge=0, le=100, description="DB에서 읽을 최소 quality_score")
    min_overall_quality_score: float = Field(0.80, ge=0.0, le=1.0)
    min_knowledge_level_score: float = Field(0.75, ge=0.0, le=1.0)
    min_personality_score: float = Field(0.75, ge=0.0, le=1.0)
    dry_run: bool = Field(False, description="True이면 파일 저장 없이 통계만 반환")


class ValidateCandidatesRequest(BaseModel):
    sample_size: int = Field(100, ge=10, le=500, description="검증할 샘플 수")
    min_db_score: int = Field(70, ge=0, le=100)


# ── 엔드포인트 ─────────────────────────────────────────────────────────────────

@router.get(
    "/training/status",
    summary="파인튜닝 상태 조회 (DB 기반 실시간 집계 포함)",
)
async def get_training_status():
    """
    파인튜닝 상태 + DB에서 실시간으로 집계한 학습 후보 현황을 반환한다.
    DB 연결 실패 시에도 기본 상태 파일 기반으로 응답한다.
    절대 "trained"를 과장하지 않는다.
    """
    # 기본 상태 파일 로드
    base_status = _load_status_file()

    # DB 실시간 집계 (실패해도 서버를 죽이지 않음)
    db_info = {}
    try:
        from app.training.db_training_data_collector import count_candidates, fetch_recent_export_info
        counts = await count_candidates()
        export_info = await fetch_recent_export_info()
        db_info = {
            "totalCandidates": counts.get("total", 0),
            "autoApproved": counts.get("auto_approved", 0),
            "holdout": counts.get("holdout", 0),
            "qualified": counts.get("qualified", 0),
            "rejected": counts.get("auto_rejected", 0),
            "duplicate": counts.get("duplicate", 0),
            "unsafe": counts.get("unsafe", 0),
            "lastExportedFile": export_info.get("last_exported_file"),
            "lastExportCount": export_info.get("last_export_count", 0),
        }
        # 데이터 부족 여부 업데이트
        qualified = counts.get("qualified", 0)
        min_required = base_status.get("readiness_check", {}).get("minimum_samples_required", 300)
        db_info["trainingDataSufficient"] = qualified >= min_required
        db_info["samplesNeeded"] = max(0, min_required - qualified)
    except Exception as e:
        logger.debug("DB 집계 실패 (기본 응답 사용): %s", e)
        db_info = {"error": "DB 연결 불가 — 실시간 집계 불가"}

    return {**base_status, "liveStats": db_info}


@router.post(
    "/training/readiness-check",
    summary="QLoRA 학습 준비 상태 상세 점검",
    dependencies=[Depends(verify_internal_token)],
)
async def readiness_check():
    """
    QLoRA 학습을 실행할 수 있는 상태인지 상세 점검한다.
    status: not_ready | ready | blocked | trained
    학습 실행은 이 API가 담당하지 않는다 (CLI 또는 관리자 승인 필요).
    """
    try:
        from app.training.qlora_readiness_checker import check_readiness, report_to_dict
        report = await check_readiness()
        return report_to_dict(report)
    except Exception as e:
        logger.error("readiness check 실패: %s", e)
        return {
            "status": "not_ready",
            "message": f"준비 상태 점검 중 오류: {type(e).__name__}",
            "error": str(e),
        }


@router.post(
    "/training/validate-candidates",
    summary="학습 후보 샘플 검증 (통과율, 실패 이유 분석)",
    dependencies=[Depends(verify_internal_token)],
)
async def validate_candidates(request: ValidateCandidatesRequest):
    """
    DB에서 학습 후보 샘플을 읽어 다중 기준으로 검증하고 통과율/실패 이유를 반환한다.
    실제 JSONL export는 하지 않는다.
    """
    try:
        from app.training.db_training_data_collector import fetch_candidates
        from app.training.training_data_validator import validate_candidates_batch, ValidationCriteria

        rows = await fetch_candidates(
            statuses=["auto_approved", "holdout"],
            min_score=request.min_db_score,
            limit=request.sample_size,
        )

        if not rows:
            return {
                "totalSampled": 0,
                "passedCount": 0,
                "failedCount": 0,
                "passRate": 0.0,
                "avgQualityScore": 0.0,
                "failureSummary": {},
                "message": "검증할 후보 데이터가 없습니다.",
            }

        results = validate_candidates_batch(rows, ValidationCriteria())
        passed = [r for r in results if r.passed]
        failed = [r for r in results if not r.passed]

        # 실패 이유 집계
        failure_summary: dict[str, int] = {}
        for r in failed:
            for reason in r.failure_reasons:
                failure_summary[reason] = failure_summary.get(reason, 0) + 1

        avg_score = (
            sum(r.overall_quality_score for r in results) / len(results)
            if results else 0.0
        )

        return {
            "totalSampled": len(rows),
            "passedCount": len(passed),
            "failedCount": len(failed),
            "passRate": round(len(passed) / len(rows), 4) if rows else 0.0,
            "avgQualityScore": round(avg_score, 4),
            "failureSummary": failure_summary,
            "message": (
                f"{len(rows)}건 샘플 검증 완료. "
                f"통과율: {len(passed)/len(rows)*100:.1f}%"
            ),
        }
    except Exception as e:
        logger.error("validate-candidates 실패: %s", e)
        raise HTTPException(status_code=500, detail=f"검증 중 오류: {e}")


@router.post(
    "/training/export-jsonl",
    summary="검증 통과 학습 데이터 JSONL 내보내기",
    dependencies=[Depends(verify_internal_token)],
)
async def export_training_jsonl(request: ExportJsonlRequest):
    """
    DB 후보 → 다중 기준 검증 → 중복 제거 → JSONL 저장.
    dry_run=True 이면 파일 저장 없이 통계만 반환한다.
    검증 통과 데이터가 없으면 export하지 않는다.

    QLoRA 학습 실행은 이 API가 담당하지 않는다.
    export된 JSONL 파일을 CLI 스크립트로 학습에 사용한다.
    """
    try:
        from app.training.training_data_validator import ValidationCriteria
        from app.training.jsonl_exporter import export_validated_jsonl

        criteria = ValidationCriteria(
            min_overall_quality_score=request.min_overall_quality_score,
            min_knowledge_level_score=request.min_knowledge_level_score,
            min_personality_score=request.min_personality_score,
        )

        result = await export_validated_jsonl(
            output_filename=request.output_filename,
            criteria=criteria,
            min_db_score=request.min_db_score,
            dry_run=request.dry_run,
        )
        return result
    except Exception as e:
        logger.error("export-jsonl 실패: %s", e)
        raise HTTPException(status_code=500, detail=f"JSONL export 중 오류: {e}")


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────────

def _load_status_file() -> dict:
    """training_status.json을 읽어 반환한다. 실패 시 기본값 반환."""
    try:
        if os.path.exists(_STATUS_FILE):
            with open(_STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("training_status.json 읽기 실패: %s", e)
    return {
        "finetuning_status": "not_ready",
        "description": "학습 파이프라인은 준비되어 있으나 데이터 부족으로 본학습 미진행.",
        "current_status": "not_ready",
        "base_model": "Qwen2.5-14B",
        "training_method": "QLoRA",
        "readiness_check": {
            "pipeline_scripts": True,
            "training_data_sufficient": False,
            "minimum_samples_required": 300,
        },
        "note": "현재 서비스는 RAG(pgvector) 중심으로 운영됩니다.",
    }
