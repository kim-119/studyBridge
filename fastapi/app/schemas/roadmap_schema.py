"""
학습 로드맵 API 스키마.
POST /api/materials/{material_id}/ai/roadmap — Spring 계약 camelCase 유지.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class RoadmapRequest(BaseModel):
    materialId: int = Field(..., description="자료 ID")
    s3Key: Optional[str] = Field(None, description="S3 오브젝트 키 (없으면 extractedText 사용)")
    fileName: Optional[str] = Field(None, description="원본 파일명")
    extractedText: Optional[str] = Field(None, description="이미 추출된 PDF 텍스트 (s3Key 없을 때)")
    weeks: Optional[int] = Field(None, ge=1, le=24, description="로드맵 주차 수 (기본 자동 결정)")
    difficulty: Optional[str] = Field(None, description="학습 난이도 (easy/medium/hard)")
    goal: Optional[str] = Field(None, description="학습 목표 (선택)")
    knowledgeLevel: Optional[str] = Field(None, description="지식수준 (입문/학사/석사/박사/전문가)")


class RoadmapWeek(BaseModel):
    week: int = Field(..., description="주차")
    title: str = Field(..., description="주차 제목")
    goal: str = Field("", description="주차 학습 목표")
    tasks: List[str] = Field(default_factory=list, description="이번 주 학습 과제")


class RoadmapResponse(BaseModel):
    materialId: int = Field(..., description="자료 ID")
    title: str = Field(..., description="로드맵 제목")
    weeks: List[RoadmapWeek] = Field(..., description="주차별 계획")
    isFallback: bool = Field(False, description="fallback 응답 여부")
