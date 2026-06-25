"""studybridge_ft 경로 SSOT. 모든 대용량 산출물은 repo 밖(~/studybridge-ft/)."""
import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
# fastapi/app/training/studybridge_ft -> repo root
REPO_ROOT = PKG_DIR.parents[3]

BASE = Path(os.environ.get("STUDYBRIDGE_FT_HOME", Path.home() / "studybridge-ft")).resolve()

SUBDIRS = {name: BASE / name for name in
           ("raw", "cleaned", "rejected", "data", "outputs", "logs", "manifests", "cache")}

def ensure_dirs() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    for d in SUBDIRS.values():
        d.mkdir(parents=True, exist_ok=True)

def assert_outside_repo(p: Path) -> None:
    """p가 repo 트리 안이면 RuntimeError. 데이터가 git에 새는 것 방지."""
    rp = Path(p).resolve()
    try:
        rp.relative_to(REPO_ROOT)
    except ValueError:
        return  # repo 밖 → OK
    raise RuntimeError(f"데이터 경로가 repo 내부입니다(금지): {rp}")
