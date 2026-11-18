"""
오프라인 답변 캐시.
자주 묻는 질문, 박사 수준 검증 통과 답변 등을 Redis에 캐시한다.
캐시 miss 시 기존 LLM pipeline을 실행한다.
"""
import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _make_cache_key(
    question: str,
    domain: str,
    knowledge_level: str,
    personality: Optional[str] = None,
    mode: Optional[str] = None,
    material_id: Optional[int] = None,
) -> str:
    """캐시 키 생성. normalized_question + domain + level + personality + mode + materialId."""
    normalized = question.strip().lower()[:200]
    key_parts = [
        f"offline_cache",
        f"domain={domain}",
        f"level={knowledge_level}",
        f"personality={personality or 'default'}",
        f"mode={mode or 'default'}",
        f"material={material_id or 'none'}",
        f"q={hashlib.sha256(normalized.encode()).hexdigest()[:16]}",
    ]
    return ":".join(key_parts)


def get(
    question: str,
    domain: str,
    knowledge_level: str,
    personality: Optional[str] = None,
    mode: Optional[str] = None,
    material_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """캐시에서 답변을 조회한다. 없으면 None 반환."""
    try:
        from app.db.redis_client import get_redis
        redis = get_redis()
        if not redis:
            return None
        key = _make_cache_key(question, domain, knowledge_level, personality, mode, material_id)
        raw = redis.get(key)
        if raw:
            logger.debug("오프라인 캐시 hit: %s", key[:60])
            return json.loads(raw)
    except Exception as e:
        logger.debug("캐시 조회 실패 (계속 진행): %s", e)
    return None


def set(
    question: str,
    domain: str,
    knowledge_level: str,
    answer_data: Dict[str, Any],
    personality: Optional[str] = None,
    mode: Optional[str] = None,
    material_id: Optional[int] = None,
) -> None:
    """답변을 캐시에 저장한다."""
    try:
        from app.db.redis_client import get_redis
        redis = get_redis()
        if not redis:
            return

        key = _make_cache_key(question, domain, knowledge_level, personality, mode, material_id)

        # 의료/법률/환경 등 최신성 중요 분야는 TTL 짧게
        high_stakes_domains = {"medicine_health", "law", "environment", "economics"}
        if domain in high_stakes_domains:
            ttl = 1800  # 30분
        elif knowledge_level == "박사":
            ttl = 7200  # 2시간
        else:
            ttl = 3600  # 1시간

        redis.setex(key, ttl, json.dumps(answer_data, ensure_ascii=False))
        logger.debug("오프라인 캐시 저장: %s (ttl=%ds)", key[:60], ttl)
    except Exception as e:
        logger.debug("캐시 저장 실패 (계속 진행): %s", e)


def invalidate_by_material(material_id: int) -> None:
    """특정 자료 업데이트 시 해당 캐시를 무효화한다."""
    try:
        from app.db.redis_client import get_redis
        redis = get_redis()
        if not redis:
            return
        pattern = f"offline_cache:*:material={material_id}:*"
        keys = redis.keys(pattern)
        if keys:
            redis.delete(*keys)
            logger.info("캐시 무효화 완료: material_id=%d (%d건)", material_id, len(keys))
    except Exception as e:
        logger.warning("캐시 무효화 실패: %s", e)
