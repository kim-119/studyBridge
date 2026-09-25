import json
from app.training.studybridge_ft.validators.quiz import QuizValidator

V = QuizValidator()


def _wrap(payload):
    return {"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "퀴즈"},
            {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)}]}


def _good():
    return {"question": "Q", "choices": ["a", "b", "c", "d"], "answer": 1,
            "explanation": "E", "difficulty": "medium", "source_hint": "ch1"}


def test_valid_quiz():
    assert V.validate(_wrap(_good())).ok


def test_broken_json():
    s = {"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "q"},
         {"role": "assistant", "content": "{not json"}]}
    assert V.validate(s).reason == "quiz_invalid_json"


def test_missing_field():
    p = _good(); del p["explanation"]
    assert V.validate(_wrap(p)).reason == "quiz_missing_field"


def test_answer_out_of_range():
    p = _good(); p["answer"] = 9
    assert V.validate(_wrap(p)).reason == "quiz_invalid_answer"
