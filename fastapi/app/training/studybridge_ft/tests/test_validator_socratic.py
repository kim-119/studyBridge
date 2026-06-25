from app.training.studybridge_ft.validators.socratic import SocraticValidator

V = SocraticValidator()


def _wrap(a):
    return {"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "개념?"},
            {"role": "assistant", "content": a}]}


GOOD = ("이 개념을 어떻게 정의할 수 있을까요? 힌트: 핵심은 관계입니다. "
        "그렇다면 왜 그럴까요? 부분 정리하면 이렇습니다. 최종 정리: 종합하면 ...")


def test_good_socratic():
    assert V.validate(_wrap(GOOD)).ok


def test_direct_answer_rejected():
    assert V.validate(_wrap("정답은 42입니다. 끝.")).reason == "socratic_direct_answer"


def test_too_few_questions():
    assert V.validate(_wrap("힌트만 줄게요. 생각해봐요.")).reason in (
        "socratic_too_few_questions", "socratic_missing_stages")
