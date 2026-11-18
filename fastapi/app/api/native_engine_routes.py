"""
C Native Engine 테스트/사용 엔드포인트 — 항상 활성화(feature flag 없음).

  GET  /api/native-engine/health    스케줄러/텍스트prep 가용성
  POST /api/native-engine/schedule  학습 시간 배분(C-native, 실패 시 python-fallback)
  POST /api/native-engine/textprep  PDF 텍스트 정규화 + 청크 분할

보안: 파일 경로/URL/shell 입력 없음. 입력은 숫자·문자열만. 크기 한도는 pydantic 으로 방어.
C 실패는 500 이 아니라 fallback 200. validation 실패만 422.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/native-engine", tags=["native-engine"])

# 입력 한도 (코드 레벨 방어)
_MAX_SUBJECTS = 20
_MAX_TOPICS = 50
_MAX_NAME = 100
_MAX_TEXT_BYTES = 2 * 1024 * 1024  # 2MB


# ── 요청 모델 (pydantic v2) ───────────────────────────────────────────
class SubjectInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=_MAX_NAME)
    topics: List[str] = Field(default_factory=list, max_length=_MAX_TOPICS)
    priority: int = Field(..., ge=1, le=5)
    weakness: int = Field(..., ge=1, le=5)
    exam_weight: int = Field(..., ge=1, le=5)

    @field_validator("topics")
    @classmethod
    def _check_topics(cls, v: List[str]) -> List[str]:
        cleaned = [str(t)[:_MAX_NAME] for t in (v or []) if str(t).strip()]
        return cleaned[:_MAX_TOPICS]


class ScheduleRequest(BaseModel):
    daily_minutes: int = Field(..., ge=30, le=720)
    days: int = Field(..., ge=1, le=30)
    subjects: List[SubjectInput] = Field(..., min_length=1, max_length=_MAX_SUBJECTS)


class TextPrepRequest(BaseModel):
    text: str = Field(..., min_length=1)
    chunk_size: int = Field(800, ge=200, le=3000)
    overlap: int = Field(120, ge=0)

    @field_validator("text")
    @classmethod
    def _check_text_size(cls, v: str) -> str:
        if len(v.encode("utf-8")) > _MAX_TEXT_BYTES:
            raise ValueError("text 가 2MB 한도를 초과했습니다.")
        return v

    @model_validator(mode="after")
    def _check_overlap(self) -> "TextPrepRequest":
        if self.overlap > self.chunk_size // 2:
            raise ValueError("overlap 은 chunk_size//2 이하여야 합니다.")
        return self


# ── 엔드포인트 ────────────────────────────────────────────────────────
@router.get("/health", summary="Native Engine 가용성")
def native_health() -> Dict[str, Any]:
    from app.services.native_scheduler import scheduler_health
    from app.services.native_textprep import textprep_health
    return {"ok": True, "scheduler": scheduler_health(), "textprep": textprep_health()}


@router.post("/schedule", summary="학습 시간 배분 (C-native / python-fallback)")
def native_schedule(req: ScheduleRequest) -> Dict[str, Any]:
    from app.services.native_scheduler import optimize_schedule
    return optimize_schedule(req.model_dump())


@router.post("/textprep", summary="PDF 텍스트 정규화 + 청크 분할 (C-native / python-fallback)")
def native_textprep(req: TextPrepRequest) -> Dict[str, Any]:
    from app.services.native_textprep import preprocess_and_chunk
    return preprocess_and_chunk(req.text, req.chunk_size, req.overlap)
