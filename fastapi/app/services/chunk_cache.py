"""
PDF chunk TTL 캐시 — RDS에 chunk 원문을 저장하지 않는다.

backend 우선순위:
  1. Redis (AI_CHUNK_CACHE_BACKEND=redis, redis-py 설치 + 연결 성공 시)
  2. in-memory TTL dict (Redis 미설치/연결 실패 시 자동 fallback)

캐시 키: chunk:{materialId}:{extractedTextHash}
같은 materialId + extractedTextHash면 재생성하지 않는다. hash가 바뀌면 재생성.
서버가 죽지 않도록 모든 외부 의존성(import/연결)은 try/except로 감싼다.
"""
import asyncio
import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CACHE_BACKEND = os.getenv("AI_CHUNK_CACHE_BACKEND", "redis").strip().lower()
CACHE_TTL = int(os.getenv("AI_CHUNK_CACHE_TTL_SECONDS", "21600"))  # 6h
REDIS_URL = os.getenv("REDIS_URL") or os.getenv("AI_CHUNK_REDIS_URL") or "redis://localhost:6379/0"

# in-memory TTL store: key -> (expiresAt, payload)
_mem_store: Dict[str, Tuple[float, str]] = {}
# per-document locks (materialId+hash 기준)
_locks: Dict[str, asyncio.Lock] = {}

_redis_client = None
_redis_tried = False


def get_extracted_text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:32]


def get_chunk_cache_key(material_id: Optional[int], extracted_text_hash: str) -> str:
    return f"chunk:{material_id if material_id is not None else 'na'}:{extracted_text_hash}"


def _get_redis():
    """sync redis 클라이언트 (없으면 None). import/연결 실패해도 서버는 죽지 않는다."""
    global _redis_client, _redis_tried
    if CACHE_BACKEND != "redis":
        return None
    if _redis_tried:
        return _redis_client
    _redis_tried = True
    try:
        import redis  # type: ignore
        client = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        _redis_client = client
        logger.info("chunk_cache: Redis 연결 성공")
    except Exception as e:
        logger.warning("chunk_cache: Redis 사용 불가 → in-memory fallback (%s)", e)
        _redis_client = None
    return _redis_client


def _mem_get(key: str) -> Optional[str]:
    item = _mem_store.get(key)
    if not item:
        return None
    expires_at, payload = item
    if time.time() > expires_at:
        _mem_store.pop(key, None)
        return None
    return payload


def _mem_set(key: str, payload: str, ttl: int) -> None:
    _mem_store[key] = (time.time() + ttl, payload)


def get_cached_chunks(key: str) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """(chunks, backend) 반환. backend: redis | memory | none."""
    r = _get_redis()
    if r is not None:
        try:
            raw = r.get(key)
            if raw:
                return json.loads(raw), "redis"
        except Exception as e:
            logger.warning("chunk_cache: Redis get 실패 → memory (%s)", e)
    raw = _mem_get(key)
    if raw:
        return json.loads(raw), "memory"
    return None, "none"


def set_cached_chunks(key: str, chunks: List[Dict[str, Any]], ttl: int = CACHE_TTL) -> str:
    """저장한 backend 문자열 반환 (redis | memory)."""
    payload = json.dumps(chunks, ensure_ascii=False)
    r = _get_redis()
    if r is not None:
        try:
            r.setex(key, ttl, payload)
            return "redis"
        except Exception as e:
            logger.warning("chunk_cache: Redis setex 실패 → memory (%s)", e)
    _mem_set(key, payload, ttl)
    return "memory"


def clear_chunk_cache(material_id: int) -> None:
    """자료 삭제 시 호출 가능. Redis는 패턴 삭제, memory는 prefix 제거."""
    prefix = f"chunk:{material_id}:"
    r = _get_redis()
    if r is not None:
        try:
            for k in r.scan_iter(match=prefix + "*"):
                r.delete(k)
        except Exception as e:
            logger.warning("chunk_cache: Redis clear 실패 (%s)", e)
    for k in list(_mem_store.keys()):
        if k.startswith(prefix):
            _mem_store.pop(k, None)


def _lock_for(key: str) -> asyncio.Lock:
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


async def get_or_build_chunks(material_id: Optional[int], extracted_text: str) -> Dict[str, Any]:
    """
    캐시 우선 chunk 조회. 없으면 per-document lock 하에 1회만 생성 후 캐시 저장.
    Returns: {chunks, cacheHit, cacheBackend, extractedTextHash}
    """
    from app.services.material_ai_manager import build_chunks_from_text

    text_hash = get_extracted_text_hash(extracted_text)
    key = get_chunk_cache_key(material_id, text_hash)

    cached, backend = get_cached_chunks(key)
    if cached is not None:
        return {"chunks": cached, "cacheHit": True, "cacheBackend": backend, "extractedTextHash": text_hash}

    async with _lock_for(key):
        # lock 획득 후 재확인 (동시 요청이 먼저 만들었을 수 있음)
        cached, backend = get_cached_chunks(key)
        if cached is not None:
            return {"chunks": cached, "cacheHit": True, "cacheBackend": backend, "extractedTextHash": text_hash}
        chunks = await asyncio.to_thread(build_chunks_from_text, extracted_text, material_id)
        used_backend = set_cached_chunks(key, chunks)
        return {"chunks": chunks, "cacheHit": False, "cacheBackend": used_backend, "extractedTextHash": text_hash}
