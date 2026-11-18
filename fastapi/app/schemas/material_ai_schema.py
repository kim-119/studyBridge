"""자료보관함 AI 분석 스키마."""
from typing import Any, Optional
from pydantic import BaseModel, Field


class MaterialAnalyzeRequest(BaseModel):
    analyze_type: str = Field(..., description="summary|quiz|roadmap|document_analysis|question_answer")
    # 자료 타입. PLANNER/ROADMAP 등 구조화 자료는 PDF 분석 대상이 아니다(있으면 가드에 사용).
    material_type: Optional[str] = None
    text: Optional[str] = None
    document_title: Optional[str] = None
    question: Optional[str] = None
    knowledge_level: str = "학사"
    personality: str = "친절_설명형"
    agent_name: str = "자료봇"
    num_questions: Optional[int] = Field(5, ge=1, le=20)


class MaterialAnalyzeResponse(BaseModel):
    material_id: int
    analyze_type: str
    result: str
    metadata: dict[str, Any] = {}
