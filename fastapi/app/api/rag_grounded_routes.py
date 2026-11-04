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

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.security import verify_internal_token

logger = logging.getLogger(__name__)
# 내부 인증 필수(fail-closed). Spring 호출자는 아직 없다(2026-11-04 backend grep 기준).
from app.core.request_guards import limited_route_class

router = APIRouter(tags=["RAG Grounded"], dependencies=[Depends(verify_internal_token)],
                   route_class=limited_route_class(64 * 1024))   # 예전: 본문 크기 제한 없음(2.1MB 수용)

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
async def grounded_query(req: GroundedQueryRequest,
                         x_ai_scope: Optional[str] = Header(default=None, alias="X-AI-Scope"),
                         x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    if not (req.question or "").strip():
        return JSONResponse(status_code=422, content={
            "success": False, "errorCode": "EMPTY_QUESTION",
            "warnings": ["question 이 비어 있습니다."],
        })
    # 사용자 자료 범위 밖 pgvector 검색 금지: materialId 필수 + 서명된 scope 안에 있어야 한다.
    # (예전: materialId 가 없으면 전체 검색, documentId 를 materialId 로 간주)
    # scope 토큰은 이 요청의 X-Request-Id 에 묶여 있어야 한다(예전: rid 미검사 → TTL 600s 안 재사용 가능).
    from app.contracts.signing import SignatureError, verify_request_scope
    try:
        mid = int(req.materialId) if req.materialId is not None else None
        scope = verify_request_scope(x_ai_scope, x_request_id)
    except (TypeError, ValueError):
        return JSONResponse(status_code=422, content={"success": False, "errorCode": "MATERIAL_ID_INVALID"})
    except SignatureError as e:
        return JSONResponse(status_code=403, content={"success": False, "errorCode": f"SCOPE_UNVERIFIED:{e.code}"})
    if mid is None or not scope.allows_material(mid):
        return JSONResponse(status_code=403, content={"success": False, "errorCode": "SCOPE_MISMATCH"})

    from app.services.rag_pipeline_service import grounded_rag_query

    started = time.time()
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                grounded_rag_query,
                req.question.strip(),
                mid,
                None,
                vector_top_k=req.vectorTopK,
                rerank_top_n=req.rerankTopN,
                generate_answer=req.generateAnswer,
            ),
            timeout=GROUNDED_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("[rag-grounded] timeout materialId=%s", req.materialId)
        # 예전: success:true + 빈 answer(정상으로 오인 가능) → 실패로 명시한다.
        return JSONResponse(status_code=200, content={
            "success": False, "errorCode": "RAG_GROUNDED_TIMEOUT", "answer": "",
            "qualityStatus": "VALIDATION_ERROR",
            "retrieval": {"vectorTopK": req.vectorTopK, "rerankTopN": req.rerankTopN,
                          "candidates": [], "selectedChunks": []},
            "usedContext": {"ragUsed": False, "rerankerUsed": False,
                            "fallbackUsed": True, "selectedChunkCount": 0},
            "warnings": ["RAG 처리 timeout 으로 답변을 생성하지 못했습니다."],
        })
    except Exception as e:  # noqa: BLE001
        # 예외 문자열/트레이스백에는 질문·청크 원문이 섞일 수 있어 클래스명만 남긴다.
        logger.error("[rag-grounded] 실패 materialId=%s: %s", req.materialId, type(e).__name__)
        return JSONResponse(status_code=200, content={
            "success": False, "errorCode": "RAG_GROUNDED_FAILED", "qualityStatus": "VALIDATION_ERROR",
            "warnings": ["처리 중 오류가 발생했습니다."],
        })

    elapsed = int((time.time() - started) * 1000)
    uc = result.get("usedContext", {})
    logger.info("[rag-grounded] materialId=%s rerankerUsed=%s fallbackUsed=%s selected=%s elapsedMs=%d",
                req.materialId, uc.get("rerankerUsed"), uc.get("fallbackUsed"),
                uc.get("selectedChunkCount"), elapsed)
    result.setdefault("qualityStatus", "NOT_EVALUATED")
    return JSONResponse(status_code=200, content=result)
