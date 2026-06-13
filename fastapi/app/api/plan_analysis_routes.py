"""
AI 계획 분석 / 다음 학습 추천 라우트.

  POST /api/ai/plan-analysis        PDF/플래너 sourceTexts → chunk→문장→행동 체크리스트
  POST /api/ai/plan-recommendation  미완료 item 기반 다음 학습 추천

정책(스펙 [1][9]):
  - 단순 요약/일반 조언 금지. 항상 원문(PDF/플래너) 근거 행동 항목.
  - 실패를 빈 배열로 숨기지 않고 명확한 error code(PLAN_ANALYSIS_*) 로 반환한다.
  - 로그에 requestId/materialId/sourceTextLength/chunkCount/sentenceCount/itemCount/errorReason 기록.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Body

from app.services import plan_analysis_service as plan

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["Plan Analysis"])

_ANALYSIS_TIMEOUT = int(os.getenv("AI_PLAN_ANALYSIS_TIMEOUT_SEC", "60"))


@router.post("/plan-analysis", summary="PDF/플래너 기반 AI 계획 분석 (chunk→문장→행동 체크리스트)")
async def plan_analysis(body: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    request_id = str(body.get("requestId") or uuid.uuid4().hex[:12])
    material_id = body.get("materialId")
    body.setdefault("requestId", request_id)
    started = time.time()

    try:
        r = await asyncio.wait_for(
            asyncio.to_thread(plan.analyze_plan, body), timeout=_ANALYSIS_TIMEOUT)
    except asyncio.TimeoutError:
        # 타임아웃 시에도 빈 결과 금지 — LLM 없이 deterministic 으로 즉시 재시도.
        logger.warning("plan-analysis timeout requestId=%s materialId=%s → deterministic 재시도",
                       request_id, material_id)
        try:
            r = await asyncio.to_thread(plan.analyze_plan, {**body, "_no_llm": True})
        except Exception as e:  # noqa: BLE001
            logger.error("plan-analysis deterministic 복구 실패 requestId=%s errorReason=%s", request_id, e)
            return {"code": "PLAN_ANALYSIS_FAILED", "message": "계획 분석에 실패했습니다.",
                    "meta": {"requestId": request_id, "materialId": material_id}}
    except Exception as e:  # noqa: BLE001
        logger.error("plan-analysis 예외 requestId=%s materialId=%s errorReason=%s",
                     request_id, material_id, e)
        return {"code": "PLAN_ANALYSIS_FAILED", "message": "계획 분석에 실패했습니다.",
                "meta": {"requestId": request_id, "materialId": material_id}}

    # 서비스가 error code 를 반환한 경우(텍스트 없음/계약 위반 등) 그대로 전달.
    if r.get("code"):
        logger.warning("plan-analysis fail requestId=%s materialId=%s code=%s",
                       request_id, material_id, r.get("code"))
        r.setdefault("meta", {})
        r["meta"].setdefault("requestId", request_id)
        r["meta"].setdefault("materialId", material_id)
        return r

    meta = r.get("meta", {})
    logger.info("plan-analysis done requestId=%s materialId=%s sourceTextLength=%s chunkCount=%s "
                "sentenceCount=%s itemCount=%s mode=%s elapsedMs=%s",
                request_id, material_id, meta.get("sourceTextLength"), meta.get("chunkCount"),
                meta.get("sentenceCount"), meta.get("itemCount"), meta.get("mode"),
                int((time.time() - started) * 1000))
    return r


@router.post("/plan-recommendation", summary="미완료 항목 기반 다음 학습 추천")
async def plan_recommendation(body: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    request_id = str(body.get("requestId") or uuid.uuid4().hex[:12])
    material_id = body.get("materialId")
    body.setdefault("requestId", request_id)
    try:
        r = await asyncio.to_thread(plan.recommend_next, body)
    except Exception as e:  # noqa: BLE001
        logger.error("plan-recommendation 예외 requestId=%s materialId=%s errorReason=%s",
                     request_id, material_id, e)
        return {"code": "PLAN_ANALYSIS_FAILED", "message": "다음 학습 추천에 실패했습니다.",
                "meta": {"requestId": request_id, "materialId": material_id}}
    logger.info("plan-recommendation done requestId=%s materialId=%s basisItemCount=%s recCount=%s",
                request_id, material_id, (r.get("meta") or {}).get("basisItemCount"),
                len(r.get("recommendations") or []))
    return r
