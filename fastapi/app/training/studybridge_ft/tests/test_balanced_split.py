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
