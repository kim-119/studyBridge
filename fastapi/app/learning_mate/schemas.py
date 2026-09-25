"""
학습메이트 요청/응답 schema.

검증 방식 B: mode/tone/learnerLevel은 strict Literal을 쓰지 않고 자유 문자열로 받아
service에서 registry 보정(alias/기본값+로그)한다 → Spring이 라벨/변형 필드를 보내도 깨지지 않음.
Spring 호환: knowledgeLevel/knowledge_level/level → learnerLevel로 흡수(AliasChoices).
"""
from typing import Any, Dict, Optional

from pydantic import AliasChoices, BaseModel, Field


class LearningMatePersona(BaseModel):
    name: str = "돌리"
    tone: str = "friendly"
    # Spring이 knowledgeLevel/level로 보내도 흡수. 응답 라벨은 '학습자 수준' 계열로 통일.
    learnerLevel: str = Field(
        default="beginner",
        validation_alias=AliasChoices("learnerLevel", "knowledgeLevel", "knowledge_level", "level"),
    )
    customInstruction: Optional[str] = ""

    model_config = {"populate_by_name": True, "extra": "ignore"}


class LearningMateChatRequest(BaseModel):
    question: Optional[str] = ""
    mode: str = "explain"
    persona: LearningMatePersona = Field(default_factory=LearningMatePersona)
    previousQuestion: Optional[str] = None
    rewriteInstruction: Optional[str] = None
    quickAction: Optional[str] = None
    advancedOptions: Optional[Dict[str, Any]] = Field(default_factory=dict)

    model_config = {"populate_by_name": True, "extra": "ignore"}


class LearningMateChatResponse(BaseModel):
    question: str
    answer: str
    mode: str
    modeLabel: str
    tone: str
    toneLabel: str
    learnerLevel: str
    learnerLevelLabel: str
    summaryLabel: str
    availableModes: list[str]
    availableQuickActions: list[str]
