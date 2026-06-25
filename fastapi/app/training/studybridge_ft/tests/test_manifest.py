from app.training.studybridge_ft.utils.manifest import Manifest


def test_manifest_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDYBRIDGE_FT_HOME", str(tmp_path))
    import app.training.studybridge_ft.paths as p
    import importlib
    importlib.reload(p)
    m = Manifest.new("run1", "abc123", "qwen3:14b", "sha256:deadbeef",
                     {"temperature": 0.7}, input_seed=42)
    m.record(accepted=3, rejected=1, repaired=1, deduped=0, category="quiz")
    m.record(accepted=2, category="quiz")
    m.finish()
    out = m.save()
    assert out.exists()
    import json
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["run_id"] == "run1" and data["git_commit"] == "abc123"
    assert data["accepted"] == 5 and data["rejected"] == 1
    assert data["category_counts"]["quiz"] == 5
    assert data["finished_at"] is not None
