"""
POST /api/ai/agent-tikitaka — 멀티 에이전트 티키타카 대화.
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import verify_internal_token
from app.schemas.agent_schema import TikiTakaRequest, TikiTakaResponse, TikiTakaTurnDTO

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/ai",
    tags=["Agent Tiki-Taka"],
    dependencies=[Depends(verify_internal_token)],
)


@router.post(
    "/agent-tikitaka",
    response_model=TikiTakaResponse,
    summary="멀티 에이전트 티키타카 대화",
    description=(
        "에이전트 A(핵심) → B(보완/비판) → C(쉬운 설명) → Moderator(정리) "
        "순서로 대화를 생성한다. max_round=2."
    ),
)
async def agent_tikitaka(request: TikiTakaRequest) -> TikiTakaResponse:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question은 비워둘 수 없습니다.")

    from app.services.agent_chat_service import run_agent_chat
    from app.services.tiki_taka_turn_manager import run_tiki_taka

    # 1차 답변 생성
    try:
        chat_result = await asyncio.to_thread(
            run_agent_chat,
            question=request.question.strip(),
            knowledge_level=request.knowledge_level,
            personality=request.personality,
            agent_name=request.agent_name,
            enable_tiki_taka=False,
        )
        first_answer = chat_result["answer"]
    except Exception as e:
        logger.error("1차 답변 생성 실패: %s", e)
        raise HTTPException(status_code=500, detail=f"1차 답변 생성 실패: {e}")

    # 티키타카 실행
    try:
        turns = await asyncio.to_thread(
            run_tiki_taka,
            question=request.question.strip(),
            agent_a_answer=first_answer,
            agent_a_name=request.agent_name,
            enable_round2=request.enable_round2,
        )
    except Exception as e:
        logger.error("티키타카 생성 실패: %s", e)
        turns = []

    return TikiTakaResponse(
        question=request.question.strip(),
        dialogue=[TikiTakaTurnDTO(**t.__dict__) for t in turns],
        round_count=min(2, max(1, len(turns) // 3)),
    )
