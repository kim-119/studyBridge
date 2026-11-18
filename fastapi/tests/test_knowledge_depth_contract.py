from app.studymate import knowledge_policy as KP
from app.studymate import plan_schema as PS
from app.studymate import prompt_compiler as PC
from app.studymate.profile_contract import KNOWLEDGE_KEYS


def test_level_blocks_distinct_and_not_length_based():
    blocks = {l: PC.knowledge_block(l) for l in KNOWLEDGE_KEYS}
    assert len(set(blocks.values())) == 5
    for b in blocks.values():
        assert "글자" not in b and "자 이상" not in b


def test_required_behaviors_per_level():
    assert "why it matters" in PC.knowledge_block("beginner")
    assert "트레이드오프" in PC.knowledge_block("master")
    phd = PC.knowledge_block("phd")
    assert "가정" in phd and "한계" in phd and "경계조건" in phd
    ex = PC.knowledge_block("expert")
    for w in ("신뢰성", "관측 가능성", "용량", "보안"):
        assert w in ex


def test_evidence_policy_only_high_levels():
    for l in KNOWLEDGE_KEYS:
        assert (KP.EVIDENCE_POLICY in PC.knowledge_block(l)) == (l in ("phd", "expert"))


def test_plan_overlay_required_fields_differ():
    fields = {l: set(PS.required_fields("logical", l)) for l in KNOWLEDGE_KEYS}
    assert "why_it_matters" in fields["beginner"] and "boundary_conditions" in fields["phd"]
    assert "operational_tradeoffs" in fields["expert"] and fields["master"] != fields["phd"]
