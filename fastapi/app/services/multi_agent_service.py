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
from typing import Any, Dict, List, Optional

from app.schemas.multi_chat_schema import (
    AgentAnswer, AgentProfile, MultiChatRequest, MultiChatResponse,
    ValidationSummary, PreviousAnswer, DebugMetadata,
    GenerationConfigMetadata, RetrievalMetadata, DepthValidationMetadata, PromptingMetadata,
)
from app.services.prompt_builder import build_agent_system_prompt, build_tikitaka_role_prompt
from app.utils.text_utils import build_context_from_previous_answers, safe_str
from app.core.config import MAX_ROUNDS, ADVANCED_AGENT_ANSWER_MAX_CHARS

logger = logging.getLogger(__name__)

_DEFAULT_AGENT = AgentProfile(
    id=0, agentId=0, name="스터디봇", role="학습 도우미",
    personality="친절_설명형", personalityStrength="moderate", knowledgeLevel="학사",
)
_SYNTHESIS_AGENT_NAME = "종합정리봇"
_MAX_ROUNDS = MAX_ROUNDS
# 답변 잘림 방지: 생성 토큰 상한은 충분히 크게 둔다.
# (ADVANCED_AGENT_ANSWER_MAX_CHARS는 '문자 수' 개념이라 토큰 상한으로 쓰면 답변이 잘린다.)
import os as _os
_MAX_TOKENS_PER_ANSWER = int(_os.getenv("AI_ANSWER_MAX_TOKENS", "2048"))


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


def _run_default_mode(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    context: str,
    rag_context: str,
) -> MultiChatResponse:
    """기존 다중 라운드 병렬 답변 모드."""
    if rag_context:
        context = f"{context}\n\n[RAG 자료]\n{rag_context}" if context else rag_context

    rounds = min(request.rounds, _MAX_ROUNDS)
    answers: List[AgentAnswer] = []
    delay_ms = _get_display_delay_ms()

    for round_idx in range(rounds):
        if round_idx > 0 and len(active_agents) <= 1:
            break
        for agent_idx, agent in enumerate(active_agents):
            order = round_idx * len(active_agents) + agent_idx + 1
            try:
                answer = _generate_agent_answer(
                    agent=agent,
                    message=request.message,
                    context=context,
                    agent_index=agent_idx,
                    total_agents=len(active_agents),
                    display_order=order,
                    display_delay_ms=(order - 1) * delay_ms,
                )
                answers.append(answer)
            except Exception as e:
                logger.error("에이전트 '%s' 답변 생성 실패: %s", agent.name, e)
                answers.append(AgentAnswer(
                    agentName=agent.name,
                    answer="일시적인 오류로 답변을 생성할 수 없습니다.",
                    displayOrder=order,
                    displayDelayMs=(order - 1) * delay_ms,
                    status="FAILED",
                ))
        if round_idx == 0 and len(active_agents) <= 1:
            break

    if not answers:
        answers.append(AgentAnswer(
            agentName="시스템",
            answer="현재 AI 서비스에 일시적으로 접근할 수 없습니다. 잠시 후 다시 시도해 주세요.",
            displayOrder=1, displayDelayMs=0, status="FAILED",
        ))

    answers = _deduplicate_agent_answers(answers)

    if request.showFinalSynthesis and len(answers) > 1:
        try:
            synthesis = _generate_synthesis(active_agents, answers, request.message)
            answers.append(synthesis)
        except Exception as e:
            logger.warning("종합 의견 생성 실패 (건너뜀): %s", e)

    status = "COMPLETED"
    if any(a.status == "FAILED" for a in answers):
        status = "PARTIAL_SUCCESS" if any(a.status == "SUCCESS" for a in answers) else "FAILED"

    return MultiChatResponse(
        mode=request.mode,
        answers=answers,
        status=status,
        question=request.message,
    )


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

    # default: 박사/전문가 수준이면 멀티패스 파이프라인 우선 시도
    if knowledge_level in ("박사", "전문가"):
        try:
            result = _run_multi_pass_pipeline(request, active_agents, knowledge_level, mode)
            if result is not None:
                return result
        except Exception as e:
            logger.warning("멀티패스 파이프라인 실패 (기존 방식으로 fallback): %s", e)

    return _run_default_mode(request, active_agents, context, rag_context)
