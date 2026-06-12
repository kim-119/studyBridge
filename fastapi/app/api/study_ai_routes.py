"""
자료보관함("문서 이해 AI") 기반 12주 × 7일 학습 로드맵.
공부 플래너("학습 실행 관리 AI")와 별도 경로/응답 구조로 유지한다.

  POST /api/ai/roadmap/generate   문서 요약/키워드 기반 12주 × 7일 = 84일 로드맵

action router(study_action_router)로 구조를 강제하고 검증/복구한다.
"""
import asyncio
import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["Study Roadmap AI"])

ROADMAP_TIMEOUT = int(os.getenv("AI_ROADMAP_TIMEOUT_SECONDS", "180"))


async def _generate_roadmap_standard(body: Dict[str, Any]) -> Dict[str, Any]:
    """입력 방어 → 84일 생성 → 표준 스키마/검증/복구. 버튼 클릭 시 최대한 실패하지 않는다."""
    from app.services.study_action_router import (
        build_roadmap_ctx, generate_12week_7day_roadmap,
        finalize_roadmap_response, roadmap_failure_response, validate_roadmap_84,
    )
    ctx = build_roadmap_ctx(body if isinstance(body, dict) else {})
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(generate_12week_7day_roadmap, ctx), timeout=ROADMAP_TIMEOUT
        )
    except asyncio.TimeoutError:
        # 타임아웃에도 빈 응답 금지 — 결정적 84일 스켈레톤으로 재구성
        try:
            result = await asyncio.to_thread(generate_12week_7day_roadmap, {**ctx, "_no_llm": True})
        except Exception as e:  # noqa: BLE001
            logger.error("roadmap/generate 타임아웃 fallback 실패: %s", e)
            return roadmap_failure_response(
                "로드맵 생성에 실패했습니다.", "LLM 타임아웃 후 결정적 fallback 생성 실패",
                "타임아웃 + fallback 실패", error_code="AI_TIMEOUT")
    except Exception as e:  # noqa: BLE001
        logger.error("roadmap/generate 실패: %s", e)
        return roadmap_failure_response(
            "로드맵 생성에 실패했습니다.", "LLM 응답 파싱 실패 또는 84일 구조 검증 실패", str(e)[:120])

    final = finalize_roadmap_response(result)
    if not final["validation"]["passed"]:
        logger.warning("roadmap/generate 검증 실패 → 결정적 재빌드: %s", final["validation"]["reason"])
        try:
            rebuilt = await asyncio.to_thread(generate_12week_7day_roadmap, {**ctx, "_no_llm": True})
            final = finalize_roadmap_response(rebuilt)
        except Exception as e:  # noqa: BLE001
            logger.error("roadmap/generate 재빌드 실패: %s", e)
        if not final["validation"]["passed"]:
            return roadmap_failure_response(
                "로드맵 생성에 실패했습니다.", "84일 구조 검증 실패(재빌드 후에도)",
                final["validation"]["reason"])
    return final


@router.post("/roadmap/generate", summary="문서 기반 12주 × 7일 로드맵 (총 84일)")
async def roadmap_generate(body: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    """자료보관함 PDF 요약/키워드 기반 12주 × 7일 = 84일 로드맵.

    Request: { material_id?, material_title?/title, document_text?/summary?/context?,
               keywords[]?, user_goal?, level?/difficulty?, weeks?, days_per_week? }
    """
    return await _generate_roadmap_standard(body)
