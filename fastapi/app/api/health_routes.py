"""GET /api/health — 서버 상태 및 설정 여부 확인.
Spring Boot 계약 필드: openaiConfigured, ollamaConfigured, tavilyConfigured, awsConfigured.
외부 서버(DB, Redis, Ollama) 실제 연결은 시도하지 않는다.
환경변수 존재 여부만으로 설정 여부를 판단한다.
실제 key 값은 절대 응답에 포함하지 않는다.
"""
import logging
import os

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Health"])


@router.get("/health", summary="서버 상태 확인")
async def health_check():
    """
    환경변수 존재 여부 기반으로 설정 상태를 반환한다.
    외부 서버 연결 검증은 하지 않는다.
    """
    from app.core.config import (
        OPENAI_API_KEY,
        TAVILY_API_KEY,
        OLLAMA_BASE_URL,
        AWS_ACCESS_KEY_ID,
        AWS_SECRET_ACCESS_KEY,
        AWS_S3_BUCKET,
    )

    openai_configured = bool(OPENAI_API_KEY)
    ollama_configured = bool(OLLAMA_BASE_URL)
    tavily_configured = bool(TAVILY_API_KEY)
    aws_configured = bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_S3_BUCKET)

    return {
        "status": "ok",
        "service": "studybridge-fastapi",
        "openaiConfigured": openai_configured,
        "ollamaConfigured": ollama_configured,
        "tavilyConfigured": tavily_configured,
        "awsConfigured": aws_configured,
    }
