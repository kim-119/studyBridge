from app.studymate import plan_schema as PS
from app.studymate.profile_contract import KNOWLEDGE_KEYS, PERSONALITY_KEYS


def test_persona_knowledge_required_fields_in_schema():
    s = PS.agent_plan_schema("critical", "phd")
    req = set(s["required"])
    assert {"assumptions", "counterexamples", "limitations", "boundary_conditions", "claims"} <= req
    assert s["properties"]["counterexamples"]["minItems"] >= 1
    s2 = PS.agent_plan_schema("creative", "beginner")
    assert {"cross_domain_connections", "alternative_views", "why_it_matters", "concrete_example"} <= set(s2["required"])
    s3 = PS.agent_plan_schema("logical", "expert")
    assert s3["properties"]["premises"]["minItems"] == 2 and "operational_tradeoffs" in s3["required"]


def test_all_combos_build():
    for p in PERSONALITY_KEYS:
        for l in KNOWLEDGE_KEYS:
            assert PS.agent_plan_schema(p, l)["required"]


def test_validator_detects_violations():
    s = PS.agent_plan_schema("critical", "bachelor")
    bad = {"claims": ["하나만"], "counterexamples": [], "limitations": ["l"], "definition": "d", "mechanism": ["m1"]}
    errs = PS.validate(bad, s)
    assert any("claims" in e for e in errs) and any("counterexamples" in e for e in errs)


def test_contribution_text_shares_claims_not_prose():
    t = PS.plan_to_contribution_text({"claims": ["A 주장"], "counterexamples": ["반례1"]}, others_claims=["B 주장"])
    assert "반례1" in t and "B 주장" in t and "반복 금지" in t
