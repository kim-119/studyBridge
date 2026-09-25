"""
Redis 클라이언트 관리.

REDIS_URL 환경변수를 사용한다.
Redis 연결 실패 시 FastAPI 전체가 죽지 않도록 degraded 모드로 동작한다.

키 구조:
  validation:{job_id}                  — 검증 작업 상태 (TTL: 1h)
  chat_lock:{user_id}:{question_hash}  — 중복 요청 방지 lock (TTL: 30s)
  ai_cache:{agent_id}:{level}:{hash}   — AI 답변 캐시 (TTL: 10min)
  tavily_cache:{query_hash}            — Tavily 검색 결과 캐시 (TTL: 10min)
  wiki_cache:{query_hash}              — Wikipedia 검색 결과 캐시 (TTL: 30min)
  agent_round:{session_id}             — 티키타카 라운드 상태 (TTL: 10min)
  rate_limit:ai:{user_id}              — 사용자별 요청 rate limit (TTL: 1min)
"""
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# TTL 상수 (초)
TTL_VALIDATION_JOB = 3600        # 1시간
TTL_CHAT_LOCK      = 30          # 30초
TTL_AI_CACHE       = 600         # 10분
TTL_TAVILY_CACHE   = 600         # 10분
TTL_WIKI_CACHE     = 1800        # 30분
TTL_AGENT_ROUND    = 600         # 10분
TTL_RATE_LIMIT     = 60          # 1분

_redis = None


async def get_redis():
    """Redis 클라이언트를 반환한다. 미초기화 시 연결 시도."""
    global _redis
    if _redis is None:
        await init_redis()
    return _redis


async def init_redis() -> None:
    """Redis 연결을 초기화한다. 실패해도 예외를 전파하지 않는다."""
    global _redis
    from app.core.config import REDIS_URL
    if not REDIS_URL:
        logger.warning("REDIS_URL이 설정되지 않았습니다. Redis 기능이 비활성화됩니다.")
        return
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(
            REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        await client.ping()
        _redis = client
        logger.info("Redis 연결 초기화 완료: %s", REDIS_URL)
    except Exception as e:
        logger.error("Redis 연결 실패 (degraded 모드): %s", e)
        _redis = None


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def health_check() -> dict:
    from app.core.config import REDIS_URL
    if not REDIS_URL:
        return {"status": "unavailable", "detail": "REDIS_URL 미설정"}
    try:
        r = await get_redis()
        if r is None:
            return {"status": "unavailable", "detail": "연결 실패"}
        await r.ping()
        return {"status": "ok", "detail": "connected"}
    except Exception as e:
        return {"status": "unavailable", "detail": str(e)}


# ── 검증 작업 상태 ────────────────────────────────────────────────────────────

async def set_validation_job(job_id: str, data: dict) -> bool:
    """검증 작업 상태를 Redis에 저장한다."""
    return await _set_json(f"validation:{job_id}", data, TTL_VALIDATION_JOB)


async def get_validation_job(job_id: str) -> Optional[dict]:
    """검증 작업 상태를 조회한다."""
    return await _get_json(f"validation:{job_id}")


async def update_validation_job(job_id: str, updates: dict) -> bool:
    """검증 작업 상태를 업데이트한다."""
    existing = await get_validation_job(job_id)
    if existing is None:
        existing = {}
    existing.update(updates)
    return await set_validation_job(job_id, existing)


# ── AI 답변 캐시 ─────────────────────────────────────────────────────────────

async def get_ai_cache(agent_id: Any, level: str, question_hash: str) -> Optional[str]:
    return await _get_json(f"ai_cache:{agent_id}:{level}:{question_hash}")


async def set_ai_cache(agent_id: Any, level: str, question_hash: str, answer: str) -> bool:
    return await _set_json(f"ai_cache:{agent_id}:{level}:{question_hash}", answer, TTL_AI_CACHE)


# ── Tavily / Wikipedia 캐시 ───────────────────────────────────────────────────

async def get_tavily_cache(query_hash: str) -> Optional[list]:
    return await _get_json(f"tavily_cache:{query_hash}")


async def set_tavily_cache(query_hash: str, results: list) -> bool:
    return await _set_json(f"tavily_cache:{query_hash}", results, TTL_TAVILY_CACHE)


async def get_wiki_cache(query_hash: str) -> Optional[list]:
    return await _get_json(f"wiki_cache:{query_hash}")


async def set_wiki_cache(query_hash: str, results: list) -> bool:
    return await _set_json(f"wiki_cache:{query_hash}", results, TTL_WIKI_CACHE)


# ── 티키타카 라운드 상태 ──────────────────────────────────────────────────────

async def set_agent_round(session_id: str, state: dict) -> bool:
    return await _set_json(f"agent_round:{session_id}", state, TTL_AGENT_ROUND)


async def get_agent_round(session_id: str) -> Optional[dict]:
    return await _get_json(f"agent_round:{session_id}")


# ── Rate limit ────────────────────────────────────────────────────────────────

async def check_rate_limit(user_id: str, max_requests: int = 10) -> bool:
    """
    True = 요청 허용, False = 한도 초과.
    1분 내 max_requests 초과 시 차단한다.
    """
    key = f"rate_limit:ai:{user_id}"
    r = await get_redis()
    if r is None:
        return True  # Redis 없으면 허용
    try:
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, TTL_RATE_LIMIT)
        results = await pipe.execute()
        count = results[0]
        return count <= max_requests
    except Exception:
        return True


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

async def _set_json(key: str, value: Any, ttl: int) -> bool:
    r = await get_redis()
    if r is None:
        return False
    try:
        await r.setex(key, ttl, json.dumps(value, ensure_ascii=False))
        return True
    except Exception as e:
        logger.warning("Redis set 실패 key=%s: %s", key, e)
        return False


async def _get_json(key: str) -> Optional[Any]:
    r = await get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning("Redis get 실패 key=%s: %s", key, e)
        return None
