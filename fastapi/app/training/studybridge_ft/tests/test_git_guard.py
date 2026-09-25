import app.training.studybridge_ft.utils.git_guard as g


def test_outside_scope_detected(monkeypatch):
    monkeypatch.setattr(g, "_porcelain", lambda: [
        " M fastapi/app/main.py",
        " M fastapi/app/training/studybridge_ft/x.py",
    ])
    out = g.tracked_changes_outside_scope()
    assert "fastapi/app/main.py" in out
    assert all("studybridge_ft" not in x for x in out)


def test_assert_safe_raises(monkeypatch):
    monkeypatch.setattr(g, "_porcelain", lambda: [" M fastapi/app/api/x.py"])
    try:
        g.assert_safe()
        assert False
    except RuntimeError:
        pass


def test_assert_safe_ok_when_only_scope(monkeypatch):
    monkeypatch.setattr(g, "_porcelain", lambda: [
        " M fastapi/app/training/studybridge_ft/y.py",
        "?? raw/quiz_0001.jsonl",
    ])
    g.assert_safe()  # 예외 없어야 함(scope 내 + repo밖 데이터)
