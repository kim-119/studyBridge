"""
Grounded RAG query endpoint (vector 후보 → cross-encoder rerank → top-3 grounded 답변).

  POST /api/ai/rag/grounded-query

기존 /api/rag/query, /api/materials/{id}/rag/query, /ai/chat, multi-chat 등과는 별개의
신규 additive 경로다. Spring 이 materialId/documentId 소유권을 검증한 뒤 호출한다.
어떤 경우에도 500으로 죽지 않고(success/warnings 포함) 안전 응답을 반환한다.
"""
import asyncio
import logging
import os
import time
from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["RAG Grounded"])

GROUNDED_TIMEOUT = int(os.getenv("AI_RAG_GROUNDED_TIMEOUT_SECONDS", "60"))


class GroundedQueryRequest(BaseModel):
    question: str = ""
    materialId: Optional[Any] = None
    documentId: Optional[Any] = None
    vectorTopK: Optional[int] = None
    rerankTopN: Optional[int] = None
    generateAnswer: bool = True

    model_config = {"extra": "ignore"}


@router.post("/api/ai/rag/grounded-query", summary="Grounded RAG (vector 후보 → rerank → top-3 근거 답변)")
async def grounded_query(req: GroundedQueryRequest):
    if not (req.question or "").strip():
        return JSONResponse(status_code=422, content={
            "success": False, "errorCode": "EMPTY_QUESTION",
            "warnings": ["question 이 비어 있습니다."],
        })

    from app.services.rag_pipeline_service import grounded_rag_query

    started = time.time()
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                grounded_rag_query,
                req.question.strip(),
                req.materialId,
                req.documentId,
                vector_top_k=req.vectorTopK,
                rerank_top_n=req.rerankTopN,
                generate_answer=req.generateAnswer,
            ),
            timeout=GROUNDED_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("[rag-grounded] timeout materialId=%s", req.materialId)
        return JSONResponse(status_code=200, content={
            "success": True, "answer": "",
            "retrieval": {"vectorTopK": req.vectorTopK, "rerankTopN": req.rerankTopN,
                          "candidates": [], "selectedChunks": []},
            "usedContext": {"ragUsed": False, "rerankerUsed": False,
                            "fallbackUsed": True, "selectedChunkCount": 0},
            "warnings": ["RAG 처리 timeout 으로 fallback 빈 응답을 반환했습니다."],
        })
    except Exception as e:  # noqa: BLE001
        logger.error("[rag-grounded] 실패 materialId=%s: %s", req.materialId, e, exc_info=True)
        return JSONResponse(status_code=200, content={
            "success": False, "errorCode": "RAG_GROUNDED_FAILED",
            "warnings": [f"처리 중 오류가 발생했습니다: {type(e).__name__}"],
        })

    elapsed = int((time.time() - started) * 1000)
    uc = result.get("usedContext", {})
    logger.info("[rag-grounded] materialId=%s rerankerUsed=%s fallbackUsed=%s selected=%s elapsedMs=%d",
                req.materialId, uc.get("rerankerUsed"), uc.get("fallbackUsed"),
                uc.get("selectedChunkCount"), elapsed)
    return JSONResponse(status_code=200, content=result)
