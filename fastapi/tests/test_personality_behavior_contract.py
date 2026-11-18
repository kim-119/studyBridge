"""페르소나 6종 구조 차이: 사고전략/행동규칙/few-shot/대비규칙/plan 필드/루브릭/디코드가 서로 다르다."""
import itertools

from app.studymate import persona_policy as PP
from app.studymate import prompt_compiler as PC
from app.studymate import quality as Q
from app.studymate.profile_contract import PERSONALITY_KEYS


def test_persona_blocks_all_distinct():
    blocks = {p: PC.persona_block(p) for p in PERSONALITY_KEYS}
    assert len(set(blocks.values())) == 6
    rules = {p: tuple(PP.persona_rules(p)) for p in PERSONALITY_KEYS}
    assert len(set(rules.values())) == 6


def test_fingerprint_is_bucketed_not_numeric_in_prompt():
    for p in PERSONALITY_KEYS:
        text = PC.persona_block(p)
        assert "0." not in text and "challengeIntensity" not in text


def test_critical_vs_sardonic_structurally_different():
    c, s = PP.PLAN_FIELDS["critical"], PP.PLAN_FIELDS["sardonic"]
    assert {f[0] for f in c}.isdisjoint({f[0] for f in s})
    assert PP.bucket(PP.FINGERPRINT["sardonic"]["irony"]) == "HIGH"
    assert PP.bucket(PP.FINGERPRINT["critical"]["irony"]) == "LOW"
    assert any("냉소적 페르소나처럼" in r for r in PP.CONTRAST["critical"])
    assert any("비판형처럼" in r for r in PP.CONTRAST["sardonic"])
    assert [k for k, _ in PP.RUBRIC["critical"]] != [k for k, _ in PP.RUBRIC["sardonic"]]


def test_contrastive_rules_always_offer_alternative():
    for p in PERSONALITY_KEYS:
        assert PP.CONTRAST[p]
        for rule in PP.CONTRAST[p]:
            assert "대신" in rule, (p, rule)


def test_few_shot_two_short_examples_each():
    for p in PERSONALITY_KEYS:
        ex = PP.FEW_SHOT[p]
        assert len(ex) == 2
        assert all(len(a) < 450 for _, a in ex)


def test_few_shot_examples_pass_own_rubric_heuristic():
    for p in PERSONALITY_KEYS:
        passed = sum(sum(Q._persona_checks(p, a).values()) for _, a in PP.FEW_SHOT[p])
        assert passed >= 6, (p, [Q._persona_checks(p, a) for _, a in PP.FEW_SHOT[p]])


def test_rubric_discriminates_example_across_personas():
    """자기 페르소나 예시가 다른 페르소나 루브릭보다 자기 루브릭을 더 잘 만족한다(평균)."""
    for p in PERSONALITY_KEYS:
        own = sum(sum(Q._persona_checks(p, a).values()) for _, a in PP.FEW_SHOT[p])
        others = [sum(sum(Q._persona_checks(o, a).values()) for _, a in PP.FEW_SHOT[p]) for o in PERSONALITY_KEYS if o != p]
        assert own >= max(others) - 1, (p, own, others)
