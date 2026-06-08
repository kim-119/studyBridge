"""
POST /api/ai/multi-chat — 멀티 에이전트 토론 (동기 JSON, 기존 호환).
POST /api/ai/multi-chat/stream — 1차/2차/3차 단계별 SSE 스트리밍 (선출력).
camelCase 필드명 유지.
"""
import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.multi_chat_schema import MultiChatRequest, MultiChatResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["Multi Agent Chat"])

_STREAM_SENTINEL = object()


def _sse(event: str, data) -> str:
    """SSE 프레임 포맷: event: <name>\\ndata: <json>\\n\\n"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post(
    "/multi-chat/stream",
    summary="멀티 에이전트 토론 (단계별 SSE 스트리밍)",
    description=(
        "1차→2차→3차 단계가 완료될 때마다 stage_complete 이벤트를 즉시 전송한다. "
        "마지막에 all_complete로 전체 응답(answers/processSteps/stages)을 한 번 더 보낸다. "
        "default 계열 모드만 단계 스트리밍하며, 그 외 모드는 all_complete 1회만 전송한다."
    ),
)
async def multi_chat_stream(request: MultiChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message는 비워둘 수 없습니다.")

    from app.services.multi_agent_service import build_stream_generator
    gen = build_stream_generator(request)

    async def event_source():
        try:
            while True:
                # 블로킹 stage 계산은 스레드풀에서 수행해 이벤트 루프를 막지 않는다.
                item = await asyncio.to_thread(next, gen, _STREAM_SENTINEL)
                if item is _STREAM_SENTINEL:
                    break
                yield _sse(item["event"], item["data"])
        except Exception as e:
            logger.error("multi-chat 스트리밍 오류: %s", e)
            yield _sse("error", {"message": "스트리밍 중 오류가 발생했습니다.", "detail": str(e)})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


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
