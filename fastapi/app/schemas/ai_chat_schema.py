"""AI 채팅 API 스키마."""
from typing import Optional
from pydantic import BaseModel, Field


class AIChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    agent_id: Optional[int] = None
    agent_name: str = "자바도우미"
    material_id: Optional[int] = None
    knowledge_level: str = "학사"
    personality: str = "친절_설명형"
    custom_instruction: Optional[str] = None
    use_gpt_validation: bool = True


class AIChatResponse(BaseModel):
    answer: str
    validation_job_id: Optional[str] = None
    status: str  # "pending_validation" | "complete" | "no_validation"
    knowledge_level: str                              # 사용자가 선택한 원본 지식수준
    requested_knowledge_level: Optional[str] = None  # 사용자 선택 지식수준 (명시적)
    effective_knowledge_level: Optional[str] = None  # 실제 적용된 지식수준 (일상대화 시 "일상대화")
    personality: str
    intent: Optional[str] = None                     # "learning_question" | "casual_greeting" 등
    process_logs: list[str] = []
