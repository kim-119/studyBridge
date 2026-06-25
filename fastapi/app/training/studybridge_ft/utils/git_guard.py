"""autodeploy/reset 환경 git 안전장치."""
import subprocess

from .. import paths

SCOPE = "fastapi/app/training/studybridge_ft"


def _run(args: list[str]) -> str:
    return subprocess.run(args, cwd=str(paths.REPO_ROOT), capture_output=True,
                          text=True, timeout=15).stdout


def current_commit() -> str:
    try:
        out = _run(["git", "rev-parse", "HEAD"]).strip()
        return out or "unknown"
    except Exception:
        return "unknown"


def _porcelain() -> list[str]:
    try:
        return [ln for ln in _run(["git", "status", "--porcelain"]).splitlines() if ln.strip()]
    except Exception:
        return []


def _path_of(line: str) -> str:
    # "XY path" 또는 "?? path" / 리네임 "R  a -> b"
    rest = line[3:].strip()
    return rest.split(" -> ")[-1].strip()


def tracked_changes_outside_scope(scope: str = SCOPE) -> list[str]:
    out = []
    for ln in _porcelain():
        if ln.startswith("??"):   # untracked(데이터 등) 무시
            continue
        path = _path_of(ln)
        if path and not path.startswith(scope):
            out.append(path)
    return out


def assert_safe(scope: str = SCOPE) -> None:
    bad = tracked_changes_outside_scope(scope)
    if bad:
        raise RuntimeError(f"studybridge_ft 외부 tracked 변경 감지 → 중단: {bad}")
