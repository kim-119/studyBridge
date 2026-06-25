import app.training.studybridge_ft.generate_seed as gs


class _FakeClient:
    def chat(self, s, u):
        return "정의: 좋은 한국어 설명. 원리, 예시, 오개념 경고, 확인 질문?"


def test_check_abort_secret(tmp_path):
    cfg = gs.load_config()
    reason = gs.check_abort({"accepted": 0, "rejected": 0, "reject_reasons": {"pii_secret": 1},
                             "quiz_total": 0, "quiz_invalid": 0, "empty": 0}, cfg)
    assert reason and ("secret" in reason.lower() or "pii" in reason.lower())


def test_dryrun_writes_outside_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDYBRIDGE_FT_HOME", str(tmp_path))
    import app.training.studybridge_ft.paths as p, importlib
    importlib.reload(p)
    importlib.reload(gs)
    monkeypatch.setattr(gs.git_guard, "assert_safe", lambda *a, **k: None)
    summary = gs.run(dry_run=True, per_category=2, client=_FakeClient())
    assert summary["dry_run"] is True
    # repo 내부에 데이터가 없어야 함
    assert not (p.REPO_ROOT / "fastapi" / "app" / "training" / "studybridge_ft" / "raw").exists()
