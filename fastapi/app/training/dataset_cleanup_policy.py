"""
오래된 dataset 보관 정책.

- active/:   최대 max_active(기본 5)개 유지
- archive/:  초과분을 tarball로 압축 이동
- blocked/:  품질/안전 문제 dataset 격리

manifest의 created_at 기준으로 오래된 순서대로 정리한다.
실제 학습에 사용한 dataset은 삭제하지 않고 manifest만 보존한다.
"""
from __future__ import annotations

import json
import logging
import shutil
import tarfile
from pathlib import Path

from app.training.dataset_manifest_writer import read_manifest

logger = logging.getLogger(__name__)


def get_active_versions_sorted(active_dir: Path) -> list[Path]:
    """active/ 디렉터리의 dataset version을 created_at 오름차순으로 반환한다."""
    versions = [p for p in active_dir.iterdir() if p.is_dir() and (p / "dataset_manifest.json").exists()]

    def _created_at(p: Path) -> str:
        m = read_manifest(p)
        return m.get("created_at", "") if m else ""

    return sorted(versions, key=_created_at)


def apply_cleanup_policy(
    active_dir: Path,
    archive_dir: Path,
    max_active: int = 5,
    protect_used: bool = True,
) -> list[str]:
    """
    active/ 디렉터리가 max_active 초과이면 오래된 것을 archive로 이동한다.

    Args:
        protect_used: True이면 'used_for_training: true' manifest를 보호한다.

    Returns:
        archived version names list
    """
    if not active_dir.exists():
        return []
    archive_dir.mkdir(parents=True, exist_ok=True)

    versions = get_active_versions_sorted(active_dir)
    overflow = len(versions) - max_active

    if overflow <= 0:
        return []

    archived: list[str] = []
    for version_dir in versions[:overflow]:
        # 사용된 dataset은 보호
        if protect_used:
            m = read_manifest(version_dir)
            if m and m.get("used_for_training"):
                logger.info("학습에 사용된 dataset 보호: %s", version_dir.name)
                continue

        _archive_version(version_dir, archive_dir)
        archived.append(version_dir.name)

    return archived


def _archive_version(version_dir: Path, archive_dir: Path) -> None:
    """version 디렉터리를 tarball로 압축해 archive/ 로 이동한다."""
    tar_name = f"{version_dir.name}.tar.gz"
    tar_path = archive_dir / tar_name

    try:
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(version_dir, arcname=version_dir.name)
        shutil.rmtree(version_dir)
        logger.info("archive 완료: %s → %s", version_dir.name, tar_path)
    except Exception as e:
        logger.error("archive 실패 (%s): %s", version_dir.name, e)


def block_dataset_version(
    version_dir: Path,
    blocked_dir: Path,
    reason: str,
) -> None:
    """
    문제가 있는 dataset version을 blocked/ 로 격리한다.
    blocked_reason.txt를 생성하고 manifest를 blocked 상태로 업데이트한다.
    """
    blocked_dir.mkdir(parents=True, exist_ok=True)
    target = blocked_dir / version_dir.name

    try:
        shutil.move(str(version_dir), str(target))

        # blocked_reason.txt 생성
        (target / "blocked_reason.txt").write_text(reason, encoding="utf-8")

        # manifest status 업데이트
        manifest_path = target / "dataset_manifest.json"
        if manifest_path.exists():
            with manifest_path.open("r+", encoding="utf-8") as f:
                data = json.load(f)
                data["status"] = "blocked"
                data["blocked_reason"] = reason
                f.seek(0)
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.truncate()

        logger.warning("dataset blocked: %s — %s", version_dir.name, reason)
    except Exception as e:
        logger.error("block 처리 실패 (%s): %s", version_dir.name, e)


def mark_used_for_training(version_dir: Path, training_run_id: str) -> None:
    """학습에 사용된 dataset을 manifest에 기록한다."""
    manifest_path = version_dir / "dataset_manifest.json"
    if not manifest_path.exists():
        return
    try:
        with manifest_path.open("r+", encoding="utf-8") as f:
            data = json.load(f)
            data["used_for_training"] = True
            data["training_run_id"] = training_run_id
            f.seek(0)
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.truncate()
    except Exception as e:
        logger.warning("used_for_training 기록 실패: %s", e)
