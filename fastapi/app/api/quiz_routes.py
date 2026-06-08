"""
POST /api/ai/quiz/generate — PDF 기반 객관식 퀴즈 생성.
Spring Boot 계약 endpoint. camelCase 필드명 유지.
difficulty / knowledgeLevel / numQuestions 를 서비스에 전달한다.
S3/LLM 실패 시에도 fallback quiz로 명세 구조를 유지한다.
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException

from app.schemas.quiz_schema import QuizGenerateRequest, QuizGenerateResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["Quiz Generation"])


@router.post(
    "/quiz/generate",
    response_model=QuizGenerateResponse,
    summary="PDF 기반 퀴즈 생성",
    description=(
        "S3에서 PDF를 로드하여 텍스트를 추출하고, LLM으로 4지선다 퀴즈를 생성한다. "
        "difficulty (쉬움/보통/어려움), knowledgeLevel (입문~전문가), "
        "numQuestions (기본 3)를 지원한다. "
        "S3/LLM 실패 시 기본 안내형 퀴즈를 반환한다."
    ),
)
async def generate_quiz(request: QuizGenerateRequest) -> QuizGenerateResponse:
    try:
        from app.services.quiz_generation_service import generate_quiz_from_pdf
        from app.core.config import QUIZ_GENERATION_TIMEOUT_SECONDS
        result = await asyncio.wait_for(
            asyncio.to_thread(
                generate_quiz_from_pdf,
                material_id=request.materialId,
                s3_key=request.s3Key,
                file_name=request.fileName,
                difficulty=request.difficulty,
                knowledge_level=request.knowledgeLevel or "학사",
                num_questions=request.numQuestions,
            ),
            timeout=QUIZ_GENERATION_TIMEOUT_SECONDS,
        )
        return result
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="퀴즈 생성 요청이 시간 초과되었습니다.")
    except Exception as e:
        logger.error("퀴즈 생성 중 예상치 못한 오류: %s", e)
        raise HTTPException(
            status_code=500,
            detail="퀴즈 생성 중 서버 오류가 발생했습니다. 잠시 후 다시 시도하세요.",
        )
