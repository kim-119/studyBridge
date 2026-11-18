"""
StudyBridge 학습 왕복 루프(Learning Loop) 통합 endpoint.

  POST /api/ai/learning-loop   taskType 기반 단일 진입점

Spring 이 materialId/documentId 소유권을 검증한 뒤, taskType 과 learningLoopContext 를
실어 호출한다. FastAPI 는 RAG 본문 근거 + 학습 이력을 결합해 구조화 JSON 을 생성·검증해
반환하고, DB 저장은 Spring 이 담당한다.

기존 /api/ai/multi-chat/stream, /ai/chat, /ai/summary, /ai/roadmap, /ai/quiz,
/ai/question, /api/rag/query 및 review-note/* 계열과는 별개의 신규 additive 경로다.
어떤 taskType/필드가 비어 있어도 요청이 실패하지 않도록 모든 컨텍스트 필드는 optional 이다.
"""
import asyncio
import logging
import os
import time
from typing import Any, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Learning Loop"])

LEARNING_LOOP_TIMEOUT = int(os.getenv("AI_LEARNING_LOOP_TIMEOUT_SECONDS", "120"))


class LearningLoopContext(BaseModel):
    """학습 이력 컨텍스트. 모든 필드 optional — 없으면 기존 방식대로 동작한다."""
    summaries: List[Any] = Field(default_factory=list)
    wrongNotes: List[Any] = Field(default_factory=list)
    quizResults: List[Any] = Field(default_factory=list)
    plannerReviews: List[Any] = Field(default_factory=list)
    userMemos: List[Any] = Field(default_factory=list)
    recentChatHistory: List[Any] = Field(default_factory=list)
    agentFeedback: List[Any] = Field(default_factory=list)


class LearningLoopRequest(BaseModel):
    taskType: str = ""
    userQuestion: Optional[str] = ""
    materialId: Optional[Any] = None
    documentId: Optional[Any] = None
    sourceText: Optional[str] = ""
    title: Optional[str] = ""
    # 생성 옵션
    count: Optional[int] = None
    difficulty: Optional[str] = ""
    # 에이전트 모드(AGENT_CHAT_WITH_FEEDBACK)
    mode: Optional[str] = ""
    personality: Optional[str] = ""
    knowledgeLevel: Optional[str] = ""
    learningLoopContext: Optional[LearningLoopContext] = None

    model_config = {"extra": "ignore"}


@router.post("/api/ai/learning-loop", summary="학습 왕복 루프 통합 처리 (taskType 디스패치)")
async def learning_loop(req: LearningLoopRequest):
    from app.services.learning_loop_service import run_learning_loop

    started = time.time()
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(run_learning_loop, req), timeout=LEARNING_LOOP_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("[learning-loop] timeout taskType=%s", req.taskType)
        from app.services.learning_loop_service import _new_used  # type: ignore
        return JSONResponse(status_code=200, content={
            "success": True,
            "taskType": (req.taskType or "").strip().upper() or "UNKNOWN",
            "items": [],
            "answer": "",
            "usedContext": _new_used(),
            "warnings": ["LLM 응답 지연으로 timeout fallback 이 사용되었습니다."],
        })
    except Exception as e:  # noqa: BLE001
        logger.error("[learning-loop] 실패 taskType=%s: %s", req.taskType, e, exc_info=True)
        return JSONResponse(status_code=200, content={
            "success": False,
            "taskType": (req.taskType or "").strip().upper() or "UNKNOWN",
            "errorCode": "LEARNING_LOOP_FAILED",
            "warnings": [f"처리 중 오류가 발생했습니다: {type(e).__name__}"],
        })

    elapsed = int((time.time() - started) * 1000)
    logger.info("[learning-loop] taskType=%s success=%s elapsedMs=%d warnings=%d",
                result.get("taskType"), result.get("success"), elapsed, len(result.get("warnings") or []))
    status = 200 if result.get("success") else 422
    return JSONResponse(status_code=status, content=result)
