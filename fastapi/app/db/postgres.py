"""
AI 전용 PostgreSQL(pgvector) 연결 관리.

AI_DATABASE_URL 환경변수를 사용한다.
기존 팀플 DB(DB_HOST/capstone)와 완전히 분리된다.

연결 실패 시 서버가 죽지 않도록 lazy connect 패턴을 사용한다.
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)

_pool = None  # asyncpg pool (lazy init)


async def get_pool():
    """asyncpg 연결 풀을 반환한다. 미초기화 시 생성한다."""
    global _pool
    if _pool is None:
        await init_pool()
    return _pool


async def init_pool() -> None:
    """AI DB 연결 풀을 초기화한다."""
    global _pool
    from app.core.config import AI_DATABASE_URL

    if not AI_DATABASE_URL:
        logger.warning("AI_DATABASE_URL이 설정되지 않았습니다. DB 기능이 비활성화됩니다.")
        return

    try:
        import asyncpg
        _pool = await asyncpg.create_pool(
            dsn=AI_DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        logger.info("AI DB 연결 풀 초기화 완료")
    except Exception as e:
        logger.error("AI DB 연결 풀 초기화 실패: %s", e)
        _pool = None


async def close_pool() -> None:
    """연결 풀을 닫는다 (서버 종료 시 호출)."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("AI DB 연결 풀 종료")


@asynccontextmanager
async def get_conn() -> AsyncIterator:
    """
    AI DB 연결 컨텍스트 매니저.

    사용 예:
        async with get_conn() as conn:
            rows = await conn.fetch("SELECT 1")
    """
    pool = await get_pool()
    if pool is None:
        raise RuntimeError(
            "AI DB에 연결할 수 없습니다. "
            "AI_DATABASE_URL이 설정되었는지, ai-db 컨테이너가 기동됐는지 확인하세요."
        )
    async with pool.acquire() as conn:
        yield conn


async def health_check() -> dict:
    """
    AI DB 연결 상태를 반환한다.

    Returns:
        {"status": "ok" | "degraded" | "unavailable", "detail": str}
    """
    from app.core.config import AI_DATABASE_URL
    if not AI_DATABASE_URL:
        return {"status": "unavailable", "detail": "AI_DATABASE_URL 미설정"}
    try:
        async with get_conn() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok", "detail": "connected"}
    except Exception as e:
        return {"status": "unavailable", "detail": str(e)}
