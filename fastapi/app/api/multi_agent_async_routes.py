"""
POST /api/ai/multi-chat/async — 비동기 3명 에이전트 병렬 답변 생성.
Spring Boot → FastAPI 직접 호출. SSE 불필요.
"""
import logging

from fastapi import APIRouter, HTTPException

from app.schemas.multi_agent_async_schema import (
    MultiAgentAsyncRequest,
    MultiAgentAsyncResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["Multi Agent Async"])


@router.post(
    "/multi-chat/async",
    response_model=MultiAgentAsyncResponse,
    summary="비동기 멀티에이전트 답변 생성",
    description=(
        "3명 에이전트가 asyncio.gather()로 병렬 답변을 생성한다. "
        "한 명이 실패해도 나머지 답변이 반환된다. "
        "RAG context는 한 번 검색 후 공유한다. "
        "피드백 검증은 enableFeedback=true일 때만 수행한다."
    ),
)
async def multi_chat_async(request: MultiAgentAsyncRequest) -> MultiAgentAsyncResponse:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question은 비워둘 수 없습니다.")

    try:
        from app.services.async_multi_agent_service import run_async_multi_agent
        result = await run_async_multi_agent(request)
        return result
    except Exception as e:
        logger.error("비동기 멀티에이전트 오류: %s", e)
        raise HTTPException(status_code=500, detail=f"멀티에이전트 처리 중 오류: {e}")
