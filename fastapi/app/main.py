"""
StudyBridge AI 서버 v0.5 진입점.

실행 방법:
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

기존 진입점(fastapi/main.py)은 하위 호환을 위해 그대로 유지한다.
이 파일은 신규 api/ 라우터 + DB/Redis lifespan을 포함한다.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.logging_config import setup_logging
from app.core.config import APP_NAME

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작/종료 시 DB·Redis·임베딩 모델을 초기화/정리한다."""
    # ── 시작 ──────────────────────────────────────────────────────────
    logger.info("%s 기동 중...", APP_NAME)

    # AI DB 연결 풀 초기화 (실패해도 서버 기동 허용)
    try:
        from app.db.postgres import init_pool
        await init_pool()
    except Exception as e:
        logger.warning("AI DB 초기화 실패 (서버는 계속 기동): %s", e)

    # Redis 연결 초기화 (실패해도 서버 기동 허용)
    try:
        from app.db.redis_client import init_redis
        await init_redis()
    except Exception as e:
        logger.warning("Redis 초기화 실패 (degraded 모드): %s", e)

    # 임베딩 모델 워밍업 (실패해도 서버 기동 허용)
    try:
        from app.services.embedding_service import _get_model
        _get_model()
        logger.info("임베딩 모델 워밍업 완료")
    except Exception as e:
        logger.warning("임베딩 모델 워밍업 실패: %s", e)

    logger.info("%s 기동 완료", APP_NAME)
    yield

    # ── 종료 ──────────────────────────────────────────────────────────
    try:
        from app.db.postgres import close_pool
        await close_pool()
    except Exception:
        pass
    try:
        from app.db.redis_client import close_redis
        await close_redis()
    except Exception:
        pass
    logger.info("%s 종료", APP_NAME)


app = FastAPI(
    title=APP_NAME,
    description=(
        "StudyBridge AI Orchestrator v0.5\n\n"
        "- 자료보관함: GPT 70% + Qwen 30% 혼합\n"
        "- 에이전트 채팅: Qwen + Tavily + Wikipedia + GPT 검증\n"
        "- pgvector RAG (ai-db 전용)\n"
        "- 티키타카 멀티에이전트\n"
        "- 학습 후보 자동 수집/검수/JSONL 내보내기"
    ),
    version="0.5.0",
    lifespan=lifespan,
)

# ── 신규 api/ 라우터 ─────────────────────────────────────────────────────────
from app.api.health_routes import router as health_router
from app.api.ai_chat_routes import router as ai_chat_router
from app.api.agent_tikitaka_routes import router as tikitaka_router
from app.api.material_ai_routes import router as material_ai_router
from app.api.rag_routes import router as rag_api_router
from app.api.validation_routes import router as validation_router
from app.api.training_candidate_routes import router as training_router

# Spring Boot 계약 API 라우터 (v0.5)
from app.api.prediction_routes import router as prediction_router
from app.api.quiz_routes import router as quiz_router
from app.api.multi_chat_routes import router as multi_chat_router
from app.api.training_status_routes import router as training_status_router

# 비동기 멀티에이전트 (v0.6)
from app.api.multi_agent_async_routes import router as multi_agent_async_router

# 학습 파이프라인 확장 (v0.6 — [8-2] / [8-3])
from app.api.auto_retrain_routes import router as auto_retrain_router
from app.api.dataset_routes import router as dataset_router

# v0.6 추가 라우터
from app.api.rag_routes import spring_rag_router
from app.api.deep_search_routes import router as deep_search_api_router

app.include_router(health_router)
app.include_router(ai_chat_router)
app.include_router(tikitaka_router)
app.include_router(material_ai_router)
app.include_router(rag_api_router)
app.include_router(validation_router)
app.include_router(training_router)

# Spring Boot 계약 API (v0.5)
app.include_router(prediction_router)       # POST /api/ai/predict/study-time
app.include_router(quiz_router)             # POST /api/ai/quiz/generate
app.include_router(multi_chat_router)       # POST /api/ai/multi-chat
app.include_router(training_status_router)  # GET/POST /api/ai/training/status|readiness-check|...
app.include_router(multi_agent_async_router)  # POST /api/ai/multi-chat/async

# 자동 재학습 + dataset 관리 (v0.6)
app.include_router(auto_retrain_router)     # GET/POST /api/ai/training/auto-retrain/*
app.include_router(dataset_router)          # GET/POST /api/ai/training/datasets/*

# RAG / Deep Search Spring 계약 (v0.6)
app.include_router(spring_rag_router)     # POST /api/rag/ingest, /api/rag/query
app.include_router(deep_search_api_router)  # POST /api/agent/deep-search

# ── 기존 routers/ 라우터 (하위 호환, agent_chat만 로드) ─────────────────────
# deep_search_router → /api/agent/deep-search (deep_search_api_router와 중복, 스킵)
# rag_legacy_router  → /api/rag/ingest, /api/rag/materials/{id} (spring_rag_router와 중복, 스킵)
try:
    from app.routers.agent_chat_router import router as agent_chat_legacy_router
    app.include_router(agent_chat_legacy_router)
    logger.info("agent_chat_router 로드 완료 (하위 호환)")
except Exception as e:
    logger.warning("agent_chat_router 로드 실패 (계속 기동): %s", e)


if __name__ == "__main__":
    import uvicorn
    from app.core.config import FASTAPI_PORT
    uvicorn.run("app.main:app", host="0.0.0.0", port=FASTAPI_PORT, reload=True)
