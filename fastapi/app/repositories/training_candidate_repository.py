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
        # 검수자가 수동 승인/거절한 건수
        "manual_approved": stat_map.get("manual_approved", 0),
        "rejected":        stat_map.get("rejected", 0),
    }


async def update_status(candidate_uuid: str, new_status: str) -> bool:
    """
    검수자가 후보의 quality_status를 수동으로 변경한다(승인/거절).
    변경된 행이 있으면 True. DB 연결 실패 시 RuntimeError.
    """
    from app.db.postgres import get_conn
    async with get_conn() as conn:
        result = await conn.execute(
            """
            UPDATE ai.training_candidate
               SET quality_status = $2
             WHERE candidate_uuid::text = $1
            """,
            candidate_uuid, new_status,
        )
    # asyncpg execute는 'UPDATE N' 문자열을 반환 → 끝 숫자로 영향 행 수 판단
    try:
        return int(str(result).rsplit(" ", 1)[-1]) > 0
    except (ValueError, IndexError):
        return False
