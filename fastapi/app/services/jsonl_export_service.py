"""
JSONL 내보내기 서비스.
ai.training_candidate에서 auto_approved 샘플만 messages 구조로 내보낸다.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def export_approved_candidates(
    output_path: str = "exported_training_data.jsonl",
    min_score: int = 90,
) -> dict:
    """
    quality_status='auto_approved' AND quality_score >= min_score인 샘플을
    messages 구조 JSONL로 저장한다.

    Returns:
        {"output_path": str, "exported_count": int, "status": str}
    """
    rows = await _fetch_approved(min_score)
    if not rows:
        return {"output_path": output_path, "exported_count": 0, "status": "empty"}

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with out.open("w", encoding="utf-8") as f:
        for row in rows:
            messages = []
            if row.get("system_prompt"):
                messages.append({"role": "system", "content": row["system_prompt"]})
            messages.append({"role": "user",      "content": row["question"]})
            messages.append({"role": "assistant", "content": row["answer"]})

            # 구조 검증
            if not all(m.get("content","").strip() for m in messages):
                continue

            f.write(json.dumps({"messages": messages}, ensure_ascii=False) + "\n")
            count += 1

    logger.info("JSONL 내보내기 완료: %d개 → %s", count, output_path)
    return {"output_path": output_path, "exported_count": count, "status": "completed"}


async def _fetch_approved(min_score: int) -> list[dict]:
    """ai-db에서 auto_approved 학습 후보를 조회한다."""
    from app.db.postgres import get_conn
    try:
        async with get_conn() as conn:
            rows = await conn.fetch(
                """
                SELECT question, answer, system_prompt, knowledge_level, personality
                FROM ai.training_candidate
                WHERE quality_status = 'auto_approved'
                  AND quality_score >= $1
                  AND is_duplicate = FALSE
                  AND is_unsafe = FALSE
                ORDER BY quality_score DESC, created_at ASC
                """,
                min_score,
            )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("학습 후보 조회 실패: %s", e)
        return []
