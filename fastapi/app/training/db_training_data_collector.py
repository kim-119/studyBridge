"""
DB 학습 후보 데이터 수집기.

ai.training_candidate 테이블에서 학습 후보 데이터를 읽는다.
기존 training_candidate_manager.py / jsonl_export_service.py의 수집 기능을 보완한다.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 기본 최소 품질 점수 (0~100 스케일, 기존 테이블 기준)
_DEFAULT_MIN_SCORE = 70


async def fetch_candidates(
    statuses: list[str] | None = None,
    min_score: int = _DEFAULT_MIN_SCORE,
    knowledge_level: Optional[str] = None,
    personality: Optional[str] = None,
    limit: int = 5000,
) -> list[dict]:
    """
    ai.training_candidate 에서 학습 후보를 조회한다.

    Args:
        statuses:        필터할 quality_status 목록 (None이면 auto_approved + holdout)
        min_score:       최소 quality_score (0~100)
        knowledge_level: 특정 지식수준으로 필터 (None이면 전체)
        personality:     특정 성격으로 필터 (None이면 전체)
        limit:           최대 조회 수

    Returns:
        [{"candidate_uuid", "question", "answer", "system_prompt",
          "knowledge_level", "personality", "quality_score", "quality_status",
          "is_duplicate", "is_unsafe", "created_at"}, ...]

    DB 연결 실패 시 빈 리스트 반환 (서버를 죽이지 않음).
    """
    if statuses is None:
        statuses = ["auto_approved", "holdout"]

    try:
        from app.db.postgres import get_conn
        async with get_conn() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    candidate_uuid::text,
                    question,
                    answer,
                    system_prompt,
                    knowledge_level,
                    personality,
                    quality_score,
                    quality_status,
                    is_duplicate,
                    is_unsafe,
                    created_at
                FROM ai.training_candidate
                WHERE quality_status = ANY($1::text[])
                  AND quality_score  >= $2
                  AND is_duplicate   = FALSE
                  AND is_unsafe      = FALSE
                  AND ($3::text IS NULL OR knowledge_level = $3)
                  AND ($4::text IS NULL OR personality     = $4)
                ORDER BY quality_score DESC, created_at ASC
                LIMIT $5
                """,
                statuses,
                min_score,
                knowledge_level,
                personality,
                limit,
            )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("학습 후보 조회 실패: %s", e)
        return []


async def count_candidates(
    statuses: list[str] | None = None,
    min_score: int = _DEFAULT_MIN_SCORE,
) -> dict[str, int]:
    """
    상태별·총계 후보 수를 반환한다.

    Returns:
        {"total": int, "auto_approved": int, "holdout": int,
         "auto_rejected": int, "duplicate": int, "unsafe": int}
    """
    if statuses is None:
        statuses = ["auto_approved", "holdout", "auto_rejected", "duplicate", "unsafe"]

    try:
        from app.db.postgres import get_conn
        async with get_conn() as conn:
            rows = await conn.fetch(
                """
                SELECT quality_status, COUNT(*) AS cnt
                FROM ai.training_candidate
                GROUP BY quality_status
                """
            )
            qualified = await conn.fetchval(
                """
                SELECT COUNT(*) FROM ai.training_candidate
                WHERE quality_status IN ('auto_approved','holdout')
                  AND quality_score >= $1
                  AND is_duplicate = FALSE
                  AND is_unsafe    = FALSE
                """,
                min_score,
            )
        stat_map = {r["quality_status"]: int(r["cnt"]) for r in rows}
        return {
            "total":          sum(stat_map.values()),
            "auto_approved":  stat_map.get("auto_approved", 0),
            "holdout":        stat_map.get("holdout", 0),
            "auto_rejected":  stat_map.get("auto_rejected", 0),
            "duplicate":      stat_map.get("duplicate", 0),
            "unsafe":         stat_map.get("unsafe", 0),
            "qualified":      int(qualified or 0),  # 실제 학습 가능 후보 수
        }
    except Exception as e:
        logger.error("후보 수 집계 실패: %s", e)
        return {
            "total": 0, "auto_approved": 0, "holdout": 0,
            "auto_rejected": 0, "duplicate": 0, "unsafe": 0, "qualified": 0,
        }


async def fetch_recent_export_info() -> dict:
    """가장 최근 JSONL export 작업 정보를 반환한다."""
    try:
        from app.db.postgres import get_conn
        async with get_conn() as conn:
            row = await conn.fetchrow(
                """
                SELECT file_path, sample_count, status, created_at
                FROM ai.training_export_job
                WHERE status = 'completed'
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
        if row:
            return {
                "last_exported_file": row["file_path"],
                "last_export_count": row["sample_count"],
                "last_export_at": str(row["created_at"]),
            }
    except Exception as e:
        logger.debug("export 이력 조회 실패: %s", e)
    return {"last_exported_file": None, "last_export_count": 0, "last_export_at": None}


async def save_export_job(
    file_path: str,
    sample_count: int,
    status: str = "completed",
    error_message: str | None = None,
) -> None:
    """export 작업 이력을 ai.training_export_job 에 저장한다."""
    try:
        from app.db.postgres import get_conn
        async with get_conn() as conn:
            await conn.execute(
                """
                INSERT INTO ai.training_export_job
                  (status, filter_status, sample_count, file_path, error_message, completed_at)
                VALUES ($1, 'validated', $2, $3, $4, NOW())
                """,
                status, sample_count, file_path, error_message,
            )
    except Exception as e:
        logger.warning("export 이력 저장 실패 (무시): %s", e)
