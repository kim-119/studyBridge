from app.training.studybridge_ft.validate_dataset import validate_rows


def _ok():
    return {"messages": [{"role": "system", "content": "S"},
            {"role": "user", "content": "U"}, {"role": "assistant", "content": "좋은 설명"}]}


def test_validate_rows_counts():
    bad = {"messages": [{"role": "user", "content": "x"}]}
    r = validate_rows([_ok(), bad])
    assert r["ok"] == 1 and r["bad"] == 1 and "schema_error" in r["reasons"]
