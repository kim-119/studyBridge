"""ai.validation_job 리포지토리."""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def get_job_by_uuid(job_uuid: str) -> Optional[dict]:
    from app.db.postgres import get_conn
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ai.validation_job WHERE job_uuid=$1::uuid",
            job_uuid,
        )
    return dict(row) if row else None
