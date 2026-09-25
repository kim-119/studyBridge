"""
POST /api/materials/{material_id}/ai/roadmap — 학습 로드맵 생성.

GPT 70% (구조화) + Qwen 30% (표현 보정) 책임 구조.
S3/LLM 실패 시 계약 구조를 유지한 fallback 반환.
Spring Boot 계약 필드명 유지.
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Path

from app.core.security import verify_internal_token
from app.schemas.roadmap_schema import RoadmapRequest, RoadmapResponse, RoadmapWeek

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/materials",
    tags=["Roadmap"],
    dependencies=[Depends(verify_internal_token)],
)

_ROADMAP_TIMEOUT_SECONDS = 30


@router.post(
    "/{material_id}/ai/roadmap",
    response_model=RoadmapResponse,
    summary="자료 기반 학습 로드맵 생성 (GPT 70% + Qwen 30%)",
    description=(
        "S3 PDF 또는 extractedText를 기반으로 주차별 학습 로드맵을 생성한다. "
        "GPT가 구조를 설계하고 Qwen이 표현을 보정한다. "
        "LLM/S3 실패 시 기초-중급-실전 fallback 로드맵을 반환한다."
    ),
)
async def generate_roadmap(
    request: RoadmapRequest,
    material_id: int = Path(..., gt=0),
) -> RoadmapResponse:
    document_title = request.fileName or f"자료 {material_id}"

    # 텍스트 확보 (extractedText 우선, 없으면 S3 로드)
    context = ""
    if request.extractedText and request.extractedText.strip():
        context = request.extractedText.strip()
    elif request.s3Key and request.s3Key.strip():
        try:
            from app.services.s3_pdf_loader import load_text_from_s3_pdf
            context = await asyncio.to_thread(
                load_text_from_s3_pdf,
                request.s3Key,
                document_title,
            )
        except Exception as e:
            logger.warning("S3 PDF 로드 실패 — fallback 사용: %s", type(e).__name__)

    # 로드맵 생성
    try:
        from app.services.roadmap_service import generate_roadmap_from_material
        raw = await asyncio.wait_for(
            asyncio.to_thread(
                generate_roadmap_from_material,
                material_id=material_id,
                document_title=document_title,
                context=context,
                weeks=request.weeks,
                difficulty=request.difficulty,
                goal=request.goal,
                knowledge_level=request.knowledgeLevel,
            ),
            timeout=_ROADMAP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("로드맵 생성 타임아웃 — fallback 반환")
        from app.services.roadmap_service import build_fallback_roadmap
        raw = build_fallback_roadmap(material_id, document_title, "timeout")
    except Exception as e:
        logger.error("로드맵 생성 오류: %s", e)
        from app.services.roadmap_service import build_fallback_roadmap
        raw = build_fallback_roadmap(material_id, document_title, str(e))

    # 스키마 변환
    try:
        weeks_objs = [
            RoadmapWeek(
                week=int(w.get("week", idx + 1)),
                title=str(w.get("title", f"{idx + 1}주차")),
                goal=str(w.get("goal", "")),
                tasks=[str(t) for t in w.get("tasks", [])],
            )
            for idx, w in enumerate(raw.get("weeks", []))
        ]
        if not weeks_objs:
            raise ValueError("weeks 없음")
    except Exception as e:
        logger.warning("weeks 변환 실패 — fallback weeks 사용: %s", e)
        from app.services.roadmap_service import build_fallback_roadmap
        fb = build_fallback_roadmap(material_id, document_title)
        weeks_objs = [RoadmapWeek(**w) for w in fb["weeks"]]
        raw["isFallback"] = True

    return RoadmapResponse(
        materialId=material_id,
        title=raw.get("title", f"{document_title} 학습 로드맵"),
        weeks=weeks_objs,
        isFallback=bool(raw.get("isFallback", False)),
    )
