"""Shared Contribution Planner — 턴당 1회 구조화 plan(JSON Schema 강제).

잘못된 구조: planner A + render A, planner B + render B, planner C + render C
이 구조:     shared planner 1회 → render A/B/C
단일 교수 basic 은 planner 를 호출하지 않는다(direct). 단, 고수준(phd/expert) 복잡 질문은
개별 plan 이 가치가 있으므로 env STUDYMATE_INDIVIDUAL_PLAN=auto 에서만 1회 plan 한다.
"""
from __future__ import annotations

import logging
import os
import re
import zlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.studymate import knowledge_policy as KP
from app.studymate import llm_gateway as G
from app.studymate import mode_policy as MP
from app.studymate import model_router
from app.studymate import persona_policy as PP
from app.studymate import plan_schema as PS
from app.studymate import quality as Q
from app.studymate.profile_contract import CanonicalAgent

logger = logging.getLogger("studybridge.studymate.planner")

_COMPLEX = re.compile(r"(비교|차이|왜|설계|트레이드오프|한계|장단점|원리|증명|어떻게 동작|아키텍처|최적화|분석)")


@dataclass
class PlanOutcome:
    plans: Dict[str, Optional[Dict[str, Any]]]
    source: str                      # direct | shared | individual | fallback
    llm_calls: int = 0
    repair_used: bool = False
    errors: List[str] = field(default_factory=list)
    elapsed_ms: int = 0
    prompt_eval_count: Optional[int] = None
    eval_count: Optional[int] = None
    novel_claims: Dict[str, List[str]] = field(default_factory=dict)
    focus: str = ""


def is_complex(question: str) -> bool:
    return len(question or "") >= 25 or bool(_COMPLEX.search(question or ""))


def individual_plan_enabled(agent: CanonicalAgent, question: str) -> bool:
    mode = (os.getenv("STUDYMATE_INDIVIDUAL_PLAN", "auto") or "auto").strip().lower()
    if mode == "off":
        return False
    if mode == "on":
        return True
    # 고수준(phd/expert)은 짧은 질문이라도 가정·경계조건/운영제약 구조가 핵심이라 개별 plan 을 만든다
    # (2026-09-17 라이브: 전문가 직답이 교과서식으로 붕괴 → 독립 분류 학사 2/3).
    return agent.knowledgeLevelKey in ("phd", "expert")


def _agent_line(a: CanonicalAgent, role: str) -> str:
    s = PP.STRATEGY[a.personalityKey]
    k = KP.CONTRACT[a.knowledgeLevelKey]
    fields = ", ".join(PS.required_fields(a.personalityKey, a.knowledgeLevelKey).keys())
    return (f"- agentId={a.agentId} | 역할={role}({MP.ROLE_CONTRACT.get(role, '')}) | "
            f"성격={s['name']}({s['thinking'].split('방식으로')[0].strip()[:60]}) | 수준={k['name']} | 채울 필드: {fields}")


def _system(n: int) -> str:
    return (
        "너는 여러 교수가 한 질문에 협업 답변할 때 각 교수의 '정보 기여'를 설계하는 Contribution Planner다.\n"
        "규칙:\n"
        "1) 교수마다 겹치지 않는 주장(claims)을 배정한다. 같은 주장을 두 교수에게 주지 않는다.\n"
        "2) 각 교수의 성격 필드와 지식수준 필드를 그 교수의 관점으로 채운다(말투가 아니라 내용 설계).\n"
        "3) 모든 값은 25자 이내의 짧은 명사구로 쓴다. 완성된 문장·설명을 쓰지 않는다. JSON 은 줄바꿈/들여쓰기 없이 한 줄로.\n"
        "4) 확실하지 않은 수치·논문·버전은 쓰지 않는다. 필요하면 조건으로 쓴다.\n"
        "5) JSON 만 출력한다." if n > 1 else
        "너는 교수 1명의 답변을 설계하는 Planner다. 성격 필드와 지식수준 필드를 25자 이내 명사구로 채운다. "
        "완성 문장을 쓰지 않는다. 확실하지 않은 수치·논문·버전은 쓰지 않는다. JSON 만 출력한다."
    )


def _user(question: str, agents: List[CanonicalAgent], roles: Dict[str, str], grounding_hint: str,
          summary: str, errors: Optional[List[str]] = None) -> str:
    parts = []
    if summary:
        parts.append(f"[대화 요약]\n{summary[:600]}")
    if grounding_hint:
        parts.append(f"[근거 자료 요약]\n{grounding_hint[:1200]}")
    parts.append("[교수 배정]\n" + "\n".join(_agent_line(a, roles[a.agentId]) for a in agents))
    if errors:
        parts.append("[이전 출력의 스키마 위반 — 이번에는 반드시 고쳐라]\n" + "\n".join(f"- {e}" for e in errors[:10]))
    parts.append(f"[질문]\n{question}")
    return "\n\n".join(parts)


def _seed(turn_id: str, salt: str) -> int:
    return zlib.crc32(f"{turn_id}:{salt}".encode("utf-8")) & 0x7FFFFFFF


def plan_turn(question: str, agents: List[CanonicalAgent], roles: Dict[str, str], *,
              grounding_hint: str = "", summary: str = "", turn_id: str = "",
              cancel=None, budget=None, force_direct: bool = False) -> PlanOutcome:
    import time
    t0 = time.time()
    if force_direct:
        return PlanOutcome(plans={a.agentId: None for a in agents}, source="direct")
    if len(agents) == 1 and not individual_plan_enabled(agents[0], question):
        return PlanOutcome(plans={agents[0].agentId: None}, source="direct")
    if budget is not None and not budget.allows("planner"):
        logger.warning("[PLANNER] budget 부족 → 결정론 plan")
        return _fallback(question, agents, roles, ["budget_skip"], t0)

    single = len(agents) == 1
    schema = (PS.single_plan_schema(agents[0].personalityKey, agents[0].knowledgeLevelKey) if single
              else PS.shared_plan_schema([(a.agentId, a.personalityKey, a.knowledgeLevelKey) for a in agents]))
    top_level = max((a.knowledgeLevelKey for a in agents), key=lambda l: KP_ORDER.get(l, 1))
    opts = model_router.resolve("planner", level=top_level, complex_question=is_complex(question),
                                seed=_seed(turn_id, "planner"))
    predict = opts.num_predict if not single else min(opts.num_predict, 700)
    if opts.think:
        predict += int(os.getenv("STUDYMATE_PLANNER_THINK_BUDGET", "600"))
    errors: List[str] = []
    outcome = PlanOutcome(plans={}, source="individual" if single else "shared")
    for attempt in range(2):     # 최초 1 + repair 1 (bounded)
        req = G.LLMRequest(system=_system(len(agents)),
                           user=_user(question, agents, roles, grounding_hint, summary, errors or None),
                           model=opts.model, num_ctx=opts.num_ctx, num_predict=predict,
                           temperature=opts.temperature, top_p=opts.top_p, seed=opts.seed,
                           think=opts.think, format=schema, timeout_s=opts.timeout_s, task="planner")
        try:
            res = G.generate(req, cancel=cancel, deadline=budget.deadline if budget else None)
        except G.LLMError as e:
            logger.warning("[PLANNER] LLM 실패 code=%s detail=%s → 결정론 plan", e.code, e.detail[:120])
            return _fallback(question, agents, roles, [e.code], t0, outcome.llm_calls + 1)
        outcome.llm_calls += 1
        outcome.prompt_eval_count, outcome.eval_count = res.prompt_eval_count, res.eval_count
        obj = PS.parse_json(res.content)
        errors = PS.validate(obj, schema) if obj is not None else ["$: invalid json"]
        if not errors:
            break
        outcome.repair_used = attempt == 0
        if budget is not None and not budget.allows("planner"):
            break
    if errors:
        logger.warning("[PLANNER] 스키마 검증 실패 → 결정론 plan errors=%s eval=%s", errors[:5], outcome.eval_count)
        return _fallback(question, agents, roles, errors, t0, outcome.llm_calls)

    if single:
        outcome.plans = {agents[0].agentId: obj}
    else:
        outcome.plans = {a.agentId: obj["agents"][a.agentId] for a in agents}
        outcome.focus = str(obj.get("question_focus") or "")
    # 신규성: 앞 교수들의 claim 과 겹치지 않는 claim 이 최소 1개 있어야 한다.
    seen: List[str] = []
    for a in agents:
        claims = [str(c) for c in (outcome.plans[a.agentId] or {}).get("claims", [])]
        outcome.novel_claims[a.agentId] = Q.novel_claims(claims, seen)
        seen.extend(claims)
    outcome.elapsed_ms = int((time.time() - t0) * 1000)
    return outcome


KP_ORDER = {"beginner": 0, "bachelor": 1, "master": 2, "phd": 3, "expert": 4}


def _fallback(question, agents, roles, errors, t0, calls=0) -> PlanOutcome:
    import time
    plans = {a.agentId: PS.minimal_plan(a.personalityKey, a.knowledgeLevelKey, question, roles[a.agentId])
             for a in agents}
    return PlanOutcome(plans=plans, source="fallback", llm_calls=calls, errors=list(errors)[:10],
                       elapsed_ms=int((time.time() - t0) * 1000),
                       novel_claims={a.agentId: [] for a in agents})
