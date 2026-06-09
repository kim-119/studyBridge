"""
멀티 에이전트 토론 서비스.
POST /api/ai/multi-chat — 동기 REST JSON 반환 (SSE는 Spring Boot가 처리).

mode별 분기:
  default     : 기존 병렬 multi-agent 답변
  tikitaka    : 기존 3라운드 티키타카
  debate      : 찬성봇 → 반대봇 → 사회자봇 순차 체인 (v0.7)
  socratic    : 소크라테스식 꼬리질문 (v0.7)

v0.8 추가:
  - domain classifier → generation config resolver → OpenAlex(박사) → depth verifier/rewriter
  - 기존 RAG / 임베딩 / pgvector / Ollama / OpenAI fallback 보존.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.multi_chat_schema import (
    AgentAnswer, AgentProfile, MultiChatRequest, MultiChatResponse,
    ValidationSummary, PreviousAnswer, DebugMetadata,
    GenerationConfigMetadata, RetrievalMetadata, DepthValidationMetadata, PromptingMetadata,
    ProcessSteps, InitialAnswerStep, ValidatedAnswerStep, PeerFeedbackStep,
    PersonalityValidationItem, StageInfo, AgentAnswerMetadata,
    DebateInitialAnswer, DebatePeerFeedback, DebateRevisedAnswer,
)
from app.services.prompt_builder import build_agent_system_prompt, build_tikitaka_role_prompt
from app.services.personality_prompt_builder import to_profile_key, build_persona_directive
from app.services.personality_validator import validate_personality_alignment, repair_personality_if_needed
from app.core import agent_settings as A
from app.utils.text_utils import build_context_from_previous_answers, safe_str
from app.core.config import MAX_ROUNDS

logger = logging.getLogger(__name__)

_DEFAULT_AGENT = AgentProfile(
    id=0, agentId=0, name="스터디봇", role="학습 도우미",
    personality="친절_설명형", personalityStrength="moderate", knowledgeLevel="학사",
)
_SYNTHESIS_AGENT_NAME = "종합정리봇"
_MAX_ROUNDS = MAX_ROUNDS
# 답변 잘림 방지: 생성 토큰 상한은 충분히 크게 둔다.
# (config.AGENT_ANSWER_MAX_CHARS 같은 '문자 수' 개념은 최종 출력에 적용하지 않는다 — 잘림 원인.)
import os as _os
_MAX_TOKENS_PER_ANSWER = int(_os.getenv("AI_ANSWER_MAX_TOKENS", "2048"))
# 단계별 token/timeout/provider 및 성격별 파라미터는 모두 app/core/agent_settings.py(env)에서 읽는다.
# (서비스 코드에 magic value를 박지 않는다.)


def _get_agents(request: MultiChatRequest) -> List[AgentProfile]:
    if not request.agents:
        logger.info("에이전트 목록이 비어있습니다. 기본 에이전트 사용.")
        return [_DEFAULT_AGENT]
    return request.agents


def _filter_agents(agents: List[AgentProfile], target_id: Optional[int]) -> List[AgentProfile]:
    if target_id is None:
        return agents
    filtered = [a for a in agents if (a.agentId == target_id or a.id == target_id)]
    if not filtered:
        logger.warning("targetAgentId=%s에 해당하는 에이전트 없음. 전체 사용.", target_id)
        return agents
    return filtered


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    knowledge_level: Optional[str] = None,
    gen_config: Optional[Dict[str, Any]] = None,
) -> str:
    try:
        from app.services.llm_engine_router import call_primary_llm
        max_tokens = _MAX_TOKENS_PER_ANSWER
        temperature = 0.5
        if gen_config:
            max_tokens = gen_config.get("max_tokens", max_tokens)
            temperature = gen_config.get("temperature", temperature)
        result = call_primary_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            knowledge_level=knowledge_level,
        )
        if result and not result.startswith("["):
            return result
        logger.warning("LLM 엔진 라우터 fallback 응답: %s", result[:80])
    except Exception as e:
        logger.error("LLM 엔진 라우터 호출 실패: %s", e)
    return "현재 AI 서비스에 일시적으로 접근할 수 없습니다. 잠시 후 다시 시도해 주세요."


def _get_rag_context(question: str, material_id: Optional[int]) -> str:
    """RAG 검색. 실패해도 서버 죽지 않음."""
    if not material_id:
        return ""
    try:
        from app.services.pdf_rag_service import search_pdf_context
        chunks = search_pdf_context(question, material_id, top_k=5)
        if not chunks:
            return ""
        return "\n\n".join(f"[청크 {i+1}]\n{c['content']}" for i, c in enumerate(chunks))
    except Exception as e:
        logger.warning("RAG 검색 실패 (계속 진행): %s", e)
        return ""


def _gather_web_evidence(question: str, knowledge_level: Optional[str]) -> Tuple[str, List[Dict[str, Any]]]:
    """
    2차 검증용 웹 근거를 질문당 1회 수집한다(Tavily + Wikipedia + OpenAlex 병렬, best-effort).
    각 소스는 개별 타임아웃, 전체는 예산 시간 내. 실패한 소스는 조용히 건너뛴다.
    반환: (evidence_text, sources[{title,url,source}]).
    """
    if not A.enable_stage2_web_verify() or not (question or "").strip():
        return "", []

    src_timeout = A.stage2_web_per_source_timeout()
    total_timeout = A.stage2_web_total_timeout()
    max_snips = A.stage2_web_max_snippets()

    def _tavily():
        from app.services.tavily_service import search_web
        out = []
        for r in (search_web(question, max_results=3) or []):
            out.append({"title": r.get("title", ""), "url": r.get("url", ""),
                        "snippet": (r.get("content", "") or "")[:400], "source": "Tavily"})
        return out

    def _wiki():
        from app.services.wikipedia_service import search_wikipedia
        out = []
        for r in (search_wikipedia(question, limit=3) or []):
            out.append({"title": r.get("title", ""), "url": r.get("url", ""),
                        "snippet": (r.get("snippet", "") or "")[:400], "source": "Wikipedia"})
        return out

    def _openalex():
        from app.services import openalex_service
        res = openalex_service.search(question, knowledge_level or "학사")
        out = []
        for w in (getattr(res, "works", None) or []):
            title = getattr(w, "display_name", "") or ""
            abstract = getattr(w, "abstract", "") or ""
            url = getattr(w, "doi", "") or getattr(w, "id", "") or ""
            out.append({"title": title, "url": url, "snippet": abstract[:400], "source": "OpenAlex"})
        return out

    sources: List[Dict[str, Any]] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(fn): name for fn, name in
                   ((_tavily, "Tavily"), (_wiki, "Wikipedia"), (_openalex, "OpenAlex"))}
        for fut in as_completed(futures, timeout=total_timeout + 1):
            name = futures[fut]
            remaining = max(1, total_timeout - int(time.time() - t0))
            try:
                sources.extend(fut.result(timeout=min(src_timeout, remaining)) or [])
            except Exception as e:
                logger.info("2차 웹근거 소스 '%s' 건너뜀: %s", name, e)

    # 스니펫 있는 것만, 최대 N개로 컷
    sources = [s for s in sources if (s.get("snippet") or s.get("title"))][:max_snips]
    if not sources:
        return "", []

    lines = []
    for i, s in enumerate(sources, 1):
        lines.append(f"[근거{i} · {s['source']}] {s.get('title','')}\n{s.get('snippet','')}".strip())
    evidence_text = "\n\n".join(lines)
    logger.info("[StudyMate] 2차 웹근거 %d건 수집 (%.1fs): %s",
                len(sources), time.time() - t0, ", ".join(sorted({s['source'] for s in sources})))
    return evidence_text, sources


def _get_display_delay_ms() -> int:
    try:
        from app.core.policy_loader import get_display_delay_ms
        return get_display_delay_ms()
    except Exception:
        return 700


def _get_knowledge_level(request: MultiChatRequest, agent: Optional[AgentProfile] = None) -> str:
    if agent and agent.knowledgeLevel:
        return agent.knowledgeLevel
    if request.knowledgeLevel:
        return request.knowledgeLevel
    return "학사"


# ── 기존 default/tikitaka 모드 ─────────────────────────────────────────────────

def _deduplicate_agent_answers(answers: List[AgentAnswer]) -> List[AgentAnswer]:
    seen: set = set()
    result: List[AgentAnswer] = []
    for ans in answers:
        key = ans.answer.strip()[:100]
        if key not in seen:
            seen.add(key)
            result.append(ans)
    return result


def _generate_agent_answer(
    agent: AgentProfile,
    message: str,
    context: str,
    agent_index: int,
    total_agents: int,
    display_order: int,
    display_delay_ms: int,
) -> AgentAnswer:
    system_prompt = build_agent_system_prompt(agent, context)
    role_hint = build_tikitaka_role_prompt(agent_index, total_agents, agent)

    user_parts = []
    if role_hint:
        user_parts.append(f"[이번 역할] {role_hint}")
    user_parts.append(f"[사용자 메시지] {message}")
    user_prompt = "\n".join(user_parts)

    answer_text = _call_llm(system_prompt, user_prompt, knowledge_level=agent.knowledgeLevel)
    return AgentAnswer(
        agentName=agent.name,
        answer=answer_text,
        agentId=agent.agentId,
        role=agent.role or "default",
        displayOrder=display_order,
        displayDelayMs=display_delay_ms,
    )


def _generate_synthesis(agents: List[AgentProfile], answers: List[AgentAnswer], message: str) -> AgentAnswer:
    existing_answers = "\n".join(f"[{a.agentName}] {a.answer[:200]}" for a in answers)
    system_prompt = (
        "너는 여러 에이전트의 답변을 종합하는 정리 전문가다. "
        "각 에이전트의 핵심 포인트를 통합하여 최종 결론을 한국어로 명확하게 제시하라. "
        "중복 내용은 제거하고 핵심만 압축하라."
    )
    user_prompt = (
        f"[사용자 질문] {message}\n\n"
        f"[에이전트 답변들]\n{existing_answers}\n\n"
        "위 내용을 종합하여 최종 정리를 제공하라."
    )
    synthesis_text = _call_llm(system_prompt, user_prompt)
    return AgentAnswer(
        agentName=_SYNTHESIS_AGENT_NAME,
        answer=synthesis_text,
        role="synthesis",
        displayOrder=len(answers) + 1,
        displayDelayMs=_get_display_delay_ms() * len(answers),
    )


_LLM_FALLBACK_MARKERS = ("현재 Ollama", "AI 응답이", "Ollama 응답", "[GPT", "현재 AI 서비스", "일시적인 오류")


def _is_llm_fallback(text: str) -> bool:
    t = (text or "").strip()
    return (not t) or any(t.startswith(m) or m in t[:40] for m in _LLM_FALLBACK_MARKERS)


def _call_llm_with_params(
    provider: str, system: str, user: str,
    params: Dict[str, Any], knowledge_level: Optional[str] = None,
) -> Tuple[str, str]:
    """
    provider별로 지원하는 파라미터만 전달해 LLM을 호출한다.
    반환: (텍스트, 실제_사용_provider). openai 미설정이면 ollama로 폴백한다.
    """
    prov = (provider or "ollama").strip().lower()
    if prov == "openai":
        from app.services.openai_client import chat_sync, is_enabled
        if is_enabled():
            text = chat_sync(
                system=system, user=user,
                temperature=params.get("temperature", 0.4),
                max_tokens=params.get("max_tokens", 1200),
                top_p=params.get("top_p"),
                presence_penalty=params.get("presence_penalty"),
                frequency_penalty=params.get("frequency_penalty"),
                timeout=params.get("timeout_seconds"),
            )  # OpenAI는 top_k/repeat_penalty 미지원 → 전달하지 않음
            return text, "openai"
        logger.info("provider=openai 비활성 → ollama 폴백")
        prov = "ollama"
    # ollama
    from app.services.ollama_client import ask_ollama
    text = ask_ollama(
        system, user,
        temperature=params.get("temperature"),
        max_tokens=params.get("max_tokens"),
        knowledge_level=knowledge_level,
        top_p=params.get("top_p"),
        top_k=params.get("top_k"),
        repeat_penalty=params.get("repeat_penalty"),
        timeout=params.get("timeout_seconds"),
    )
    return text, "ollama"


def _stage1_initial(agent: AgentProfile, message: str, context: str) -> str:
    """1차 빠른 초안 — 반드시 Ollama (provider는 agent_settings에서 stage=1로 강제)."""
    system = build_agent_system_prompt(agent, context)
    # 성격 지시를 user 프롬프트 '마지막'에 다시 못박는다(system만으로는 모델이 성격을 버림).
    directive = build_persona_directive(
        agent.personality or agent.tone or agent.style, agent.customInstruction
    )
    user = (
        f"[사용자 질문] {message}\n\n"
        "[이번 단계: 1차 빠른 초안]\n"
        "핵심 정의 → 대표 예시 → 한 줄 결론 순서로 빠르게 답하라. "
        "완벽하게 길게 쓰려 하지 말고, 질문에 바로 도움이 되는 핵심만 담아라.\n\n"
        f"{directive}"
    )
    params = A.resolve_agent_generation_params(to_profile_key(agent.personality or agent.tone or agent.style), 1)
    text, _ = _call_llm_with_params("ollama", system, user, params, knowledge_level=agent.knowledgeLevel)
    return text


def _stage2_validate(agent: AgentProfile, message: str, own_initial: str, others_text: str,
                     repair_instruction: Optional[str] = None, evidence: str = "") -> Tuple[str, str]:
    """2차 검증/정제 답안 — provider는 agent_settings stage=2. 반환: (텍스트, provider)."""
    system = build_agent_system_prompt(agent)
    user_parts = [
        f"[사용자 질문] {message}",
        f"[너의 1차 초안]\n{own_initial}",
    ]
    if others_text:
        user_parts.append(f"[다른 에이전트의 1차 초안]\n{others_text}")
    if evidence:
        user_parts.append(
            "[웹 근거 자료 — 사실 검증용]\n" + evidence +
            "\n위 근거와 충돌하는 내용은 근거에 맞게 바로잡아라. 근거에 없는 내용을 지어내지 마라."
        )
    user_parts.append(
        "[이번 단계: 2차 검증 답안]\n"
        "1차 초안의 오류·누락·개념 혼동을 점검하고 바로잡아, 더 정확하고 정제된 답을 작성하라. "
        "특히 SQL/프로그래밍/수학/과학 개념은 정확성을 최우선으로 한다. "
        "예: DML(SELECT/INSERT/UPDATE/DELETE)과 DDL(CREATE/ALTER/DROP)을 섞지 마라. "
        "1차 초안을 그대로 반복하지 말고 보완하라."
    )
    # 정확성 지시 뒤에 성격 지시를 마지막에 못박는다(정확성에 눌려 성격이 사라지는 것 방지).
    user_parts.append(build_persona_directive(
        agent.personality or agent.tone or agent.style, agent.customInstruction, repair_instruction
    ))
    params = A.resolve_agent_generation_params(to_profile_key(agent.personality or agent.tone or agent.style), 2)
    return _call_llm_with_params(params["provider"], system, "\n\n".join(user_parts),
                                 params, knowledge_level=agent.knowledgeLevel)


def _stage3_feedback(from_agent: AgentProfile, targets: List[Tuple[AgentProfile, str]],
                     message: str) -> Tuple[str, str]:
    """3차 상호 피드백 (from → 나머지 에이전트 전원). 반환: (피드백, provider)."""
    system = build_agent_system_prompt(from_agent)
    target_block = "\n\n".join(
        f"[{tgt.name}의 답변]\n{ans}" for tgt, ans in targets
    )
    target_names = ", ".join(tgt.name for tgt, _ in targets)
    user = (
        f"[사용자 질문] {message}\n\n"
        f"{target_block}\n\n"
        "[이번 단계: 3차 상호 피드백]\n"
        f"위 다른 에이전트({target_names})의 답변을 너의 성격과 관점에서 평가하라. "
        "각 답변의 좋은 점 / 부족한 점 / 개선 방향을 구체적으로 짚어라. "
        "단순 칭찬은 금지하고, 실제로 도움이 되는 피드백을 작성하라.\n\n"
        + build_persona_directive(
            from_agent.personality or from_agent.tone or from_agent.style, from_agent.customInstruction
        )
    )
    params = A.resolve_agent_generation_params(_personality_type(from_agent), 3)
    return _call_llm_with_params(params["provider"], system, user, params, knowledge_level=from_agent.knowledgeLevel)


def _run_pool(fn, items, parallel):
    """단계 내 병렬 실행 헬퍼 (parallel=False면 순차)."""
    if parallel and len(items) > 1:
        with ThreadPoolExecutor(max_workers=len(items)) as ex:
            return list(ex.map(fn, items))
    return [fn(i) for i in items]


# ── 단계별 compute 헬퍼 (블로킹/스트리밍 공용) ───────────────────────────────────

def _personality_type(agent: AgentProfile) -> str:
    """프론트 카드 표시용 정규 성격 키 (creative/sardonic/logical/...)."""
    return to_profile_key(agent.personality or agent.tone or agent.style)


def _agent_index_map(agents: List[AgentProfile]) -> Dict[str, int]:
    """에이전트 이름 → 1-based 표시 순서. 프론트가 에이전트 1→2→3을 확정 정렬하는 키."""
    return {a.name: i + 1 for i, a in enumerate(agents)}


def _compute_stage1(request: MultiChatRequest, agents: List[AgentProfile], context: str):
    """1차 빠른 초안 (Ollama 전용, 병렬). 반환: (steps, initial_map, provider, elapsedMs, status)."""
    provider = A.resolve_provider_for_stage(1)
    t1 = time.time()
    # 라이브 진단용: 각 에이전트의 '도착한 성격 라벨 → 정규키'를 남긴다.
    # 모든 에이전트가 friendly로 찍히면 Spring/프론트가 성격 라벨을 안 보내는 것이다.
    logger.info("[StudyMate] stage1 persona 매핑: %s", {
        a.name: f"{(a.personality or a.tone or a.style) or 'None'}→{_personality_type(a)}" for a in agents
    })

    def _run1(a: AgentProfile):
        t_agent = time.time()
        try:
            text = _stage1_initial(a, request.message, context)
        except Exception as e:
            logger.error("stage1 에이전트 '%s' 실패: %s", a.name, e)
            text = A.stage1_timeout_fallback_text()
        return a, text, int((time.time() - t_agent) * 1000)

    results = _run_pool(_run1, agents, A.enable_parallel_stage1())
    elapsed = int((time.time() - t1) * 1000)
    status = "completed"
    initial_map: Dict[str, str] = {}
    steps: List[InitialAnswerStep] = []
    idx_map = _agent_index_map(agents)
    for a, text, agent_ms in results:
        if _is_llm_fallback(text):
            status = "timeout_fallback"
            if not (text or "").strip():
                text = A.stage1_timeout_fallback_text()
        initial_map[a.name] = text
        ai = idx_map.get(a.name)
        steps.append(InitialAnswerStep(
            agentName=a.name, answer=text, agentId=a.agentId,
            agentIndex=ai, displayOrder=ai, stage=1,
            personalityType=_personality_type(a), knowledgeLevel=a.knowledgeLevel,
            provider=provider, elapsedMs=agent_ms,
        ))
    logger.info("[StudyMate] stage=1 provider=%s elapsedMs=%d status=%s agents=%d",
                provider, elapsed, status, len(agents))
    return steps, initial_map, provider, elapsed, status


def _compute_stage2(request: MultiChatRequest, agents: List[AgentProfile], initial_map: Dict[str, str]):
    """2차 검증/정제 (병렬, best-effort). 반환: (steps, validated_map, provider, elapsedMs, sources)."""
    provider = A.resolve_provider_for_stage(2)
    t2 = time.time()

    # 웹 근거는 질문당 1회만 수집해 모든 에이전트가 공유한다(지연/비용 관리).
    kl = _get_knowledge_level(request, agents[0] if agents else None)
    evidence, sources = _gather_web_evidence(request.message, kl)

    def _run2(a: AgentProfile):
        own = initial_map.get(a.name, "")
        # 다른 에이전트 1차 초안은 컨텍스트 참고용으로만 축약(contextPreview) — 최종 출력은 자르지 않는다.
        others = "\n\n".join(
            f"[{b.name}]\n{initial_map.get(b.name, '')[:300]}" for b in agents if b.name != a.name
        )
        t_agent = time.time()
        try:
            text, prov = _stage2_validate(a, request.message, own, others, evidence=evidence)
            return a, text, prov, int((time.time() - t_agent) * 1000)
        except Exception as e:
            logger.warning("stage2 에이전트 '%s' 실패 (1차로 대체): %s", a.name, e)
            return a, own, "ollama", int((time.time() - t_agent) * 1000)

    try:
        results = _run_pool(_run2, agents, A.enable_parallel_stage2())
    except Exception as e:
        logger.warning("stage2 전체 실패 (1차로 대체): %s", e)
        results = [(a, initial_map.get(a.name, ""), "ollama", 0) for a in agents]
    elapsed = int((time.time() - t2) * 1000)

    validated_map: Dict[str, str] = {}
    steps: List[ValidatedAnswerStep] = []
    provs: set = set()
    idx_map = _agent_index_map(agents)
    for a, text, prov, agent_ms in results:
        provs.add(prov)
        final_text = text or initial_map.get(a.name, "")
        if _is_llm_fallback(text):
            final_text = initial_map.get(a.name, "") or final_text
        validated_map[a.name] = final_text
        revised = final_text.strip() != initial_map.get(a.name, "").strip()
        ai = idx_map.get(a.name)
        steps.append(ValidatedAnswerStep(
            agentName=a.name, answer=final_text, agentId=a.agentId, revised=revised,
            agentIndex=ai, displayOrder=ai, stage=2,
            personalityType=_personality_type(a), knowledgeLevel=a.knowledgeLevel,
            provider=prov, elapsedMs=agent_ms, sources=sources,
        ))
    actual = ",".join(sorted(provs)) if provs else provider
    logger.info("[StudyMate] stage=2 provider=%s elapsedMs=%d status=completed sources=%d",
                actual, elapsed, len(sources))
    return steps, validated_map, actual, elapsed, sources


def _validate_mode_personas(agents: List[AgentProfile], answers) -> List[PersonalityValidationItem]:
    """
    debate/socratic 등 비-staged 모드의 답변에도 성격 정합성 검증을 부착한다.
    answer.agentName으로 에이전트를 찾아 성격 검증을 수행한다(매칭 안 되면 건너뜀).
    """
    if not A.enable_personality_validation():
        return []
    by_name = {a.name: a for a in agents}
    texts = [getattr(ans, "answer", "") or "" for ans in answers]
    summary: List[PersonalityValidationItem] = []
    for ans in answers:
        name = getattr(ans, "agentName", None)
        agent = by_name.get(name)
        if agent is None:
            continue
        peers = [t for t in texts if t and t != (getattr(ans, "answer", "") or "")]
        try:
            v = validate_personality_alignment(getattr(ans, "answer", "") or "", agent, 2, peer_answers=peers)
        except Exception as e:
            logger.warning("모드 성격 검증 실패 '%s': %s", name, e)
            continue
        summary.append(PersonalityValidationItem(
            agentName=name, personalityType=v.get("personalityType"),
            score=v.get("score"), passed=v.get("passed"),
            issues=v.get("issues", []), note=v.get("note"),
        ))
    return summary


def _summarize_validation(agents, validation_map) -> List[PersonalityValidationItem]:
    summary: List[PersonalityValidationItem] = []
    for a in agents:
        v = validation_map.get(a.name)
        if not v:
            continue
        summary.append(PersonalityValidationItem(
            agentName=a.name, personalityType=v.get("personalityType"),
            score=v.get("score"), passed=v.get("passed"),
            issues=v.get("issues", []), note=v.get("note"),
        ))
    return summary


def _compute_validation(request: MultiChatRequest, agents: List[AgentProfile],
                        initial_map: Dict[str, str], validated_map: Dict[str, str],
                        validated_steps: List[ValidatedAnswerStep]):
    """
    성격 검증 + 미달 시 보정(repair). 2차 답안 기준.
    - validate_personality_alignment로 점수화
    - 점수 미달 + repair 활성 시: 성격 지시를 못박아 stage2를 1회 재생성하고 더 좋아지면 채택
    - validated_map / validated_steps(answer·revised) 를 보정 결과로 갱신
    반환: (validation_map, pv_summary)
    """
    validation_map: Dict[str, Dict[str, Any]] = {}
    if not A.enable_personality_validation():
        return validation_map, []

    step_by_name = {s.agentName: s for s in validated_steps}

    for a in agents:
        peers = [validated_map.get(b.name, "") for b in agents if b.name != a.name]
        try:
            v = validate_personality_alignment(validated_map.get(a.name, ""), a, 2, peer_answers=peers)
        except Exception as e:
            logger.warning("성격 검증 실패 '%s': %s", a.name, e)
            continue

        # 미달이면 성격 지시 + repairInstruction을 못박아 stage2 재생성으로 보정한다.
        if not v.get("passed", True):
            others = "\n\n".join(
                f"[{b.name}]\n{initial_map.get(b.name, '')[:300]}" for b in agents if b.name != a.name
            )
            own = initial_map.get(a.name, "")

            def _regen(instruction: str, _a=a, _own=own, _others=others) -> str:
                text, _ = _stage2_validate(_a, request.message, _own, _others, repair_instruction=instruction)
                return text

            try:
                new_text, repaired, used = repair_personality_if_needed(
                    validated_map.get(a.name, ""), v, a, 2, regenerate=_regen
                )
            except Exception as e:
                logger.warning("성격 보정 실패 '%s' (원문 유지): %s", a.name, e)
                new_text, repaired = validated_map.get(a.name, ""), False

            if repaired and new_text and not _is_llm_fallback(new_text):
                validated_map[a.name] = new_text
                # 재검증으로 점수/통과 갱신
                try:
                    v = validate_personality_alignment(new_text, a, 2, peer_answers=peers)
                except Exception:
                    pass
                step = step_by_name.get(a.name)
                if step is not None:
                    step.answer = new_text
                    step.revised = new_text.strip() != initial_map.get(a.name, "").strip()
                logger.info("[StudyMate] 성격 보정 적용 agent=%s score→%.3f passed=%s",
                            a.name, v.get("score", 0.0), v.get("passed"))

        validation_map[a.name] = v

    return validation_map, _summarize_validation(agents, validation_map)


def _compute_stage3(request: MultiChatRequest, agents: List[AgentProfile],
                    validated_map: Dict[str, str], validation_map: Dict[str, Dict[str, Any]]):
    """3차 상호 피드백 (병렬, 2명 이상). 반환: (peer_steps, provider, elapsedMs)."""
    provider = A.resolve_provider_for_stage(3)
    peer_steps: List[PeerFeedbackStep] = []
    elapsed = 0
    provs: set = set()
    n = len(agents)
    # 에이전트가 2명 이상이면 항상 fromAgent당 1개씩 피드백을 만든다.
    # (실패해도 빈 배열로 두지 않고 fallback 피드백을 채워 length == N을 보장한다.)
    idx_map = _agent_index_map(agents)
    if n >= 2:
        t3 = time.time()

        def _run3(frm: AgentProfile):
            targets = [(b, validated_map.get(b.name, "")) for b in agents if b.name != frm.name]
            target_ids = [b.agentId for b in agents if b.name != frm.name and b.agentId is not None]
            target_names = ", ".join(b.name for b, _ in targets)
            t_agent = time.time()
            try:
                fb, prov = _stage3_feedback(frm, targets, request.message)
                if _is_llm_fallback(fb):
                    raise ValueError("stage3 fallback marker in feedback")
            except Exception as e:
                logger.warning("stage3 %s 실패 (fallback 피드백 생성): %s", frm.name, e)
                fb = (
                    f"상호 피드백 생성 중 일부 오류가 발생했지만, 1차/2차 답변을 기준으로 "
                    f"{target_names}의 답변에 대한 보완점을 정리합니다. "
                    "핵심 개념의 정확성과 예시의 적절성을 다시 확인하고, 누락된 부분을 보강하면 좋겠습니다."
                )
                prov = "fallback"
            pv = validation_map.get(frm.name)
            pv_obj = ({"passed": pv.get("passed"), "score": pv.get("score")} if pv else None)
            ai = idx_map.get(frm.name)
            step = PeerFeedbackStep(
                fromAgent=frm.name, toAgent=target_names, feedback=fb,
                personalityValidation=pv_obj, fromAgentId=frm.agentId,
                agentIndex=ai, displayOrder=ai, stage=3,
                targetAgentIds=target_ids, personalityType=_personality_type(frm),
                provider=prov, elapsedMs=int((time.time() - t_agent) * 1000),
            )
            return step, prov

        for step, prov in _run_pool(_run3, agents, True):
            peer_steps.append(step)
            if prov:
                provs.add(prov)
        elapsed = int((time.time() - t3) * 1000)
        if provs:
            provider = ",".join(sorted(provs))
        logger.info("[StudyMate] stage=3 provider=%s elapsedMs=%d status=completed feedbacks=%d",
                    provider, elapsed, len(peer_steps))
    return peer_steps, provider, elapsed


# ── 토론(debate) 전용 헬퍼: 1차 의견 → 상호 피드백 → 보완 답변 → 종합 정리 ──────────

# 토론 입장 분화용 관점 시드 — 각 토론자가 서로 다른 각도를 잡게 한다(성격과 결합해 입장이 갈림).
_DEBATE_STANCES = [
    "원리·정의 중심 입장(이 주제의 본질이 무엇인지가 핵심이라고 주장)",
    "실용·응용 중심 입장(실제로 어떻게 쓰이고 왜 중요한지가 핵심이라고 주장)",
    "오해·함정 중심 입장(사람들이 흔히 틀리는 지점이 핵심이라고 주장)",
    "비판·한계 중심 입장(이 개념/주장의 한계와 반례가 핵심이라고 주장)",
]
_DEBATE_MODE_ALIASES = {"debate", "discussion", "tikitaka", "multi_agent_discussion", "토론", "토론 모드"}
_DEBATE_CRITIQUE_TERMS = ("부족", "보완", "틀림", "불명확", "오해", "빠짐", "관점", "반박", "부정확", "약점", "한계")
_DEBATE_REQUIRED_SYSTEM_PROMPT = (
    "너희는 각자 독립된 에이전트다. 각자 답변만 하고 끝내면 안 된다. "
    "먼저 1차 의견을 낸 뒤, 반드시 다른 에이전트의 답변을 직접 지목해서 부족한 점, "
    "틀린 점, 보완할 점, 관점 차이를 말해야 한다. 그 다음 받은 피드백을 반영해 "
    "보완 답변을 작성한다. 출력은 반드시 initialAnswers, peerFeedbacks, revisedAnswers, "
    "debateSummary 구조를 따른다. peerFeedbacks가 비어 있으면 실패다."
)


def _debate_display_name(agent: AgentProfile, index: int) -> str:
    return f"에이전트 {index}({agent.name})"


def _ensure_debate_agents(agents: List[AgentProfile]) -> List[AgentProfile]:
    if len(agents) >= 2:
        return agents
    base = list(agents) if agents else [_DEFAULT_AGENT]
    base.append(AgentProfile(
        id=-2, agentId=-2, name="비판 검토 에이전트", role="debater",
        personality="비판형", personalityStrength="moderate", knowledgeLevel=base[0].knowledgeLevel or "학사",
        customInstruction="다른 에이전트의 주장에 부족한 점과 보완할 점을 논리적으로 지적한다.",
    ))
    return base


def _feedback_mentions_target(feedback: str, target: AgentProfile, target_index: int) -> bool:
    text = feedback or ""
    return target.name in text or f"에이전트 {target_index}" in text


def _feedback_has_critique(feedback: str) -> bool:
    text = feedback or ""
    formal_only = ("좋은 답변입니다", "잘 설명했습니다", "동의합니다", "보완할 점이 없습니다")
    if any(bad in text for bad in formal_only) and not any(term in text for term in _DEBATE_CRITIQUE_TERMS):
        return False
    return any(term in text for term in _DEBATE_CRITIQUE_TERMS)


def _valid_debate_feedback(feedback: str, target: AgentProfile, target_index: int) -> bool:
    return bool((feedback or "").strip()) and _feedback_mentions_target(feedback, target, target_index) and _feedback_has_critique(feedback)


def _fallback_debate_feedback(from_agent: AgentProfile, from_index: int, target: AgentProfile, target_index: int) -> str:
    variants = [
        f"{_debate_display_name(target, target_index)}의 답변은 핵심 설명은 있지만, {_debate_display_name(from_agent, from_index)}의 관점과 비교했을 때 구체적인 예시가 부족합니다. 사용자가 개념을 실제 상황에 연결하기 어렵기 때문에 예시 보완이 필요합니다.",
        f"{_debate_display_name(target, target_index)}의 답변은 쉽게 설명하려는 장점은 있지만, 기술적 정확성이 부족합니다. 특히 용어 정의와 실제 작동 방식이 분리되어 있어 보완이 필요합니다.",
        f"{_debate_display_name(target, target_index)}의 답변은 전문성은 있지만, 초보자가 이해하기에는 설명이 압축되어 있습니다. 개념을 처음 접하는 사용자를 위해 쉬운 비유나 단계적 설명이 필요합니다.",
    ]
    return variants[(from_index + target_index) % len(variants)]


def _debate_initial_records(agents: List[AgentProfile], initial_map: Dict[str, str]) -> List[DebateInitialAnswer]:
    return [DebateInitialAnswer(
        agentIndex=i + 1, agentName=a.name, displayName=_debate_display_name(a, i + 1),
        answer=initial_map.get(a.name, ""),
    ) for i, a in enumerate(agents)]


def _debate_revised_records(agents: List[AgentProfile], revised_map: Dict[str, str]) -> List[DebateRevisedAnswer]:
    return [DebateRevisedAnswer(
        agentIndex=i + 1, agentName=a.name, displayName=_debate_display_name(a, i + 1),
        answer=revised_map.get(a.name, ""),
    ) for i, a in enumerate(agents)]


def _peer_step_from_debate_feedback(item: DebatePeerFeedback, provider: str, elapsed_ms: int) -> PeerFeedbackStep:
    return PeerFeedbackStep(
        fromAgent=item.fromAgentName, toAgent=item.toAgentName, feedback=item.feedback,
        agentIndex=item.fromAgentIndex, displayOrder=item.fromAgentIndex, stage=3,
        fromAgentId=None, targetAgentIds=[], personalityType=None, provider=provider, elapsedMs=elapsed_ms,
    )


def _compute_debate_opening(request: MultiChatRequest, agents: List[AgentProfile], context: str):
    """
    1차 입론 — **순차** 진행. 첫 토론자는 입장을 세우고, 이후 토론자는 '앞 토론자의 발언을 직접 보고'
    이름을 부르며 동의/반박하면서 자기 입장을 편다. (병렬이면 서로를 못 봐서 토론이 안 됨 → 순차 강제.)
    """
    provider = A.resolve_provider_for_stage(1)
    t = time.time()
    opening_map: Dict[str, str] = {}
    steps: List[InitialAnswerStep] = []
    transcript: List[str] = []  # 지금까지의 발언 기록(이름 포함)

    for i, a in enumerate(agents):
        stance = _DEBATE_STANCES[i % len(_DEBATE_STANCES)]
        system = build_agent_system_prompt(a, context) + "\n\n" + _DEBATE_REQUIRED_SYSTEM_PROMPT
        if not transcript:
            turn_instr = (
                "너는 첫 번째 토론자다. 이 주제에 대한 '너만의 분명한 입장'을 한 문장으로 못박고, "
                "타당한 근거 1~2개로 주장하라. 청중(사용자)을 설득하는 게 목표다."
            )
        else:
            prior = "\n\n".join(transcript)
            turn_instr = (
                f"[지금까지의 토론]\n{prior}\n\n"
                "이제 네 차례다. 위 앞 토론자(들)의 발언을 **이름을 부르며 직접** 받아쳐라. "
                "어디에 동의하고 어디가 틀렸는지 콕 집어 반박하고(예: '○○ 말은 ~한데, 그건 ~라서 약해'), "
                "그 위에 너만의 입장을 세워 청중을 설득하라. 앞사람과 같은 말 반복 금지."
            )
        user = (
            f"[토론 주제] {request.message}\n\n"
            f"[너의 입장 각도] {stance}\n\n"
            "[이번 단계: 1차 입론 — 서로 주고받는 토론이다]\n"
            f"{turn_instr}\n짧고 설득력 있게.\n\n"
            + build_persona_directive(a.personality or a.tone or a.style, a.customInstruction)
        )
        params = A.resolve_agent_generation_params(_personality_type(a), 1)
        t_a = time.time()
        try:
            text, _ = _call_llm_with_params("ollama", system, user, params, knowledge_level=a.knowledgeLevel)
        except Exception as e:
            logger.error("debate 입론 '%s' 실패: %s", a.name, e)
            text = A.stage1_timeout_fallback_text()
        if not (text or "").strip():
            text = A.stage1_timeout_fallback_text()
        opening_map[a.name] = text
        transcript.append(f"[{a.name}]\n{text}")
        steps.append(InitialAnswerStep(
            agentName=a.name, answer=text, agentId=a.agentId,
            agentIndex=i + 1, displayOrder=i + 1, stage=1,
            personalityType=_personality_type(a), knowledgeLevel=a.knowledgeLevel,
            provider=provider, elapsedMs=int((time.time() - t_a) * 1000),
        ))
    elapsed = int((time.time() - t) * 1000)
    logger.info("[StudyMate] debate 입론(순차) elapsedMs=%d agents=%d", elapsed, len(agents))
    return steps, opening_map, provider, elapsed


def _compute_debate_rebuttal(request: MultiChatRequest, agents: List[AgentProfile],
                             opening_map: Dict[str, str]):
    """상호 반박: 모든 토론자 쌍(from -> to)에 대해 실제 대상 지목 피드백을 보장한다."""
    provider = A.resolve_provider_for_stage(3)
    t = time.time()
    peer_steps: List[PeerFeedbackStep] = []
    peer_feedbacks: List[DebatePeerFeedback] = []
    provs: set = set()
    if len(agents) < 2:
        return peer_steps, peer_feedbacks, provider, 0

    all_openings = "\n\n".join(
        f"[{_debate_display_name(a, i + 1)}]\n{opening_map.get(a.name, '')}"
        for i, a in enumerate(agents)
    )

    def _run(pair):
        from_index, frm, target_index, target = pair
        target_answer = opening_map.get(target.name, "")
        system = build_agent_system_prompt(frm) + "\n\n" + _DEBATE_REQUIRED_SYSTEM_PROMPT
        params = A.resolve_agent_generation_params(_personality_type(frm), 3)
        t_a = time.time()
        prov = params.get("provider", provider)
        feedback = ""
        for attempt in range(2):
            retry = "\n이전 피드백은 대상 지목이나 비평성이 부족했다. 이번에는 반드시 대상 이름과 부족/보완/오해/관점 차이를 포함하라." if attempt else ""
            user = (
                f"[토론 주제] {request.message}\n\n"
                f"[전체 1차 의견]\n{all_openings}\n\n"
                f"[네가 평가할 대상] {_debate_display_name(target, target_index)}\n"
                f"[대상 답변]\n{target_answer}\n\n"
                "[이번 단계: 서로 피드백]\n"
                f"너는 {_debate_display_name(frm, from_index)}다. "
                f"반드시 {_debate_display_name(target, target_index)}의 답변을 직접 지목해서 평가하라. "
                "형식적 칭찬, 단순 동의, '보완할 점 없음'은 실패다. "
                "부족한 점, 틀린 점, 불명확한 점, 오해 가능성, 관점 차이 중 최소 하나를 구체적으로 지적하고 "
                "사용자가 왜 보완 설명을 필요로 하는지 말하라. 2~4문장으로 작성하라."
                f"{retry}\n\n"
                + build_persona_directive(frm.personality or frm.tone or frm.style, frm.customInstruction)
            )
            try:
                candidate, prov = _call_llm_with_params(params["provider"], system, user, params,
                                                        knowledge_level=frm.knowledgeLevel)
                if candidate and not _is_llm_fallback(candidate) and _valid_debate_feedback(candidate, target, target_index):
                    feedback = candidate.strip()
                    break
            except Exception as e:
                logger.warning("debate 피드백 %s -> %s 생성 실패(attempt=%d): %s", frm.name, target.name, attempt + 1, e)
        if not feedback:
            feedback = _fallback_debate_feedback(frm, from_index, target, target_index)
            prov = "fallback"

        item = DebatePeerFeedback(
            fromAgentIndex=from_index,
            fromAgentName=frm.name,
            toAgentIndex=target_index,
            toAgentName=target.name,
            title=f"{_debate_display_name(frm, from_index)} → {_debate_display_name(target, target_index)}",
            feedback=feedback,
        )
        elapsed_ms = int((time.time() - t_a) * 1000)
        return item, _peer_step_from_debate_feedback(item, prov, elapsed_ms), prov

    pairs = [
        (i + 1, frm, j + 1, target)
        for i, frm in enumerate(agents)
        for j, target in enumerate(agents)
        if i != j
    ]
    for item, step, prov in _run_pool(_run, pairs, True):
        peer_feedbacks.append(item)
        peer_steps.append(step)
        if prov:
            provs.add(prov)

    if not peer_feedbacks and len(agents) >= 2:
        frm, target = agents[0], agents[1]
        item = DebatePeerFeedback(
            fromAgentIndex=1,
            fromAgentName=frm.name,
            toAgentIndex=2,
            toAgentName=target.name,
            title=f"{_debate_display_name(frm, 1)} → {_debate_display_name(target, 2)}",
            feedback=_fallback_debate_feedback(frm, 1, target, 2),
        )
        peer_feedbacks.append(item)
        peer_steps.append(_peer_step_from_debate_feedback(item, "fallback", 0))
        provs.add("fallback")

    elapsed = int((time.time() - t) * 1000)
    if provs:
        provider = ",".join(sorted(provs))
    logger.info("[StudyMate] debate pairwise 피드백 elapsedMs=%d feedbacks=%d", elapsed, len(peer_feedbacks))
    return peer_steps, peer_feedbacks, provider, elapsed

def _feedback_received_map(agents: List[AgentProfile], peer_feedbacks: List[DebatePeerFeedback]) -> Dict[str, str]:
    """각 에이전트가 받은 pairwise 피드백을 모은다. 최종 변론 입력용."""
    out: Dict[str, str] = {}
    for a in agents:
        parts = [
            f"[{fb.title}]\n{fb.feedback}"
            for fb in peer_feedbacks
            if fb.toAgentName == a.name
        ]
        out[a.name] = "\n\n".join(parts)
    return out


def _compute_debate_revision(request: MultiChatRequest, agents: List[AgentProfile],
                             initial_map: Dict[str, str], fb_map: Dict[str, str]):
    """최종 변론: 받은 반박에 재반론하고 입장을 강화해 청중을 설득한다. 반환: (steps, revised_map, provider, elapsedMs)."""
    provider = A.resolve_provider_for_stage(2)
    t = time.time()

    def _run(a: AgentProfile):
        own = initial_map.get(a.name, "")
        fb = fb_map.get(a.name, "")
        system = build_agent_system_prompt(a) + "\n\n" + _DEBATE_REQUIRED_SYSTEM_PROMPT
        user = (
            f"[토론 주제] {request.message}\n\n"
            f"[너의 1차 입론]\n{own}\n\n"
            f"[상대 토론자들이 너에게 한 반박]\n{fb or '(특별한 반박은 없었다)'}\n\n"
            "[이번 단계: 최종 변론]\n"
            "상대의 반박에 재반론하라. 타당한 지적은 인정해 보완하고, 동의 못 하는 부분은 근거로 되받아쳐라. "
            "그리고 네 입장이 옳다는 걸 청중(사용자)에게 한 번 더 설득력 있게 마무리하라. 성격·말투는 유지한다.\n\n"
            + build_persona_directive(a.personality or a.tone or a.style, a.customInstruction)
        )
        params = A.resolve_agent_generation_params(_personality_type(a), 2)
        t_a = time.time()
        try:
            text, prov = _call_llm_with_params(params["provider"], system, user, params,
                                               knowledge_level=a.knowledgeLevel)
        except Exception as e:
            logger.warning("debate 보완 '%s' 실패 (1차 유지): %s", a.name, e)
            text, prov = own, "fallback"
        return a, text, prov, int((time.time() - t_a) * 1000)

    results = _run_pool(_run, agents, A.enable_parallel_stage2())
    elapsed = int((time.time() - t) * 1000)
    revised_map: Dict[str, str] = {}
    steps: List[ValidatedAnswerStep] = []
    provs: set = set()
    idx_map = _agent_index_map(agents)
    for a, text, prov, ms in results:
        final = text if (text and not _is_llm_fallback(text)) else initial_map.get(a.name, "")
        revised_map[a.name] = final
        provs.add(prov)
        ai = idx_map.get(a.name)
        steps.append(ValidatedAnswerStep(
            agentName=a.name, answer=final, agentId=a.agentId,
            revised=(final.strip() != initial_map.get(a.name, "").strip()),
            agentIndex=ai, displayOrder=ai, stage=2,
            personalityType=_personality_type(a), knowledgeLevel=a.knowledgeLevel,
            provider=prov, elapsedMs=ms,
        ))
    actual = ",".join(sorted(provs)) if provs else provider
    logger.info("[StudyMate] debate 보완 elapsedMs=%d agents=%d", elapsed, len(agents))
    return steps, revised_map, actual, elapsed


def _compute_debate_summary(request: MultiChatRequest, agents: List[AgentProfile],
                            revised_map: Dict[str, str]) -> str:
    """심사 정리: 양측 핵심 논거를 공정히 정리하고 최종 판단을 청중(사용자)에게 위임한다."""
    block = "\n\n".join(f"[{a.name}]\n{revised_map.get(a.name, '')}" for a in agents)
    system = _DEBATE_REQUIRED_SYSTEM_PROMPT + "\n\n" + (
        "너는 토론 심사 진행자다. 양측 토론자의 가장 강한 논거를 어느 한쪽으로 치우치지 않게 공정히 정리하고, "
        "최종 판단은 청중에게 맡긴다. 정답을 단정하지 않는다. 반드시 한국어로."
    )
    user = (
        f"[토론 주제] {request.message}\n\n[토론자들의 최종 변론]\n{block}\n\n"
        "각 토론자의 핵심 주장과 가장 설득력 있던 근거를 한 줄씩 공정하게 정리하라. "
        "그리고 '최종 판단은 청중(당신)의 몫'이라고 밝히며, 어느 쪽 논거가 더 설득력 있었는지 "
        "사용자에게 묻는 질문 1개로 마무리하라. 특정 입장을 정답으로 단정하지 마라."
    )
    params = A.resolve_agent_generation_params("professional", 3)
    try:
        text, _ = _call_llm_with_params(
            params["provider"], system, user, params,
            knowledge_level=_get_knowledge_level(request, agents[0] if agents else None),
        )
        if text and not _is_llm_fallback(text):
            return text.strip()
    except Exception as e:
        logger.warning("debate 종합 정리 실패: %s", e)
    return ""


def _build_stage_infos(initial_steps, validated_steps, peer_steps, pv_summary,
                       s1, s2, s3, sources=None):
    """3개 StageInfo를 만든다. s1/s2/s3 = (provider, elapsedMs, status) 튜플."""
    return [
        StageInfo(stage=1, title="1차 답변 - 빠른 초안", provider=s1[0], status=s1[2],
                  elapsedMs=s1[1], answers=[s.model_dump() for s in initial_steps]),
        StageInfo(stage=2, title="2차 답변 - 검증 답안", provider=s2[0], status=s2[2],
                  elapsedMs=s2[1], answers=[s.model_dump() for s in validated_steps],
                  sources=sources or []),
        StageInfo(stage=3, title="3차 답변 - 에이전트 피드백 및 성격 검증", provider=s3[0], status=s3[2],
                  elapsedMs=s3[1], feedbacks=[s.model_dump() for s in peer_steps],
                  personalityValidationSummary=pv_summary),
    ]


def _build_default_response(request, agents, initial_map, validated_map,
                            initial_steps, validated_steps, peer_steps, pv_summary, stages):
    delay_ms = _get_display_delay_ms()
    answers: List[AgentAnswer] = []
    for idx, a in enumerate(agents):
        answers.append(AgentAnswer(
            agentName=a.name,
            answer=validated_map.get(a.name) or initial_map.get(a.name, ""),
            agentId=a.agentId,
            role=a.role or "default",
            displayOrder=idx + 1,
            displayDelayMs=idx * delay_ms,
            status="SUCCESS",
        ))
    if not answers:
        answers.append(AgentAnswer(
            agentName="시스템",
            answer="현재 AI 서비스에 일시적으로 접근할 수 없습니다. 잠시 후 다시 시도해 주세요.",
            displayOrder=1, displayDelayMs=0, status="FAILED",
        ))
    process_steps = ProcessSteps(
        initialAnswers=initial_steps,
        validatedAnswers=validated_steps,
        peerFeedback=peer_steps,
        personalityValidationSummary=pv_summary,
    )
    return MultiChatResponse(
        mode=request.mode,
        answers=answers,
        status="COMPLETED",
        question=request.message,
        processSteps=process_steps,
        stages=stages,
    )


def _prep_default_context(context: str, rag_context: str) -> str:
    if rag_context:
        return f"{context}\n\n[RAG 자료]\n{rag_context}" if context else rag_context
    return context


def _run_default_mode(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    context: str,
    rag_context: str,
) -> MultiChatResponse:
    """
    1차/2차/3차 실데이터 파이프라인 (블로킹, 모든 지식수준 공통).
    스트리밍(run_default_mode_stream)과 동일한 compute 헬퍼를 공유한다.
    """
    context = _prep_default_context(context, rag_context)
    agents = active_agents or [_DEFAULT_AGENT]

    initial_steps, initial_map, p1, e1, st1 = _compute_stage1(request, agents, context)
    validated_steps, validated_map, p2, e2, sources = _compute_stage2(request, agents, initial_map)
    validation_map, pv_summary = _compute_validation(request, agents, initial_map, validated_map, validated_steps)
    peer_steps, p3, e3 = _compute_stage3(request, agents, validated_map, validation_map)

    stages = _build_stage_infos(initial_steps, validated_steps, peer_steps, pv_summary,
                                (p1, e1, st1), (p2, e2, "completed"), (p3, e3, "completed"), sources)
    return _build_default_response(request, agents, initial_map, validated_map,
                                   initial_steps, validated_steps, peer_steps, pv_summary, stages)


def run_default_mode_stream(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    context: str,
    rag_context: str,
):
    """
    제너레이터: 각 단계 완료 시 {"event","data"} dict를 yield (sync generator).
    SSE 라우트가 stage_start/stage_complete/all_complete 이벤트로 변환한다.
    """
    context = _prep_default_context(context, rag_context)
    agents = active_agents or [_DEFAULT_AGENT]

    # 1차
    yield {"event": "stage_start", "data": {"stage": 1, "title": "1차 답변 - 빠른 초안", "status": "running"}}
    initial_steps, initial_map, p1, e1, st1 = _compute_stage1(request, agents, context)
    stage1 = _build_stage_infos(initial_steps, [], [], [], (p1, e1, st1), (None, 0, "running"), (None, 0, "running"))[0]
    yield {"event": "stage_complete", "data": stage1.model_dump()}

    # 2차 (검증 포함)
    yield {"event": "stage_start", "data": {"stage": 2, "title": "2차 답변 - 검증 답안", "status": "running"}}
    validated_steps, validated_map, p2, e2, sources = _compute_stage2(request, agents, initial_map)
    validation_map, pv_summary = _compute_validation(request, agents, initial_map, validated_map, validated_steps)
    stage2 = _build_stage_infos([], validated_steps, [], pv_summary, (None, 0, "completed"), (p2, e2, "completed"), (None, 0, "running"), sources)[1]
    yield {"event": "stage_complete", "data": stage2.model_dump()}

    # 3차
    yield {"event": "stage_start", "data": {"stage": 3, "title": "3차 답변 - 에이전트 피드백 및 성격 검증", "status": "running"}}
    peer_steps, p3, e3 = _compute_stage3(request, agents, validated_map, validation_map)
    stage3 = _build_stage_infos([], [], peer_steps, pv_summary, (None, 0, "completed"), (None, 0, "completed"), (p3, e3, "completed"))[2]
    yield {"event": "stage_complete", "data": stage3.model_dump()}

    # 최종 (저장/하위호환 전체 응답)
    stages = [stage1, stage2, stage3]
    final = _build_default_response(request, agents, initial_map, validated_map,
                                    initial_steps, validated_steps, peer_steps, pv_summary, stages)
    yield {"event": "all_complete", "data": final.model_dump()}


def build_stream_generator(request: MultiChatRequest):
    """
    SSE용 이벤트 제너레이터를 만든다.
    default 계열 모드만 단계별 스트리밍하고, 그 외 모드는 블로킹 실행 후 all_complete 1회만 emit한다.
    """
    # ── feature flag: LangGraph 오케스트레이터 ──────────────────────────────
    # USE_LANGGRAPH_ORCHESTRATOR=true이면 그래프로 실행 후 all_complete 1회만 emit한다.
    # (스트리밍 단계 분해는 기존 경로에만 적용. 그래프는 흐름 제어/구조화가 목적.)
    try:
        from app.core import config as _cfg
        if getattr(_cfg, "USE_LANGGRAPH_ORCHESTRATOR", False):
            from app.services.langgraph_agent_orchestrator import run_langgraph_multi_agent

            def _graph_single():
                result = run_langgraph_multi_agent(request)
                yield {"event": "all_complete", "data": result.model_dump()}
            return _graph_single()
    except Exception as e:
        logger.warning("LangGraph 스트림 분기 실패 → 기존 경로 사용: %s", e)

    agents = _get_agents(request)
    active_agents = _filter_agents(agents, request.targetAgentId)
    context = build_context_from_previous_answers(request.previousAnswers, max_items=20)
    rag_context = _get_rag_context(request.message, request.materialId)

    # 스트리밍 표시는 '명시적으로 고른 모드'를 따른다.
    #  - 기본 채팅(basic) → 1차/2차/3차 staged (에이전트 2명 이상이어도 자동 토론 승격 안 함)
    #  - 명시적 토론(debate/discussion/...) → 토론 섹션, 명시적 소크라테스 → 소크라테스
    # (자동 토론 승격은 블로킹 run_multi_chat에만 남겨 두어 두 표시 경로를 분리한다.)
    raw = (request.mode or "default").strip().lower()
    lm = (getattr(request, "learningMode", None) or "").strip().lower()
    explicit_socratic = lm == "socratic" or (not lm and raw == "socratic")
    explicit_debate = (lm in _DEBATE_MODE_ALIASES) or (not lm and raw in _DEBATE_MODE_ALIASES)
    logger.info("[StudyMate] stream route raw=%s lm=%s explicit_debate=%s explicit_socratic=%s agents=%d",
                raw, lm, explicit_debate, explicit_socratic, len(active_agents))

    # 모드별 전용 SSE 제너레이터. all_complete 1회만 기다리지 않고 단계/섹션 단위로 즉시 내보낸다.
    if explicit_socratic:
        return run_socratic_mode_stream(request, active_agents, rag_context)
    if explicit_debate:
        return run_debate_mode_stream(request, active_agents, rag_context)
    if raw == "group_study_ai":
        # 그룹스터디 봇 모드는 단계 분해 없이 블로킹 후 all_complete 1회.
        def _single():
            result = run_multi_chat(request)
            yield {"event": "all_complete", "data": result.model_dump()}
        return _single()

    return run_default_mode_stream(request, active_agents, context, rag_context)


def _run_tikitaka_mode(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    context: str,
    rag_context: str,
) -> MultiChatResponse:
    """티키타카 3라운드 순차 체인 모드."""
    if rag_context:
        context = f"{context}\n\n[RAG 자료]\n{rag_context}" if context else rag_context

    delay_ms = _get_display_delay_ms()
    answers: List[AgentAnswer] = []

    # Round 1: initial_answer
    for idx, agent in enumerate(active_agents):
        try:
            system = build_agent_system_prompt(agent, context)
            user = f"[이번 역할] 이 질문의 핵심 개념과 원리를 명확하게 설명하라.\n[사용자 질문] {request.message}"
            text = _call_llm(system, user, knowledge_level=agent.knowledgeLevel)
            answers.append(AgentAnswer(
                agentName=agent.name,
                answer=text,
                agentId=agent.agentId,
                role=agent.role or "default",
                speechType="initial_answer",
                displayOrder=idx + 1,
                displayDelayMs=idx * delay_ms,
                status="SUCCESS",
            ))
        except Exception as e:
            logger.error("Round1 에이전트 '%s' 실패: %s", agent.name, e)
            answers.append(AgentAnswer(
                agentName=agent.name, answer="답변 생성 실패.",
                speechType="initial_answer",
                displayOrder=idx + 1, displayDelayMs=idx * delay_ms, status="FAILED",
            ))

    prev_answers_text = "\n\n".join(
        f"[{a.agentName}]\n{a.answer[:300]}" for a in answers if a.status == "SUCCESS"
    )
    base_order = len(answers)

    # Round 2: critique (policy YAML에서 키워드 참조)
    try:
        from app.core.policy_loader import get_tikitaka_validation
        tiki_policy = get_tikitaka_validation()
        critique_terms = tiki_policy.get("critique_keywords", ["부족", "누락", "한계"])
    except Exception:
        critique_terms = ["부족", "누락", "한계"]

    for idx, agent in enumerate(active_agents[:2]):  # 비판형 위주 2명
        try:
            system = build_agent_system_prompt(agent, context)
            user = (
                f"[이전 답변들]\n{prev_answers_text}\n\n"
                f"[사용자 질문] {request.message}\n\n"
                "[이번 역할] 앞서 설명된 내용에서 부족한 점, 누락된 개념, 보완이 필요한 부분을 지적하고 개선 방향을 제시하라."
            )
            text = _call_llm(system, user, knowledge_level=agent.knowledgeLevel)
            answers.append(AgentAnswer(
                agentName=agent.name, answer=text,
                agentId=agent.agentId, role=agent.role or "critic",
                speechType="critique",
                displayOrder=base_order + idx + 1,
                displayDelayMs=(base_order + idx) * delay_ms,
                status="SUCCESS",
            ))
        except Exception as e:
            logger.error("Round2 에이전트 '%s' 실패: %s", agent.name, e)

    base_order = len(answers)
    critique_text = "\n\n".join(
        f"[{a.agentName}]\n{a.answer[:300]}"
        for a in answers if a.speechType == "critique" and a.status == "SUCCESS"
    )

    # Round 3: rebuttal_or_refinement
    for idx, agent in enumerate(active_agents):
        try:
            system = build_agent_system_prompt(agent, context)
            user = (
                f"[원래 질문] {request.message}\n\n"
                f"[1차 답변]\n{prev_answers_text}\n\n"
                f"[비판/보완 의견]\n{critique_text}\n\n"
                "[이번 역할] 비판/보완 의견을 반영하여 설명을 보완하거나 반박하라. "
                "명확하게 한 가지 포인트만 추가 설명하라."
            )
            text = _call_llm(system, user, knowledge_level=agent.knowledgeLevel)
            answers.append(AgentAnswer(
                agentName=agent.name, answer=text,
                agentId=agent.agentId, role=agent.role or "default",
                speechType="rebuttal_or_refinement",
                displayOrder=base_order + idx + 1,
                displayDelayMs=(base_order + idx) * delay_ms,
                status="SUCCESS",
            ))
        except Exception as e:
            logger.error("Round3 에이전트 '%s' 실패: %s", agent.name, e)

    # 티키타카 검증
    try:
        from app.services.mode_validator import validate_mode_response
        v_result = validate_mode_response("tikitaka", [a.model_dump() for a in answers])
        validation = ValidationSummary(
            passed=v_result["passed"],
            issues=v_result.get("issues", []),
        )
    except Exception as e:
        logger.warning("티키타카 검증 실패: %s", e)
        validation = ValidationSummary(passed=True, issues=[])

    success_count = sum(1 for a in answers if a.status == "SUCCESS")
    status = "COMPLETED" if success_count == len(answers) else (
        "PARTIAL_SUCCESS" if success_count > 0 else "FAILED"
    )

    return MultiChatResponse(
        mode=request.mode,
        answers=answers,
        status=status,
        question=request.message,
        validation=validation,
    )


def _debate_ensure_feedbacks(agents, peer_steps, peer_feedbacks):
    """토론 모드에서 빈 peerFeedbacks는 허용하지 않는다(방어선)."""
    if peer_feedbacks:
        return peer_steps, peer_feedbacks
    frm, target = agents[0], agents[1]
    fallback = DebatePeerFeedback(
        fromAgentIndex=1, fromAgentName=frm.name,
        toAgentIndex=2, toAgentName=target.name,
        title=f"{_debate_display_name(frm, 1)} → {_debate_display_name(target, 2)}",
        feedback=_fallback_debate_feedback(frm, 1, target, 2),
    )
    return [_peer_step_from_debate_feedback(fallback, "fallback", 0)], [fallback]


def _debate_default_summary(summary: str) -> str:
    if summary:
        return summary
    return (
        "토론 정리: 각 에이전트는 같은 주제를 서로 다른 관점에서 설명했고, 핵심은 1차 답변을 그대로 받아들이기보다 "
        "부족한 점과 오해 가능성을 비교해 개념 정의, 실제 예시, 기술적 정확성을 함께 확인하는 것입니다."
    )


def _assemble_debate_response(
    request, agents, rag_context,
    initial_steps, initial_map, peer_steps, peer_feedbacks,
    revised_steps, revised_map, summary,
) -> MultiChatResponse:
    """compute된 토론 단계들을 최종 MultiChatResponse로 조립한다(블로킹/스트리밍 공용)."""
    delay_ms = _get_display_delay_ms()
    initial_answers = _debate_initial_records(agents, initial_map)
    revised_answers = _debate_revised_records(agents, revised_map)

    answers: List[AgentAnswer] = []
    for idx, a in enumerate(agents):
        answers.append(AgentAnswer(
            agentName=_debate_display_name(a, idx + 1),
            answer=revised_map.get(a.name) or initial_map.get(a.name, ""),
            agentId=a.agentId,
            role="debater",
            displayOrder=idx + 1,
            displayDelayMs=idx * delay_ms,
            status="SUCCESS",
            metadata=AgentAnswerMetadata(
                knowledgeLevel=a.knowledgeLevel, personality=a.personality,
                usedRag=bool(rag_context),
            ),
        ))

    pv_summary = _validate_mode_personas(
        agents,
        [AgentAnswer(agentName=a.name, answer=revised_map.get(a.name, "")) for a in agents],
    )

    process_steps = ProcessSteps(
        initialAnswers=initial_steps,
        peerFeedback=peer_steps,
        revisedAnswers=revised_steps,
        debateSummary=summary,
        personalityValidationSummary=pv_summary,
    )
    issues = []
    if len(initial_answers) < 2:
        issues.append("initialAnswers 길이가 2보다 작습니다.")
    if len(peer_feedbacks) < 1:
        issues.append("peerFeedbacks가 비어 있습니다.")
    if not revised_answers and not summary:
        issues.append("revisedAnswers 또는 debateSummary가 필요합니다.")
    invalid_feedbacks = [
        fb.title for fb in peer_feedbacks
        if not _valid_debate_feedback(fb.feedback, agents[fb.toAgentIndex - 1], fb.toAgentIndex)
    ]
    if invalid_feedbacks:
        issues.append("비평성 또는 대상 지목이 약한 피드백: " + ", ".join(invalid_feedbacks[:3]))

    logger.info("[StudyMate] debate 완료 agents=%d initial=%d feedback=%d revised=%d summary=%s",
                len(agents), len(initial_answers), len(peer_feedbacks), len(revised_answers), bool(summary))
    return MultiChatResponse(
        mode="debate",
        answers=answers,
        status="COMPLETED" if not issues else "PARTIAL_SUCCESS",
        question=request.message,
        validation=ValidationSummary(passed=not issues, issues=issues),
        feedbacks=[fb.model_dump() for fb in peer_feedbacks],
        initialAnswers=initial_answers,
        peerFeedbacks=peer_feedbacks,
        revisedAnswers=revised_answers,
        debateSummary=summary,
        processSteps=process_steps,
    )


def _run_debate_mode(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    rag_context: str,
) -> MultiChatResponse:
    """
    토론 모드 전용 파이프라인.
    Step 1 initialAnswers -> Step 2 peerFeedbacks -> Step 3 revisedAnswers -> Step 4 debateSummary.
    일반 multi-agent 답변 나열로 폴백하지 않는다.
    """
    agents = _ensure_debate_agents(active_agents)
    context = build_context_from_previous_answers(request.previousAnswers, max_items=20)
    context = _prep_default_context(context, rag_context)

    initial_steps, initial_map, _p1, _e1 = _compute_debate_opening(request, agents, context)
    peer_steps, peer_feedbacks, _p3, _e3 = _compute_debate_rebuttal(request, agents, initial_map)
    peer_steps, peer_feedbacks = _debate_ensure_feedbacks(agents, peer_steps, peer_feedbacks)
    fb_map = _feedback_received_map(agents, peer_feedbacks)
    revised_steps, revised_map, _p2, _e2 = _compute_debate_revision(request, agents, initial_map, fb_map)
    summary = _debate_default_summary(_compute_debate_summary(request, agents, revised_map))

    return _assemble_debate_response(
        request, agents, rag_context,
        initial_steps, initial_map, peer_steps, peer_feedbacks,
        revised_steps, revised_map, summary,
    )


def run_debate_mode_stream(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    rag_context: str,
):
    """
    토론 모드 SSE 제너레이터. 각 단계 완료 즉시 debate_section 이벤트를 yield하고,
    마지막에 all_complete로 전체 응답을 1회 더 보낸다.
    이벤트 순서: 1차 의견 → 서로 피드백 → 보완 답변 → 토론 정리 → all_complete.
    """
    agents = _ensure_debate_agents(active_agents)
    context = build_context_from_previous_answers(request.previousAnswers, max_items=20)
    context = _prep_default_context(context, rag_context)

    initial_steps, initial_map, _p1, _e1 = _compute_debate_opening(request, agents, context)
    initial_answers = _debate_initial_records(agents, initial_map)
    yield {"event": "debate_section", "data": {
        "section": "initialAnswers", "title": "1차 의견",
        "items": [r.model_dump() for r in initial_answers]}}

    peer_steps, peer_feedbacks, _p3, _e3 = _compute_debate_rebuttal(request, agents, initial_map)
    peer_steps, peer_feedbacks = _debate_ensure_feedbacks(agents, peer_steps, peer_feedbacks)
    yield {"event": "debate_section", "data": {
        "section": "peerFeedbacks", "title": "서로 피드백",
        "items": [fb.model_dump() for fb in peer_feedbacks]}}

    fb_map = _feedback_received_map(agents, peer_feedbacks)
    revised_steps, revised_map, _p2, _e2 = _compute_debate_revision(request, agents, initial_map, fb_map)
    revised_answers = _debate_revised_records(agents, revised_map)
    yield {"event": "debate_section", "data": {
        "section": "revisedAnswers", "title": "보완 답변",
        "items": [r.model_dump() for r in revised_answers]}}

    summary = _debate_default_summary(_compute_debate_summary(request, agents, revised_map))
    yield {"event": "debate_section", "data": {
        "section": "debateSummary", "title": "토론 정리", "content": summary}}

    final = _assemble_debate_response(
        request, agents, rag_context,
        initial_steps, initial_map, peer_steps, peer_feedbacks,
        revised_steps, revised_map, summary,
    )
    yield {"event": "all_complete", "data": final.model_dump()}


def run_socratic_mode_stream(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    rag_context: str,
):
    """
    소크라테스 모드 SSE 제너레이터. 답변이 준비되는 즉시 socratic_answer 이벤트로 내보내고,
    all_complete로 전체 응답을 1회 더 보낸다.
    """
    final = _run_socratic_mode(request, active_agents, rag_context)
    answer_text = final.answers[0].answer if final.answers else ""
    yield {"event": "socratic_answer", "data": {
        "answer": answer_text,
        "agentName": final.answers[0].agentName if final.answers else "소크라테스 튜터",
        "status": final.answers[0].status if final.answers else "SUCCESS",
    }}
    yield {"event": "all_complete", "data": final.model_dump()}

def _run_socratic_mode(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    rag_context: str,
) -> MultiChatResponse:
    """소크라테스 모드 — socratic_mode_service 위임."""
    from app.services.socratic_mode_service import run_socratic_mode
    knowledge_level = _get_knowledge_level(request)

    answers = run_socratic_mode(
        question=request.message,
        user_attempt=request.userAttempt,
        agents=active_agents,
        knowledge_level=knowledge_level,
        rag_context=rag_context,
    )

    # 검증
    try:
        from app.services.mode_validator import validate_mode_response
        v = validate_mode_response("socratic", [a.model_dump() for a in answers])
        validation = ValidationSummary(
            passed=v["passed"],
            issues=v.get("issues", []),
            directAnswerBlocked=v.get("directAnswerBlocked", False),
        )
    except Exception:
        validation = ValidationSummary(passed=True, issues=[])

    status = "COMPLETED" if answers and answers[0].status in ("SUCCESS", "REWRITTEN") else "FAILED"

    pv_summary = _validate_mode_personas(active_agents, answers)
    return MultiChatResponse(
        mode=request.mode,
        answers=answers,
        status=status,
        question=request.message,
        validation=validation,
        processSteps=ProcessSteps(personalityValidationSummary=pv_summary) if pv_summary else None,
    )


# ── 멀티패스 파이프라인 (박사/전문가 수준) ───────────────────────────────────

def _run_multi_pass_pipeline(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    knowledge_level: str,
    mode: str,
) -> Optional[MultiChatResponse]:
    """
    박사/전문가 수준 멀티패스 파이프라인:
    1. domain classifier
    2. generation config 계산
    3. source router → OpenAlex(박사)
    4. prompt example selector
    5. 답변 생성
    6. depth verifier → depth rewriter (필요 시 1회)
    7. source leakage guard
    """
    if knowledge_level not in ("박사", "전문가"):
        return None

    # 1. 도메인 분류
    domain = "general_study"
    domain_confidence = 0.0
    used_llm_domain = False
    try:
        from app.services.academic_domain_classifier import classify as classify_domain
        domain_result = classify_domain(
            question=request.message,
            material_title=None,
        )
        domain = domain_result.domain
        domain_confidence = domain_result.confidence
        used_llm_domain = domain_result.used_llm_fallback
    except Exception as e:
        logger.warning("도메인 분류 실패 (general_study 사용): %s", e)

    # 2. generation config 계산
    gen_config: Dict[str, Any] = {}
    personality = active_agents[0].personality if active_agents else None
    try:
        from app.services.generation_config_resolver import resolve as resolve_config
        gen_config = resolve_config(
            knowledge_level=knowledge_level,
            personality=personality,
            mode=mode,
            domain=domain,
        )
    except Exception as e:
        logger.warning("generation config 계산 실패: %s", e)

    # 3. source router + OpenAlex
    openalex_context = ""
    used_openalex = False
    openalex_count = 0
    openalex_min_date = "2020-01-01"
    try:
        if gen_config.get("use_openalex", False) or knowledge_level == "박사":
            from app.services.openalex_service import search as openalex_search
            oa_result = openalex_search(
                question=request.message,
                knowledge_level=knowledge_level,
                domain=domain,
            )
            if not oa_result.skipped and oa_result.works:
                openalex_context = oa_result.to_context_text()
                used_openalex = True
                openalex_count = len(oa_result.works)
                openalex_min_date = oa_result.min_publication_date
    except Exception as e:
        logger.warning("OpenAlex 호출 실패 (계속 진행): %s", e)

    # 4. prompt example selector
    prompting_strategy = "zero_shot"
    prompting_example_file = ""
    few_shot_prefix = ""
    try:
        from app.services.prompt_example_selector import select as select_example, build_few_shot_prefix
        ex = select_example(knowledge_level=knowledge_level, mode=mode)
        prompting_strategy = ex["strategy"]
        prompting_example_file = ex.get("example_file", "")
        if ex.get("example_text"):
            few_shot_prefix = build_few_shot_prefix(ex["example_text"])
    except Exception as e:
        logger.warning("prompt example selector 실패: %s", e)

    # 5. RAG + 답변 생성
    rag_context = _get_rag_context(request.message, request.materialId)
    context = ""
    if openalex_context:
        context = openalex_context
    if rag_context:
        context = f"{context}\n\n[RAG 자료]\n{rag_context}" if context else rag_context

    if not active_agents:
        return None

    agent = active_agents[0]
    system_prompt = build_agent_system_prompt(agent, context)
    if few_shot_prefix:
        system_prompt = few_shot_prefix + system_prompt

    answer_text = _call_llm(
        system_prompt=system_prompt,
        user_prompt=f"[사용자 질문] {request.message}",
        knowledge_level=knowledge_level,
        gen_config=gen_config,
    )

    # 6. depth verifier + rewriter
    rewrite_applied = False
    depth_coverage = 0.0
    leakage_detected = False
    depth_warning = None
    enable_depth = getattr(request, "enableDepthValidation", None)
    should_verify = (enable_depth is not False) and gen_config.get("use_depth_verifier", False)

    if should_verify:
        try:
            from app.services.academic_depth_verifier import verify as depth_verify
            v_result = depth_verify(answer_text, domain, knowledge_level)
            depth_coverage = v_result.domain_depth_coverage
            leakage_detected = v_result.source_leakage_detected

            enable_rewrite = getattr(request, "enableDepthRewrite", None)
            should_rewrite = (enable_rewrite is not False) and gen_config.get("use_depth_rewrite", False)

            if v_result.rewrite_required and should_rewrite:
                from app.services.academic_depth_rewriter import rewrite as depth_rewrite
                rw = depth_rewrite(
                    original_answer=answer_text,
                    domain=domain,
                    knowledge_level=knowledge_level,
                    missing_requirements=v_result.missing_requirements,
                    question=request.message,
                    additional_context=openalex_context,
                )
                if rw.rewrite_applied:
                    answer_text = rw.rewritten_answer
                    rewrite_applied = True
                    if rw.verification_after_rewrite:
                        depth_coverage = rw.verification_after_rewrite.domain_depth_coverage
                        depth_warning = rw.verification_after_rewrite.warning_message
        except Exception as e:
            logger.warning("depth verifier/rewriter 실패 (계속 진행): %s", e)

    # 7. source leakage guard (최종 검사)
    try:
        from app.services.source_leakage_guard import detect as detect_leakage, clean as clean_leakage
        leakage_detected_final, _ = detect_leakage(answer_text)
        if leakage_detected_final:
            answer_text = clean_leakage(answer_text)
            leakage_detected = True
    except Exception as e:
        logger.warning("source leakage guard 실패: %s", e)

    # debug metadata 구성
    debug_meta = None
    if getattr(request, "debugMetadata", False):
        debug_meta = DebugMetadata(
            domain=domain,
            domainConfidence=round(domain_confidence, 3),
            requestedKnowledgeLevel=knowledge_level,
            effectiveKnowledgeLevel=knowledge_level,
            generationConfig=GenerationConfigMetadata(
                temperature=gen_config.get("temperature"),
                topP=gen_config.get("top_p"),
                topK=gen_config.get("top_k"),
                maxTokens=gen_config.get("max_tokens"),
                reasoningOrThinkingLevel=gen_config.get("reasoning_or_thinking_level"),
            ),
            retrieval=RetrievalMetadata(
                usedRag=bool(rag_context),
                usedOpenAlex=used_openalex,
                openAlexMinPublicationDate=openalex_min_date if used_openalex else None,
                openAlexResultCount=openalex_count if used_openalex else None,
            ),
            prompting=PromptingMetadata(
                strategy=prompting_strategy,
                exampleSet=prompting_example_file or None,
            ),
            depthValidation=DepthValidationMetadata(
                domainDepthCoverage=round(depth_coverage, 3) if depth_coverage else None,
                rewriteApplied=rewrite_applied,
                sourceLeakageDetected=leakage_detected,
                warningMessage=depth_warning,
            ),
        )

    delay_ms = _get_display_delay_ms()
    answers = [AgentAnswer(
        agentName=agent.name,
        answer=answer_text,
        agentId=agent.agentId,
        role=agent.role or "default",
        displayOrder=1,
        displayDelayMs=0,
        status="SUCCESS",
        metadata=None,
    )]

    # 나머지 에이전트들도 기존 방식으로 처리
    for idx, a in enumerate(active_agents[1:], start=2):
        try:
            sys_p = build_agent_system_prompt(a, rag_context)
            ans = _call_llm(sys_p, f"[사용자 질문] {request.message}", a.knowledgeLevel, gen_config)
            answers.append(AgentAnswer(
                agentName=a.name, answer=ans, agentId=a.agentId,
                role=a.role or "default", displayOrder=idx,
                displayDelayMs=(idx - 1) * delay_ms, status="SUCCESS",
            ))
        except Exception as e:
            logger.error("추가 에이전트 '%s' 실패: %s", a.name, e)

    return MultiChatResponse(
        mode=request.mode,
        answers=answers,
        status="COMPLETED",
        question=request.message,
        debugMetadata=debug_meta,
    )


# ── group_study_ai 모드 (그룹스터디 AI 봇 3종) ────────────────────────────────
#
# 봇별 모델 라우팅:
#   summary_bot / SummaryAgent          → Qwen/Ollama  (call_primary_llm)
#   quiz_bot    / QuizAgent             → GPT/OpenAI   (openai chat_sync)
#   search_bot  / TavilyAgent(SearchAgent) → Tavily 검색 + GPT/OpenAI
#
# 일정봇 계열(schedule_bot/calendar_bot/todo_bot)은 등록하지 않으며 라우팅하지 않는다.

_GROUP_BOT_REGISTRY: Dict[str, Dict[str, str]] = {
    "summary_bot": {"agentName": "SummaryAgent", "displayName": "요약봇", "modelProvider": "qwen_ollama"},
    "quiz_bot":    {"agentName": "QuizAgent",    "displayName": "퀴즈봇", "modelProvider": "openai_gpt"},
    "search_bot":  {"agentName": "TavilyAgent",  "displayName": "검색봇", "modelProvider": "openai_gpt_tavily"},
}

# agentName → botType (TavilyAgent/SearchAgent 모두 검색봇으로 처리)
_AGENT_NAME_TO_BOT: Dict[str, str] = {
    "SummaryAgent": "summary_bot",
    "QuizAgent": "quiz_bot",
    "TavilyAgent": "search_bot",
    "SearchAgent": "search_bot",
}

# 절대 허용하지 않는 봇 (일정봇 계열 방어)
_FORBIDDEN_BOT_TYPES = {"schedule_bot", "calendar_bot", "todo_bot"}
_FORBIDDEN_AGENT_NAMES = {"ScheduleAgent", "CalendarAgent", "TodoAgent"}


def _infer_bot_type(agent: AgentProfile) -> Optional[str]:
    """AgentProfile에서 botType을 결정한다. (botType 우선, 없으면 name 기반)"""
    if agent.botType and agent.botType in _GROUP_BOT_REGISTRY:
        return agent.botType
    return _AGENT_NAME_TO_BOT.get((agent.name or "").strip())


def _is_forbidden_bot(agent: AgentProfile) -> bool:
    bt = (agent.botType or "").strip()
    nm = (agent.name or "").strip()
    return bt in _FORBIDDEN_BOT_TYPES or nm in _FORBIDDEN_AGENT_NAMES


def _summary_bot_answer(message: str, context: str) -> str:
    """요약봇 → Qwen/Ollama."""
    system = (
        "너는 StudyBridge의 '요약봇'이다. "
        "스터디 내용과 학습 자료를 핵심 개념, 키워드, 시험 포인트 중심으로 정리한다. "
        "불필요한 군더더기 없이 구조화된 한국어 요약을 제공한다. "
        "가능하면 '핵심 개념', '키워드', '시험 포인트' 소제목으로 정리하라."
    )
    user_parts = []
    if context:
        user_parts.append(context)
    user_parts.append(f"[요약 요청]\n{message}")
    return _call_llm(system, "\n\n".join(user_parts))


def _quiz_bot_answer(message: str, context: str) -> str:
    """퀴즈봇 → GPT/OpenAI."""
    from app.services.openai_client import chat_sync, is_enabled
    system = (
        "너는 StudyBridge의 '퀴즈봇'이다. "
        "학습 내용을 바탕으로 퀴즈를 만들고 각 문항의 정답과 해설까지 제공한다. "
        "문항은 번호를 매기고, 각 문항 끝에 '정답:'과 '해설:'을 반드시 포함한다. "
        "반드시 한국어로 작성한다."
    )
    user_parts = []
    if context:
        user_parts.append(context)
    user_parts.append(f"[퀴즈 요청]\n{message}")
    user = "\n\n".join(user_parts)
    if not is_enabled():
        # GPT 미설정 시 Qwen으로 폴백
        logger.info("퀴즈봇: OpenAI 비활성 → Qwen 폴백")
        return _call_llm(system, user)
    text = chat_sync(system=system, user=user, temperature=0.4, max_tokens=_MAX_TOKENS_PER_ANSWER)
    if text and not text.startswith("[GPT"):
        return text
    logger.warning("퀴즈봇 GPT 응답 실패 → Qwen 폴백: %s", text[:80] if text else "")
    return _call_llm(system, user)


def _search_bot_answer(message: str, context: str) -> str:
    """검색봇 → Tavily 검색 + GPT/OpenAI 종합."""
    search_block = ""
    try:
        from app.services.tavily_service import search_web
        results = search_web(message, max_results=5)
        if results:
            lines = []
            for i, r in enumerate(results, start=1):
                lines.append(
                    f"[출처 {i}] {r.get('title','')}\nURL: {r.get('url','')}\n{r.get('content','')}"
                )
            search_block = "[웹 검색 결과]\n" + "\n\n".join(lines)
    except Exception as e:
        logger.warning("검색봇 Tavily 검색 실패 (검색 없이 진행): %s", e)

    system = (
        "너는 StudyBridge의 '검색봇'이다. "
        "웹 검색 결과를 근거로 최신 정보를 정리하고, 학습 답변을 보강한다. "
        "답변에는 사용한 출처를 '출처:' 형태로 명시한다. "
        "검색 결과가 없으면 보유 지식으로 답하되 출처가 없음을 밝힌다. "
        "반드시 한국어로 답변한다."
    )
    user_parts = []
    if context:
        user_parts.append(context)
    if search_block:
        user_parts.append(search_block)
    user_parts.append(f"[검색 요청]\n{message}")
    user = "\n\n".join(user_parts)

    from app.services.openai_client import chat_sync, is_enabled
    if is_enabled():
        text = chat_sync(system=system, user=user, temperature=0.3, max_tokens=_MAX_TOKENS_PER_ANSWER)
        if text and not text.startswith("[GPT"):
            return text
        logger.warning("검색봇 GPT 응답 실패 → Qwen 폴백")
    return _call_llm(system, user)


def _route_group_bot_answer(bot_type: str, message: str, context: str) -> str:
    if bot_type == "summary_bot":
        return _summary_bot_answer(message, context)
    if bot_type == "quiz_bot":
        return _quiz_bot_answer(message, context)
    if bot_type == "search_bot":
        return _search_bot_answer(message, context)
    # 알 수 없는 봇 — 기본 요약봇 처리
    logger.warning("알 수 없는 botType=%s → 요약봇으로 처리", bot_type)
    return _summary_bot_answer(message, context)


def _run_group_study_ai_mode(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    context: str,
    rag_context: str,
) -> MultiChatResponse:
    """
    그룹스터디 AI 봇 모드.
    요청된 agents를 '요청 순서대로' 실행한다.
      - single   : agents에 1개
      - all_bots : agents에 3개 (검색봇 → 요약봇 → 퀴즈봇 순서는 호출자가 보장)
    각 봇은 botType/agentName에 따라 모델이 라우팅된다.
    """
    if rag_context:
        context = f"{context}\n\n[RAG 자료]\n{rag_context}" if context else rag_context

    delay_ms = _get_display_delay_ms()
    answers: List[AgentAnswer] = []

    for idx, agent in enumerate(active_agents):
        # 일정봇 계열 방어 — 실행하지 않고 오류 응답
        if _is_forbidden_bot(agent):
            logger.warning("group_study_ai: 금지된 봇 차단 name=%s botType=%s", agent.name, agent.botType)
            answers.append(AgentAnswer(
                agentName=agent.name or "시스템",
                answer="지원하지 않는 AI 봇입니다. 사용 가능: 요약봇, 퀴즈봇, 검색봇.",
                role="blocked",
                displayOrder=idx + 1,
                displayDelayMs=idx * delay_ms,
                status="BLOCKED",
            ))
            continue

        bot_type = _infer_bot_type(agent)
        if bot_type is None:
            logger.warning("group_study_ai: botType 판별 실패 name=%s → 요약봇 처리", agent.name)
            bot_type = "summary_bot"

        reg = _GROUP_BOT_REGISTRY[bot_type]
        try:
            answer_text = _route_group_bot_answer(bot_type, request.message, context)
            status = "SUCCESS"
        except Exception as e:
            logger.error("group_study_ai 봇 '%s' 실행 실패: %s", bot_type, e)
            answer_text = "일시적인 오류로 답변을 생성할 수 없습니다. 잠시 후 다시 시도해 주세요."
            status = "FAILED"

        answers.append(AgentAnswer(
            agentName=agent.name or reg["agentName"],
            answer=answer_text,
            agentId=agent.agentId,
            role=bot_type,
            displayOrder=idx + 1,
            displayDelayMs=idx * delay_ms,
            status=status,
        ))

    if not answers:
        answers.append(AgentAnswer(
            agentName="시스템",
            answer="실행할 AI 봇이 지정되지 않았습니다.",
            displayOrder=1, displayDelayMs=0, status="FAILED",
        ))

    success_count = sum(1 for a in answers if a.status == "SUCCESS")
    status = "COMPLETED" if success_count == len(answers) else (
        "PARTIAL_SUCCESS" if success_count > 0 else "FAILED"
    )

    return MultiChatResponse(
        mode=request.mode,
        answers=answers,
        status=status,
        question=request.message,
    )


# ── 진입점 ────────────────────────────────────────────────────────────────────

def _resolve_mode(request: MultiChatRequest, agent_count: Optional[int] = None) -> str:
    """
    mode와 learningMode(+에이전트 수)를 합쳐 실행 모드를 정한다.
    - 프론트 learningMode(basic/socratic/debate)가 명시되면 우선.
    - learningMode 없으면 request.mode 기준.
    - tikitaka/multi_agent_discussion 등은 토론(피드백 포함)·default로 정규화.
    - 자동 토론: 위에서 default로 정해졌고 에이전트가 2명 이상이면 debate로 승격
      (AGENT_AUTO_DEBATE_MULTI=true). 단일 에이전트는 일반 답변(default) 유지.
    반환: default | debate | socratic | group_study_ai
    """
    raw = (request.mode or "default").strip().lower()
    lm = (getattr(request, "learningMode", None) or "").strip().lower()

    base = None
    # 1) 프론트 학습모드 우선
    if lm in _DEBATE_MODE_ALIASES:
        base = "debate"
    elif lm == "socratic":
        base = "socratic"
    elif lm == "basic":
        base = "group_study_ai" if raw == "group_study_ai" else "default"
    # 2) learningMode 미지정 → request.mode 기준
    elif raw == "group_study_ai":
        base = "group_study_ai"
    elif raw in _DEBATE_MODE_ALIASES:
        base = "debate"
    elif raw == "socratic":
        base = "socratic"
    else:
        # multi_agent_discussion / default 등 generic → staged default(상호 피드백 포함)
        base = "default"

    # 3) 자동 토론: 모드 미지정(default)인데 에이전트 2명 이상이면 토론으로 진입
    if base == "default" and agent_count is not None and agent_count >= 2 and A.enable_auto_debate():
        return "debate"
    return base


def run_multi_chat(request: MultiChatRequest) -> MultiChatResponse:
    """
    mode에 따라 적절한 실행 함수로 분기한다.

    mode:
      "default"   → 기존 병렬 multi-agent (박사/전문가면 멀티패스 우선)
      "tikitaka"  → 3라운드 티키타카
      "debate"    → 찬성/반대/사회자 순차 체인
      "socratic"  → 소크라테스식 꼬리질문
      그 외        → default와 동일
    """
    agents = _get_agents(request)
    active_agents = _filter_agents(agents, request.targetAgentId)
    context = build_context_from_previous_answers(request.previousAnswers, max_items=20)

    # RAG 검색 (materialId 있으면 수행)
    rag_context = _get_rag_context(request.message, request.materialId)

    mode = _resolve_mode(request, len(active_agents))

    # group_study_ai: 그룹스터디 AI 봇 모드 (요약/퀴즈/검색 봇 라우팅)
    if mode == "group_study_ai":
        logger.info("multi-chat 실행: mode=group_study_ai runMode=%s agents=%d",
                    request.runMode, len(active_agents))
        return _run_group_study_ai_mode(request, active_agents, context, rag_context)

    knowledge_level = _get_knowledge_level(request, active_agents[0] if active_agents else None)
    logger.info("multi-chat 실행: mode=%s (raw=%s/lm=%s) level=%s agents=%d",
                mode, request.mode, getattr(request, "learningMode", None), knowledge_level, len(active_agents))

    if mode == "debate":
        return _run_debate_mode(request, active_agents, rag_context)
    if mode == "socratic":
        return _run_socratic_mode(request, active_agents, rag_context)

    # default: 모든 지식수준(입문~전문가)을 동일한 1/2/3차 staged 파이프라인으로 처리한다.
    # (이전엔 박사/전문가가 _run_multi_pass_pipeline로 분기되어 stages/processSteps가 생성되지 않았음.
    #  OpenAlex/depth 보강은 staged 모드에서 현재 미적용 — 후속 통합 과제.)
    return _run_default_mode(request, active_agents, context, rag_context)
