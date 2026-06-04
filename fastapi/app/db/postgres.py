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


# alias — caller에서 check_ai_db_health()로 호출 가능
check_ai_db_health = health_check


# ── MAIN_DATABASE_URL (기존 팀플 DB) — 사용 주의 ────────────────────────────
# FastAPI는 기본적으로 MAIN_DATABASE_URL을 사용하지 않는다.
# Spring Boot가 데이터 주인이다.
# 아래 함수는 read-only 보조 조회가 필요한 경우에만 사용한다.
# production에서는 MAIN_DATABASE_READONLY=true 강제 권장.
async def get_main_db_conn_readonly():
    """
    기존 팀플 DB에 read-only 연결을 반환한다.
    MAIN_DATABASE_URL이 미설정이면 RuntimeError.
    FastAPI가 기존 capstone-db를 직접 조회해야 하는 예외적인 경우에만 사용한다.
    """
    import os
    main_url = os.getenv("MAIN_DATABASE_URL")
    if not main_url:
        raise RuntimeError(
            "MAIN_DATABASE_URL이 설정되지 않았습니다. "
            "기본적으로 Spring Boot를 통해 데이터를 받는 구조를 우선합니다."
        )
    try:
        import asyncpg
        conn = await asyncpg.connect(dsn=main_url)
        return conn
    except Exception as e:
        logger.error("MAIN DB read-only 연결 실패: %s", type(e).__name__)
        raise RuntimeError(f"기존 DB 연결 실패: {type(e).__name__}") from e
