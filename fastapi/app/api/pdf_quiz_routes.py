"""
PDF/DOCX 자료 본문 기반 퀴즈 생성 라우터 (source_mode = PDF_BASED).

  POST /api/ai/quiz/pdf-generate
    req:  { material_id?, material_title?/title, difficulty(쉬움|보통|어려움|easy|normal|hard),
            count?, document_text?, core_content_text?, detailed_content_text?, summary?,
            keywords?[], generate_admin_quiz? }
    resp: { success, error_code, source_mode=PDF_BASED, document_type, material_id, material_title,
            difficulty_requested, difficulty_applied, difficulty_policy, provider_policy,
            questions[{question, choices[4], correct_answer, explanation, wrong_explanations[],
                       source_trace{...}}], validation{passed, reason} }

이 엔드포인트는 로드맵 day 를 기준으로 만들지 않는다(roadmap_context/ROADMAP_ONLY 강제 없음).
난이도별 모델 비중과 강의계획서(Qwen3B 100%) 분기는 ai07(pdf_quiz_service)에서 처리한다.
"""
import asyncio
import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai/quiz", tags=["PDF Quiz"])

QUIZ_TIMEOUT = int(os.getenv("AI_PDF_QUIZ_TIMEOUT_SECONDS", "90"))


@router.post("/pdf-generate", summary="PDF/DOCX 본문 기반 퀴즈 (난이도별 provider 라우팅)")
async def pdf_quiz_generate(body: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    from app.services.pdf_quiz_service import generate_pdf_quiz

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(generate_pdf_quiz, body), timeout=QUIZ_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("pdf-quiz 타임아웃 → deterministic 재시도")
        try:
            from app.services.pdf_quiz_service import generate_pdf_quiz as _g
            return await asyncio.to_thread(_g, {**body, "_no_llm": True})
        except Exception as e:  # noqa: BLE001
            logger.error("pdf-quiz 타임아웃 복구 실패: %s", e)
            return {"success": False, "error_code": "AI_TIMEOUT",
                    "message": "AI 응답 시간이 초과되었습니다.", "questions": []}
    except Exception as e:  # noqa: BLE001
        logger.error("pdf-quiz 실패: %s", e)
        return {"success": False, "error_code": "QUIZ_GENERATION_FAILED",
                "message": "퀴즈 생성에 실패했습니다.", "questions": []}
    return result
