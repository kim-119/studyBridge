"""
Realtime group-study quiz generation schemas.

Spring calls POST /api/ai/realtime-quiz/generate through the reverse SSH tunnel.
The browser must keep using Spring as the proxy/orchestrator.
"""
from __future__ import annotations

from typing import List, Optional, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


QuestionType = Literal["multiple_choice", "true_false", "short_answer"]
Difficulty = Literal["easy", "medium", "hard"]


class RealtimeQuizGenerateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    group_id: Optional[int] = Field(None, validation_alias=AliasChoices("group_id", "groupId"), description="Group study room id")
    material_id: Optional[int] = Field(None, validation_alias=AliasChoices("material_id", "materialId"), description="Uploaded material id")
    title: Optional[str] = Field(None, description="Source material title")
    text: Optional[str] = Field(None, description="Extracted material text from Spring")
    quiz_count: int = Field(5, validation_alias=AliasChoices("quiz_count", "quizCount", "questionCount", "count", "numQuestions"), ge=1, le=20, description="Number of questions to generate")
    difficulty: str = Field("medium", description="easy | medium | hard")
    question_types: List[str] = Field(
        default_factory=lambda: ["multiple_choice"],
        validation_alias=AliasChoices("question_types", "questionTypes", "types"),
        description="Allowed question types: multiple_choice, true_false, short_answer",
    )


class RealtimeQuizQuestion(BaseModel):
    id: int
    type: str = "multiple_choice"
    question: str
    choices: List[str] = Field(default_factory=list)
    answer: str
    answer_index: Optional[int] = None
    explanation: str
    difficulty: str = "medium"
    source: str = ""


class RealtimeQuizSuccessResponse(BaseModel):
    status: Literal["SUCCESS"] = "SUCCESS"
    quiz_id: Optional[str] = None
    group_id: Optional[int] = None
    material_id: Optional[int] = None
    title: str = "실시간 퀴즈"
    quiz_count: int
    questions: List[RealtimeQuizQuestion]


class RealtimeQuizErrorResponse(BaseModel):
    status: Literal["ERROR"] = "ERROR"
    error_code: str = "QUIZ_GENERATE_FAILED"
    message: str
