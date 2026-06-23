"""
studymate_discussion_planner 단위 테스트.

플래너는 순수 함수(시드 주면 재현)다. 기본개념모드에서 N명 에이전트 + 질문을 받아
'발화 계획'(speech act 순서)을 만든다. 답변(DIRECT_ANSWER+REACTION)은 확률적으로
[min,max]=[3,7] 개가 나오고, 항상 첫 발화는 질문 직답, 마지막은 사용자용 정리(WRAP)다.
"""
from collections import Counter

import pytest

from app.services.studymate_discussion_planner import (
    ACT_DIRECT_ANSWER,
    ACT_REACTION,
    ACT_WRAP,
    SpeechAct,
    plan_discussion,
)


def _answers(acts):
    """WRAP을 제외한 실제 답변 act만."""
    return [a for a in acts if a.act_type in (ACT_DIRECT_ANSWER, ACT_REACTION)]


# ── 기본 불변식 ──────────────────────────────────────────────────────────────
def test_first_act_is_direct_answer():
    acts = plan_discussion(["a", "b", "c"], seed=1)
    assert acts[0].act_type == ACT_DIRECT_ANSWER
    assert acts[0].target_id is None


def test_last_act_is_wrap():
    acts = plan_discussion(["a", "b", "c"], seed=1)
    assert acts[-1].act_type == ACT_WRAP
    assert acts[-1].target_id is None


def test_exactly_one_wrap():
    acts = plan_discussion(["a", "b", "c"], seed=7)
    assert sum(1 for a in acts if a.act_type == ACT_WRAP) == 1


def test_three_agents_answer_count_in_band():
    for seed in range(50):
        acts = plan_discussion(["a", "b", "c"], seed=seed)
        n = len(_answers(acts))
        assert 3 <= n <= 7, f"seed={seed} produced {n} answers"


def test_base_round_covers_every_agent_once():
    # 답변의 floor는 기본 라운드: 각 에이전트가 최소 1번 DIRECT_ANSWER로 등장.
    acts = plan_discussion(["a", "b", "c"], seed=3)
    direct_speakers = {a.speaker_id for a in acts if a.act_type == ACT_DIRECT_ANSWER}
    assert direct_speakers == {"a", "b", "c"}


# ── REACTION 유효성 ──────────────────────────────────────────────────────────
def test_reactions_have_distinct_valid_target():
    agents = ["a", "b", "c"]
    for seed in range(50):
        acts = plan_discussion(agents, seed=seed)
        for a in acts:
            if a.act_type == ACT_REACTION:
                assert a.target_id in agents
                assert a.target_id != a.speaker_id, f"seed={seed} self-react"


def test_no_immediate_duplicate_reaction_pair():
    agents = ["a", "b", "c"]
    for seed in range(50):
        acts = plan_discussion(agents, seed=seed)
        reacts = [a for a in acts if a.act_type == ACT_REACTION]
        for prev, cur in zip(reacts, reacts[1:]):
            assert (prev.speaker_id, prev.target_id) != (cur.speaker_id, cur.target_id), (
                f"seed={seed} immediate duplicate reaction pair"
            )


# ── 재현성(시드) ─────────────────────────────────────────────────────────────
def test_same_seed_is_reproducible():
    a1 = plan_discussion(["a", "b", "c"], seed=42)
    a2 = plan_discussion(["a", "b", "c"], seed=42)
    assert a1 == a2


def test_different_seeds_vary():
    # 여러 시드에서 적어도 두 가지 이상의 서로 다른 계획이 나온다(확률성 확인).
    plans = {tuple((a.act_type, a.speaker_id, a.target_id) for a in plan_discussion(["a", "b", "c"], seed=s))
             for s in range(30)}
    assert len(plans) >= 2


# ── 분포 ─────────────────────────────────────────────────────────────────────
def test_distribution_centers_above_floor():
    # 충분한 시드에서 평균 답변 수가 floor(3)보다 확실히 커야 한다(추가 반응이 실제로 붙음).
    counts = [len(_answers(plan_discussion(["a", "b", "c"], seed=s))) for s in range(300)]
    avg = sum(counts) / len(counts)
    assert avg > 3.5, f"avg={avg} — 추가 반응이 거의 안 붙음"
    assert max(counts) == 7, "최대 7에 도달하는 시드가 있어야 함"
    assert min(counts) == 3, "최소 3으로 떨어지는 시드가 있어야 함"


# ── 에이전트 수 엣지 ─────────────────────────────────────────────────────────
def test_two_agents_padded_to_min():
    for seed in range(30):
        acts = plan_discussion(["a", "b"], seed=seed)
        assert len(_answers(acts)) >= 3, f"seed={seed}: 2명도 최소 3 답변"
        assert acts[0].act_type == ACT_DIRECT_ANSWER
        assert acts[-1].act_type == ACT_WRAP


def test_many_agents_capped_at_max():
    agents = [f"ag{i}" for i in range(10)]
    for seed in range(30):
        acts = plan_discussion(agents, seed=seed)
        assert len(_answers(acts)) <= 7, f"seed={seed}: 10명이어도 최대 7"


def test_single_agent_no_self_reaction():
    # 1명뿐이면 반응 대상이 없으므로 자기반응을 만들지 않는다(직답 + 정리).
    acts = plan_discussion(["solo"], seed=1)
    assert acts[0].act_type == ACT_DIRECT_ANSWER
    assert acts[-1].act_type == ACT_WRAP
    assert all(a.act_type != ACT_REACTION for a in acts)


# ── 커스텀 band ──────────────────────────────────────────────────────────────
def test_custom_min_max_band_respected():
    for seed in range(50):
        acts = plan_discussion(["a", "b", "c", "d"], seed=seed, min_acts=4, max_acts=5)
        n = len(_answers(acts))
        assert 4 <= n <= 5, f"seed={seed}: custom band violated ({n})"


def test_speechact_is_hashable_frozen():
    s = SpeechAct(speaker_id="a", act_type=ACT_DIRECT_ANSWER, target_id=None)
    {s}  # frozen/hashable
    with pytest.raises(Exception):
        s.speaker_id = "b"  # type: ignore[misc]
