"""에이전트 1명 발화 실행기: Render → Cheap Validation → (조건부 Judge) → Repair-first → bounded Regenerate.

런타임 재시도 상한(사용자 요청 내부):
  repair      ≤ STUDYMATE_MAX_REPAIR (기본 1)
  regenerate  ≤ STUDYMATE_MAX_REGENERATE (기본 1)
그 이후에는 PARTIAL(degraded) 또는 FAILED 로 종료한다. 예산이 부족하면 시작하지 않는다.
"""
from __future__ import annotations

import logging
import os
import zlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.studymate import llm_gateway as G
from app.studymate import model_router
from app.studymate import prompt_compiler as PC
from app.studymate import quality as Q
from app.studymate.budget import TurnBudget
from app.studymate.cancellation import CancelToken, CancelledByClient
from app.studymate.profile_contract import CanonicalAgent
from app.studymate.trace import AgentExecutionTrace

logger = logging.getLogger("studybridge.studymate.executor")


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


@dataclass
class AgentOutcome:
    status: str                     # SUCCESS | FAILED | CANCELLED
    text: str = ""
    code: Optional[str] = None
    quality_status: str = "PASS"    # PASS | PARTIAL
    degraded: bool = False
    rubric: Dict[str, Any] = field(default_factory=dict)
    trace: Optional[AgentExecutionTrace] = None
    issues: List[str] = field(default_factory=list)


@dataclass
class RenderSpec:
    agent: CanonicalAgent
    mode: str
    role: str
    question: str
    turn_id: str
    request_id: str
    act: str = "DIRECT_ANSWER"
    plan: Optional[Dict[str, Any]] = None
    plan_source: str = "direct"
    contribution_text: str = ""
    recent_turns: List[str] = field(default_factory=list)
    rolling_summary: str = ""
    grounding_items: List[str] = field(default_factory=list)
    grounding_sources: List[str] = field(default_factory=list)
    grounding_failures: List[str] = field(default_factory=list)
    evidence_text: str = ""
    prior_texts: List[str] = field(default_factory=list)
    required_novel_claims: List[str] = field(default_factory=list)
    task_body: str = ""
    social: bool = False
    evaluate_rubric: bool = True
    repair_allowance_s: Optional[float] = None    # soft 목표 안에서 이 발화가 추가로 쓸 수 있는 시간(없으면 제한 없음)


def _clean_output(text: str) -> str:
    """모델 출력 선두의 고아 구두점/머리표('.', ',', '이교수:')를 제거한다(라이브 관측: '.Redis가 …')."""
    import re as _re
    t = (text or "").strip()
    t = _re.sub(r"^[\s.,;:·…\-–—]+(?=\S)", "", t)
    t = _re.sub(r"^[가-힣A-Za-z]{1,10}(교수|메이트)\s*[:：]\s*", "", t)
    return t.strip()


def _seed(turn_id: str, agent_id: str, act: str, attempt: int) -> int:
    return zlib.crc32(f"{turn_id}:{agent_id}:{act}:{attempt}".encode("utf-8")) & 0x7FFFFFFF


def _judge_mode() -> str:
    return (os.getenv("STUDYMATE_JUDGE", "auto") or "auto").strip().lower()


def _compile(spec: RenderSpec, reserve: int, num_ctx: int) -> PC.CompiledPrompt:
    ci = spec.agent.customInstruction.text if spec.agent.customInstruction else None
    return PC.compile_prompt(PC.CompileInput(
        mode=spec.mode, role=spec.role, persona=spec.agent.personalityKey, level=spec.agent.knowledgeLevelKey,
        agent_name=spec.agent.name, question=spec.question, persona_overlay=spec.agent.personalityOverlay,
        custom_instruction=ci, recent_turns=spec.recent_turns, rolling_summary=spec.rolling_summary,
        grounding_items=spec.grounding_items, contribution=spec.contribution_text, task_body=spec.task_body,
        few_shot=not spec.social, output_reserve=reserve, num_ctx=num_ctx,
        evidence_available=bool(spec.grounding_items)))


def _evaluate(text: str, spec: RenderSpec) -> Dict[str, Any]:
    ev: Dict[str, Any] = {"major": [], "minor": []}
    if len(Q._norm(text)) < (8 if spec.social else 60):
        ev["major"].append("too_short")
    leak = Q.leakage(text)
    if leak:
        ev["major"].append(f"leakage:{leak[:30]}")
    dup = Q.duplicate_against(text, spec.prior_texts)
    ev["dup"] = {"lcs": dup.lcs, "jaccard": round(dup.jaccard, 3), "prefix": dup.prefix}
    if dup.duplicate:
        ev["major"].append(f"duplicate:{dup.reason}")
    if spec.agent.knowledgeLevelKey in ("phd", "expert") and not spec.social:
        uns = Q.unsupported_specifics(text, spec.evidence_text)
        ev["unsupported"] = uns
        if len(uns) >= 3:
            ev["major"].append("unsupported_specifics")
        elif uns:
            ev["minor"].append("unsupported_specifics")
    if spec.plan and spec.plan_source in ("shared", "individual") and not spec.social:
        claims = [str(c) for c in spec.plan.get("claims", [])]
        covered = [c for c in claims if Q.claim_covered(text, c)]
        ev["claimCoverage"] = f"{len(covered)}/{len(claims)}"
        # plan 주장은 짧은 명사구라 본문이 바꿔 말하면 문자 bigram 이 낮게 나온다(2026-09-17 라이브: repair 오탐 1순위).
        # → 신호(signals)로만 기록하고 단독으로 LLM 재호출을 일으키지 않는다. 교수 간 복제는 duplicate 가드가 막는다.
        ev.setdefault("signals", [])
        if claims and not covered:
            ev["signals"].append("claims_not_covered")
        if spec.required_novel_claims and not any(Q.claim_covered(text, c) for c in spec.required_novel_claims):
            ev["signals"].append("novel_claim_missing")
    if spec.evaluate_rubric and not spec.social:
        r = Q.heuristic_rubric(text, spec.agent.personalityKey, spec.agent.knowledgeLevelKey)
        ev["rubric"] = r
    return ev


def _decision(ev: Dict[str, Any]) -> str:
    """Major 위반만 REGENERATE. 루브릭 미달은 repair-first:
    - judge 가 확인한 페르소나 붕괴(≤1/4)만 REGENERATE('사실상 다른 persona')
    - 그 외 루브릭 미달/minor 는 REPAIR (휴리스틱 단독 판정으로 전체 재생성하지 않는다)"""
    if ev["major"]:
        return Q.REGENERATE
    r = ev.get("rubric")
    if r is None:
        return Q.REPAIR if ev["minor"] else Q.PASS
    if r.source == "judge" and r.persona and sum(1 for v in r.persona.values() if v) <= 1:
        return Q.REGENERATE
    if r.verdict == Q.PASS:
        return Q.REPAIR if [m for m in ev["minor"] if not m.startswith("judge_")] else Q.PASS
    return Q.REPAIR


def execute(spec: RenderSpec, *, cancel: CancelToken, budget: TurnBudget,
            parallelism: int = 1) -> AgentOutcome:
    a = spec.agent
    opts = model_router.resolve("render", level=a.knowledgeLevelKey, persona=a.personalityKey)
    reserve = opts.num_predict if not spec.social else 220
    tr = AgentExecutionTrace(
        requestId=spec.request_id, turnId=spec.turn_id, agentId=a.agentId, agentIndex=a.agentIndex,
        mode=spec.mode, stage=spec.act, personalityKey=a.personalityKey, knowledgeLevelKey=a.knowledgeLevelKey,
        model=opts.model, numCtx=opts.num_ctx, thinkingEnabled=False, groundingSources=list(spec.grounding_sources),
        groundingFailures=list(spec.grounding_failures), parallelism=parallelism,
    )
    compiled = _compile(spec, reserve, opts.num_ctx)
    tr.promptVersion, tr.promptHash = compiled.prompt_version, compiled.prompt_hash
    tr.estimatedPromptTokens, tr.droppedSections = compiled.estimated_tokens, compiled.dropped_sections
    max_repair = _int_env("STUDYMATE_MAX_REPAIR", 1)
    max_regen = _int_env("STUDYMATE_MAX_REGENERATE", 1)

    def call(user_suffix: str, attempt: int, guard: bool) -> G.LLMResult:
        res = _call(user_suffix, attempt, guard)
        res.content = _clean_output(res.content)
        if not res.content:
            raise G.LLMEmptyResponse("empty after cleanup")
        return res

    def _call(user_suffix: str, attempt: int, guard: bool) -> G.LLMResult:
        req = G.LLMRequest(system=compiled.system, user=compiled.user + user_suffix, model=opts.model,
                           num_ctx=opts.num_ctx, num_predict=reserve, temperature=opts.temperature,
                           top_p=opts.top_p, seed=_seed(spec.turn_id, a.agentId, spec.act, attempt),
                           think=False, timeout_s=opts.timeout_s, task="render" if attempt == 0 else "repair")
        res = G.generate(req, cancel=cancel, deadline=budget.deadline,
                         prefix_guard=Q.prefix_guard(spec.prior_texts) if (guard and spec.prior_texts) else None)
        tr.actualPromptEvalCount = res.prompt_eval_count
        tr.completionTokens = res.eval_count
        tr.contextSaturated = tr.contextSaturated or res.context_saturated
        if tr.ttftMs is None:
            tr.ttftMs = res.ttft_ms
        return res

    text = ""
    ev: Dict[str, Any] = {}
    decision = Q.PASS
    attempt = 0
    import time as _time
    t_start = _time.time()

    def soft_allows_retry() -> bool:
        """추가 생성(repair) 1회를 soft 목표 안에 끝낼 수 있을 때만 True. 소요 추정 = 지금까지의 1회 생성 시간."""
        if spec.repair_allowance_s is None:
            return True
        spent = _time.time() - t_start
        ok = spent * 2 <= spec.repair_allowance_s
        if not ok:
            tr.rubric.setdefault("judgeNotes", []).append("repair_skipped_soft_budget")
        return ok
    try:
        try:
            text = call("", attempt, guard=True).content
        except G.LLMAborted as ab:
            ev = {"major": [f"duplicate:{ab.detail}"], "minor": []}
            decision = Q.REGENERATE
            text = ""
        else:
            ev = _evaluate(text, spec)
            decision = _decision(ev)
            if decision != Q.PASS and _judge_mode() != "off" and budget.allows("judge") and not ev["major"] \
                    and (spec.repair_allowance_s is None or (_time.time() - t_start) * 2 <= spec.repair_allowance_s):
                decision, ev = _judge(text, spec, ev, cancel, budget, tr)
            elif _judge_mode() == "always" and budget.allows("judge") and not ev["major"]:
                decision, ev = _judge(text, spec, ev, cancel, budget, tr)
            if decision == Q.REPAIR and _judge_mode() != "off" and ev.get("rubric") is not None \
                    and ev["rubric"].source != "judge" and not [m for m in ev["minor"] if not m.startswith("judge_")]:
                # judge 를 못 돌렸다(예산/실패). 휴리스틱 단독 미달로는 LLM 재호출을 쓰지 않는다 → PARTIAL 표시.
                decision = "PARTIAL"

        # Repair-first (minor) → bounded
        if decision == Q.REPAIR and tr.repairCount < max_repair and budget.allows("repair") and text and soft_allows_retry():
            missing = ev["rubric"].missing() if ev.get("rubric") is not None else []
            if "claims_not_covered" in ev["minor"] and spec.plan:
                missing.append("plan_claims")
            instr = Q.repair_instruction(missing, ev.get("unsupported") or [])
            attempt += 1
            tr.repairCount += 1
            try:
                candidate = call(f"\n\n[이전 답변 초안]\n{text}\n\n{instr}", attempt, guard=False).content
                cev = _evaluate(candidate, spec)
                if not cev["major"]:
                    text, ev = candidate, cev
                    # repair 결과는 휴리스틱으로만 재평가한다. 추가 regenerate 는 major 위반일 때만.
                    decision = Q.PASS if (cev.get("rubric") is None or cev["rubric"].verdict == Q.PASS) else "PARTIAL"
            except G.LLMEmptyResponse:
                pass

        # Full regenerate (major) → bounded
        if decision == Q.REGENERATE and tr.regenerationCount < max_regen and budget.allows("regenerate"):
            attempt += 1
            tr.regenerationCount += 1
            reasons = ", ".join(ev.get("major") or ["rubric"])
            suffix = ("\n\n[재생성 지시] 이전 시도가 다음 이유로 거부됐다: " + reasons +
                      ". 앞선 교수 답변과 다른 첫 문장·다른 예시로, 위 모드/성격/수준 규칙을 지켜 새로 작성한다.")
            try:
                candidate = call(suffix, attempt, guard=True).content
                cev = _evaluate(candidate, spec)
                if not cev["major"]:
                    text, ev = candidate, cev
                    decision = _decision(cev)
                    if decision != Q.PASS:
                        decision = "PARTIAL"
                else:
                    ev = cev
                    text = candidate if candidate else text
            except (G.LLMAborted, G.LLMEmptyResponse) as e:
                ev.setdefault("major", []).append(f"regenerate_failed:{e.code}")
    except CancelledByClient:
        tr.cancelled = True
        tr.finish("CANCELLED", "CLIENT_CANCELLED").log()
        return AgentOutcome("CANCELLED", code="CLIENT_CANCELLED", trace=tr)
    except G.LLMError as e:
        code = "TURN_TIMEOUT" if (e.code == "LLM_TIMEOUT" and budget.exhausted()) else e.code
        logger.warning("[EXECUTOR] agent=%s act=%s LLM 실패 code=%s detail=%s", a.agentId, spec.act, code, e.detail[:120])
        tr.finish("FAILED", code).log()
        return AgentOutcome("FAILED", code=code, trace=tr, degraded=True)

    rubric = ev.get("rubric")
    judge_notes = list(tr.rubric.get("judgeNotes") or [])
    tr.rubric = {"decision": decision, "judgeNotes": judge_notes, **(rubric.to_dict() if rubric is not None else {}),
                 "major": ev.get("major", []), "minor": ev.get("minor", []),
                 "dup": ev.get("dup"), "claimCoverage": ev.get("claimCoverage"), "signals": ev.get("signals", []),
                 "unsupported": ev.get("unsupported")}
    if ev.get("major"):
        code = "AGENT_DUPLICATE" if any(m.startswith("duplicate") for m in ev["major"]) else "QUALITY_FAILED"
        tr.finish("FAILED", code).log()
        return AgentOutcome("FAILED", code=code, trace=tr, degraded=True, rubric=tr.rubric,
                            issues=list(ev["major"]))
    if decision == Q.REPAIR:
        decision = "PARTIAL"   # repair 가 예산 때문에 생략됨 → 품질 미검증 표시
    quality = "PASS" if decision == Q.PASS else "PARTIAL"
    tr.fallbackUsed = spec.plan_source == "fallback"
    tr.finish("SUCCESS").log()
    return AgentOutcome("SUCCESS", text=text, quality_status=quality, degraded=quality != "PASS",
                        rubric=tr.rubric, trace=tr, issues=list(ev.get("minor") or []))


def _judge(text: str, spec: RenderSpec, ev: Dict[str, Any], cancel, budget, tr):
    system, user, schema = Q.judge_prompts(text, spec.agent.personalityKey, spec.agent.knowledgeLevelKey, spec.question)
    opts = model_router.resolve("judge")
    req = G.LLMRequest(system=system, user=user, model=opts.model, num_ctx=opts.num_ctx, num_predict=opts.num_predict,
                       temperature=0.0, top_p=1.0, seed=7, think=False, format=schema,
                       timeout_s=opts.timeout_s, task="judge")
    tr.judgeUsed = True
    try:
        res = G.generate(req, cancel=cancel, deadline=budget.deadline)
    except CancelledByClient:
        raise
    except G.LLMError as e:
        # judge 실패는 원본을 '성공'으로 승격하지 않는다: heuristic 판정을 그대로 유지하고 trace 에 남긴다.
        ev.setdefault("minor", []).append(f"judge_failed:{e.code}")
        tr.rubric.setdefault("judgeNotes", []).append(f"judge_failed:{e.code}")
        return _decision(ev), ev
    r = Q.parse_judge(res.content, spec.agent.personalityKey, spec.agent.knowledgeLevelKey)
    if r is None:
        ev.setdefault("minor", []).append("judge_unparseable")
        tr.rubric.setdefault("judgeNotes", []).append("judge_unparseable")
        return _decision(ev), ev
    ev["rubric"] = r
    return _decision(ev), ev
