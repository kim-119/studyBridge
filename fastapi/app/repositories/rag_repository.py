"""rag.document_chunk 리포지토리."""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def count_chunks_by_material(material_id: int) -> int:
    from app.db.postgres import get_conn
    async with get_conn() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM rag.document_chunk WHERE material_id=$1",
            material_id,
        ) or 0


async def delete_by_material(material_id: int) -> int:
    from app.db.postgres import get_conn
    async with get_conn() as conn:
        result = await conn.execute(
            "DELETE FROM rag.document_chunk WHERE material_id=$1",
            material_id,
        )
    # DELETE 1 → 1
    return int(result.split()[-1]) if result else 0
