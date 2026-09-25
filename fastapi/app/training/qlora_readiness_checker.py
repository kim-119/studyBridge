"""
QLoRA 학습 준비 상태 체커.

DB의 학습 후보 데이터 품질과 수량을 분석하여 학습 실행 가능 여부를 판단한다.

상태 정의:
  not_ready : 검증 통과 데이터가 부족하거나 품질 기준 미달
  ready     : 최소 300개 이상, 품질 기준 통과, 중복률 낮음
  blocked   : 개인정보/보안정보/위험 내용 감지
  trained   : 실제 학습이 완료되고 모델 파일이 저장된 경우만 (현재 해당 없음)

중요:
  QLoRA 학습 실행은 이 모듈이 담당하지 않는다.
  이 모듈은 "실행해도 되는가"를 판단만 한다.
  실제 실행은 CLI 스크립트 또는 관리자 승인 후 수동으로 한다.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 학습 실행 최소 기준
_MIN_SAMPLES_REQUIRED = 300
_MIN_AVG_QUALITY_SCORE = 0.78
_MAX_DUPLICATION_RATE = 0.25
_SAMPLE_CHECK_SIZE = 50  # 안전성 검사 샘플 수

# 실제 학습 완료 모델 경로 (파일이 있어야 trained)
_TRAINED_MODEL_PATH = os.environ.get(
    "FINETUNED_ADAPTER_PATH",
    "./adapters/qwen25_14b_studybridge"
)


@dataclass
class ReadinessReport:
    status: str                    # "not_ready" | "ready" | "blocked" | "trained"
    total_candidates: int = 0
    validated_samples: int = 0     # 검증 통과 수
    required_samples: int = _MIN_SAMPLES_REQUIRED
    average_quality_score: float = 0.0
    duplication_rate: float = 0.0
    safety_blocked: bool = False
    safety_blocked_reason: str = ""
    last_exported_file: str | None = None
    last_export_count: int = 0
    model_file_exists: bool = False
    message: str = ""
    detail: dict = field(default_factory=dict)


async def check_readiness() -> ReadinessReport:
    """
    QLoRA 학습 준비 상태를 종합 점검한다.

    1. 모델 파일 존재 여부 (trained 상태)
    2. DB 후보 수 집계
    3. 검증 통과 데이터 수 계산
    4. 평균 품질 점수
    5. 중복률
    6. 안전성 샘플 검사
    7. 최근 export 이력

    Returns:
        ReadinessReport
    """
    report = ReadinessReport(status="not_ready")

    # ── 1. 모델 파일 존재 확인 ──────────────────────────────────────────
    report.model_file_exists = _check_model_file_exists()
    if report.model_file_exists:
        report.status = "trained"
        report.message = (
            "실제 학습 완료 모델 파일이 존재합니다. "
            "ollama list 또는 adapter 경로를 확인하세요."
        )
        return report

    # ── 2. DB 후보 수 집계 ──────────────────────────────────────────────
    try:
        from app.training.db_training_data_collector import (
            count_candidates,
            fetch_recent_export_info,
        )
        counts = await count_candidates()
        export_info = await fetch_recent_export_info()
    except Exception as e:
        logger.error("DB 집계 실패: %s", e)
        report.message = f"DB 연결 실패로 준비 상태를 확인할 수 없습니다: {e}"
        return report

    report.total_candidates = counts.get("total", 0)
    qualified_count = counts.get("qualified", 0)
    report.last_exported_file = export_info.get("last_exported_file")
    report.last_export_count = export_info.get("last_export_count", 0)

    # ── 3. 검증 통과 데이터 계산 ────────────────────────────────────────
    # DB qualified 수로 빠른 1차 체크
    report.validated_samples = qualified_count
    report.detail["db_counts"] = counts

    # ── 4. 샘플 기반 품질 점수 및 안전성 검사 ─────────────────────────
    try:
        from app.training.db_training_data_collector import fetch_candidates
        from app.training.training_data_validator import (
            validate_candidates_batch,
            ValidationCriteria,
        )

        # 품질/안전성 체크용 샘플 조회 (전체 검증은 export 시점에 수행)
        sample_rows = await fetch_candidates(
            statuses=["auto_approved", "holdout"],
            limit=_SAMPLE_CHECK_SIZE,
        )

        if sample_rows:
            sample_results = validate_candidates_batch(
                sample_rows, ValidationCriteria(min_overall_quality_score=0.0)
            )

            # 안전성 블록 확인
            safety_fails = [r for r in sample_results if r.safety_score < 1.0]
            if safety_fails:
                report.safety_blocked = True
                report.safety_blocked_reason = (
                    f"샘플 {len(safety_fails)}건에서 PII/secret/위험 내용 감지"
                )
                report.status = "blocked"
                report.message = report.safety_blocked_reason
                return report

            # 평균 품질 점수
            scores = [r.overall_quality_score for r in sample_results]
            report.average_quality_score = round(sum(scores) / len(scores), 4) if scores else 0.0

            # 중복률 추정
            dup_risks = [r.duplication_score for r in sample_results]
            report.duplication_rate = round(sum(dup_risks) / len(dup_risks), 4) if dup_risks else 0.0

    except Exception as e:
        logger.warning("샘플 검증 실패 (계속 진행): %s", e)

    # ── 5. 최종 준비 상태 판단 ──────────────────────────────────────────
    reasons_not_ready = []

    if qualified_count < _MIN_SAMPLES_REQUIRED:
        reasons_not_ready.append(
            f"검증 통과 데이터 {qualified_count}건 (최소 {_MIN_SAMPLES_REQUIRED}건 필요)"
        )

    if report.average_quality_score > 0 and report.average_quality_score < _MIN_AVG_QUALITY_SCORE:
        reasons_not_ready.append(
            f"평균 품질 점수 {report.average_quality_score:.2f} (최소 {_MIN_AVG_QUALITY_SCORE} 필요)"
        )

    if report.duplication_rate > _MAX_DUPLICATION_RATE:
        reasons_not_ready.append(
            f"중복률 {report.duplication_rate:.2%} (최대 {_MAX_DUPLICATION_RATE:.0%} 허용)"
        )

    if reasons_not_ready:
        report.status = "not_ready"
        report.message = (
            "QLoRA 학습을 실행하지 않습니다. "
            + " / ".join(reasons_not_ready)
        )
    else:
        report.status = "ready"
        report.message = (
            f"학습 준비 완료. 검증 통과 데이터 {qualified_count}건. "
            "CLI 스크립트 또는 관리자 승인 후 학습을 실행하세요."
        )

    report.detail["reasons_not_ready"] = reasons_not_ready
    return report


def _check_model_file_exists() -> bool:
    """실제 학습 완료 모델 파일이 존재하는지 확인한다."""
    if not _TRAINED_MODEL_PATH:
        return False
    try:
        return os.path.exists(_TRAINED_MODEL_PATH) and os.path.isdir(_TRAINED_MODEL_PATH)
    except Exception:
        return False


def report_to_dict(report: ReadinessReport) -> dict:
    """ReadinessReport를 API 응답 dict로 변환한다."""
    return {
        "status": report.status,
        "totalCandidates": report.total_candidates,
        "validatedSamples": report.validated_samples,
        "requiredSamples": report.required_samples,
        "averageQualityScore": report.average_quality_score,
        "duplicationRate": report.duplication_rate,
        "safetyBlocked": report.safety_blocked,
        "lastExportedFile": report.last_exported_file,
        "lastExportCount": report.last_export_count,
        "modelFileExists": report.model_file_exists,
        "message": report.message,
        "detail": report.detail,
    }
