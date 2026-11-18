"""
자동 QLoRA 재학습 파이프라인 오케스트레이터.

흐름:
  1. config 로드 → autoTrain 플래그 확인
  2. DB 후보 수집
  3. 검증 (training_data_validator)
  4. Dataset version 생성 (dedup + split + manifest)
  5. Readiness gate 통과 확인
  6. QLoRA 학습 실행 (autoTrain=true일 때만)
  7. 새 모델 평가 (model_evaluator)
  8. 평가 통과 시 candidate로 등록 (model_registry)
  9. autoDeploy=true + canaryDeploy=true이면 production 승격
 10. rollbackOnFailure=true이면 오류 감지 시 자동 rollback

중요:
  - autoTrain=false(기본)이면 dataset 생성까지만 수행하고 학습을 실행하지 않는다.
  - autoDeploy=false(기본)이면 평가 통과 후에도 production으로 자동 반영하지 않는다.
  - 서비스 중인 production 모델을 바로 덮어쓰지 않는다.
  - "파인튜닝 완료"라고 과장하지 않는다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "auto_retrain_config.json")
)


# ── 설정 ───────────────────────────────────────────────────────────────────────

@dataclass
class AutoRetrainConfig:
    auto_retrain_enabled: bool = False
    auto_train: bool = False
    auto_deploy: bool = False
    canary_deploy: bool = True
    rollback_on_failure: bool = True

    min_validated_samples: int = 300
    min_average_quality_score: float = 0.80
    max_duplication_rate: float = 0.30
    require_safety_pass: bool = True
    gpu_required: bool = True

    max_train_samples: int = 5000
    max_valid_samples: int = 500
    max_test_samples:  int = 500
    max_active_datasets: int = 5

    model_name: str = "Qwen/Qwen2.5-14B-Instruct"
    num_train_epochs: int = 1
    lora_r: int = 16
    lora_alpha: int = 32
    learning_rate: float = 2e-4

    candidate_dir: str = "models/qlora/candidate"
    production_dir: str = "models/qlora/production"
    rollback_dir: str = "models/qlora/rollback"
    registry_file: str = "models/qlora/registry.json"
    export_dir: str = "training_exports"


def load_config(config_path: str = _DEFAULT_CONFIG_PATH) -> AutoRetrainConfig:
    """auto_retrain_config.json을 로드한다. 실패 시 기본값 반환."""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        logger.warning("config 로드 실패 (%s): %s — 기본값 사용", config_path, e)
        return AutoRetrainConfig()

    rg = raw.get("readinessGate", {})
    dc = raw.get("datasetConfig", {})
    ta = raw.get("trainingArgs", {})
    mp = raw.get("modelPaths", {})

    return AutoRetrainConfig(
        auto_retrain_enabled=raw.get("autoRetrainEnabled", False),
        auto_train=raw.get("autoTrain", False),
        auto_deploy=raw.get("autoDeploy", False),
        canary_deploy=raw.get("canaryDeploy", True),
        rollback_on_failure=raw.get("rollbackOnFailure", True),
        min_validated_samples=rg.get("minValidatedSamples", 300),
        min_average_quality_score=rg.get("minAverageQualityScore", 0.80),
        max_duplication_rate=rg.get("maxDuplicationRate", 0.30),
        require_safety_pass=rg.get("requireSafetyPass", True),
        gpu_required=rg.get("gpuRequired", True),
        max_train_samples=dc.get("maxTrainSamples", 5000),
        max_valid_samples=dc.get("maxValidSamples", 500),
        max_test_samples=dc.get("maxTestSamples", 500),
        max_active_datasets=dc.get("maxActiveDatasets", 5),
        model_name=ta.get("modelName", "Qwen/Qwen2.5-14B-Instruct"),
        num_train_epochs=ta.get("numTrainEpochs", 1),
        lora_r=ta.get("loraR", 16),
        lora_alpha=ta.get("loraAlpha", 32),
        learning_rate=ta.get("learningRate", 2e-4),
        candidate_dir=mp.get("candidateDir", "models/qlora/candidate"),
        production_dir=mp.get("productionDir", "models/qlora/production"),
        rollback_dir=mp.get("rollbackDir", "models/qlora/rollback"),
        registry_file=raw.get("registryFile", "models/qlora/registry.json"),
        export_dir=raw.get("exportDir", "training_exports"),
    )


# ── 결과 ───────────────────────────────────────────────────────────────────────

@dataclass
class AutoRetrainResult:
    run_id: str
    status: str           # "completed" | "skipped" | "blocked" | "failed" | "dry_run"
    dry_run: bool = False

    # 각 단계 상태
    step_data_collect:  str = "pending"
    step_validate:      str = "pending"
    step_dataset:       str = "pending"
    step_readiness:     str = "pending"
    step_train:         str = "pending"
    step_evaluate:      str = "pending"
    step_register:      str = "pending"
    step_deploy:        str = "pending"

    dataset_version: str = ""
    candidate_model_path: str = ""
    eval_scores: dict = field(default_factory=dict)
    production_updated: bool = False

    validated_samples: int = 0
    safety_blocked: int = 0

    message: str = ""
    errors: list[str] = field(default_factory=list)


# ── 메인 파이프라인 ─────────────────────────────────────────────────────────────

async def run_auto_retrain(
    config: AutoRetrainConfig | None = None,
    dry_run: bool = False,
    force_train: bool = False,
) -> AutoRetrainResult:
    """
    자동 재학습 파이프라인 전체를 실행한다.

    Args:
        config:      설정 (None이면 auto_retrain_config.json 로드)
        dry_run:     True이면 학습/배포를 실행하지 않고 dataset까지만 수행
        force_train: True이면 auto_train 플래그 무시하고 학습 실행

    Returns:
        AutoRetrainResult
    """
    if config is None:
        config = load_config()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    result = AutoRetrainResult(run_id=run_id, status="skipped", dry_run=dry_run)

    logger.info("=== 자동 재학습 파이프라인 시작 [%s] dry_run=%s ===", run_id, dry_run)

    # ── 1. DB 후보 수집 ────────────────────────────────────────────────────────
    result.step_data_collect = "running"
    try:
        from app.training.db_training_data_collector import fetch_candidates
        rows = await fetch_candidates(statuses=["auto_approved", "holdout"])
        result.step_data_collect = f"ok ({len(rows)}건)"
        logger.info("[1/8] 후보 수집: %d건", len(rows))
    except Exception as e:
        result.step_data_collect = f"failed: {e}"
        result.status = "failed"
        result.errors.append(f"DB 수집 실패: {e}")
        return result

    # ── 2. 검증 ────────────────────────────────────────────────────────────────
    result.step_validate = "running"
    try:
        from app.training.training_data_validator import validate_candidates_batch, ValidationCriteria
        criteria = ValidationCriteria(
            min_overall_quality_score=config.min_average_quality_score,
            require_safety_pass=config.require_safety_pass,
        )
        vresults = validate_candidates_batch(rows, criteria)
        passed = sum(1 for r in vresults if r.passed)
        safety_blocked = sum(1 for r in vresults if r.safety_score < 1.0)
        result.validated_samples = passed
        result.safety_blocked = safety_blocked
        result.step_validate = f"ok ({passed}건 통과, {safety_blocked}건 안전 차단)"
        logger.info("[2/8] 검증: %d/%d 통과, %d건 안전 차단", passed, len(rows), safety_blocked)
    except Exception as e:
        result.step_validate = f"failed: {e}"
        result.status = "failed"
        result.errors.append(f"검증 실패: {e}")
        return result

    if safety_blocked > 0 and config.require_safety_pass:
        logger.error("안전 위반 데이터 감지 — 파이프라인 중단")
        result.status = "blocked"
        result.message = f"안전 위반 데이터 {safety_blocked}건 감지. 데이터 정제 후 재실행하세요."
        return result

    # ── 3. Dataset version 생성 ────────────────────────────────────────────────
    result.step_dataset = "running"
    try:
        from app.training.dataset_version_manager import (
            create_dataset_version,
            DatasetVersionConfig,
        )
        ds_config = DatasetVersionConfig(
            max_train_samples=config.max_train_samples,
            max_valid_samples=config.max_valid_samples,
            max_test_samples=config.max_test_samples,
            max_active_datasets=config.max_active_datasets,
        )
        ds_result = await create_dataset_version(ds_config)

        if ds_result.status not in ("created",):
            result.step_dataset = f"skipped: {ds_result.message}"
            result.status = "skipped"
            result.message = ds_result.message
            return result

        result.dataset_version = ds_result.version_name
        result.step_dataset = f"ok ({ds_result.version_name})"
        logger.info("[3/8] dataset: %s", ds_result.version_name)
    except Exception as e:
        result.step_dataset = f"failed: {e}"
        result.status = "failed"
        result.errors.append(f"dataset 생성 실패: {e}")
        return result

    # ── 4. Readiness gate ──────────────────────────────────────────────────────
    result.step_readiness = "running"
    try:
        from app.training.qlora_readiness_checker import check_readiness
        readiness = await check_readiness()
        result.step_readiness = f"ok (status={readiness.status})"
        logger.info("[4/8] readiness: %s", readiness.status)

        if readiness.status in ("not_ready", "blocked"):
            result.status = "skipped"
            result.message = readiness.message
            return result
    except Exception as e:
        result.step_readiness = f"warning: {e}"
        logger.warning("[4/8] readiness check 실패 (계속): %s", e)

    # dry_run이면 여기서 중단
    if dry_run:
        result.status = "dry_run"
        result.step_train    = "skipped (dry_run)"
        result.step_evaluate = "skipped (dry_run)"
        result.step_register = "skipped (dry_run)"
        result.step_deploy   = "skipped (dry_run)"
        result.message = f"dry_run 완료. dataset={result.dataset_version}, 검증 통과={passed}건"
        return result

    # ── 5. QLoRA 학습 ─────────────────────────────────────────────────────────
    if not config.auto_train and not force_train:
        result.step_train = "skipped (autoTrain=false)"
        logger.info("[5/8] 학습 건너뜀: autoTrain=false")
    else:
        result.step_train = "running"
        train_result = await _run_qlora_training(config, result.dataset_version, run_id)
        result.step_train = train_result["status"]
        result.candidate_model_path = train_result.get("output_dir", "")
        logger.info("[5/8] 학습: %s", train_result["status"])

        if train_result["status"].startswith("failed"):
            result.status = "failed"
            result.errors.append(train_result.get("error", "학습 실패"))
            return result

    # ── 6. 평가 ────────────────────────────────────────────────────────────────
    if not result.candidate_model_path:
        result.step_evaluate = "skipped (모델 없음)"
        result.step_register = "skipped"
        result.step_deploy   = "skipped"
        result.status = "completed"
        result.message = "학습 미실행 — dataset만 생성됨."
        return result

    result.step_evaluate = "running"
    try:
        from app.training.model_evaluator import evaluate_model, EvaluationGate
        from app.training.model_registry import get_registry

        reg = get_registry(config.registry_file)
        baseline_path = reg.get_production()

        # baseline이 있으면 먼저 평가
        baseline_eval = None
        if baseline_path:
            test_path = _resolve_test_path(result.dataset_version, config)
            baseline_eval = await evaluate_model(baseline_path["path"], test_path)

        eval_result = await evaluate_model(
            result.candidate_model_path,
            _resolve_test_path(result.dataset_version, config),
            baseline_eval=baseline_eval,
        )
        result.eval_scores = {
            "avg_quality": eval_result.avg_quality_score,
            "avg_personality": eval_result.avg_personality_score,
            "avg_knowledge_level": eval_result.avg_knowledge_level_score,
            "avg_rag_grounding": eval_result.avg_rag_grounding_score,
            "hallucination_rate": eval_result.hallucination_rate,
            "passed": eval_result.passed,
        }
        result.step_evaluate = f"ok (passed={eval_result.passed})"
        logger.info("[6/8] 평가: passed=%s", eval_result.passed)

        if not eval_result.passed:
            result.status = "completed"
            result.message = "평가 미통과 — 배포하지 않습니다. 이유: " + ", ".join(eval_result.failure_reasons)
            result.step_register = "skipped (evaluation failed)"
            result.step_deploy   = "skipped (evaluation failed)"
            return result
    except Exception as e:
        result.step_evaluate = f"warning: {e}"
        logger.warning("[6/8] 평가 실패 (계속): %s", e)

    # ── 7. candidate 등록 ──────────────────────────────────────────────────────
    result.step_register = "running"
    try:
        from app.training.model_registry import get_registry
        reg = get_registry(config.registry_file)
        reg.register_candidate(
            model_path=result.candidate_model_path,
            dataset_version=result.dataset_version,
            eval_scores=result.eval_scores,
        )
        result.step_register = "ok"
        logger.info("[7/8] candidate 등록 완료")
    except Exception as e:
        result.step_register = f"warning: {e}"

    # ── 8. 배포 ────────────────────────────────────────────────────────────────
    if not config.auto_deploy:
        result.step_deploy = "skipped (autoDeploy=false)"
        result.status = "completed"
        result.message = (
            f"자동 학습 완료. candidate={result.candidate_model_path}. "
            "자동 배포는 비활성화되어 있습니다. 수동으로 promote 후 확인하세요."
        )
        return result

    result.step_deploy = "running"
    try:
        from app.training.model_registry import get_registry
        reg = get_registry(config.registry_file)
        success = reg.promote_candidate_to_production()
        if success:
            result.production_updated = True
            result.step_deploy = "ok (canary)" if config.canary_deploy else "ok"
            result.message = "production 자동 배포 완료."
        else:
            result.step_deploy = "failed (promote 실패)"
        logger.info("[8/8] 배포: %s", result.step_deploy)
    except Exception as e:
        result.step_deploy = f"failed: {e}"
        result.errors.append(f"배포 실패: {e}")

    result.status = "completed"
    return result


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────────

async def _run_qlora_training(
    config: AutoRetrainConfig,
    dataset_version: str,
    run_id: str,
) -> dict:
    """train_qlora.py를 subprocess로 실행한다."""
    fastapi_root = Path(__file__).parent.parent.parent  # fastapi/
    export_root  = fastapi_root / config.export_dir
    version_dir  = export_root / "active" / dataset_version
    train_file   = version_dir / "train.jsonl"
    valid_file   = version_dir / "valid.jsonl"
    output_dir   = fastapi_root / config.candidate_dir / run_id

    output_dir.mkdir(parents=True, exist_ok=True)

    if not train_file.exists():
        return {"status": "failed: train.jsonl 없음", "error": str(train_file)}

    # GPU 체크
    if config.gpu_required and not _has_gpu():
        return {
            "status": "skipped (GPU 없음 — 캡스톤 환경에서는 실제 학습 미실행)",
            "output_dir": str(output_dir),
        }

    cmd = [
        sys.executable,
        str(fastapi_root / "app" / "training" / "train_qlora.py"),
        "--model_name",     config.model_name,
        "--train_file",     str(train_file),
        "--validation_file", str(valid_file) if valid_file.exists() else str(train_file),
        "--output_dir",     str(output_dir),
        "--num_train_epochs", str(config.num_train_epochs),
        "--lora_r",         str(config.lora_r),
        "--lora_alpha",     str(config.lora_alpha),
        "--learning_rate",  str(config.learning_rate),
        "--load_in_4bit",   "true",
    ]

    logger.info("QLoRA 학습 실행: %s", " ".join(cmd[:5]) + " ...")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(fastapi_root),
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=7200,  # 2시간 타임아웃
        )

        if proc.returncode == 0:
            return {"status": "ok", "output_dir": str(output_dir)}
        else:
            err_msg = stderr.decode("utf-8", errors="ignore")[:500]
            return {"status": f"failed (returncode={proc.returncode})", "error": err_msg}
    except asyncio.TimeoutError:
        return {"status": "failed (timeout)", "error": "학습 2시간 초과"}
    except Exception as e:
        return {"status": f"failed: {e}", "error": str(e)}


def _resolve_test_path(dataset_version: str, config: AutoRetrainConfig) -> str:
    fastapi_root = Path(__file__).parent.parent.parent
    return str(fastapi_root / config.export_dir / "active" / dataset_version / "test.jsonl")


def _has_gpu() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False
