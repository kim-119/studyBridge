"""
학습메이트 endpoint — POST /api/ai/learning-mate/chat

endpoint는 요청 검증 → service 호출 → 응답 변환만 담당한다(정책/프롬프트 로직 없음).
"""
import logging

from fastapi import APIRouter, HTTPException

from .schemas import LearningMateChatRequest, LearningMateChatResponse
from .service import LearningMateLLMError, generate_chat

logger = logging.getLogger("studybridge.learning_mate")
router = APIRouter(prefix="/api/ai/learning-mate", tags=["Learning Mate"])


@router.post("/chat", response_model=LearningMateChatResponse, summary="학습메이트 mode 기반 답변 생성")
async def learning_mate_chat(request: LearningMateChatRequest) -> LearningMateChatResponse:
    # 입력 검증: question과 previousQuestion이 모두 비어 있으면 422
    q = (request.question or "").strip()
    prev = (request.previousQuestion or "").strip()
    if not q and not prev:
        raise HTTPException(status_code=422, detail="question 또는 previousQuestion 중 하나는 필요합니다.")

    try:
        return generate_chat(request)
    except LearningMateLLMError as e:
        # 가짜 답변 금지 — 명확한 실패로 전달(Spring/React가 '답변 생성 실패' 표시).
        raise HTTPException(status_code=502, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("learning_mate 처리 중 예외: %s", e)
        raise HTTPException(status_code=500, detail="학습메이트 처리 중 오류가 발생했습니다.")
