"""
학습 데이터 내보내기 작업(export_job) 저장소.
ai.training_export_job 테이블에 작업 상태를 기록한다.
DB 연결 실패 시 RuntimeError를 전파한다.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


async def create_export_job(filter_status: str = "auto_approved") -> dict:
    """
    내보내기 작업을 생성하고 반환한다.

    Returns:
        {"export_uuid": str, "status": "pending", "created_at": str}
    """
    from app.db.postgres import get_conn
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO ai.training_export_job (status, filter_status, created_at)
            VALUES ('pending', $1, NOW())
            RETURNING export_uuid::text, status, created_at
            """,
            filter_status,
        )
        return dict(row)


async def update_export_job(
    export_uuid: str,
    status: str,
    sample_count: Optional[int] = None,
    file_path: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """내보내기 작업 상태를 업데이트한다."""
    from app.db.postgres import get_conn
    async with get_conn() as conn:
        await conn.execute(
            """
            UPDATE ai.training_export_job
            SET status       = $2,
                sample_count = COALESCE($3, sample_count),
                file_path    = COALESCE($4, file_path),
                error_message = COALESCE($5, error_message),
                completed_at = CASE WHEN $2 IN ('completed', 'failed') THEN NOW() ELSE completed_at END
            WHERE export_uuid = $1::uuid
            """,
            export_uuid,
            status,
            sample_count,
            file_path,
            error_message,
        )


async def get_export_job(export_uuid: str) -> Optional[dict]:
    """내보내기 작업 상태를 조회한다."""
    from app.db.postgres import get_conn
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ai.training_export_job WHERE export_uuid = $1::uuid",
            export_uuid,
        )
        return dict(row) if row else None
