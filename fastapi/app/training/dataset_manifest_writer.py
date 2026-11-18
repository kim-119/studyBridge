"""
dataset_manifest.json 생성기.

각 dataset version 디렉터리에 manifest를 저장한다.
manifest에는 버전, 통계, 분포, 상태가 포함된다.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DatasetManifest:
    dataset_version: str
    created_at: str
    source: str = "db"
    total_candidates: int = 0
    validated_samples: int = 0
    train_samples: int = 0
    valid_samples: int = 0
    test_samples: int = 0
    average_quality_score: float = 0.0
    duplication_rate: float = 0.0
    safety_blocked_count: int = 0
    personality_distribution: dict[str, int] = field(default_factory=dict)
    knowledge_level_distribution: dict[str, int] = field(default_factory=dict)
    status: str = "ready"   # ready | blocked | archived
    notes: str = ""


def create_manifest(
    version_name: str,
    train: list[dict],
    valid: list[dict],
    test: list[dict],
    total_candidates: int = 0,
    safety_blocked_count: int = 0,
    duplication_removed: int = 0,
) -> DatasetManifest:
    """DatasetManifest 객체를 생성한다."""
    all_rows = train + valid + test
    validated = len(all_rows)

    avg_quality = (
        sum(r.get("quality_score", 0) for r in all_rows) / validated
        if validated else 0.0
    )
    dup_rate = (
        duplication_removed / (total_candidates + duplication_removed)
        if (total_candidates + duplication_removed) > 0 else 0.0
    )

    return DatasetManifest(
        dataset_version=version_name,
        created_at=datetime.now(timezone.utc).isoformat(),
        total_candidates=total_candidates,
        validated_samples=validated,
        train_samples=len(train),
        valid_samples=len(valid),
        test_samples=len(test),
        average_quality_score=round(avg_quality / 100.0, 4) if avg_quality > 1 else round(avg_quality, 4),
        duplication_rate=round(dup_rate, 4),
        safety_blocked_count=safety_blocked_count,
        personality_distribution=_count_field(all_rows, "personality"),
        knowledge_level_distribution=_count_field(all_rows, "knowledge_level"),
    )


def write_manifest(manifest: DatasetManifest, output_dir: Path) -> Path:
    """manifest를 output_dir/dataset_manifest.json 에 저장한다."""
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "dataset_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(asdict(manifest), f, ensure_ascii=False, indent=2)
    logger.info("manifest 저장: %s", manifest_path)
    return manifest_path


def read_manifest(version_dir: Path) -> dict | None:
    """version_dir/dataset_manifest.json을 읽어 dict로 반환한다."""
    manifest_path = version_dir / "dataset_manifest.json"
    if not manifest_path.exists():
        return None
    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("manifest 읽기 실패 (%s): %s", manifest_path, e)
        return None


def _count_field(rows: list[dict], field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        val = str(r.get(field_name, "unknown") or "unknown")
        counts[val] = counts.get(val, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))
