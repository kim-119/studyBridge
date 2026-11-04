"""안전한 데이터셋 내보내기(JSONL + 불변 manifest).

- 출력 위치는 API 가 정하지 않는다. 고정된 비공개 루트(AI_TRAINING_DATASET_DIR, 기본 ~/.local/share/studybridge/
  training-datasets, 0700) 아래 새 디렉터리(dataset_id)를 O_EXCL 로 만들고 그 안에만 쓴다 → 임의 경로/상위 경로/
  symlink escape/기존 파일 덮어쓰기 불가.
- 파일: 임시파일(O_EXCL|O_NOFOLLOW, 0600) → fsync → link(no-clobber) → unlink tmp → 0400. manifest 에 sha256.
- 동시 export: 프로세스 락 + 파일 락(flock, non-blocking) → 경합 시 BUSY.
- 크기 제한(샘플 수/바이트). 실패 시 이번 export 디렉터리만 정리(rollback)하고 FAILED.
- manifest 를 DB(lineage)에 등록하지 못하면 내보내기 자체를 FAILED 로 되돌린다(철회 추적 불가한 데이터셋 금지).
- dataset_id = train_vYYYYMMDD_NNN_<rand8>: 같은 날 여러 번 내보내도 충돌하지 않는다. empty/failed/completed 분리.
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app.training_pipeline.dataset_builder import (SPLITS, TEMPLATE_VERSION, TRAINING_SYSTEM_PROMPT_V1,
                                                   LeakageError, build_dataset, split_hash)
from app.training_pipeline.records import ManifestRecord
from app.training_pipeline.states import CandidateState

DATASET_ID_RE = re.compile(r"^train_v\d{8}_\d{3}_[0-9a-f]{8}$")
ELIGIBILITY_POLICY_VERSION = "elig-1.0.0"
_proc_lock = asyncio.Lock()


@dataclass
class ExportResult:
    status: str                       # completed | empty | busy | failed
    dataset_id: Optional[str] = None
    sample_counts: Dict[str, int] = field(default_factory=dict)
    excluded: Dict[str, int] = field(default_factory=dict)
    manifest_sha256: Optional[str] = None
    relative_path: Optional[str] = None
    error_code: Optional[str] = None
    split_warnings: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.sample_counts.values())


def datasets_root() -> Path:
    raw = os.getenv("AI_TRAINING_DATASET_DIR") or str(Path.home() / ".local/share/studybridge/training-datasets")
    p = Path(raw)
    if not p.is_absolute():
        raise ValueError("AI_TRAINING_DATASET_DIR must be absolute")
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    if p.is_symlink():
        raise ValueError("dataset root must not be a symlink")
    os.chmod(p, 0o700)
    return p.resolve()


def _limits() -> tuple:
    return (int(os.getenv("AI_TRAINING_EXPORT_MAX_SAMPLES", "50000")),
            int(os.getenv("AI_TRAINING_EXPORT_MAX_BYTES", str(256 * 1024 * 1024))))


def code_revision() -> str:
    env = os.getenv("AI_CODE_REVISION")
    if env:
        return env
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(Path(__file__).resolve().parent),
                           capture_output=True, text=True, timeout=2)
        return r.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _new_dataset_dir(root: Path) -> tuple:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    for _ in range(8):
        seq = 1 + sum(1 for d in root.iterdir() if d.name.startswith(f"train_v{day}_"))
        ds_id = f"train_v{day}_{seq:03d}_{secrets.token_hex(4)}"
        d = root / ds_id
        try:
            os.mkdir(d, 0o700)           # 이미 있으면 FileExistsError → 다른 id 로 재시도
        except FileExistsError:
            continue
        return ds_id, d
    raise RuntimeError("DATASET_ID_ALLOCATION_FAILED")


def _write_no_clobber(directory: Path, name: str, data: bytes) -> str:
    if "/" in name or name.startswith("."):
        raise ValueError("invalid file name")
    tmp = directory / f".{name}.tmp-{secrets.token_hex(4)}"
    final = directory / name
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.link(tmp, final)              # final 이 존재하면 실패(덮어쓰기 불가)
    finally:
        os.unlink(tmp)
    os.chmod(final, 0o400)
    return hashlib.sha256(data).hexdigest()


def _fsync_dir(d: Path) -> None:
    fd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


async def export_dataset(repo, *, actor: str, request_id: str,
                         frozen_test_hashes: Optional[set] = None) -> ExportResult:
    if _proc_lock.locked():
        return ExportResult(status="busy", error_code="EXPORT_IN_PROGRESS")
    async with _proc_lock:
        root = datasets_root()
        lock_fd = os.open(root / ".export.lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return ExportResult(status="busy", error_code="EXPORT_IN_PROGRESS")
            return await _export_locked(repo, root, actor=actor, request_id=request_id,
                                        frozen_test_hashes=frozen_test_hashes)
        finally:
            os.close(lock_fd)


async def _export_locked(repo, root: Path, *, actor: str, request_id: str, frozen_test_hashes) -> ExportResult:
    max_samples, max_bytes = _limits()
    records = await repo.list_by(states=[CandidateState.TRAIN_ELIGIBLE], limit=max_samples + 1)
    if len(records) > max_samples:
        return ExportResult(status="failed", error_code="EXPORT_TOO_MANY_SAMPLES")
    try:
        # 전체 PII 재스캔/그룹 분할은 CPU 작업 → 이벤트 루프를 막지 않게 스레드에서 실행
        build = await asyncio.to_thread(build_dataset, records, frozen_test_hashes=frozen_test_hashes)
    except LeakageError:
        return ExportResult(status="failed", error_code="SPLIT_LEAKAGE_DETECTED")
    if build.total == 0:
        return ExportResult(status="empty", excluded=build.excluded)

    ds_id, d = _new_dataset_dir(root)
    registered = False
    try:
        blobs, files, split_meta, written = {}, {}, {}, 0
        for split in SPLITS:
            items = build.splits[split]
            data = "".join(json.dumps({"messages": s.messages}, ensure_ascii=False) + "\n" for s in items).encode("utf-8")
            written += len(data)
            if written > max_bytes:
                raise OverflowError("EXPORT_TOO_LARGE")
            name = f"{split}.jsonl"
            blobs[name] = data
            files[name] = hashlib.sha256(data).hexdigest()
            split_meta[split] = {"count": len(items), "file": name, "sha256": files[name],
                                 "memberSetSha256": split_hash(items)}
        all_items = [s for split in SPLITS for s in build.splits[split]]
        recs = [s.record for s in all_items]
        manifest = _manifest(ds_id, actor, request_id, build, split_meta, files, recs, all_items)
        mbytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        manifest_sha = hashlib.sha256(mbytes).hexdigest()
        # 1) 파일을 쓰기 전에 lineage 를 PENDING 으로 먼저 등록 → 그 사이 철회돼도 이 manifest 가 무효화 대상이 된다.
        await repo.save_manifest(ManifestRecord(dataset_id=ds_id, status="PENDING", manifest_sha256=manifest_sha,
                                                member_hashes=manifest["memberContentHashes"],
                                                created_at=datetime.now(timezone.utc)))
        registered = True
        # 2) 파일 기록(no-clobber, 0400)
        for name, data in blobs.items():
            _write_no_clobber(d, name, data)
        _write_no_clobber(d, "manifest.json", mbytes)
        _fsync_dir(d)
        # 3) 멤버가 아직 전부 TRAIN_ELIGIBLE 인지 재확인 후 CAS 활성화(PENDING 이 아니면 실패)
        still = {r.content_hash for r in await repo.list_by(states=[CandidateState.TRAIN_ELIGIBLE], limit=max_samples + 1)}
        if not set(manifest["memberContentHashes"]) <= still:
            await repo.invalidate_manifest(ds_id, "MEMBER_REVOKED_DURING_EXPORT")
            _force_rmtree(d)
            return ExportResult(status="failed", dataset_id=ds_id, error_code="MEMBER_REVOKED_DURING_EXPORT")
        if not await repo.activate_manifest(ds_id):
            _force_rmtree(d)
            return ExportResult(status="failed", dataset_id=ds_id, error_code="MANIFEST_INVALIDATED_DURING_EXPORT")
    except OverflowError:
        shutil.rmtree(d, ignore_errors=True)
        return ExportResult(status="failed", error_code="EXPORT_TOO_LARGE")
    except Exception as e:  # noqa: BLE001
        if registered:
            try:
                await repo.invalidate_manifest(ds_id, "EXPORT_FAILED")
            except Exception:  # noqa: BLE001
                pass
        _force_rmtree(d)
        return ExportResult(status="failed", error_code=f"EXPORT_FAILED_{type(e).__name__}"[:64])
    return ExportResult(status="completed", dataset_id=ds_id,
                        sample_counts={k: len(build.splits[k]) for k in SPLITS}, excluded=build.excluded,
                        manifest_sha256=manifest_sha, relative_path=f"{ds_id}/",
                        split_warnings=manifest["splitWarnings"])


def _manifest(ds_id, actor, request_id, build, split_meta, files, recs, all_items) -> dict:
    return {
        "schemaVersion": "dataset-manifest.v1",
        "datasetId": ds_id,
        # 상태(ACTIVE/INVALIDATED)는 변할 수 있으므로 불변 파일에 쓰지 않는다 — DB 가 단일 소스.
        "statusSource": "ai.training_dataset_manifest.status",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "createdBy": actor,
        "requestId": request_id,
        "codeRevision": code_revision(),
        "templateVersion": TEMPLATE_VERSION,
        "trainingSystemPromptSha256": hashlib.sha256(TRAINING_SYSTEM_PROMPT_V1.encode()).hexdigest(),
        "eligibilityPolicyVersion": ELIGIBILITY_POLICY_VERSION,
        "baseModelReference": {"id": os.getenv("AI_QLORA_BASE_MODEL", "Qwen/Qwen3-14B"),
                               "revision": os.getenv("AI_QLORA_BASE_REVISION", "40c069824f4251a91eefaf281ebe4c544efd3e18"),
                               "license": os.getenv("AI_QLORA_BASE_LICENSE", "apache-2.0")},
        "productionBaseline": {"ollamaTag": os.getenv("OLLAMA_MODEL", "qwen3:14b"),
                               "digest": os.getenv("AI_PRODUCTION_MODEL_DIGEST")},
        "splits": split_meta,
        "files": files,
        "groups": build.groups,
        # 그룹 수가 적으면 해시 분할로 split 이 비어 early stopping/독립 평가가 불가능하다 → 학습 전 확인 필요.
        "splitWarnings": [f"{k.upper()}_SPLIT_EMPTY" for k in SPLITS if not build.splits[k]]
                         + (["TOO_FEW_GROUPS_FOR_RELIABLE_SPLIT"] if build.groups < 30 else []),
        "excluded": build.excluded,
        "consentVersions": dict(Counter(r.consent_version for r in recs)),
        "rightsStatus": dict(Counter(r.rights_status for r in recs)),
        "sourceKinds": dict(Counter(r.source_kind for r in recs)),
        "modelDigests": dict(Counter(r.model_digest or "unknown" for r in recs)),
        "evaluatorVersions": sorted({r.quality_evaluator_version or "unknown" for r in recs}),
        "verificationMethods": dict(Counter(str((r.verification or {}).get("method")) for r in recs)),
        "deletionLineage": sorted({r.deletion_tracking_id for r in recs}),
        "memberContentHashes": sorted(s.content_hash for s in all_items),
        "deidentification": "pii_filter v2 rescan at export; CLEAN required; masked/quarantined excluded",
        "license": "internal research use only; derived from consented, rights-verified samples; no redistribution",
        "weightsErasureNote": "학습된 어댑터에서 개별 샘플을 지울 수 없다. 철회 시 이 manifest 는 INVALIDATED 되고 "
                              "이를 사용한 어댑터는 RETIREMENT_REQUIRED(퇴역 또는 재학습) 대상이 된다.",
    }


_DATASET_ID_RE = __import__("re").compile(r"^train_v\d{8}_\d{3}_[0-9a-f]{8}$")


def purge_dataset_files(dataset_id: str) -> bool:
    """삭제/동의 철회된 원문이 담긴 export 파일을 파기한다(manifest 레코드와 해시 lineage 는 DB 에 남는다).
    고정 비공개 루트 아래의 정해진 형식 디렉터리만 지운다(경로 주입/심볼릭 링크 불가). 이미 없으면 False."""
    if not _DATASET_ID_RE.match(dataset_id or ""):
        return False
    root = datasets_root()
    d = root / dataset_id
    if d.is_symlink() or not d.is_dir() or d.resolve().parent != root:
        return False
    _force_rmtree(d)
    return not d.exists()


def _force_rmtree(d: Path) -> None:
    for p in d.glob("*"):
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    shutil.rmtree(d, ignore_errors=True)
