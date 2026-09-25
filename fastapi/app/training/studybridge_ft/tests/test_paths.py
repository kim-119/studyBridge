import os
from pathlib import Path
import importlib

def test_base_defaults_to_home(monkeypatch):
    monkeypatch.delenv("STUDYBRIDGE_FT_HOME", raising=False)
    import app.training.studybridge_ft.paths as p
    importlib.reload(p)
    assert p.BASE == Path.home() / "studybridge-ft"

def test_base_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDYBRIDGE_FT_HOME", str(tmp_path))
    import app.training.studybridge_ft.paths as p
    importlib.reload(p)
    assert p.BASE == tmp_path
    p.ensure_dirs()
    assert (tmp_path / "raw").is_dir()
    assert (tmp_path / "manifests").is_dir()

def test_assert_outside_repo_blocks_repo_path(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDYBRIDGE_FT_HOME", str(tmp_path))
    import app.training.studybridge_ft.paths as p
    importlib.reload(p)
    inside = p.REPO_ROOT / "fastapi" / "app" / "x.jsonl"
    try:
        p.assert_outside_repo(inside)
        assert False, "repo 내부 경로는 막아야 함"
    except RuntimeError:
        pass
    p.assert_outside_repo(tmp_path / "data" / "train.jsonl")  # 예외 없어야 함
