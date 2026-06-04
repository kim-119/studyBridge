"""
멀티 에이전트 토론 서비스.
POST /api/ai/multi-chat — 동기 REST JSON 반환 (SSE는 Spring Boot가 처리).

흐름:
1. 에이전트 목록 검증 (없으면 기본 에이전트 생성)
2. targetAgentId가 있으면 해당 에이전트만, 없으면 전체 에이전트
3. previousAnswers에서 최근 20개를 컨텍스트로 활용
4. Ollama 우선, 실패 시 OpenAI, 둘 다 실패 시 기본 안내 답변
5. showFinalSynthesis=true이면 종합 에이전트 답변 추가
6. rounds 수만큼 반복하되 무한루프 방지 (최대 3라운드)
"""
import logging
from typing import List, Optional

from app.schemas.multi_chat_schema import (
    AgentAnswer, AgentProfile, MultiChatRequest, MultiChatResponse, PreviousAnswer
)
from app.services.prompt_builder import build_agent_system_prompt, build_tikitaka_role_prompt
from app.utils.text_utils import build_context_from_previous_answers, safe_str
from app.core.config import MAX_ROUNDS, ADVANCED_AGENT_ANSWER_MAX_CHARS

logger = logging.getLogger(__name__)

_DEFAULT_AGENT = AgentProfile(
    id=0,
    agentId=0,
    name="스터디봇",
    role="학습 도우미",
    personality="친절_설명형",
    personalityStrength="moderate",
    knowledgeLevel="학사",
)

_SYNTHESIS_AGENT_NAME = "종합정리봇"

_MAX_ROUNDS = MAX_ROUNDS
_MAX_TOKENS_PER_ANSWER = ADVANCED_AGENT_ANSWER_MAX_CHARS


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
        logger.warning("targetAgentId=%s에 해당하는 에이전트를 찾을 수 없습니다. 전체 사용.", target_id)
        return agents
    return filtered


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    knowledge_level: Optional[str] = None,
) -> str:
    """
    주력 LLM 호출 — llm_engine_router를 통해 Ollama(qwen2.5:14b) 우선,
    실패 시 OpenAI fallback.
    vLLM은 사용하지 않는다.
    """
    try:
        from app.services.llm_engine_router import call_primary_llm
        result = call_primary_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=_MAX_TOKENS_PER_ANSWER,
            temperature=0.5,
            knowledge_level=knowledge_level,
        )
        if result and not result.startswith("["):
            return result
        logger.warning("LLM 엔진 라우터 fallback 응답: %s", result[:80])
    except Exception as e:
        logger.error("LLM 엔진 라우터 호출 실패: %s", e)

    return (
        "현재 AI 서비스에 일시적으로 접근할 수 없습니다. "
        "잠시 후 다시 시도해 주세요. "
        "(Ollama 실행 여부와 qwen2.5:14b 모델 로드 상태를 확인하세요.)"
    )


def _deduplicate_agent_answers(answers: List[AgentAnswer]) -> List[AgentAnswer]:
    """에이전트 답변 중 내용이 거의 동일한 것을 제거한다 (앞 100자 기준)."""
    seen: set[str] = set()
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
) -> AgentAnswer:
    system_prompt = build_agent_system_prompt(agent, context)
    role_hint = build_tikitaka_role_prompt(agent_index, total_agents, agent)

    user_prompt_parts = []
    if role_hint:
        user_prompt_parts.append(f"[이번 역할] {role_hint}")
    user_prompt_parts.append(f"[사용자 메시지] {message}")
    user_prompt = "\n".join(user_prompt_parts)

    answer_text = _call_llm(system_prompt, user_prompt, knowledge_level=agent.knowledgeLevel)
    return AgentAnswer(agentName=agent.name, answer=answer_text)


def _generate_synthesis(
    agents: List[AgentProfile],
    answers: List[AgentAnswer],
    message: str,
) -> AgentAnswer:
    """showFinalSynthesis=true일 때 종합 의견 에이전트 답변 생성."""
    existing_answers = "\n".join(
        f"[{a.agentName}] {a.answer[:200]}" for a in answers
    )
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
    return AgentAnswer(agentName=_SYNTHESIS_AGENT_NAME, answer=synthesis_text)


def run_multi_chat(request: MultiChatRequest) -> MultiChatResponse:
    """
    멀티 에이전트 토론 실행.

    Args:
        request: MultiChatRequest 객체

    Returns:
        MultiChatResponse (mode + answers 배열)
    """
    agents = _get_agents(request)
    active_agents = _filter_agents(agents, request.targetAgentId)
    context = build_context_from_previous_answers(request.previousAnswers, max_items=20)

    rounds = min(request.rounds, _MAX_ROUNDS)
    answers: List[AgentAnswer] = []

    for round_idx in range(rounds):
        if round_idx > 0 and len(active_agents) <= 1:
            break

        for agent_idx, agent in enumerate(active_agents):
            try:
                answer = _generate_agent_answer(
                    agent=agent,
                    message=request.message,
                    context=context,
                    agent_index=agent_idx,
                    total_agents=len(active_agents),
                )
                answers.append(answer)
            except Exception as e:
                logger.error("에이전트 '%s' 답변 생성 실패: %s", agent.name, e)
                answers.append(
                    AgentAnswer(
                        agentName=agent.name,
                        answer="일시적인 오류로 답변을 생성할 수 없습니다.",
                    )
                )

        if round_idx == 0 and len(active_agents) <= 1:
            break

    if not answers:
        answers.append(
            AgentAnswer(
                agentName="시스템",
                answer="현재 AI 서비스에 일시적으로 접근할 수 없습니다. 잠시 후 다시 시도해 주세요.",
            )
        )

    # 중복 답변 제거
    answers = _deduplicate_agent_answers(answers)

    # 최종 종합 의견 추가
    if request.showFinalSynthesis and len(answers) > 1:
        try:
            synthesis = _generate_synthesis(active_agents, answers, request.message)
            answers.append(synthesis)
        except Exception as e:
            logger.warning("종합 의견 생성 실패 (건너뜀): %s", e)

    return MultiChatResponse(mode=request.mode, answers=answers)
