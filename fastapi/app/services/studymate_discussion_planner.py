"""
StudyMate 기본개념모드 — 확률적 다중답변 발화 플래너 (순수 결정론).

목적: 에이전트가 N명이라도 답변이 정확히 N개로 고정되지 않고, 확률적으로
최소~최대(기본 3~7) 사이의 답변이 나오게 한다. 에이전트끼리 서로 반박/보완하되
항상 사용자가 중심이 되도록, 첫 발화는 직접 답변, 마지막 발화는 한 줄 정리로 못박는다.

이 모듈은 LLM을 호출하지 않는다(시드를 주면 완전히 재현 가능). 실제 문장 생성은
multi_agent_service의 기존 생성 함수(_stage1_initial / _stage3_feedback /
_generate_synthesis)가 act_type에 따라 담당한다. 여기서는 "누가, 어떤 행위로,
누구를 향해" 발화할지의 순서(speech act plan)만 만든다.

설계 doc: docs/superpowers/specs/2026-06-23-studymate-personality-emphasis-discussion-planner-design.md (섹션 B)

카운트 의미(확정):
  - 답변 카운트 = DIRECT_ANSWER + REACTION 개수. [min,max](기본 3~7)는 이 카운트에 적용.
  - WRAP(한 줄 정리)은 답변이 아니라 마무리이므로 항상 끝에 1개 추가하되 카운트에서 제외.

qwen3 빈응답 이슈(think 토큰 소진)를 피하려고 플래너 중간에 LLM 판단을 끼우지 않는다.
"""
from __future__ import annotations

import os
import random
from collections import namedtuple
from typing import List, Optional

# ── 행위 유형 상수 ─────────────────────────────────────────────────────────────
DIRECT_ANSWER = "DIRECT_ANSWER"   # 질문에 직접 답(기본 라운드) — _stage1_initial
REACTION = "REACTION"             # 다른 에이전트 답에 반박/보완 — _stage3_feedback
WRAP = "WRAP"                     # 사용자용 한 줄 정리 + 다음 질문 — _generate_synthesis

# Act: 하나의 발화 계획. target은 REACTION일 때만 대상 에이전트 id, 그 외 None.
Act = namedtuple("Act", ["speaker", "act_type", "target"])

# 추가 반응(REACTION) 개수의 기본 가중치. 총 답변이 ~4-5개에 몰리도록.
# index = 추가 반응 개수, 값 = 상대 가중치.
_REACTION_WEIGHTS = [10, 20, 30, 25, 15]  # 0→10%, 1→20%, 2→30%, 3→25%, 4→15%


# ── env helpers ────────────────────────────────────────────────────────────────
def default_min() -> int:
    try:
        return int(os.getenv("STUDYMATE_DISCUSSION_MIN", "3"))
    except (TypeError, ValueError):
        return 3


def default_max() -> int:
    try:
        return int(os.getenv("STUDYMATE_DISCUSSION_MAX", "7"))
    except (TypeError, ValueError):
        return 7


def planner_enabled() -> bool:
    """off/false/0 이면 비활성(기존 1인1답으로 롤백)."""
    val = os.getenv("STUDYMATE_DISCUSSION_PLANNER", "on").strip().lower()
    return val not in ("off", "false", "0", "no", "")


# ── 핵심 플래너 ────────────────────────────────────────────────────────────────
def plan_discussion(
    agent_ids: List[str],
    *,
    seed: Optional[int] = None,
    min_answers: Optional[int] = None,
    max_answers: Optional[int] = None,
    include_wrap: bool = False,
) -> List[Act]:
    """N명 에이전트 + 질문에 대한 발화 계획을 만든다.

    반환: Act 리스트. 첫 Act는 DIRECT_ANSWER.
    답변(DIRECT_ANSWER+REACTION) 개수는 [min_answers, max_answers]로 클램프.
    WRAP(한 줄 정리)은 온디맨드: include_wrap=True 일 때만 맨 끝에 정확히 1개 추가한다
    (사용자가 정리/요약을 요청했을 때만). 기본 턴은 직접답변+반박만.
    """
    if not agent_ids:
        return []

    lo = min_answers if min_answers is not None else default_min()
    hi = max_answers if max_answers is not None else default_max()
    if lo < 1:
        lo = 1
    if hi < lo:
        hi = lo

    rng = random.Random(seed)
    n = len(agent_ids)

    # 1) 기본 라운드(floor): 앞 min(N, hi)명이 distinct DIRECT_ANSWER 1번씩.
    base_count = min(n, hi)
    base_agents = list(agent_ids[:base_count])
    rng.shuffle(base_agents)
    acts: List[Act] = [Act(a, DIRECT_ANSWER, None) for a in base_agents]

    # 2) 추가 반응 개수 결정. 답변 총합을 [lo, hi]로 강제.
    #    reactions 가능 범위: [lo - base_count, hi - base_count] 를 0 미만은 0으로.
    reaction_min = max(0, lo - base_count)
    reaction_max = max(0, hi - base_count)

    # 반응 대상이 2명 미만이면(에이전트 1명) 반응 불가 → padding도 포기.
    if base_count < 2:
        reaction_min = reaction_max = 0

    extra = _sample_reaction_count(rng, reaction_min, reaction_max)

    # 3) 반응 (reactor, target) 쌍 생성 — self 금지, 직전 동일쌍 즉시반복 회피.
    pool = base_agents  # 답변에 참여한 에이전트들끼리 상호작용
    prev_pair: Optional[tuple] = None
    for _ in range(extra):
        pair = _pick_reaction_pair(rng, pool, prev_pair)
        if pair is None:
            break
        acts.append(Act(pair[0], REACTION, pair[1]))
        prev_pair = pair

    # 4) 마지막 WRAP — 온디맨드(사용자 정리 요청 시에만). 화자는 무작위 에이전트.
    if include_wrap:
        wrap_speaker = rng.choice(base_agents)
        acts.append(Act(wrap_speaker, WRAP, None))

    return acts


# ── 내부 helpers ───────────────────────────────────────────────────────────────
def _sample_reaction_count(rng: random.Random, lo: int, hi: int) -> int:
    """[lo, hi] 범위에서 가중치(_REACTION_WEIGHTS)를 따라 추가 반응 개수를 뽑는다."""
    if hi <= lo:
        return lo
    candidates = list(range(lo, hi + 1))
    weights = [_REACTION_WEIGHTS[c] if c < len(_REACTION_WEIGHTS) else 1 for c in candidates]
    return rng.choices(candidates, weights=weights, k=1)[0]


def _pick_reaction_pair(rng: random.Random, pool: List[str], prev_pair) -> Optional[tuple]:
    """self 금지 + 직전 동일쌍 즉시반복 회피 조건으로 (reactor, target)을 고른다."""
    if len(pool) < 2:
        return None
    # 최대 몇 번 재시도해서 prev_pair와 다른 쌍을 찾는다. 못 찾으면 self만 피한 쌍 허용.
    fallback: Optional[tuple] = None
    for _ in range(12):
        reactor = rng.choice(pool)
        target = rng.choice(pool)
        if reactor == target:
            continue
        pair = (reactor, target)
        fallback = pair
        if pair != prev_pair:
            return pair
    return fallback
