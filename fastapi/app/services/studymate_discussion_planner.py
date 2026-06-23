"""
StudyMate 기본개념모드 '확률적 다중답변 피드백' 발화 플래너.

에이전트가 3명이라도 답변이 정확히 3개가 아니라, 확률적으로 [min,max]=[3,7] 개가 나오게
한다. 에이전트끼리 서로 반박/보완하되, 항상 사용자가 중심이 되도록:
- 첫 발화는 무조건 질문 직답(DIRECT_ANSWER)
- 마지막은 무조건 사용자용 정리(WRAP)
- 중간 반응(REACTION)은 다른 에이전트를 향하지만 결국 사용자에게 설명(프롬프트 계약은 wiring에서)

이 모듈은 LLM을 호출하지 않는 순수 함수다(시드 주면 재현). qwen3 빈응답/think 토큰 이슈를
중간 판단에 끌어들이지 않으려는 의도적 결정론 설계.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

ACT_DIRECT_ANSWER = "DIRECT_ANSWER"
ACT_REACTION = "REACTION"
ACT_WRAP = "WRAP"

# 추가 반응 개수(기본 라운드 위에 더 붙는 REACTION 수)의 가중치. 합이 1일 필요는 없다.
# 중심을 ~2개에 두어 총 답변이 ~4-5에 몰리도록 한다.
DEFAULT_EXTRA_WEIGHTS: Dict[int, float] = {0: 0.10, 1: 0.20, 2: 0.30, 3: 0.25, 4: 0.15}


@dataclass(frozen=True)
class SpeechAct:
    """한 번의 발화 계획. speaker가 act_type을 수행하며, REACTION이면 target을 향한다."""

    speaker_id: str
    act_type: str
    target_id: Optional[str] = None


def _weighted_extra(rng: random.Random, weights: Dict[int, float], cap: int) -> int:
    """가중치에서 추가 반응 개수를 뽑되, cap을 넘지 않게 제한한다."""
    items = [(k, w) for k, w in weights.items() if 0 <= k <= cap and w > 0]
    if not items:
        return 0
    total = sum(w for _, w in items)
    r = rng.random() * total
    acc = 0.0
    for k, w in items:
        acc += w
        if r <= acc:
            return k
    return items[-1][0]


def _pick_reaction_pair(
    rng: random.Random, agent_ids: Sequence[str], prev_pair: Optional[tuple]
) -> Optional[tuple]:
    """자기자신 금지 + 직전 동일 쌍 즉시 반복 회피로 (reactor, target)를 고른다."""
    pairs = [(r, t) for r in agent_ids for t in agent_ids if r != t]
    if not pairs:
        return None
    avoid_dup = [p for p in pairs if p != prev_pair]
    return rng.choice(avoid_dup or pairs)


def plan_discussion(
    agent_ids: Sequence[str],
    *,
    seed: Optional[int] = None,
    min_acts: int = 3,
    max_acts: int = 7,
    weights: Optional[Dict[int, float]] = None,
) -> List[SpeechAct]:
    """
    발화 계획을 만든다.

    - 답변(DIRECT_ANSWER + REACTION) 수는 [min_acts, max_acts]로 클램프된다.
    - 첫 act는 DIRECT_ANSWER, 마지막 act는 WRAP(항상 1개).
    - 에이전트 2명 미만이면 REACTION을 만들 수 없으므로(대상 부재) floor 강제는 best-effort.
    """
    ids = list(agent_ids)
    weights = weights or DEFAULT_EXTRA_WEIGHTS
    rng = random.Random(seed)

    if not ids:
        return [SpeechAct("agent", ACT_WRAP, None)]

    # 1) 기본 라운드: 가중 셔플 후 max_acts로 캡. 각 에이전트가 질문에 직답.
    shuffled = rng.sample(ids, len(ids))
    base_ids = shuffled[:max_acts]
    acts: List[SpeechAct] = [SpeechAct(a, ACT_DIRECT_ANSWER, None) for a in base_ids]
    base_count = len(acts)

    # 2) 추가 반응 개수 결정. 2명 미만이면 반응 불가.
    can_react = len(ids) >= 2
    num_reactions = 0
    if can_react:
        floor_pad = max(0, min_acts - base_count)
        capacity = max(0, max_acts - base_count - floor_pad)
        extra = _weighted_extra(rng, weights, capacity)
        num_reactions = floor_pad + extra

    # 3) 반응 act 추가(자기자신 금지 + 직전 쌍 반복 회피).
    prev_pair: Optional[tuple] = None
    for _ in range(num_reactions):
        pair = _pick_reaction_pair(rng, ids, prev_pair)
        if pair is None:
            break
        prev_pair = pair
        acts.append(SpeechAct(pair[0], ACT_REACTION, pair[1]))

    # 4) 마지막 사용자용 정리(WRAP) — 항상 1개.
    wrap_speaker = rng.choice(ids)
    acts.append(SpeechAct(wrap_speaker, ACT_WRAP, None))
    return acts
