"""
POST /api/ai/chat — 에이전트 채팅
Qwen/Ollama 1차 답변 즉시 반환 + GPT 검증 background task.
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.core.security import verify_internal_token
from app.schemas.ai_chat_schema import AIChatRequest, AIChatResponse

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/ai",
    tags=["AI Chat"],
    dependencies=[Depends(verify_internal_token)],
)


@router.post(
    "/chat",
    response_model=AIChatResponse,
    summary="에이전트 채팅 (즉시 답변 + 비동기 검증)",
)
async def ai_chat(
    request: AIChatRequest,
    background_tasks: BackgroundTasks,
) -> AIChatResponse:
    """
    지식수준·성격 기반 에이전트 채팅.
    Qwen/Ollama 1차 답변을 즉시 반환하고
    GPT 검증·학습 후보 수집은 백그라운드에서 실행한다.
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question은 비워둘 수 없습니다.")

    import asyncio
    from app.services.agent_chat_service import run_agent_chat
    from app.services.validation_manager import create_validation_job_async

    # 동기 파이프라인을 thread에서 실행 (이벤트 루프 블로킹 방지)
    try:
        result = await asyncio.to_thread(
            run_agent_chat,
            question=request.question.strip(),
            knowledge_level=request.knowledge_level,
            personality=request.personality,
            agent_name=request.agent_name,
            custom_instruction=request.custom_instruction,
            material_id=request.material_id,
            enable_tiki_taka=False,  # 티키타카는 별도 엔드포인트
        )
    except Exception as e:
        logger.error("agent_chat 실행 실패: %s", e)
        # fallback: 빈 답변 반환 (DB 장애 시에도 채팅 전체 실패 방지)
        result = {
            "answer": f"일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요. ({type(e).__name__})",
            "tiki_taka_dialogue": [],
            "process_logs": [str(e)],
            "knowledge_level": request.knowledge_level,
            "personality": request.personality,
        }

    # GPT 검증 + 학습 후보 수집 background task
    job_id = None
    if request.use_gpt_validation:
        job_id = await create_validation_job_async(
            question=request.question.strip(),
            answer=result["answer"],
            knowledge_level=request.knowledge_level,
            personality=request.personality,
        )
        from app.services.validation_manager import run_validation_background
        background_tasks.add_task(
            run_validation_background,
            job_id,
            request.question.strip(),
            result["answer"],
            request.knowledge_level,
            request.personality,
        )

    return AIChatResponse(
        answer=result["answer"],
        validation_job_id=job_id,
        status="pending_validation" if job_id else "complete",
        knowledge_level=result["knowledge_level"],
        personality=result["personality"],
        process_logs=result["process_logs"],
    )
