"""BASIC 모드 적응형 파이프라인 (학습메이트 v2).

단일 교수:  PromptCompiler → direct render(1 call) → cheap validation → (조건부 judge/repair)
            단, phd/expert 복잡 질문은 개별 plan 1회(STUDYMATE_INDIVIDUAL_PLAN=auto)
다중 교수:  Shared Contribution Planner 1회(JSON schema) → 교수별 render → 검증 → (repair/regen)
            교수 간에는 원문(prose)이 아니라 plan 의 주장(claims) 목록만 공유한다.
REACTION:   확률적 발화 플래너의 반박/보완 쌍. 예산이 남을 때만 시작한다.

이벤트 불변식(한 발화 단위): agent_start → agent_answer | agent_error. 성공만 all_complete.answers 에 싣고
실패는 agentErrors 에 싣는다(Spring 은 answers 를 AI 메시지로 영속하므로 실패 문구를 섞지 않는다).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Generator, List, Optional

from app.studymate import grounding as GR
from app.studymate import llm_gateway as G
from app.studymate import memory_summary as MS
from app.studymate import mode_policy as MP
from app.studymate import plan_schema as PS
from app.studymate import planner as PL
from app.studymate.agent_executor import RenderSpec, execute
from app.studymate.budget import TurnBudget
from app.studymate.profile_contract import CanonicalAgent, canonicalize_agents
from app.studymate.prompt_compiler import PROMPT_VERSION
from app.studymate.runtime_context import RequestRuntime, new_runtime
from app.studymate.trace import AgentCoverage

logger = logging.getLogger("studybridge.studymate.basic")

CONTRACT_VERSION = "studymate-sse-2"

FOLLOW_UP_CHIPS = [
    {"id": "deeper", "label": "🔍 더 깊이 파고들기", "act": "DEEPEN"},
    {"id": "other_view", "label": "🗣️ 다른 의견도 듣기", "act": "ALT_VIEW"},
    {"id": "simpler", "label": "📝 더 쉬운 예시로", "act": "SIMPLIFY"},
]


def pipeline_enabled() -> bool:
    return (os.getenv("STUDYMATE_PIPELINE_V2", "on") or "on").strip().lower() not in ("off", "0", "false", "no")


def _min_gap() -> float:
    try:
        return max(0.0, float(os.getenv("STUDYMATE_MIN_ANSWER_GAP_SECONDS", "4")))
    except (TypeError, ValueError):
        return 4.0


def recent_turns_from_request(request: Any, limit: int = 6, clip: int = 320) -> List[str]:
    """previousAnswers 를 구조화 턴으로. (Redis 기억 블록과 이중 주입하지 않는다 — 호출부 참고)"""
    turns: List[str] = []
    for pa in (getattr(request, "previousAnswers", None) or [])[-limit:]:
        role = (getattr(pa, "role", "") or "").upper()
        who = "사용자" if role == "USER" or (getattr(pa, "agentName", "") or "").upper() == "USER" else (pa.agentName or "교수")
        text = " ".join((pa.answer or "").split())
        if text:
            turns.append(f"- {who}: {text[:clip]}{'…' if len(text) > clip else ''}")
    return turns


def recent_turns_from_memory_block(raw_message: str, limit: int = 6) -> List[str]:
    if "[현재 질문]" not in (raw_message or ""):
        return []
    block = raw_message.rsplit("[현재 질문]", 1)[0]
    lines = [l.strip() for l in block.splitlines() if l.strip().startswith("- ")]
    return [l[:340] for l in lines[-limit:]]


def _agent_event_base(a: CanonicalAgent, *, act: str, phase: str, order: int, reply_to: Optional[str],
                      rt: RequestRuntime) -> Dict[str, Any]:
    return {
        "agentId": a.agentIdRaw, "agentIndex": a.agentIndex, "agentName": a.name,
        "actType": act, "phase": phase, "replyTo": reply_to, "displayOrder": order,
        "requestId": rt.request_id, "visible": True, **a.identity_payload(),
    }


def run_basic_turn(request: Any, agents_raw: List[Any], *, current_message: str, social: bool,
                   rt: Optional[RequestRuntime] = None, mode: str = "basic") -> Generator[Dict[str, Any], None, None]:
    rt = rt or new_runtime()
    agents = canonicalize_agents(agents_raw)
    n = len(agents)
    budget = rt.budget or TurnBudget.for_kind("basic_single" if n <= 1 else "basic_multi")
    rt.budget = budget
    cancel = rt.cancel
    target = getattr(request, "targetAgentId", None)
    coverage = AgentCoverage(selected=[a.agentId for a in agents], targeted=target not in (None, ""))

    yield {"event": "turn_start", "data": {
        "type": "turn_start", "message": "에이전트가 답변을 준비하고 있습니다...", "phase": "FIRST_DRAFT",
        "visible": True, "mode": mode, "requestId": rt.request_id, "contractVersion": CONTRACT_VERSION,
        "targetAgentId": str(target) if target not in (None, "") else None,
        "responderAgentIds": [a.agentId for a in agents],
        "pipeline": "basic_v2",
    }}

    # 첫 교수의 '작성 중' 말풍선을 grounding/planning 전에 즉시 띄운다(체감 대기 단축). 짝(start→answer/error)은 유지.
    early_started: Optional[str] = None
    if agents and not cancel.cancelled:
        early_started = agents[0].agentId
        yield {"event": "agent_start", "data": {"type": "agent_start", **_agent_event_base(
            agents[0], act="DIRECT_ANSWER", phase="FIRST_DRAFT", order=1, reply_to=None, rt=rt)}}

    # ── 컨텍스트(이중 주입 금지): previousAnswers 우선, 없으면 Redis 기억 블록 ──
    raw_message = getattr(request, "message", "") or ""
    recent = recent_turns_from_request(request) or recent_turns_from_memory_block(raw_message)
    summary = MS.load_summary_sync(request)

    # ── Grounding: 현재 질문만 검색 질의로. 교수 수준 합집합을 병렬 1회 ──
    bundle = GR.GroundingBundle(query="")
    if not social and budget.allows("grounding"):
        bundle = GR.gather(current_message, [a.knowledgeLevelKey for a in agents], cancel=cancel,
                           max_wait_s=min(float(os.getenv("STUDYMATE_GROUNDING_WAIT_S", "3.5")),
                                          max(0.5, budget.remaining() - 30)))
        for f in bundle.failures:
            rt.note(f"grounding:{f}")

    roles = {a.agentId: (MP.role_for_position(i, n)) for i, a in enumerate(agents)}
    plan = PL.plan_turn(current_message, agents, roles,
                        grounding_hint="\n".join(v[:400] for v in bundle.by_source.values() if v),
                        summary=summary, turn_id=rt.turn_id, cancel=cancel, budget=budget, force_direct=social)
    if plan.source == "fallback":
        rt.note(f"planner_fallback:{','.join(plan.errors[:3])}")

    answers: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    traces: List[Dict[str, Any]] = []
    prior_texts: List[str] = []
    order = 0
    gap = _min_gap()

    def emit_outcome(a: CanonicalAgent, outcome, *, act: str, phase: str, stage: int, reply_to: Optional[str], ord_: int):
        base = _agent_event_base(a, act=act, phase=phase, order=ord_, reply_to=reply_to, rt=rt)
        if outcome.trace is not None:
            traces.append(outcome.trace.public_dict())
            rt.add_trace(outcome.trace.to_dict())
        if outcome.status == "SUCCESS":
            data = {"type": "agent_answer", **base, "answer": outcome.text, "content": outcome.text,
                    "stage": stage, "status": "SUCCESS", "qualityStatus": outcome.quality_status,
                    "degraded": outcome.degraded, "displayDelayMs": 0}
            answers.append({k: v for k, v in data.items() if k != "type"})
            coverage.mark("executed", a.agentId)
            coverage.mark("emitted", a.agentId)
            prior_texts.append(outcome.text)
            return {"event": "agent_answer", "data": data}
        code = outcome.code or "AGENT_FAILED"
        data = {"type": "agent_error", **base, "stage": stage, "status": "FAILED", "code": code,
                "degraded": True, "message": G.user_message_for(code)}
        errors.append({k: v for k, v in data.items() if k != "type"})
        coverage.mark("executed", a.agentId)
        coverage.mark("failed", a.agentId)
        return {"event": "agent_error", "data": data}

    cancelled = False
    for i, a in enumerate(agents):
        if cancel.cancelled:
            cancelled = True
            break
        order += 1
        already_started = early_started == a.agentId and i == 0
        if not budget.allows("render"):
            if not already_started:
                yield {"event": "agent_start", "data": {"type": "agent_start", **_agent_event_base(
                    a, act="DIRECT_ANSWER", phase="FIRST_DRAFT", order=order, reply_to=None, rt=rt)}}
            data = {"type": "agent_error", **_agent_event_base(a, act="DIRECT_ANSWER", phase="FIRST_DRAFT",
                                                               order=order, reply_to=None, rt=rt),
                    "stage": 1, "status": "FAILED", "code": "TURN_TIMEOUT", "degraded": True,
                    "message": G.user_message_for("TURN_TIMEOUT")}
            errors.append({k: v for k, v in data.items() if k != "type"})
            coverage.mark("failed", a.agentId)
            yield {"event": "agent_error", "data": data}
            continue
        t0 = time.time()
        if not already_started:
            yield {"event": "agent_start", "data": {"type": "agent_start", **_agent_event_base(
                a, act="DIRECT_ANSWER", phase="FIRST_DRAFT", order=order, reply_to=None, rt=rt)}}
        agent_plan = plan.plans.get(a.agentId)
        others = [str(c) for b in agents if b.agentId != a.agentId
                  for c in ((plan.plans.get(b.agentId) or {}).get("claims", []) if plan.source != "fallback" else [])]
        spec = RenderSpec(
            agent=a, mode=mode, role=roles[a.agentId], question=current_message, turn_id=rt.turn_id,
            request_id=rt.request_id, act="DIRECT_ANSWER", plan=agent_plan, plan_source=plan.source,
            contribution_text=PS.plan_to_contribution_text(agent_plan, others) if agent_plan else "",
            recent_turns=recent, rolling_summary=summary,
            grounding_items=bundle.items_for(a.knowledgeLevelKey),
            grounding_sources=bundle.sources_for(a.knowledgeLevelKey),
            grounding_failures=[f for f in bundle.failures if f.split(":")[0] in GR.LEVEL_SOURCES.get(a.knowledgeLevelKey, ())],
            evidence_text=bundle.evidence_text(), prior_texts=list(prior_texts),
            required_novel_claims=plan.novel_claims.get(a.agentId, []) if i > 0 else [],
            task_body=("[지금은 인사/잡담이다] 학습 설명을 하지 말고, 네 성격 말투로 1~2문장만 가볍게 받아라."
                       if social else ""),
            social=social,
            repair_allowance_s=max(0.0, budget.soft_remaining() / max(1, n - i)),
        )
        outcome = execute(spec, cancel=cancel, budget=budget)
        if outcome.status == "CANCELLED":
            cancelled = True
            break
        yield emit_outcome(a, outcome, act="DIRECT_ANSWER", phase="FIRST_DRAFT", stage=1, reply_to=None, ord_=order)
        if i < n - 1 and gap > 0:
            remaining_gap = gap - (time.time() - t0)
            if remaining_gap > 0 and budget.remaining() > remaining_gap + 20:
                cancel._event.wait(remaining_gap)

    # ── REACTION: 예산이 남을 때만. 대상 교수의 '주장 목록'만 전달 ──
    if not cancelled and not social and n >= 2 and plan.source != "direct":
        try:
            from app.services import studymate_discussion_planner as DP
            max_reactions = int(os.getenv("STUDYMATE_MAX_REACTIONS", "1"))
            acts = [x for x in DP.plan_discussion([a.agentId for a in agents], seed=hash(rt.turn_id) & 0xFFFF)
                    if x.act_type == DP.REACTION][:max_reactions] if DP.planner_enabled() else []
        except Exception as e:  # 플래너 오류는 반응 발화만 생략(본 답변 유지)
            logger.warning("[BASIC-V2] reaction planner skipped: %s", type(e).__name__)
            acts = []
        by_id = {a.agentId: a for a in agents}
        ok_ids = {str(x["agentId"]) for x in answers}
        for act in acts:
            if cancel.cancelled:
                cancelled = True
                break
            if act.target not in ok_ids or act.speaker not in ok_ids:
                continue
            soft = float(os.getenv("STUDYMATE_REACTION_SOFT_TARGET_S", "30"))
            if not budget.allows("reaction") or budget.elapsed_ms() / 1000.0 > soft:
                coverage.suppressedReason = "reaction_budget"
                rt.note("reaction_skipped_budget")
                break
            a, tgt = by_id[act.speaker], by_id[act.target]
            order += 1
            yield {"event": "agent_start", "data": {"type": "agent_start", **_agent_event_base(
                a, act="REACTION", phase="REACTION", order=order, reply_to=tgt.agentIdRaw, rt=rt)}}
            tclaims = [str(c) for c in (plan.plans.get(tgt.agentId) or {}).get("claims", [])]
            spec = RenderSpec(
                agent=a, mode=mode, role="reaction", question=current_message, turn_id=rt.turn_id,
                request_id=rt.request_id, act="REACTION", plan=None, plan_source="reaction",
                contribution_text=("- 대상 교수: " + tgt.name + "\n- 대상 교수의 주장: " + " / ".join(tclaims) +
                                   "\n- 이 중 하나를 골라 네 성격 관점에서 보완하거나 반박하라. 대상 교수의 표현을 되풀이하지 않는다."),
                recent_turns=[], rolling_summary="", grounding_items=bundle.items_for(a.knowledgeLevelKey)[:1],
                evidence_text=bundle.evidence_text(), prior_texts=list(prior_texts),
                task_body="분량은 3~6문장. 사용자에게 설명하듯 말한다.",
            )
            outcome = execute(spec, cancel=cancel, budget=budget)
            if outcome.status == "CANCELLED":
                cancelled = True
                break
            yield emit_outcome(a, outcome, act="REACTION", phase="REACTION", stage=2, reply_to=tgt.agentIdRaw, ord_=order)

    if cancelled:
        logger.info("[BASIC-V2] cancelled request=%s — 새 추론 시작 중단", rt.request_id)
        return

    if not social and answers:
        yield {"event": "follow_up_suggestions", "data": {
            "type": "follow_up_suggestions", "phase": "FOLLOW_UP", "visible": True,
            "suggestions": list(FOLLOW_UP_CHIPS), "requestId": rt.request_id}}

    degraded = coverage.degraded() or any(x.get("degraded") for x in answers)
    yield {"event": "all_complete", "data": {
        "type": "all_complete", "mode": mode, "learningMode": mode, "requestId": rt.request_id,
        "answers": answers, "messages": answers, "agentErrors": errors,
        "status": "COMPLETED" if answers and not errors else ("PARTIAL" if answers else "FAILED"),
        "phase": "ALL_COMPLETE", "visible": True, "route": "basic_v2",
        "suppressAgentFill": True,     # 누락은 agent_error 로 이미 드러냈다(compat 필러 금지)
        "degraded": degraded, "agentCoverage": coverage.to_dict(),
        "plan": {"source": plan.source, "llmCalls": plan.llm_calls, "repairUsed": plan.repair_used,
                 "failed": bool(plan.errors), "elapsedMs": plan.elapsed_ms},
        "grounding": {"degraded": bool(bundle.failures), "elapsedMs": bundle.elapsed_ms},
        "budget": {k: v for k, v in budget.snapshot().items() if k in ("kind", "elapsedMs", "skippedStages")},
        "promptVersion": PROMPT_VERSION,
        "trace": traces, "degradedNotes": list(rt.degraded_notes),
        "contractVersion": CONTRACT_VERSION,
    }}
