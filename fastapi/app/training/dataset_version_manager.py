"""
Dataset version 관리자.

흐름:
  1. DB 후보 조회
  2. 검증 (training_data_validator)
  3. 중복 제거 (dataset_deduplicator)
  4. 샘플링 + train/valid/test 분리 (dataset_splitter)
  5. JSONL 저장 (active/<version>/)
  6. manifest 생성 (dataset_manifest_writer)
  7. cleanup 정책 적용 (dataset_cleanup_policy)

버전 이름: sft_v001, sft_v002, ... (active/ 내 최대 번호 + 1)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 기본 export 루트: fastapi/training_exports/
_DEFAULT_EXPORT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "training_exports")
)


@dataclass
class DatasetVersionConfig:
    max_train_samples: int = 5000
    max_valid_samples: int = 500
    max_test_samples:  int = 500
    recent_data_ratio: float = 0.60
    high_quality_legacy_ratio: float = 0.30
    edge_case_ratio: float = 0.10
    train_split: float = 0.80
    valid_split: float = 0.10
    test_split:  float = 0.10
    max_active_datasets: int = 5
    min_db_score: int = 70
    export_root: str = _DEFAULT_EXPORT_ROOT


@dataclass
class DatasetCreationResult:
    status: str                        # "created" | "empty" | "blocked" | "error"
    version_name: str = ""
    version_dir: str = ""
    train_samples: int = 0
    valid_samples: int = 0
    test_samples: int = 0
    total_candidates: int = 0
    validated_samples: int = 0
    dedup_removed: int = 0
    safety_blocked: int = 0
    average_quality_score: float = 0.0
    manifest_path: str = ""
    message: str = ""
    archived_versions: list[str] = field(default_factory=list)


async def create_dataset_version(
    config: DatasetVersionConfig | None = None,
) -> DatasetCreationResult:
    """
    DB에서 학습 후보를 수집하고 검증·중복제거·분리·저장을 수행한다.

    Returns:
        DatasetCreationResult
    """
    if config is None:
        config = DatasetVersionConfig()

    export_root = Path(config.export_root)
    active_dir  = export_root / "active"
    archive_dir = export_root / "archive"
    blocked_dir = export_root / "blocked"
    active_dir.mkdir(parents=True, exist_ok=True)

    # 1. DB 후보 조회
    try:
        from app.training.db_training_data_collector import fetch_candidates
        rows = await fetch_candidates(
            statuses=["auto_approved", "holdout"],
            min_score=config.min_db_score,
        )
    except Exception as e:
        return DatasetCreationResult(status="error", message=f"DB 조회 실패: {e}")

    total_candidates = len(rows)
    if total_candidates == 0:
        return DatasetCreationResult(status="empty", message="학습 후보 데이터가 없습니다.")

    # 2. 검증
    try:
        from app.training.training_data_validator import validate_candidates_batch, ValidationCriteria
        criteria = ValidationCriteria()
        results = validate_candidates_batch(rows, criteria)
    except Exception as e:
        return DatasetCreationResult(status="error", message=f"검증 실패: {e}")

    passed_rows = [
        row for row, res in zip(rows, results)
        if res.passed
    ]
    safety_blocked = sum(1 for r in results if r.safety_score < 1.0)

    # 안전성 차단된 데이터가 있으면 blocked dataset으로 격리
    if safety_blocked > 0:
        logger.warning("안전성 차단: %d건 포함 — 해당 데이터는 제외됩니다.", safety_blocked)

    if not passed_rows:
        return DatasetCreationResult(
            status="empty",
            total_candidates=total_candidates,
            safety_blocked=safety_blocked,
            message="검증 통과 데이터가 없습니다.",
        )

    # 3. 중복 제거
    from app.training.dataset_deduplicator import deduplicate_pipeline
    dedup_result = deduplicate_pipeline(passed_rows)
    clean_rows = dedup_result.rows

    # 4. train/valid/test 분리
    from app.training.dataset_splitter import SplitConfig, split_dataset
    split_cfg = SplitConfig(
        train_ratio=config.train_split,
        valid_ratio=config.valid_split,
        test_ratio=config.test_split,
        max_train_samples=config.max_train_samples,
        max_valid_samples=config.max_valid_samples,
        max_test_samples=config.max_test_samples,
        recent_data_ratio=config.recent_data_ratio,
        high_quality_legacy_ratio=config.high_quality_legacy_ratio,
        edge_case_ratio=config.edge_case_ratio,
    )
    split = split_dataset(clean_rows, split_cfg)

    if split.total == 0:
        return DatasetCreationResult(
            status="empty",
            total_candidates=total_candidates,
            message="분리 후 유효 샘플이 없습니다.",
        )

    # 5. version 디렉터리 생성
    version_name = _get_next_version_name(active_dir)
    version_dir = active_dir / version_name
    version_dir.mkdir(parents=True, exist_ok=True)

    # 6. JSONL 저장
    _write_split_jsonl(version_dir, "train", split.train)
    _write_split_jsonl(version_dir, "valid", split.valid)
    _write_split_jsonl(version_dir, "test",  split.test)

    # 7. manifest 생성
    from app.training.dataset_manifest_writer import create_manifest, write_manifest
    avg_score = (
        sum(r.get("quality_score", 0) for r in (split.train + split.valid + split.test))
        / split.total
        if split.total else 0.0
    )
    manifest = create_manifest(
        version_name=version_name,
        train=split.train,
        valid=split.valid,
        test=split.test,
        total_candidates=total_candidates,
        safety_blocked_count=safety_blocked,
        duplication_removed=dedup_result.removed_count,
    )
    manifest_path = write_manifest(manifest, version_dir)

    # 8. cleanup 정책
    from app.training.dataset_cleanup_policy import apply_cleanup_policy
    archived = apply_cleanup_policy(active_dir, archive_dir, max_active=config.max_active_datasets)

    logger.info(
        "dataset version 생성 완료: %s (train=%d, valid=%d, test=%d)",
        version_name, len(split.train), len(split.valid), len(split.test),
    )

    return DatasetCreationResult(
        status="created",
        version_name=version_name,
        version_dir=str(version_dir),
        train_samples=len(split.train),
        valid_samples=len(split.valid),
        test_samples=len(split.test),
        total_candidates=total_candidates,
        validated_samples=len(passed_rows),
        dedup_removed=dedup_result.removed_count,
        safety_blocked=safety_blocked,
        average_quality_score=round(avg_score / 100.0 if avg_score > 1 else avg_score, 4),
        manifest_path=str(manifest_path),
        message=f"{version_name} 생성 완료.",
        archived_versions=archived,
    )


def list_dataset_versions(export_root: str = _DEFAULT_EXPORT_ROOT) -> list[dict]:
    """active dataset version 목록을 반환한다."""
    from app.training.dataset_cleanup_policy import get_active_versions_sorted
    from app.training.dataset_manifest_writer import read_manifest

    active_dir = Path(export_root) / "active"
    if not active_dir.exists():
        return []

    result = []
    for vdir in reversed(get_active_versions_sorted(active_dir)):  # 최신 순
        m = read_manifest(vdir)
        if m:
            result.append(m)
        else:
            result.append({"dataset_version": vdir.name, "status": "manifest_missing"})
    return result


def get_dataset_version(
    version_name: str,
    export_root: str = _DEFAULT_EXPORT_ROOT,
) -> dict | None:
    """특정 version의 manifest를 반환한다."""
    from app.training.dataset_manifest_writer import read_manifest
    version_dir = Path(export_root) / "active" / version_name
    if not version_dir.exists():
        return None
    return read_manifest(version_dir)


def get_latest_version_dir(export_root: str = _DEFAULT_EXPORT_ROOT) -> Path | None:
    """가장 최근 active version 디렉터리를 반환한다."""
    from app.training.dataset_cleanup_policy import get_active_versions_sorted
    active_dir = Path(export_root) / "active"
    if not active_dir.exists():
        return None
    versions = get_active_versions_sorted(active_dir)
    return versions[-1] if versions else None


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────────

def _get_next_version_name(active_dir: Path) -> str:
    """sft_v001, sft_v002 형식의 다음 버전 이름을 생성한다."""
    existing = [
        int(p.name.replace("sft_v", ""))
        for p in active_dir.iterdir()
        if p.is_dir() and p.name.startswith("sft_v") and p.name[5:].isdigit()
    ]
    next_num = max(existing, default=0) + 1
    return f"sft_v{next_num:03d}"


def _write_split_jsonl(version_dir: Path, split_name: str, rows: list[dict]) -> None:
    """split 데이터를 JSONL 파일로 저장한다."""
    if not rows:
        return
    out_path = version_dir / f"{split_name}.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            messages = _build_messages(row)
            if messages:
                f.write(json.dumps({"messages": messages}, ensure_ascii=False) + "\n")
    logger.debug("%s.jsonl 저장: %d건", split_name, len(rows))


def _build_messages(row: dict) -> list[dict] | None:
    question   = str(row.get("question",      "") or "").strip()
    answer     = str(row.get("answer",        "") or "").strip()
    sys_prompt = str(row.get("system_prompt", "") or "").strip()
    if not question or not answer:
        return None
    msgs = []
    if sys_prompt:
        msgs.append({"role": "system", "content": sys_prompt})
    msgs.append({"role": "user",      "content": question})
    msgs.append({"role": "assistant", "content": answer})
    return msgs
