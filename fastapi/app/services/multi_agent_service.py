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
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.multi_chat_schema import (
    AgentAnswer, AgentProfile, MultiChatRequest, MultiChatResponse,
    ValidationSummary, PreviousAnswer, DebugMetadata,
    GenerationConfigMetadata, RetrievalMetadata, DepthValidationMetadata, PromptingMetadata,
    ProcessSteps, InitialAnswerStep, ValidatedAnswerStep, PeerFeedbackStep,
    PersonalityValidationItem, StageInfo,
)
from app.services.prompt_builder import build_agent_system_prompt, build_tikitaka_role_prompt
from app.services.personality_prompt_builder import to_profile_key
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
    user = (
        f"[사용자 질문] {message}\n\n"
        "[이번 단계: 1차 빠른 초안]\n"
        "핵심 정의 → 대표 예시 → 한 줄 결론 순서로 빠르게 답하라. "
        "완벽하게 길게 쓰려 하지 말고, 질문에 바로 도움이 되는 핵심만 담아라."
    )
    params = A.resolve_agent_generation_params(to_profile_key(agent.personality or agent.tone or agent.style), 1)
    text, _ = _call_llm_with_params("ollama", system, user, params, knowledge_level=agent.knowledgeLevel)
    return text


def _stage2_validate(agent: AgentProfile, message: str, own_initial: str, others_text: str) -> str:
    """2차 검증/정제 답안 — provider는 agent_settings stage=2."""
    system = build_agent_system_prompt(agent)
    user_parts = [
        f"[사용자 질문] {message}",
        f"[너의 1차 초안]\n{own_initial}",
    ]
    if others_text:
        user_parts.append(f"[다른 에이전트의 1차 초안]\n{others_text}")
    user_parts.append(
        "[이번 단계: 2차 검증 답안]\n"
        "1차 초안의 오류·누락·개념 혼동을 점검하고 바로잡아, 더 정확하고 정제된 답을 작성하라. "
        "특히 SQL/프로그래밍/수학/과학 개념은 정확성을 최우선으로 한다. "
        "예: DML(SELECT/INSERT/UPDATE/DELETE)과 DDL(CREATE/ALTER/DROP)을 섞지 마라. "
        "1차 초안을 그대로 반복하지 말고 보완하라."
    )
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
        "단순 칭찬은 금지하고, 실제로 도움이 되는 피드백을 작성하라."
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


def _compute_stage1(request: MultiChatRequest, agents: List[AgentProfile], context: str):
    """1차 빠른 초안 (Ollama 전용, 병렬). 반환: (steps, initial_map, provider, elapsedMs, status)."""
    provider = A.resolve_provider_for_stage(1)
    t1 = time.time()

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
    for a, text, agent_ms in results:
        if _is_llm_fallback(text):
            status = "timeout_fallback"
            if not (text or "").strip():
                text = A.stage1_timeout_fallback_text()
        initial_map[a.name] = text
        steps.append(InitialAnswerStep(
            agentName=a.name, answer=text, agentId=a.agentId,
            personalityType=_personality_type(a), knowledgeLevel=a.knowledgeLevel,
            provider=provider, elapsedMs=agent_ms,
        ))
    logger.info("[StudyMate] stage=1 provider=%s elapsedMs=%d status=%s agents=%d",
                provider, elapsed, status, len(agents))
    return steps, initial_map, provider, elapsed, status


def _compute_stage2(request: MultiChatRequest, agents: List[AgentProfile], initial_map: Dict[str, str]):
    """2차 검증/정제 (병렬, best-effort). 반환: (steps, validated_map, provider, elapsedMs)."""
    provider = A.resolve_provider_for_stage(2)
    t2 = time.time()

    def _run2(a: AgentProfile):
        own = initial_map.get(a.name, "")
        # 다른 에이전트 1차 초안은 컨텍스트 참고용으로만 축약(contextPreview) — 최종 출력은 자르지 않는다.
        others = "\n\n".join(
            f"[{b.name}]\n{initial_map.get(b.name, '')[:300]}" for b in agents if b.name != a.name
        )
        t_agent = time.time()
        try:
            text, prov = _stage2_validate(a, request.message, own, others)
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
    for a, text, prov, agent_ms in results:
        provs.add(prov)
        final_text = text or initial_map.get(a.name, "")
        if _is_llm_fallback(text):
            final_text = initial_map.get(a.name, "") or final_text
        validated_map[a.name] = final_text
        revised = final_text.strip() != initial_map.get(a.name, "").strip()
        steps.append(ValidatedAnswerStep(
            agentName=a.name, answer=final_text, agentId=a.agentId, revised=revised,
            personalityType=_personality_type(a), knowledgeLevel=a.knowledgeLevel,
            provider=prov, elapsedMs=agent_ms,
        ))
    actual = ",".join(sorted(provs)) if provs else provider
    logger.info("[StudyMate] stage=2 provider=%s elapsedMs=%d status=completed", actual, elapsed)
    return steps, validated_map, actual, elapsed


def _compute_validation(agents: List[AgentProfile], validated_map: Dict[str, str]):
    """성격 검증 (2차 답안 기준). 반환: (validation_map, pv_summary)."""
    validation_map: Dict[str, Dict[str, Any]] = {}
    summary: List[PersonalityValidationItem] = []
    if A.enable_personality_validation():
        for a in agents:
            peers = [validated_map.get(b.name, "") for b in agents if b.name != a.name]
            try:
                v = validate_personality_alignment(validated_map.get(a.name, ""), a, 2, peer_answers=peers)
            except Exception as e:
                logger.warning("성격 검증 실패 '%s': %s", a.name, e)
                continue
            validation_map[a.name] = v
            summary.append(PersonalityValidationItem(
                agentName=a.name, personalityType=v.get("personalityType"),
                score=v.get("score"), passed=v.get("passed"),
                issues=v.get("issues", []), note=v.get("note"),
            ))
    return validation_map, summary


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
            step = PeerFeedbackStep(
                fromAgent=frm.name, toAgent=target_names, feedback=fb,
                personalityValidation=pv_obj, fromAgentId=frm.agentId,
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


def _build_stage_infos(initial_steps, validated_steps, peer_steps, pv_summary,
                       s1, s2, s3):
    """3개 StageInfo를 만든다. s1/s2/s3 = (provider, elapsedMs, status) 튜플."""
    return [
        StageInfo(stage=1, title="1차 답변 - 빠른 초안", provider=s1[0], status=s1[2],
                  elapsedMs=s1[1], answers=[s.model_dump() for s in initial_steps]),
        StageInfo(stage=2, title="2차 답변 - 검증 답안", provider=s2[0], status=s2[2],
                  elapsedMs=s2[1], answers=[s.model_dump() for s in validated_steps]),
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
    validated_steps, validated_map, p2, e2 = _compute_stage2(request, agents, initial_map)
    validation_map, pv_summary = _compute_validation(agents, validated_map)
    peer_steps, p3, e3 = _compute_stage3(request, agents, validated_map, validation_map)

    stages = _build_stage_infos(initial_steps, validated_steps, peer_steps, pv_summary,
                                (p1, e1, st1), (p2, e2, "completed"), (p3, e3, "completed"))
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
    validated_steps, validated_map, p2, e2 = _compute_stage2(request, agents, initial_map)
    validation_map, pv_summary = _compute_validation(agents, validated_map)
    stage2 = _build_stage_infos([], validated_steps, [], pv_summary, (None, 0, "completed"), (p2, e2, "completed"), (None, 0, "running"))[1]
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
    agents = _get_agents(request)
    active_agents = _filter_agents(agents, request.targetAgentId)
    context = build_context_from_previous_answers(request.previousAnswers, max_items=20)
    rag_context = _get_rag_context(request.message, request.materialId)

    raw_mode = (request.mode or "default").lower()
    if raw_mode in ("tikitaka", "debate", "socratic", "group_study_ai"):
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


def _run_debate_mode(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    rag_context: str,
) -> MultiChatResponse:
    """토론 모드 — debate_mode_service 위임."""
    from app.services.debate_mode_service import run_debate_mode
    knowledge_level = _get_knowledge_level(request)
    delay_ms = _get_display_delay_ms()

    answers = run_debate_mode(
        question=request.message,
        agents=active_agents,
        knowledge_level=knowledge_level,
        rag_context=rag_context,
        delay_ms=delay_ms,
    )

    # 검증
    try:
        from app.services.mode_validator import validate_mode_response
        v = validate_mode_response("debate", [a.model_dump() for a in answers])
        validation = ValidationSummary(passed=v["passed"], issues=v.get("issues", []))
    except Exception:
        validation = ValidationSummary(passed=True, issues=[])

    success_count = sum(1 for a in answers if a.status in ("SUCCESS", "REWRITTEN"))
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

    return MultiChatResponse(
        mode=request.mode,
        answers=answers,
        status=status,
        question=request.message,
        validation=validation,
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

    raw_mode = (request.mode or "default").lower()

    # group_study_ai: 그룹스터디 AI 봇 모드 (요약/퀴즈/검색 봇 라우팅)
    if raw_mode == "group_study_ai":
        logger.info("multi-chat 실행: mode=group_study_ai runMode=%s agents=%d",
                    request.runMode, len(active_agents))
        return _run_group_study_ai_mode(request, active_agents, context, rag_context)

    mode = raw_mode
    if mode not in ("tikitaka", "debate", "socratic"):
        mode = "default"

    knowledge_level = _get_knowledge_level(request, active_agents[0] if active_agents else None)
    logger.info("multi-chat 실행: mode=%s level=%s agents=%d", mode, knowledge_level, len(active_agents))

    if mode == "debate":
        return _run_debate_mode(request, active_agents, rag_context)
    if mode == "socratic":
        return _run_socratic_mode(request, active_agents, rag_context)
    if mode == "tikitaka":
        return _run_tikitaka_mode(request, active_agents, context, rag_context)

    # default: 모든 지식수준(입문~전문가)을 동일한 1/2/3차 staged 파이프라인으로 처리한다.
    # (이전엔 박사/전문가가 _run_multi_pass_pipeline로 분기되어 stages/processSteps가 생성되지 않았음.
    #  OpenAlex/depth 보강은 staged 모드에서 현재 미적용 — 후속 통합 과제.)
    return _run_default_mode(request, active_agents, context, rag_context)
