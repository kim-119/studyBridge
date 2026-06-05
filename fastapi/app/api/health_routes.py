"""
GET /api/health        — 빠른 상태 확인 (환경변수 존재 여부만)
GET /api/ai/health     — 상세 연결 검증 (DB/pgvector/임베딩/Ollama 실제 확인)

Spring Boot 계약 필드(openaiConfigured 등)는 /api/health 에 유지한다.
/api/ai/health 는 캡스톤 시연용 상세 진단 엔드포인트다.

주의: 어떤 항목이 실패해도 서버가 죽지 않도록 모든 체크는 try/except로 보호한다.
DB 접속 정보·secret·API key는 응답에 절대 노출하지 않는다.
"""
import logging
import os

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Health"])


@router.get("/health", summary="서버 상태 확인 (환경변수 기반)")
async def health_check():
    """환경변수 존재 여부 기반으로 설정 상태를 반환한다."""
    from app.core.config import (
        OPENAI_API_KEY,
        TAVILY_API_KEY,
        OLLAMA_BASE_URL,
        AWS_ACCESS_KEY_ID,
        AWS_SECRET_ACCESS_KEY,
        AWS_S3_BUCKET,
    )
    return {
        "status": "ok",
        "service": "studybridge-fastapi",
        "openaiConfigured": bool(OPENAI_API_KEY),
        "ollamaConfigured": bool(OLLAMA_BASE_URL),
        "tavilyConfigured": bool(TAVILY_API_KEY),
        "awsConfigured": bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_S3_BUCKET),
    }


@router.get("/ai/health", summary="상세 연결 검증 (DB·pgvector·임베딩·Ollama)")
async def ai_health_check():
    """
    실제 연결을 시도하여 각 컴포넌트의 상태를 확인한다.
    응답 body에 secret은 절대 포함하지 않는다.
    status: ok | degraded | unhealthy
    각 check 항목: {"status": "ok"|"fail"|"unknown"|"configured", "message": str}
    """
    from app.core.config import (
        OPENAI_API_KEY,
        OLLAMA_BASE_URL,
        VECTOR_DATABASE_URL,
        REDIS_URL,
        EMBEDDING_MODEL_NAME,
    )

    checks: dict[str, dict] = {}

    # 1) PostgreSQL + pgvector 연결
    db_result = _check_database(VECTOR_DATABASE_URL)
    checks["database"] = db_result

    # 2) pgvector extension
    if db_result["status"] == "ok":
        checks["pgvector"] = _check_pgvector_extension(VECTOR_DATABASE_URL)
    else:
        checks["pgvector"] = {"status": "unknown", "message": "DB 연결 실패로 확인 불가"}

    # 3) ai.document_chunks 테이블
    if db_result["status"] == "ok":
        checks["documentChunksTable"] = _check_document_chunks_table(VECTOR_DATABASE_URL)
    else:
        checks["documentChunksTable"] = {"status": "unknown", "message": "DB 연결 실패로 확인 불가"}

    # 4) ai.training_candidate 테이블
    if db_result["status"] == "ok":
        checks["trainingCandidateTable"] = _check_training_candidate_table(VECTOR_DATABASE_URL)
    else:
        checks["trainingCandidateTable"] = {"status": "unknown", "message": "DB 연결 실패로 확인 불가"}

    # 5) 임베딩 모델 로드 여부
    checks["embeddingModel"] = _check_embedding_model()

    # 6) Ollama 서버 응답
    checks["ollama"] = await _check_ollama(OLLAMA_BASE_URL)

    # 7) OpenAI 키 설정 여부 (실제 호출 없음)
    checks["openai"] = (
        {"status": "configured", "message": "API 키 설정됨"}
        if OPENAI_API_KEY
        else {"status": "not_configured", "message": "OPENAI_API_KEY 미설정 (optional)"}
    )

    # 8) Redis (설정된 경우만)
    if REDIS_URL:
        checks["redis"] = await _check_redis(REDIS_URL)

    # overall status 계산
    fail_count = sum(1 for v in checks.values() if v.get("status") == "fail")
    ok_count = sum(
        1 for v in checks.values()
        if v.get("status") in ("ok", "configured")
    )

    if fail_count == 0:
        overall = "ok"
    elif ok_count == 0:
        overall = "unhealthy"
    else:
        overall = "degraded"

    return {"status": overall, "checks": checks}


# ── 체크 헬퍼 함수 (각각 {"status": str, "message": str} 반환) ───────────────

def _check_database(db_url: str | None) -> dict:
    if not db_url:
        return {"status": "fail", "message": "AI_DATABASE_URL / VECTOR_DATABASE_URL 미설정"}
    try:
        import psycopg
        with psycopg.connect(db_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return {"status": "ok", "message": "PostgreSQL 연결 성공"}
    except Exception as e:
        logger.debug("DB 연결 실패: %s", e)
        return {"status": "fail", "message": f"DB 연결 실패 ({type(e).__name__})"}


def _check_pgvector_extension(db_url: str | None) -> dict:
    if not db_url:
        return {"status": "fail", "message": "DB URL 미설정"}
    try:
        import psycopg
        with psycopg.connect(db_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT installed_version FROM pg_available_extensions WHERE name='vector'"
                )
                row = cur.fetchone()
                if row and row[0]:
                    return {"status": "ok", "message": f"pgvector {row[0]} 설치됨"}
                return {"status": "fail", "message": "pgvector extension 미설치"}
    except Exception as e:
        logger.debug("pgvector 확인 실패: %s", e)
        return {"status": "fail", "message": f"pgvector 확인 실패 ({type(e).__name__})"}


def _check_document_chunks_table(db_url: str | None) -> dict:
    if not db_url:
        return {"status": "fail", "message": "DB URL 미설정"}
    try:
        import psycopg
        with psycopg.connect(db_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('ai.document_chunks')")
                row = cur.fetchone()
                if row and row[0]:
                    return {"status": "ok", "message": "ai.document_chunks 테이블 존재"}
                return {"status": "fail", "message": "ai.document_chunks 테이블 없음"}
    except Exception as e:
        logger.debug("document_chunks 테이블 확인 실패: %s", e)
        return {"status": "fail", "message": f"테이블 확인 실패 ({type(e).__name__})"}


def _check_training_candidate_table(db_url: str | None) -> dict:
    if not db_url:
        return {"status": "fail", "message": "DB URL 미설정"}
    try:
        import psycopg
        with psycopg.connect(db_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('ai.training_candidate')")
                row = cur.fetchone()
                if row and row[0]:
                    return {"status": "ok", "message": "ai.training_candidate 테이블 존재"}
                return {"status": "fail", "message": "ai.training_candidate 테이블 없음"}
    except Exception as e:
        logger.debug("training_candidate 테이블 확인 실패: %s", e)
        return {"status": "fail", "message": f"테이블 확인 실패 ({type(e).__name__})"}


def _check_embedding_model() -> dict:
    try:
        from app.services.embedding_service import _get_model
        model = _get_model()
        if model is not None:
            return {"status": "ok", "message": "임베딩 모델 로드됨"}
        return {"status": "fail", "message": "임베딩 모델이 None"}
    except Exception as e:
        logger.debug("임베딩 모델 확인 실패: %s", e)
        return {"status": "fail", "message": f"임베딩 모델 로드 실패 ({type(e).__name__})"}


async def _check_ollama(ollama_url: str) -> dict:
    try:
        import asyncio
        import urllib.request
        def _ping():
            req = urllib.request.Request(f"{ollama_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        result = await asyncio.to_thread(_ping)
        if result:
            return {"status": "ok", "message": f"Ollama 응답 정상 ({ollama_url})"}
        return {"status": "fail", "message": "Ollama 응답 코드 비정상"}
    except Exception as e:
        logger.debug("Ollama 연결 실패: %s", e)
        return {"status": "fail", "message": f"Ollama 연결 실패 ({type(e).__name__})"}


async def _check_redis(redis_url: str) -> dict:
    try:
        import asyncio
        import redis as redis_lib
        def _ping():
            r = redis_lib.from_url(redis_url, socket_connect_timeout=3)
            return r.ping()
        result = await asyncio.to_thread(_ping)
        if result:
            return {"status": "ok", "message": "Redis PING 성공"}
        return {"status": "fail", "message": "Redis PING false 반환"}
    except Exception as e:
        logger.debug("Redis 연결 실패: %s", e)
        return {"status": "fail", "message": f"Redis 연결 실패 ({type(e).__name__})"}
