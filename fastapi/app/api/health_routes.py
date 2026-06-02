"""GET /api/health — 서버 및 의존 서비스 상태 확인."""
import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Health"])


@router.get("/health", summary="서버 상태 확인")
async def health_check():
    """
    FastAPI 서버, ai-db, Redis, OpenAI Key, Tavily Key, Ollama 상태를 반환한다.
    인증 불필요.
    """
    from app.core.config import (
        OPENAI_API_KEY, TAVILY_API_KEY, OLLAMA_BASE_URL, OLLAMA_MODEL,
        AI_DATABASE_URL, REDIS_URL,
    )

    # ── AI DB 상태 ────────────────────────────────────────────────────
    try:
        from app.db.postgres import health_check as db_check
        db_status = await db_check()
    except Exception as e:
        db_status = {"status": "unavailable", "detail": str(e)}

    # ── Redis 상태 ────────────────────────────────────────────────────
    try:
        from app.db.redis_client import health_check as redis_check
        redis_status = await redis_check()
    except Exception as e:
        redis_status = {"status": "unavailable", "detail": str(e)}

    # ── Ollama 상태 (optional) ────────────────────────────────────────
    ollama_status = {"status": "unchecked"}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
        if resp.status_code == 200:
            ollama_status = {"status": "ok", "model": OLLAMA_MODEL}
        else:
            ollama_status = {"status": "degraded", "detail": f"HTTP {resp.status_code}"}
    except Exception as e:
        ollama_status = {"status": "unavailable", "detail": str(e)}

    return {
        "status": "ok",
        "service": "StudyBridge AI Server",
        "version": "0.5.0",
        "dependencies": {
            "ai_db": db_status,
            "redis": redis_status,
            "ollama": ollama_status,
            "openai_key_set": bool(OPENAI_API_KEY),
            "tavily_key_set": bool(TAVILY_API_KEY),
            "ai_database_url_set": bool(AI_DATABASE_URL),
            "redis_url_set": bool(REDIS_URL),
        },
    }
