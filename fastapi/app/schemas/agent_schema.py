"""에이전트 티키타카 스키마."""
from pydantic import BaseModel, Field


class TikiTakaRequest(BaseModel):
    question: str = Field(..., min_length=1)
    agent_name: str = "자바도우미"
    knowledge_level: str = "학사"
    personality: str = "친절_설명형"
    enable_round2: bool = False


class TikiTakaTurnDTO(BaseModel):
    agent_name: str
    role_description: str
    content: str


class TikiTakaResponse(BaseModel):
    question: str
    dialogue: list[TikiTakaTurnDTO]
    round_count: int
