"""
PDF 기반 퀴즈 생성 API 스키마.
POST /api/ai/quiz/generate — Spring Boot 계약 필드명 유지 (camelCase).
"""
from typing import Any, List, Optional, Literal
from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class QuizGenerateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    groupId: Optional[int] = Field(None, validation_alias=AliasChoices("groupId", "group_id"), description="그룹스터디 방 ID")
    materialId: Optional[int] = Field(None, validation_alias=AliasChoices("materialId", "material_id"), description="자료 ID")
    s3Key: Optional[str] = Field(None, validation_alias=AliasChoices("s3Key", "s3_key"), description="S3 오브젝트 키")
    fileUrl: Optional[str] = Field(None, validation_alias=AliasChoices("fileUrl", "file_url"), description="PDF 파일 URL")
    fileName: Optional[str] = Field(None, validation_alias=AliasChoices("fileName", "file_name"), description="원본 파일명")

    difficulty: Literal["쉬움", "보통", "어려움", "easy", "medium", "normal", "hard"] = Field(
        "medium", description="퀴즈 난이도"
    )
    knowledgeLevel: Optional[str] = Field("학사", description="사용자 지식수준")
    numQuestions: Optional[int] = Field(
        None, validation_alias=AliasChoices("numQuestions", "num_questions"), ge=1, le=20, description="생성할 문항 수"
    )
    count: Optional[int] = Field(None, ge=1, le=20, description="생성할 문항 수")
    questionType: Literal[
        "객관식", "주관식", "혼합",
        "multiple_choice", "short_answer", "mixed",
    ] = Field("multiple_choice", validation_alias=AliasChoices("questionType", "question_type"), description="문항 유형")
    language: str = Field("ko", description="응답 언어")
    strictGrounding: bool = Field(True, validation_alias=AliasChoices("strictGrounding", "strict_grounding"), description="PDF 근거 강제 여부")
    sourceName: Optional[str] = Field(None, description="자료 표시명")
    range: Optional[Any] = Field(None, description="자료 범위 옵션")


class QuizQuestion(BaseModel):
    question: str = Field(..., description="문제 내용")
    options: List[str] = Field(default_factory=list, description="객관식 보기")
    correctAnswer: Optional[int] = Field(None, ge=0, le=3, description="객관식 정답 인덱스 (0-based)")
    answer: Optional[str] = Field(None, description="주관식 정답")
    explanation: Optional[str] = Field(None, description="정답 해설")
    questionType: Optional[str] = Field(None, description="문항 유형")
    sourceSnippet: Optional[str] = Field(None, description="PDF 근거 문장 또는 구절")
    timeLimitSeconds: int = Field(30, description="제한 시간 (초)")


class QuizGenerateResponse(BaseModel):
    success: bool = Field(True, description="성공 여부")
    quizTitle: Optional[str] = Field(None, description="퀴즈 제목")
    errorCode: Optional[str] = None
    message: Optional[str] = None
    materialId: Optional[int] = None
    groupId: Optional[int] = None
    fileName: Optional[str] = None
    sourceTextLength: Optional[int] = None
    usedContextLength: Optional[int] = None
    warning: Optional[str] = None
    questions: List[QuizQuestion] = Field(default_factory=list, description="퀴즈 문항 목록")
    difficulty: str = Field("보통", description="적용된 난이도")
    knowledgeLevel: str = Field("학사", description="적용된 지식수준")
