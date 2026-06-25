from app.training.studybridge_ft.balanced import balanced_sampler as bs
from app.training.studybridge_ft.balanced import taxonomy as tx


def test_plan_total_exact():
    plan = bs.build_plan(2400, seed=42)
    assert len(plan) == 2400


def test_plan_deterministic():
    a = bs.build_plan(960, seed=7)
    b = bs.build_plan(960, seed=7)
    assert a == b
    c = bs.build_plan(960, seed=8)
    assert a != c  # 다른 seed면 순서 다름


def test_distribution_within_caps():
    plan = bs.build_plan(2400, seed=42)
    ok, issues = bs.check_distribution(plan)
    assert ok, f"분포 캡 위반: {issues}"


def test_all_domains_present_even_small():
    # 스펙 23: 작아도 모든 학문 최소 1회
    plan = bs.build_plan(120, seed=1)
    doms = {c.domain for c in plan}
    assert doms == set(tx.all_domains())


def test_professor_uses_personas():
    plan = bs.build_plan(960, seed=3)
    prof_personas = {c.persona for c in plan if c.task_type == "professor"}
    assert prof_personas == set(tx.PERSONAS)
    # 비professor는 default
    assert all(c.persona == "default" for c in plan if c.task_type != "professor")


def test_subdomain_rotation():
    plan = bs.build_plan(2400, seed=42)
    # 물리학이 운동량 한 주제로만 쏠리지 않음 — 세부주제 다수 등장
    phys_subs = {c.subdomain for c in plan if c.domain == "물리학"}
    assert len(phys_subs) >= 4
