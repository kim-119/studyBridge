"""
Deep Search 라우터.
POST /api/agent/deep-search 엔드포인트를 제공한다.
내부 인증 헤더(Authorization: Bearer ...)를 검사한다.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.core.security import verify_internal_token
from app.schemas.deep_search_schema import DeepSearchRequest, DeepSearchResponse
from app.services.answer_orchestrator import run_deep_search_pipeline

router = APIRouter(
    prefix="/api/agent",
    tags=["Deep Search Agent"],
    dependencies=[Depends(verify_internal_token)],
)


@router.post(
    "/deep-search",
    response_model=DeepSearchResponse,
    summary="Deep Search 파이프라인 실행",
    description=(
        "질문 유형을 분류하고 pgvector RAG / Tavily / Wikipedia를 선택적으로 호출한 뒤, "
        "수집된 자료를 Qwen2.5에 전달하여 1차 답변을 생성한다."
    ),
)
async def deep_search(request: DeepSearchRequest):
    """
    사용자 질문을 받아 Deep Search 파이프라인을 실행한다.
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question은 비워둘 수 없습니다.")

    result = run_deep_search_pipeline(
        question=request.question.strip(),
        material_id=request.material_id,
    )

    return DeepSearchResponse(**result)
