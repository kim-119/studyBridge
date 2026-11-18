from app.training.studybridge_ft.generators import REGISTRY
from app.training.studybridge_ft.generators.base import BaseGenerator


def test_registry_has_7():
    assert set(REGISTRY) == {"concept", "archive_qa", "quiz", "socratic",
                             "debate", "professor", "format_safety"}
    for cls in REGISTRY.values():
        assert issubclass(cls, BaseGenerator)


def test_quiz_parse_wraps_json():
    g = REGISTRY["quiz"]()
    s = g.parse('{"question":"Q"}')
    asst = [m for m in s["messages"] if m["role"] == "assistant"][0]["content"]
    assert asst == '{"question":"Q"}'


def test_professor_parse_attaches_metadata():
    g = REGISTRY["professor"]()
    s = g.parse("[김교수] 답")
    assert "metadata" in s
