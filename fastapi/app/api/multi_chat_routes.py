"""
POST /api/ai/multi-chat — 멀티 에이전트 토론.
Spring Boot 계약 endpoint. camelCase 필드명 유지.
FastAPI는 동기 REST JSON만 반환한다. SSE는 Spring Boot가 처리한다.
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException

from app.schemas.multi_chat_schema import MultiChatRequest, MultiChatResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["Multi Agent Chat"])


@router.post(
    "/multi-chat",
    response_model=MultiChatResponse,
    summary="멀티 에이전트 토론",
    description=(
        "여러 에이전트가 사용자 메시지에 대해 토론한다. "
        "FastAPI는 동기 JSON만 반환하고, SSE 스트리밍은 Spring Boot가 처리한다. "
        "agents 배열이 비어있으면 기본 에이전트를 사용한다."
    ),
)
async def multi_chat(request: MultiChatRequest) -> MultiChatResponse:
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message는 비워둘 수 없습니다.")

    try:
        from app.services.multi_agent_service import run_multi_chat
        from app.core.config import MULTI_CHAT_TIMEOUT_SECONDS
        from app.schemas.multi_chat_schema import AgentAnswer
        result = await asyncio.wait_for(
            asyncio.to_thread(run_multi_chat, request),
            timeout=MULTI_CHAT_TIMEOUT_SECONDS,
        )
        return result
    except asyncio.TimeoutError:
        logger.warning("멀티 에이전트 채팅 타임아웃 (%ss)", MULTI_CHAT_TIMEOUT_SECONDS)
        from app.schemas.multi_chat_schema import AgentAnswer
        return MultiChatResponse(
            mode=request.mode,
            answers=[
                AgentAnswer(
                    agentName="시스템",
                    answer="AI 응답 시간이 초과되었습니다. 에이전트 수를 줄이거나 잠시 후 다시 시도해 주세요.",
                )
            ],
        )
    except Exception as e:
        logger.error("멀티 에이전트 채팅 중 오류: %s", e)
        from app.schemas.multi_chat_schema import AgentAnswer
        return MultiChatResponse(
            mode=request.mode,
            answers=[
                AgentAnswer(
                    agentName="시스템",
                    answer="현재 AI 서비스에 일시적으로 접근할 수 없습니다. 잠시 후 다시 시도해 주세요.",
                )
            ],
        )
