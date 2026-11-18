"""
POST /api/agent/deep-search — Deep Search 파이프라인.
app/api/ 위치의 Spring 계약 라우터.
기존 app/routers/deep_search_router.py와 동일한 endpoint를 제공하되
deep_search_service를 통해 응답을 정규화한다.
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import verify_internal_token
from app.schemas.deep_search_schema import DeepSearchRequest, DeepSearchResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/agent",
    tags=["Deep Search"],
    dependencies=[Depends(verify_internal_token)],
)


@router.post(
    "/deep-search",
    response_model=DeepSearchResponse,
    summary="Deep Search 파이프라인 (RAG + 웹 검색 + LLM)",
    description=(
        "질문 유형에 따라 RAG / Tavily / Wikipedia를 선택적으로 호출하고 "
        "LLM으로 최종 답변을 생성한다. "
        "route, sources, process_logs를 반드시 반환한다."
    ),
)
async def deep_search(request: DeepSearchRequest) -> DeepSearchResponse:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question은 비워둘 수 없습니다.")

    from app.services.deep_search_service import run_deep_search
    result = await asyncio.to_thread(
        run_deep_search,
        question=request.question.strip(),
        material_id=request.material_id,
    )
    return DeepSearchResponse(**result)
