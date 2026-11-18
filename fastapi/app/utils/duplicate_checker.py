"""
중복 Q/A 검사 유틸리티.
content_hash(SHA-256)를 ai-db에서 조회해 중복 여부를 판단한다.
DB 연결 실패 시 False(중복 아님)를 반환해 데이터 수집을 차단하지 않는다.
"""
import logging

logger = logging.getLogger(__name__)


async def is_duplicate(content_hash: str) -> bool:
    """content_hash가 ai.training_candidate에 이미 있으면 True를 반환한다."""
    try:
        from app.db.postgres import get_conn
        async with get_conn() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM ai.training_candidate WHERE content_hash=$1",
                content_hash,
            )
        return (count or 0) > 0
    except Exception as e:
        logger.warning("중복 검사 실패 (False 반환): %s", e)
        return False
