"""
검증 작업 관리자.
Redis에 작업 상태를 저장하고 GPT 비동기 검증을 실행한다.
ai-db validation_job 테이블에 최종 결과를 저장한다.
"""
import logging
import uuid

logger = logging.getLogger(__name__)


async def create_validation_job_async(
    question: str,
    answer: str,
    knowledge_level: str,
    personality: str,
) -> str:
    """
    Redis에 pending 상태 검증 작업을 생성하고 job_id를 반환한다.
    Redis 미설정 시 in-memory fallback.
    """
    job_id = str(uuid.uuid4())
    job_data = {
        "status":           "pending",
        "question":         question,
        "answer":           answer,
        "knowledge_level":  knowledge_level,
        "personality":      personality,
        "result":           None,
        "corrected_answer": None,
    }
    try:
        from app.db.redis_client import set_validation_job
        await set_validation_job(job_id, job_data)
    except Exception as e:
        logger.warning("Redis 저장 실패, 인메모리 fallback: %s", e)
        _in_memory_jobs[job_id] = job_data

    return job_id


# 인메모리 fallback (Redis 미설정 시)
_in_memory_jobs: dict = {}


async def run_validation_background(
    job_id: str,
    question: str,
    answer: str,
    knowledge_level: str,
    personality: str,
) -> None:
    """
    Background task: GPT로 답변을 검증하고 결과를 Redis + ai-db에 저장한다.
    """
    from app.db.redis_client import update_validation_job
    await update_validation_job(job_id, {"status": "running"})

    try:
        from app.services.gpt_verifier import verify_answer_async, generate_corrected_answer_async
        result = await verify_answer_async(question, answer, knowledge_level, personality)

        corrected = None
        if result.get("correction_needed") and result.get("suggestion"):
            corrected = await generate_corrected_answer_async(
                question, answer, result["suggestion"], knowledge_level, personality
            )

        await update_validation_job(job_id, {
            "status":           "completed",
            "result":           result,
            "corrected_answer": corrected,
        })

        # ai-db 영구 저장 (실패해도 무시)
        try:
            await _save_to_db(job_id, question, answer, knowledge_level, personality, result, corrected)
        except Exception as e:
            logger.warning("ai-db validation_job 저장 실패 (무시): %s", e)

        logger.info("검증 완료 job_id=%s score=%.2f", job_id, result.get("score", 0))

    except Exception as e:
        logger.error("검증 실패 job_id=%s: %s", job_id, e)
        await update_validation_job(job_id, {
            "status": "failed",
            "result": {"error": str(e)},
        })


async def _save_to_db(
    job_id: str,
    question: str,
    answer: str,
    knowledge_level: str,
    personality: str,
    result: dict,
    corrected: str | None,
) -> None:
    """ai-db validation_job 테이블에 최종 결과를 저장한다."""
    from app.db.postgres import get_conn
    import json
    async with get_conn() as conn:
        await conn.execute(
            """
            INSERT INTO ai.validation_job
              (job_uuid, question, answer, knowledge_level, personality,
               status, score, is_valid, issues, correction_needed,
               suggestion, corrected_answer, completed_at)
            VALUES ($1,$2,$3,$4,$5,'completed',$6,$7,$8::jsonb,$9,$10,$11,NOW())
            ON CONFLICT (job_uuid) DO UPDATE
              SET status=EXCLUDED.status, score=EXCLUDED.score,
                  is_valid=EXCLUDED.is_valid, issues=EXCLUDED.issues,
                  correction_needed=EXCLUDED.correction_needed,
                  suggestion=EXCLUDED.suggestion, corrected_answer=EXCLUDED.corrected_answer,
                  completed_at=EXCLUDED.completed_at
            """,
            job_id,
            question, answer, knowledge_level, personality,
            result.get("score"),
            result.get("is_valid"),
            json.dumps(result.get("issues", []), ensure_ascii=False),
            result.get("correction_needed", False),
            result.get("suggestion", ""),
            corrected,
        )
