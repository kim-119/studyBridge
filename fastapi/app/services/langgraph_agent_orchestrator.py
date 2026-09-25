"""
LangGraph 기반 멀티 에이전트 오케스트레이터 (흐름 제어용).

설계 원칙
---------
- RAG/LLM 로직을 재구현하지 않는다. 기존 multi_agent_service의 compute 헬퍼
  (_compute_stage1/2/3, debate/socratic 파이프라인)와 기존 pgvector RAG
  (rag_retriever.retrieve_similar_chunks)를 LangGraph 노드에서 '호출'만 한다.
- feature flag(USE_LANGGRAPH_ORCHESTRATOR)로만 진입한다. langgraph 미설치 시
  기존 run_multi_chat으로 안전하게 폴백한다(서버를 죽이지 않음).
- 최종 답변을 즉시 학습하지 않는다. collect_training_candidate_node는 후보 dict만
  state에 적재하고, 실제 DB 영속화/학습은 검수 게이트(collect 엔드포인트/배치)가 담당한다.

그래프 흐름
-----------
normalize → retrieve_rag → route_mode
  ├ default : stage1 → stage2_validate → peer_feedback → quality_gate
  ├ debate  : stage1 → peer_feedback → revised_answer → debate_summary → quality_gate
  └ socratic: socratic → quality_gate
quality_gate → (미달 시) rewrite → collect_training_candidate → finalize → END
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TypedDict

logger = logging.getLogger(__name__)

# langgraph는 선택 의존성. 미설치면 그래프를 만들지 않고 기존 경로로 폴백한다.
try:
    from langgraph.graph import StateGraph, END
    _LANGGRAPH_AVAILABLE = True
except Exception as _e:  # pragma: no cover - 설치 안 된 환경 방어
    StateGraph = None  # type: ignore
    END = "__end__"     # type: ignore
    _LANGGRAPH_AVAILABLE = False
    logger.info("langgraph 미설치 → run_langgraph_multi_agent는 기존 경로로 폴백합니다.")

from app.schemas.multi_chat_schema import MultiChatRequest, MultiChatResponse
from app.services import multi_agent_service as M

# 품질 게이트 임계값/금지표현/재작성 한도
_QUALITY_MIN = 0.55
_MAX_REWRITE = 1
_FORBIDDEN_MARKERS = ("씨발", "개새끼", "병신")  # 안전 필터(욕설). PII는 pii_filter로 별도 검사.


class AgentGraphState(TypedDict, total=False):
    # 공개 상태 (task 명세)
    message: str
    mode: str
    learningMode: Optional[str]
    materialId: Optional[int]
    agents: list
    ragChunks: list
    ragContext: str
    stage1Answers: list
    stage2Answers: list
    peerFeedbacks: list
    revisedAnswers: list
    debateSummary: Optional[str]
    socraticAnswer: Optional[str]
    trainingCandidate: Optional[dict]
    errors: list
    metadata: dict
    # 내부 상태 (노드 간 객체 전달용 — 응답엔 노출 안 함)
    _request: Any
    _route: str
    _agents: list
    _context: str
    _rag_context: str
    _initial_steps: list
    _initial_map: dict
    _validated_steps: list
    _validated_map: dict
    _validation_map: dict
    _pv_summary: list
    _sources: list
    _peer_steps: list
    _peer_feedbacks: list
    _revised_steps: list
    _revised_map: dict
    _summary: Optional[str]
    _socratic_response: Any
    _response: Any
    _rewrite_count: int


# ── 노드 1. normalize_request ────────────────────────────────────────────────
def normalize_request_node(state: AgentGraphState) -> Dict[str, Any]:
    req: MultiChatRequest = state["_request"]
    agents = M._filter_agents(M._get_agents(req), req.targetAgentId)

    raw = (req.mode or "default").strip().lower()
    lm = (getattr(req, "learningMode", None) or "").strip().lower()
    if lm == "socratic" or (not lm and raw == "socratic"):
        route = "socratic"
    elif (lm in M._DEBATE_MODE_ALIASES) or (not lm and raw in M._DEBATE_MODE_ALIASES):
        route = "debate"
    else:
        route = "default"

    logger.info("[LangGraph] normalize route=%s agents=%d mode=%s lm=%s",
                route, len(agents), raw, lm or None)
    return {
        "message": req.message,
        "mode": raw,
        "learningMode": lm or None,
        "materialId": req.materialId,
        "agents": [a.name for a in agents],
        "_agents": agents,
        "_route": route,
        "_rewrite_count": 0,
        "errors": [],
        "metadata": {"route": route},
    }


# ── 노드 2. retrieve_rag ─────────────────────────────────────────────────────
def retrieve_rag_node(state: AgentGraphState) -> Dict[str, Any]:
    req: MultiChatRequest = state["_request"]
    meta = dict(state.get("metadata") or {})
    chunks: List[dict] = []
    rag_context = ""
    rag_score = 0.0
    try:
        if req.materialId:
            from app.services.rag_retriever import retrieve_similar_chunks, is_result_sufficient
            from app.core.config import RAG_TOP_K
            chunks = retrieve_similar_chunks(req.message, req.materialId, top_k=RAG_TOP_K) or []
            if is_result_sufficient(chunks):
                rag_context = "\n\n".join(
                    f"[청크 {i + 1}] {c.get('content', '')}" for i, c in enumerate(chunks)
                )
                rag_score = max((float(c.get("similarity", 0.0)) for c in chunks), default=0.0)
                meta["ragStatus"] = "grounded"
            else:
                meta["ragStatus"] = "empty"
        else:
            meta["ragStatus"] = "no_material"
    except Exception as e:
        # RAG 실패해도 서버를 죽이지 않는다. "자료 기반 근거 없음"으로 진행.
        logger.warning("[LangGraph] retrieve_rag 실패 (근거 없이 진행): %s", e)
        meta["ragStatus"] = "error"
    meta["ragScore"] = round(rag_score, 4)
    meta["ragChunkIds"] = [c.get("id") for c in chunks if c.get("id") is not None]

    # 컨텍스트는 previousAnswers + RAG를 합쳐 default/debate 헬퍼가 쓰는 형식으로 만든다.
    base_ctx = M.build_context_from_previous_answers(req.previousAnswers, max_items=20)
    full_ctx = M._prep_default_context(base_ctx, rag_context)
    return {
        "ragChunks": chunks,
        "ragContext": rag_context,
        "_rag_context": rag_context,
        "_context": full_ctx,
        "metadata": meta,
    }


# ── 노드 3. route_mode (조건 분기용) ─────────────────────────────────────────
def route_mode_node(state: AgentGraphState) -> Dict[str, Any]:
    # 분기는 _route_selector가 담당. 이 노드는 로깅/패스스루.
    logger.info("[LangGraph] route_mode → %s", state.get("_route"))
    return {}


def _route_selector(state: AgentGraphState) -> str:
    return state.get("_route", "default")


# ── 노드 4. stage1 ───────────────────────────────────────────────────────────
def stage1_node(state: AgentGraphState) -> Dict[str, Any]:
    req, agents, ctx = state["_request"], state["_agents"], state.get("_context", "")
    if state.get("_route") == "debate":
        steps, initial_map, _p, _e = M._compute_debate_opening(req, M._ensure_debate_agents(agents), ctx)
        # debate는 _ensure_debate_agents로 보강될 수 있으므로 agents를 갱신
        agents = M._ensure_debate_agents(agents)
    else:
        steps, initial_map, _p, _e, _st = M._compute_stage1(req, agents, ctx)
    return {
        "_agents": agents,
        "_initial_steps": steps,
        "_initial_map": initial_map,
        "stage1Answers": [s.model_dump() for s in steps],
    }


# ── 노드 5. stage2_validate (default 전용) ───────────────────────────────────
def stage2_validate_node(state: AgentGraphState) -> Dict[str, Any]:
    req, agents = state["_request"], state["_agents"]
    initial_map = state["_initial_map"]
    v_steps, v_map, _p, _e, sources = M._compute_stage2(req, agents, initial_map)
    validation_map, pv_summary = M._compute_validation(req, agents, initial_map, v_map, v_steps)
    meta = dict(state.get("metadata") or {})
    meta["ragGrounded"] = bool(state.get("_rag_context"))
    return {
        "_validated_steps": v_steps,
        "_validated_map": v_map,
        "_validation_map": validation_map,
        "_pv_summary": pv_summary,
        "_sources": sources,
        "stage2Answers": [s.model_dump() for s in v_steps],
        "metadata": meta,
    }


# ── 노드 6. peer_feedback ────────────────────────────────────────────────────
def peer_feedback_node(state: AgentGraphState) -> Dict[str, Any]:
    req, agents = state["_request"], state["_agents"]
    if state.get("_route") == "debate":
        peer_steps, peer_feedbacks, _p, _e = M._compute_debate_rebuttal(req, agents, state["_initial_map"])
        peer_steps, peer_feedbacks = M._debate_ensure_feedbacks(agents, peer_steps, peer_feedbacks)
        return {
            "_peer_steps": peer_steps,
            "_peer_feedbacks": peer_feedbacks,
            "peerFeedbacks": [fb.model_dump() for fb in peer_feedbacks],
        }
    # default: 2명 이상이면 상호 피드백 필수
    peer_steps, _p, _e = M._compute_stage3(
        req, agents, state.get("_validated_map", {}), state.get("_validation_map", {})
    )
    return {
        "_peer_steps": peer_steps,
        "peerFeedbacks": [s.model_dump() for s in peer_steps],
    }


# ── 노드 7. revised_answer (debate 전용) ─────────────────────────────────────
def revised_answer_node(state: AgentGraphState) -> Dict[str, Any]:
    req, agents = state["_request"], state["_agents"]
    fb_map = M._feedback_received_map(agents, state["_peer_feedbacks"])
    r_steps, r_map, _p, _e = M._compute_debate_revision(req, agents, state["_initial_map"], fb_map)
    return {
        "_revised_steps": r_steps,
        "_revised_map": r_map,
        "revisedAnswers": [r.model_dump() for r in M._debate_revised_records(agents, r_map)],
    }


# ── 노드 8. debate_summary (debate 전용) ─────────────────────────────────────
def debate_summary_node(state: AgentGraphState) -> Dict[str, Any]:
    req, agents = state["_request"], state["_agents"]
    summary = M._debate_default_summary(M._compute_debate_summary(req, agents, state["_revised_map"]))
    return {"_summary": summary, "debateSummary": summary}


# ── 노드 9. socratic ─────────────────────────────────────────────────────────
def socratic_node(state: AgentGraphState) -> Dict[str, Any]:
    req, agents = state["_request"], state["_agents"]
    resp = M._run_socratic_mode(req, agents, state.get("_rag_context", ""))
    answer = resp.answers[0].answer if resp.answers else ""
    return {"_socratic_response": resp, "socraticAnswer": answer}


# ── 노드 10. quality_gate ────────────────────────────────────────────────────
def _primary_answer(state: AgentGraphState) -> str:
    route = state.get("_route")
    if route == "socratic":
        return state.get("socraticAnswer") or ""
    if route == "debate":
        rmap = state.get("_revised_map") or {}
        imap = state.get("_initial_map") or {}
        for a in state["_agents"]:
            if rmap.get(a.name) or imap.get(a.name):
                return rmap.get(a.name) or imap.get(a.name)
        return ""
    vmap = state.get("_validated_map") or state.get("_initial_map") or {}
    for a in state["_agents"]:
        if vmap.get(a.name):
            return vmap.get(a.name)
    return ""


def quality_gate_node(state: AgentGraphState) -> Dict[str, Any]:
    meta = dict(state.get("metadata") or {})
    answer = _primary_answer(state)

    # 안전 필터 (욕설 + PII)
    safety = "safe"
    try:
        from app.utils.pii_filter import has_pii
        if has_pii(answer):
            safety = "pii"
    except Exception:
        pass
    if any(m in answer for m in _FORBIDDEN_MARKERS):
        safety = "forbidden"

    # 품질 점수: 길이/금지표현/성격검증(pv)/RAG grounding을 종합한 가벼운 휴리스틱
    score = 0.0
    if answer and not answer.startswith("["):
        score += 0.4
    if len(answer.strip()) >= 80:
        score += 0.2
    pv = state.get("_pv_summary") or []
    if pv:
        passed = [p for p in pv if getattr(p, "passed", None) or (isinstance(p, dict) and p.get("passed"))]
        score += 0.2 * (len(passed) / max(len(pv), 1))
    else:
        score += 0.1
    if meta.get("ragStatus") == "grounded":
        score += 0.2
    elif state.get("_route") != "default":
        score += 0.1  # 토론/소크라테스는 RAG 없이도 성립

    meta["qualityScore"] = round(min(score, 1.0), 4)
    meta["safetyStatus"] = safety
    passed = (safety == "safe") and meta["qualityScore"] >= _QUALITY_MIN
    meta["qualityPassed"] = passed
    logger.info("[LangGraph] quality_gate score=%.2f safety=%s passed=%s rewrite=%d",
                meta["qualityScore"], safety, passed, state.get("_rewrite_count", 0))
    return {"metadata": meta}


def _quality_selector(state: AgentGraphState) -> str:
    meta = state.get("metadata") or {}
    if not meta.get("qualityPassed", True) and state.get("_rewrite_count", 0) < _MAX_REWRITE:
        return "rewrite"
    return "pass"


# ── 노드 11. rewrite (최대 _MAX_REWRITE회) ──────────────────────────────────
def rewrite_node(state: AgentGraphState) -> Dict[str, Any]:
    count = state.get("_rewrite_count", 0) + 1
    meta = dict(state.get("metadata") or {})
    meta["rewriteApplied"] = True
    out: Dict[str, Any] = {"_rewrite_count": count, "metadata": meta}
    try:
        if state.get("_route") == "default":
            # 2차 검증 답안을 1회 재생성한다(성격/정확성 보정은 _compute_stage2/validation 내부 로직 재사용).
            req, agents = state["_request"], state["_agents"]
            v_steps, v_map, _p, _e, sources = M._compute_stage2(req, agents, state["_initial_map"])
            validation_map, pv_summary = M._compute_validation(req, agents, state["_initial_map"], v_map, v_steps)
            out.update({
                "_validated_steps": v_steps, "_validated_map": v_map,
                "_validation_map": validation_map, "_pv_summary": pv_summary, "_sources": sources,
                "stage2Answers": [s.model_dump() for s in v_steps],
            })
        # debate/socratic은 파이프라인 자체에 보완/재작성 단계가 포함되어 추가 재작성을 생략한다.
    except Exception as e:
        logger.warning("[LangGraph] rewrite 실패 (원답 유지): %s", e)
    return out


# ── 노드 12. collect_training_candidate ──────────────────────────────────────
def collect_training_candidate_node(state: AgentGraphState) -> Dict[str, Any]:
    """
    최종 답변을 '학습 후보 dict'로만 적재한다. 여기서 실제 학습/DB 영속화는 하지 않는다.
    (영속화는 검수 게이트가 있는 collect 엔드포인트/배치가 담당 — 즉시 재학습 금지.)
    """
    req: MultiChatRequest = state["_request"]
    agents = state["_agents"]
    meta = state.get("metadata") or {}
    answer = _primary_answer(state)
    first = agents[0] if agents else None

    system_prompt = ""
    try:
        if first is not None:
            from app.services.prompt_builder import build_agent_system_prompt
            system_prompt = build_agent_system_prompt(first, state.get("_rag_context", ""))
    except Exception:
        system_prompt = ""

    quality_score = float(meta.get("qualityScore", 0.0))
    safety_status = meta.get("safetyStatus", "safe")
    quality_passed = bool(meta.get("qualityPassed", False))

    candidate = {
        "question": req.message,
        "answer": answer,
        "system_prompt": system_prompt,
        "agentName": first.name if first else None,
        "personality": (first.personality if first else None),
        "knowledge_level": (first.knowledgeLevel if first else None),
        "mode": state.get("_route"),
        "materialId": req.materialId,
        "rag_context": state.get("_rag_context", ""),
        "rag_score": meta.get("ragScore", 0.0),
        "rag_grounding_score": meta.get("ragScore", 0.0),
        "quality_score": quality_score,
        "safety_status": safety_status,
        "duplicate_status": "unknown",  # 실제 중복판정은 collect 엔드포인트(content_hash)에서 수행
        # 품질 게이트 통과 + 안전 + 사용자 부정피드백 없음일 때만 auto_approved 후보
        "auto_approved": quality_passed and safety_status == "safe",
        "quality_status": "auto_approved" if (quality_passed and safety_status == "safe") else "holdout",
    }
    return {"trainingCandidate": candidate}


# ── 노드 13. finalize ────────────────────────────────────────────────────────
def finalize_node(state: AgentGraphState) -> Dict[str, Any]:
    req, agents = state["_request"], state["_agents"]
    route = state.get("_route")
    try:
        if route == "socratic":
            resp = state.get("_socratic_response")
            if resp is None:
                resp = M._run_socratic_mode(req, agents, state.get("_rag_context", ""))
        elif route == "debate":
            resp = M._assemble_debate_response(
                req, agents, state.get("_rag_context", ""),
                state["_initial_steps"], state["_initial_map"],
                state["_peer_steps"], state["_peer_feedbacks"],
                state.get("_revised_steps", []), state.get("_revised_map", {}),
                state.get("_summary") or "",
            )
        else:
            initial_steps = state["_initial_steps"]
            validated_steps = state.get("_validated_steps", [])
            peer_steps = state.get("_peer_steps", [])
            pv_summary = state.get("_pv_summary", [])
            sources = state.get("_sources", [])
            stages = M._build_stage_infos(
                initial_steps, validated_steps, peer_steps, pv_summary,
                ("ollama", 0, "completed"), ("mixed", 0, "completed"), ("mixed", 0, "completed"),
                sources,
            )
            resp = M._build_default_response(
                req, agents, state["_initial_map"], state.get("_validated_map", {}),
                initial_steps, validated_steps, peer_steps, pv_summary, stages,
            )
        # 학습 후보(metadata)는 응답에 직접 노출하지 않되, 디버그용으로 debugMetadata엔 싣지 않는다.
        return {"_response": resp}
    except Exception as e:
        logger.error("[LangGraph] finalize 실패 → 기존 run_multi_chat 폴백: %s", e)
        return {"_response": M.run_multi_chat(req)}


# ── 그래프 빌드 (1회 컴파일 후 캐시) ─────────────────────────────────────────
_COMPILED_GRAPH = None


def _build_graph():
    g = StateGraph(AgentGraphState)
    g.add_node("normalize", normalize_request_node)
    g.add_node("retrieve_rag", retrieve_rag_node)
    g.add_node("route_mode", route_mode_node)
    g.add_node("stage1", stage1_node)
    g.add_node("stage2_validate", stage2_validate_node)
    g.add_node("peer_feedback", peer_feedback_node)
    g.add_node("revised_answer", revised_answer_node)
    g.add_node("debate_summary", debate_summary_node)
    g.add_node("socratic", socratic_node)
    g.add_node("quality_gate", quality_gate_node)
    g.add_node("rewrite", rewrite_node)
    g.add_node("collect_candidate", collect_training_candidate_node)
    g.add_node("finalize", finalize_node)

    g.set_entry_point("normalize")
    g.add_edge("normalize", "retrieve_rag")
    g.add_edge("retrieve_rag", "route_mode")
    g.add_conditional_edges("route_mode", _route_selector, {
        "default": "stage1", "debate": "stage1", "socratic": "socratic",
    })
    # stage1 이후 default↔debate 분기
    g.add_conditional_edges("stage1", _route_selector, {
        "default": "stage2_validate", "debate": "peer_feedback",
    })
    g.add_edge("stage2_validate", "peer_feedback")
    # peer_feedback 이후 default→quality_gate, debate→revised
    g.add_conditional_edges("peer_feedback", _route_selector, {
        "default": "quality_gate", "debate": "revised_answer",
    })
    g.add_edge("revised_answer", "debate_summary")
    g.add_edge("debate_summary", "quality_gate")
    g.add_edge("socratic", "quality_gate")
    g.add_conditional_edges("quality_gate", _quality_selector, {
        "rewrite": "rewrite", "pass": "collect_candidate",
    })
    g.add_edge("rewrite", "quality_gate")
    g.add_edge("collect_candidate", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


def _get_graph():
    global _COMPILED_GRAPH
    if _COMPILED_GRAPH is None:
        _COMPILED_GRAPH = _build_graph()
    return _COMPILED_GRAPH


def run_langgraph_multi_agent(request: MultiChatRequest) -> MultiChatResponse:
    """
    LangGraph 그래프로 멀티 에이전트 플로우를 실행한다.
    langgraph 미설치/오류 시 기존 run_multi_chat으로 폴백한다(안전).
    반환은 기존과 동일한 MultiChatResponse라 feature flag 전환이 투명하다.
    """
    if not _LANGGRAPH_AVAILABLE:
        logger.info("[LangGraph] 미설치 → run_multi_chat 폴백")
        return M.run_multi_chat(request)
    try:
        graph = _get_graph()
        final_state = graph.invoke({"_request": request})
        resp = final_state.get("_response")
        if resp is None:
            raise RuntimeError("그래프가 _response를 생성하지 못함")
        return resp
    except Exception as e:
        logger.error("[LangGraph] 실행 실패 → run_multi_chat 폴백: %s", e)
        return M.run_multi_chat(request)
