from app.training.studybridge_ft.validators.chatml import ChatMLValidator

V = ChatMLValidator()


def _ok():
    return {"messages": [{"role": "system", "content": "S"},
                         {"role": "user", "content": "U"},
                         {"role": "assistant", "content": "A"}]}


def test_valid_passes():
    assert V.validate(_ok()).ok


def test_empty_assistant_rejected():
    s = _ok()
    s["messages"][2]["content"] = "  "
    r = V.validate(s)
    assert not r.ok and r.reason == "empty_answer"


def test_missing_roles_rejected():
    s = {"messages": [{"role": "user", "content": "U"}]}
    r = V.validate(s)
    assert not r.ok and r.reason == "schema_error"
