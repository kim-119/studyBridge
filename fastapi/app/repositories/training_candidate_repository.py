"""ai.training_candidate 리포지토리."""
import logging

logger = logging.getLogger(__name__)


async def get_stats() -> dict:
    """상태별 개수를 반환한다. DB 연결 실패 시 RuntimeError."""
    from app.db.postgres import get_conn
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT quality_status, COUNT(*) AS cnt
            FROM ai.training_candidate
            GROUP BY quality_status
            """
        )
    stat_map = {r["quality_status"]: r["cnt"] for r in rows}
    # 전체 수집 건수
    all_count = sum(stat_map.values())
    return {
        "auto_collected": all_count,
        "auto_approved":  stat_map.get("auto_approved", 0),
        "auto_rejected":  stat_map.get("auto_rejected", 0),
        "holdout":        stat_map.get("holdout", 0),
        "duplicate":      stat_map.get("duplicate", 0),
        "unsafe":         stat_map.get("unsafe", 0),
    }
