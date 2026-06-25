from app.training.studybridge_ft.balanced import split_balanced as sp
from app.training.studybridge_ft.balanced import prompt_builder_balanced as pb
from app.training.studybridge_ft.balanced.balanced_sampler import build_plan


def _samples(total, seed=42):
    return [pb.make_sample(c, f"내용 {i} " + "가" * 60) for i, c in enumerate(build_plan(total, seed))]


def test_split_sums_to_input_after_dedup():
    s = _samples(480)
    r = sp.split(s, seed=0)
    assert len(r["train"]) + len(r["valid"]) + len(r["test"]) == len(s)


def test_split_train_majority():
    s = _samples(2400)
    r = sp.split(s, seed=0)
    assert len(r["train"]) >= 0.8 * len(s)


def test_split_preserves_domain_coverage():
    s = _samples(2400)
    r = sp.split(s, seed=0)
    train_domains = {x["metadata"]["domain"] for x in r["train"]}
    assert len(train_domains) == 12  # 모든 학문이 train에 존재


def test_split_deterministic():
    s = _samples(480)
    a = sp.split(s, seed=1)
    b = sp.split(s, seed=1)
    assert [x["messages"] for x in a["train"]] == [x["messages"] for x in b["train"]]


def test_split_valid_nonempty():
    # 잘게 쪼개진 strata(도메인×task×난이도)에서도 validation이 굶지 않아야 한다.
    # (회귀: per-stratum 정수 반올림이 valid를 항상 0으로 만들어 학습 로더가 죽던 버그)
    s = _samples(2400)
    r = sp.split(s, seed=0)
    assert len(r["valid"]) > 0
    assert len(r["test"]) > 0


def test_split_ratios_approximate():
    s = _samples(2400)
    n = len(s)
    r = sp.split(s, ratios=(0.90, 0.05, 0.05), seed=0)
    # 전역 비율이 대략 보존(층화 반올림 허용오차)
    assert 0.85 * n <= len(r["train"]) <= 0.93 * n
    assert 0.02 * n <= len(r["valid"]) <= 0.09 * n
    assert 0.02 * n <= len(r["test"]) <= 0.09 * n
