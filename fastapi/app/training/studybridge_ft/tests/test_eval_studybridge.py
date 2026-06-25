from app.training.studybridge_ft.eval_studybridge import run_eval, EVAL_CASES


def test_ten_cases():
    assert len(EVAL_CASES) == 10


def test_run_eval_with_fake(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDYBRIDGE_FT_HOME", str(tmp_path))
    import app.training.studybridge_ft.paths as p, importlib
    importlib.reload(p)
    import app.training.studybridge_ft.eval_studybridge as e
    importlib.reload(e)

    def responder(messages):  # 항상 형식 좋은 응답
        return ('{"question":"q","choices":["a","b"],"answer":0,"explanation":"e",'
                '"difficulty":"easy","source_hint":"h"}')

    r = e.run_eval(responder)
    assert "results" in r and len(r["results"]) == 10
    assert any(f.suffix == ".md" for f in (p.SUBDIRS["outputs"]).glob("eval_report_*.md"))
