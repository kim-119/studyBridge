from app.training.studybridge_ft.validators.professor import ProfessorValidator

V = ProfessorValidator()


def _wrap(a, expected=None):
    s = {"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "김교수님께"},
         {"role": "assistant", "content": a}]}
    if expected:
        s["metadata"] = {"expected_speaker": expected}
    return s


def test_correct_speaker():
    assert V.validate(_wrap("[김교수] 그건 이렇습니다.", expected="김교수")).ok


def test_wrong_speaker():
    r = V.validate(_wrap("[이교수] 제가 답합니다.", expected="김교수"))
    assert r.reason == "professor_speaker_mismatch"


def test_duplicate_answers():
    a = "[김교수] 같은 말.\n[이교수] 같은 말.\n[박교수] 같은 말."
    assert V.validate(_wrap(a)).reason == "professor_duplicate_answers"


def test_distinct_multi_ok():
    a = "[김교수] 정의 측면.\n[이교수] 예시 측면.\n[박교수] 반례 측면."
    assert V.validate(_wrap(a)).ok
