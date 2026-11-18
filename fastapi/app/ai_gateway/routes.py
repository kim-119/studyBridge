"""GET /api/ai/gateway/status — 스케줄러/GPU/브레이커/예산 상태(읽기 전용, 프롬프트·사용자 데이터 없음)."""
from __future__ import annotations

from fastapi import APIRouter

import app.ai_gateway as gw

router = APIRouter(tags=["ai-gateway"])


@router.get("/api/ai/gateway/status")
def gateway_status() -> dict:
    return gw.status()
