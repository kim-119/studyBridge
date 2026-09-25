from app.training.studybridge_ft.validators.debate import DebateValidator

V = DebateValidator()


def _wrap(a):
    return {"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "논제"},
            {"role": "assistant", "content": a}]}


GOOD = "주장: A다. 반박: 그러나 B. 재반박: 그럼에도 C. 검증 기준: D로 확인. 결론: 따라서 E."


def test_good_debate():
    assert V.validate(_wrap(GOOD)).ok


def test_plain_pro_con_rejected():
    assert V.validate(_wrap("찬성합니다. 좋아요.")).reason == "debate_missing_structure"
