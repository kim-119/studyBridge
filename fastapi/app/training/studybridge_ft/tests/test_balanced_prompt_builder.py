from app.training.studybridge_ft.balanced.balanced_sampler import Cell
from app.training.studybridge_ft.balanced import prompt_builder_balanced as pb


def _cell(domain="화학", sub="유기화학", task="concept", diff="학사", persona="default"):
    return Cell(domain, sub, task, diff, persona)


def test_prompt_injects_domain_and_difficulty():
    sysp, userp = pb.build(_cell())
    assert "화학" in userp and "유기화학" in userp
    assert pb.DIFFICULTY_DEPTH["학사"] in sysp


def test_anti_bias_constraint_present():
    _, userp = pb.build(_cell(domain="의학/보건", sub="약리학"))
    assert "운동량" in userp and "인공지능" in userp  # 남용 금지 명시
    assert "다른 학문" in userp


def test_risk_domain_safe_note():
    sysp, _ = pb.build(_cell(domain="의학/보건", sub="약리학"))
    assert "처방" in sysp or "교육용" in sysp


def test_professor_persona_isolated():
    sysp, userp = pb.build(_cell(task="professor", persona="비판형"))
    assert "비판형" in sysp
    assert "다른 교수" in sysp


def test_quiz_asks_json():
    _, userp = pb.build(_cell(task="quiz"))
    assert "JSON" in userp and "answer" in userp and "source_hint" in userp


def test_make_sample_has_metadata():
    s = pb.make_sample(_cell(domain="법/정책", sub="헌법", task="debate", diff="박사"), "내용")
    md = s["metadata"]
    assert md["domain"] == "법/정책" and md["task_type"] == "debate"
    assert md["difficulty"] == "박사" and md["source_style"]
    roles = [m["role"] for m in s["messages"]]
    assert roles == ["system", "user", "assistant"]
