from app.training.studybridge_ft.validators.safety import SafetyValidator

V = SafetyValidator()


def test_clean_ok():
    s = {"messages": [{"role": "assistant", "content": "평범한 설명"}]}
    assert V.validate(s).ok


def test_secret_rejected():
    s = {"messages": [{"role": "assistant", "content": "키 sk-ABCDEFGHIJKLMNOPQRSTUV1234567890"}]}
    assert V.validate(s).reason == "pii_secret"
