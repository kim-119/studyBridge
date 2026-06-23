"""
StudyMate 기본개념모드 — 확률적 다중답변 발화 플래너(순수 결정론) 계약 테스트.

플래너는 LLM을 호출하지 않는다. N명 에이전트 + 시드 → 발화 계획(Act 리스트)을
만든다. 각 Act = (speaker, act_type, target). 이 테스트는 네트워크 비의존
결정론 경로만 검증한다.

계약(설계 doc 2026-06-23 섹션 B 5.1~5.2 기준, 카운트 의미 확정):
  - act_type ∈ {DIRECT_ANSWER, REACTION, WRAP}
  - 답변 카운트 = DIRECT_ANSWER + REACTION 개수 ∈ [min_answers, max_answers] (기본 3~7)
  - WRAP(한 줄 정리)은 항상 끝에 정확히 1개 추가, 답변 카운트에서 제외
  - 첫 act = DIRECT_ANSWER, 마지막 act = WRAP
  - base round = min(N, max_answers)명이 distinct DIRECT_ANSWER 1번씩
  - REACTION: target != speaker, 유효한 에이전트, 직전 동일 (speaker,target) 즉시반복 금지
  - 동일 시드 → 동일 계획(결정론)
"""
import os
from collections import Counter

import pytest

from app.services import studymate_discussion_planner as P


AGENTS_3 = ["a1", "a2", "a3"]
AGENTS_5 = ["a1", "a2", "a3", "a4", "a5"]
AGENTS_2 = ["a1", "a2"]
AGENTS_8 = [f"a{i}" for i in range(1, 9)]


def _answers(acts):
    return [a for a in acts if a.act_type in (P.DIRECT_ANSWER, P.REACTION)]


# ── 기본 구조 ──────────────────────────────────────────────────────────────────
def test_returns_list_of_acts():
    acts = P.plan_discussion(AGENTS_3, seed=1)
    assert isinstance(acts, list)
    assert all(hasattr(a, "speaker") and hasattr(a, "act_type") and hasattr(a, "target") for a in acts)


def test_first_act_is_direct_answer():
    for seed in range(50):
        acts = P.plan_discussion(AGENTS_3, seed=seed)
        assert acts[0].act_type == P.DIRECT_ANSWER, f"seed={seed} first={acts[0]}"


def test_last_act_is_wrap_and_exactly_one():
    for seed in range(50):
        acts = P.plan_discussion(AGENTS_5, seed=seed)
        assert acts[-1].act_type == P.WRAP, f"seed={seed}"
        assert sum(1 for a in acts if a.act_type == P.WRAP) == 1, f"seed={seed}"


def test_wrap_speaker_is_valid_agent():
    for seed in range(30):
        acts = P.plan_discussion(AGENTS_3, seed=seed)
        wrap = acts[-1]
        assert wrap.speaker in AGENTS_3


# ── 카운트 불변식 ──────────────────────────────────────────────────────────────
def test_answer_count_within_bounds_default():
    for seed in range(200):
        acts = P.plan_discussion(AGENTS_3, seed=seed)
        n = len(_answers(acts))
        assert 3 <= n <= 7, f"seed={seed} answers={n}"


def test_answer_count_respects_custom_bounds():
    for seed in range(100):
        acts = P.plan_discussion(AGENTS_5, seed=seed, min_answers=4, max_answers=5)
        n = len(_answers(acts))
        assert 4 <= n <= 5, f"seed={seed} answers={n}"


def test_base_round_all_agents_direct_answer_once():
    # N <= max → 모든 에이전트가 정확히 한 번 DIRECT_ANSWER
    acts = P.plan_discussion(AGENTS_3, seed=7)
    direct_speakers = [a.speaker for a in acts if a.act_type == P.DIRECT_ANSWER]
    assert Counter(direct_speakers) == Counter(AGENTS_3)


# ── REACTION 규칙 ──────────────────────────────────────────────────────────────
def test_reactions_never_target_self_and_valid():
    for seed in range(100):
        acts = P.plan_discussion(AGENTS_5, seed=seed)
        for a in acts:
            if a.act_type == P.REACTION:
                assert a.target is not None
                assert a.target != a.speaker
                assert a.speaker in AGENTS_5 and a.target in AGENTS_5


def test_direct_and_wrap_have_no_target():
    acts = P.plan_discussion(AGENTS_3, seed=3)
    for a in acts:
        if a.act_type in (P.DIRECT_ANSWER, P.WRAP):
            assert a.target is None


def test_no_immediate_repeat_reaction_pair():
    for seed in range(100):
        acts = P.plan_discussion(AGENTS_5, seed=seed)
        reactions = [(a.speaker, a.target) for a in acts if a.act_type == P.REACTION]
        for i in range(1, len(reactions)):
            assert reactions[i] != reactions[i - 1], f"seed={seed} repeat {reactions[i]}"


# ── 결정론 ─────────────────────────────────────────────────────────────────────
def test_deterministic_same_seed():
    a = P.plan_discussion(AGENTS_5, seed=123)
    b = P.plan_discussion(AGENTS_5, seed=123)
    assert a == b


def test_different_seeds_can_differ():
    seen = {tuple(P.plan_discussion(AGENTS_5, seed=s)) for s in range(40)}
    assert len(seen) > 1


# ── 엣지 케이스 ────────────────────────────────────────────────────────────────
def test_two_agents_padded_to_min():
    for seed in range(60):
        acts = P.plan_discussion(AGENTS_2, seed=seed)
        n = len(_answers(acts))
        assert 3 <= n <= 7, f"seed={seed} answers={n}"
        assert acts[0].act_type == P.DIRECT_ANSWER
        assert acts[-1].act_type == P.WRAP


def test_eight_agents_capped_to_max():
    for seed in range(60):
        acts = P.plan_discussion(AGENTS_8, seed=seed)
        n = len(_answers(acts))
        assert n <= 7, f"seed={seed} answers={n}"
        direct = [a.speaker for a in acts if a.act_type == P.DIRECT_ANSWER]
        assert len(direct) <= 7
        assert len(set(direct)) == len(direct)  # distinct


def test_single_agent_does_not_crash():
    acts = P.plan_discussion(["solo"], seed=1)
    assert acts[0].act_type == P.DIRECT_ANSWER
    assert acts[-1].act_type == P.WRAP
    # 단일 에이전트는 REACTION 대상이 없으므로 답변은 1개(DIRECT)만
    assert all(a.act_type != P.REACTION for a in acts)


def test_empty_agents_returns_empty_or_safe():
    acts = P.plan_discussion([], seed=1)
    assert acts == []


# ── 분포(통계, 느슨한 허용오차) ────────────────────────────────────────────────
def test_reaction_count_distribution_is_centered():
    # 추가 반응이 평균적으로 1~4개 부근에 몰려야 한다(정확히 3개로 고정되지 않음).
    counts = []
    for seed in range(400):
        acts = P.plan_discussion(AGENTS_3, seed=seed)
        reactions = sum(1 for a in acts if a.act_type == P.REACTION)
        counts.append(reactions)
    mean = sum(counts) / len(counts)
    assert 1.0 <= mean <= 4.0, f"mean reactions={mean}"
    # 항상 같은 값이면 안 됨(확률적)
    assert len(set(counts)) >= 3


# ── env 기반 기본값/토글 ───────────────────────────────────────────────────────
def test_env_min_max_defaults(monkeypatch):
    monkeypatch.setenv("STUDYMATE_DISCUSSION_MIN", "3")
    monkeypatch.setenv("STUDYMATE_DISCUSSION_MAX", "7")
    assert P.default_min() == 3
    assert P.default_max() == 7


def test_planner_enabled_toggle(monkeypatch):
    monkeypatch.setenv("STUDYMATE_DISCUSSION_PLANNER", "off")
    assert P.planner_enabled() is False
    monkeypatch.setenv("STUDYMATE_DISCUSSION_PLANNER", "on")
    assert P.planner_enabled() is True
