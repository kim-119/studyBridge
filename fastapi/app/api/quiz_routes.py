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
        "strictGrounding=true이면 S3/PDF/검증 실패 시 일반 fallback 퀴즈를 반환하지 않는다."
    ),
)
async def generate_quiz(request: QuizGenerateRequest) -> QuizGenerateResponse:
    if request.materialId is None:
        raise HTTPException(status_code=400, detail="materialId는 필수입니다.")
    if not (request.s3Key or request.fileUrl):
        raise HTTPException(status_code=400, detail="s3Key 또는 fileUrl 중 하나는 필수입니다.")
    try:
        from app.services.quiz_generation_service import generate_quiz_from_pdf
        from app.core.config import QUIZ_GENERATION_TIMEOUT_SECONDS
        result = await asyncio.wait_for(
            asyncio.to_thread(
                generate_quiz_from_pdf,
                material_id=request.materialId,
                s3_key=request.s3Key or "",
                file_name=request.sourceName or request.fileName or "PDF",
                difficulty=request.difficulty,
                knowledge_level=request.knowledgeLevel or "학사",
                num_questions=request.count or request.numQuestions or 5,
                question_type=request.questionType,
                language=request.language or "ko",
                group_id=request.groupId,
                file_url=request.fileUrl,
                strict_grounding=True if request.strictGrounding is None else bool(request.strictGrounding),
            ),
            timeout=QUIZ_GENERATION_TIMEOUT_SECONDS,
        )
        return result
    except asyncio.TimeoutError:
        return QuizGenerateResponse(
            success=False,
            errorCode="QUIZ_GENERATE_TIMEOUT",
            message="퀴즈 생성 요청이 시간 초과되었습니다.",
            materialId=request.materialId,
            groupId=request.groupId,
            fileName=request.fileName,
            questions=[],
        )
    except Exception as e:
        logger.error("퀴즈 생성 중 예상치 못한 오류: %s", e)
        return QuizGenerateResponse(
            success=False,
            errorCode="QUIZ_GENERATE_FAILED",
            message="퀴즈 생성 중 서버 오류가 발생했습니다.",
            materialId=request.materialId,
            groupId=request.groupId,
            fileName=request.fileName,
            questions=[],
        )
