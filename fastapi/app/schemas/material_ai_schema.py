"""자료보관함 AI 분석 스키마."""
from typing import Any, Optional
from pydantic import BaseModel, Field


class MaterialAnalyzeRequest(BaseModel):
    analyze_type: str = Field(..., description="summary|quiz|roadmap|document_analysis|question_answer")
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
