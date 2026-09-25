"""
비동기 멀티에이전트 답변 생성 서비스.
3명 에이전트를 asyncio.gather()로 병렬 실행하고,
한 명이 실패해도 나머지 결과를 반환한다.
RAG context는 한 번 검색 후 공유(shareRagContext=True 기본값).
"""
import asyncio
import logging
import time
from typing import Optional

from app.schemas.multi_agent_async_schema import (
    AsyncAgentProfile,
    AsyncAgentAnswer,
    AgentAnswerMetadata,
    MultiAgentAsyncRequest,
    MultiAgentAsyncResponse,
    FeedbackValidationSummary,
)

logger = logging.getLogger(__name__)

_DEFAULT_AGENTS: list[AsyncAgentProfile] = [
    AsyncAgentProfile(agentId=1, name="교수형",  personality="논리적_탐구형",  knowledgeLevel="박사"),
    AsyncAgentProfile(agentId=2, name="비판형",  personality="비판적_분석형", knowledgeLevel="학사"),
    AsyncAgentProfile(agentId=3, name="입문형",  personality="친절_설명형",  knowledgeLevel="입문"),
]


def _build_agent_system_prompt(agent: AsyncAgentProfile, context: str) -> str:
    from app.services.personality_prompt_builder import build_personality_prompt
    from app.services.knowledge_level_controller import get_level_instruction

    personality_block = build_personality_prompt(agent.personality)
    level_block = get_level_instruction(agent.knowledgeLevel)
    context_block = f"\n\n[참고 자료]\n{context}" if context else ""

    return (
        f"너는 StudyBridge 학습 도우미 에이전트 [{agent.name}]이다.\n\n"
        f"{personality_block}\n\n"
        f"{level_block}"
        f"{context_block}\n\n"
        "반드시 한국어로 답변하라. 학습에 실질적으로 도움이 되는 답변을 작성하라."
    )


def _retrieve_rag_context(question: str, material_id: Optional[int]) -> str:
    """RAG 검색을 동기로 실행하고 컨텍스트 문자열을 반환한다. 실패 시 빈 문자열."""
    if not material_id:
        return ""
    try:
        from app.services.pdf_rag_service import search_pdf_context
        chunks = search_pdf_context(question, material_id, top_k=5)
        if not chunks:
            return ""
        parts = [f"[청크 {i+1}]\n{c['content']}" for i, c in enumerate(chunks)]
        return "\n\n".join(parts)
    except Exception as e:
        logger.warning("RAG 검색 실패 (계속 진행): %s", e)
        return ""


async def _generate_agent_answer(
    agent: AsyncAgentProfile,
    question: str,
    context: str,
    timeout_seconds: int,
    display_order: int,
    display_delay_ms: int,
) -> AsyncAgentAnswer:
    """단일 에이전트 답변을 비동기로 생성한다. timeout 또는 예외 시 FAILED 반환."""
    start_ms = int(time.monotonic() * 1000)
    system_prompt = _build_agent_system_prompt(agent, context)
    used_rag = bool(context)

    try:
        from app.services.qwen_service import ask_qwen
        answer = await asyncio.wait_for(
            asyncio.to_thread(ask_qwen, system_prompt, question, 0.4, 768),
            timeout=timeout_seconds,
        )
        latency_ms = int(time.monotonic() * 1000) - start_ms
        return AsyncAgentAnswer(
            agentId=agent.agentId,
            agentName=agent.name,
            status="SUCCESS",
            displayOrder=display_order,
            displayDelayMs=display_delay_ms,
            answer=answer,
            metadata=AgentAnswerMetadata(
                knowledgeLevel=agent.knowledgeLevel,
                personality=agent.personality,
                usedRag=used_rag,
                latencyMs=latency_ms,
            ),
        )
    except asyncio.TimeoutError:
        logger.warning("[%s] 에이전트 타임아웃 (%ss)", agent.name, timeout_seconds)
        return AsyncAgentAnswer(
            agentId=agent.agentId,
            agentName=agent.name,
            status="TIMEOUT",
            displayOrder=display_order,
            displayDelayMs=display_delay_ms,
            answer=f"[{agent.name}] 응답 시간이 초과되었습니다.",
            metadata=AgentAnswerMetadata(
                knowledgeLevel=agent.knowledgeLevel,
                personality=agent.personality,
                usedRag=used_rag,
                latencyMs=timeout_seconds * 1000,
            ),
        )
    except Exception as e:
        logger.error("[%s] 에이전트 오류: %s", agent.name, e)
        return AsyncAgentAnswer(
            agentId=agent.agentId,
            agentName=agent.name,
            status="FAILED",
            displayOrder=display_order,
            displayDelayMs=display_delay_ms,
            answer=f"[{agent.name}] 답변 생성 중 오류가 발생했습니다.",
            metadata=AgentAnswerMetadata(
                knowledgeLevel=agent.knowledgeLevel,
                personality=agent.personality,
                usedRag=used_rag,
                latencyMs=int(time.monotonic() * 1000) - start_ms,
            ),
        )


async def run_async_multi_agent(request: MultiAgentAsyncRequest) -> MultiAgentAsyncResponse:
    """
    에이전트를 displayOrder 순서대로 순차 실행한다.
    Agent1 완료 후 Agent2, Agent2 완료 후 Agent3를 실행한다.
    RAG context는 한 번 검색 후 공유한다 (shareRagContext=True).
    """
    agents = request.agents if request.agents else _DEFAULT_AGENTS

    # RAG context 검색 (공유)
    context = ""
    if request.shareRagContext and request.materialId:
        context = await asyncio.to_thread(
            _retrieve_rag_context, request.question, request.materialId
        )

    # 순차 생성: Agent1 완료 후 Agent2, Agent2 완료 후 Agent3 실행
    answers = []

    for idx, agent in enumerate(agents):
        answer = await _generate_agent_answer(
            agent=agent,
            question=request.question,
            context=context,
            timeout_seconds=request.timeoutSecondsPerAgent,
            display_order=idx + 1,
            display_delay_ms=0,
        )
        answers.append(answer)

    answers = sorted(answers, key=lambda a: a.displayOrder)

    success_count = sum(1 for a in answers if a.status == "SUCCESS")
    if success_count == len(answers):
        overall_status = "COMPLETED"
    elif success_count > 0:
        overall_status = "PARTIAL_SUCCESS"
    else:
        overall_status = "FAILED"

    # 피드백 검증 (enableFeedback=True일 때만)
    feedbacks: list[dict] = []
    blocked_count = 0
    rewritten_count = 0

    if request.enableFeedback and request.enableFeedbackValidation:
        feedbacks, blocked_count, rewritten_count = _process_feedbacks(answers, request)

    return MultiAgentAsyncResponse(
        status=overall_status,
        question=request.question,
        answers=list(answers),
        feedbacks=feedbacks,
        validation=FeedbackValidationSummary(
            passed=blocked_count == 0,
            blockedFeedbackCount=blocked_count,
            rewrittenFeedbackCount=rewritten_count,
        ),
    )


def _process_feedbacks(
    answers: tuple,
    request: MultiAgentAsyncRequest,
) -> tuple[list[dict], int, int]:
    """에이전트 간 피드백을 생성하고 검증한다."""
    from app.services.constructive_feedback_rewriter import process_feedback
    from app.services.qwen_service import ask_qwen

    feedbacks: list[dict] = []
    blocked = 0
    rewritten = 0

    successful = [a for a in answers if a.status == "SUCCESS"]
    if len(successful) < 2:
        return feedbacks, blocked, rewritten

    # Agent 2 → Agent 1 피드백 생성
    if len(successful) >= 2:
        fb_prompt = (
            f"다음 질문에 대한 답변을 검토하라:\n\n"
            f"질문: {request.question}\n\n"
            f"[{successful[0].agentName}]의 답변:\n{successful[0].answer}\n\n"
            "위 답변의 논리·근거·누락점을 지적하고 개선 방향을 제시하라. "
            "인신공격 없이 200자 이내로."
        )
        sys_prompt = (
            "너는 학습 내용 피드백 에이전트다. 다른 에이전트의 답변을 분석하여 "
            "건설적인 개선 의견을 제시한다. 인신공격이나 조롱은 절대 금지한다. "
            "반드시 한국어로 답변하라."
        )
        try:
            raw_fb = ask_qwen(sys_prompt, fb_prompt, temperature=0.3, max_tokens=256)
            result = process_feedback(raw_fb)
            feedbacks.append({
                "fromAgent": successful[1].agentName,
                "toAgent": successful[0].agentName,
                "feedback": result.finalFeedback,
                "debug": {
                    "wasBlocked": result.wasBlocked,
                    "wasRewritten": result.wasRewritten,
                    "toxicityScore": result.toxicityScore,
                },
            })
            if result.wasBlocked:
                blocked += 1
            elif result.wasRewritten:
                rewritten += 1
        except Exception as e:
            logger.warning("피드백 생성 실패: %s", e)

    return feedbacks, blocked, rewritten
