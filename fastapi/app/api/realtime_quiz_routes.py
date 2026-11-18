"""Realtime group-study quiz API."""
from __future__ import annotations

import asyncio
import logging
from typing import Union

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.core.security import verify_internal_token
from app.schemas.realtime_quiz_schema import (
    RealtimeQuizErrorResponse,
    RealtimeQuizGenerateRequest,
    RealtimeQuizSuccessResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/ai",
    tags=["Realtime Quiz"],
    dependencies=[Depends(verify_internal_token)],
)


@router.post(
    "/realtime-quiz/generate",
    response_model=Union[RealtimeQuizSuccessResponse, RealtimeQuizErrorResponse],
    summary="그룹스터디 실시간 퀴즈 생성",
)
async def generate_realtime_quiz_endpoint(request: RealtimeQuizGenerateRequest):
    try:
        from app.services.realtime_quiz_service import generate_realtime_quiz
        result = await asyncio.wait_for(
            asyncio.to_thread(generate_realtime_quiz, request),
            timeout=120,
        )
        result.pop("_elapsed_ms", None)
        return RealtimeQuizSuccessResponse(**result)
    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"status": "ERROR", "error_code": "QUIZ_INPUT_INVALID", "message": str(e)},
        )
    except asyncio.TimeoutError:
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content={"status": "ERROR", "error_code": "QUIZ_GENERATE_TIMEOUT", "message": "퀴즈 생성 요청이 시간 초과되었습니다."},
        )
    except Exception as e:
        logger.exception("realtime quiz generation failed")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": "ERROR", "error_code": "QUIZ_GENERATE_FAILED", "message": "실시간 퀴즈 생성에 실패했습니다."},
        )
