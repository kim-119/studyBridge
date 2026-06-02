"""
StudyBridge AI 서버 진입점.
FastAPI 앱을 생성하고 라우터를 등록한다.
"""
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from app.routers.deep_search_router import router as deep_search_router
from app.routers.rag_router import router as rag_router
from app.routers.agent_chat_router import router as agent_chat_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    서버 시작 시 임베딩 모델을 미리 로드한다.
    첫 요청 지연(cold start) 방지 목적.
    """
    try:
        from app.services.embedding_service import _get_model
        _get_model()
        logger.info("임베딩 모델 로드 완료")
    except Exception as e:
        # 모델 로드 실패해도 서버 기동은 허용 (임베딩 호출 시 재시도)
        logger.warning(f"임베딩 모델 워밍업 실패 (서버는 계속 기동): {e}")

    yield  # 서버 실행 중

    logger.info("StudyBridge AI 서버 종료")


app = FastAPI(
    title="StudyBridge AI Server",
    description=(
        "StudyBridge 캡스톤 프로젝트 AI Orchestrator. "
        "자료보관함(GPT 70%+Qwen 30%) + 에이전트 채팅(Qwen+Tavily+Wikipedia+GPT 검증) "
        "+ pgvector RAG + 티키타카 + 지식수준별/성격별 답변 차등화"
    ),
    version="0.4.0",
    lifespan=lifespan,
)


# ── 헬스 체크 ────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"])
async def health_check():
    """서버 정상 동작 여부를 확인한다. 인증 불필요."""
    return {"status": "ok", "service": "StudyBridge AI Server", "version": "0.4.0"}


# ── 라우터 등록 ──────────────────────────────────────────────────────
app.include_router(deep_search_router)
app.include_router(rag_router)
app.include_router(agent_chat_router)   # v0.4: 에이전트 채팅 + 자료보관함 AI


# ── 직접 실행 시 (개발용) ─────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
