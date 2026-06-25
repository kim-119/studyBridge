import json
from app.training.studybridge_ft.balanced import validate_balanced as vb
from app.training.studybridge_ft.balanced import prompt_builder_balanced as pb
from app.training.studybridge_ft.balanced.balanced_sampler import Cell


def _mk(domain, task, text):
    return pb.make_sample(Cell(domain, "x", task, "학사", "default"), text)


def test_empty_rejected():
    ok, reason, _ = vb.validate_sample(_mk("화학", "concept", "   "))
    assert not ok and reason == "empty"


def test_too_short_rejected():
    ok, reason, _ = vb.validate_sample(_mk("화학", "concept", "짧음"))
    assert not ok and reason == "too_short"


def test_repetition_rejected():
    txt = "같은 문장이 반복됩니다.\n" * 5
    ok, reason, _ = vb.validate_sample(_mk("수학", "concept", txt))
    assert not ok and reason == "repetition"


def test_off_domain_drift_rejected():
    txt = ("이 화학 주제를 설명하면 운동량과 인공지능 알고리즘 모델로 비유할 수 있다. "
           "운동량 인공지능 운동량 인공지능 알고리즘 모델 신경망 딥러닝.")
    ok, reason, _ = vb.validate_sample(_mk("화학", "concept", txt))
    assert not ok and reason == "off_domain_drift"


def test_drift_ok_in_physics():
    txt = "운동량은 질량과 속도의 곱이다. 운동량 보존 법칙은 외력이 없을 때 운동량이 일정함을 뜻한다. 운동량 예시."
    ok, reason, _ = vb.validate_sample(_mk("물리학", "concept", txt))
    assert ok, reason


def test_risk_expression_rejected():
    ok, reason, _ = vb.validate_sample(
        _mk("의학/보건", "concept", "이 환자에게는 아목시실린을 복용하세요. 충분한 설명입니다 한국어 텍스트."))
    assert not ok and reason == "risk_expression"


def test_quiz_invalid_json_rejected():
    ok, reason, _ = vb.validate_sample(_mk("수학", "quiz",
        "이건 JSON이 아니라 그냥 자연어 텍스트입니다. 퀴즈는 JSON 객체로만 출력해야 하는데 그렇지 않습니다 어쩌고 저쩌고 길게."))
    assert not ok and reason == "quiz_invalid_json"


def test_quiz_valid_passes():
    payload = json.dumps({"question": "1+1?", "choices": ["1", "2", "3", "4"],
                          "answer": 1, "explanation": "둘", "difficulty": "입문",
                          "source_hint": "산수"}, ensure_ascii=False)
    ok, reason, _ = vb.validate_sample(_mk("수학", "quiz", payload))
    assert ok, reason


def test_good_concept_passes_with_risk_tag():
    txt = "병리학의 염증은 조직 손상에 대한 방어 반응이다. 정의와 원리, 예시를 교육적으로 설명한다 충분히."
    ok, reason, tags = vb.validate_sample(_mk("의학/보건", "concept", txt))
    assert ok and "risk_domain_reviewed" in tags


def test_gate_distribution_balanced():
    from app.training.studybridge_ft.balanced.balanced_sampler import build_plan
    plan = build_plan(2400, seed=42)
    samples = [pb.make_sample(c, "x" * 60) for c in plan]
    ok, issues = vb.gate_distribution(samples)
    assert ok, issues
