"""
PDF 기반 퀴즈 생성 API 스키마.
POST /api/ai/quiz/generate — Spring Boot 계약 필드명 유지 (camelCase).
"""
from typing import Any, List, Optional, Literal
from pydantic import BaseModel, Field


class QuizGenerateRequest(BaseModel):
    materialId: int = Field(..., description="자료 ID")
    s3Key: str = Field(..., description="S3 오브젝트 키 (경로)")
    fileName: str = Field(..., description="원본 파일명")

    # 난이도 및 지식수준 (선택, 기본값 적용)
    difficulty: Literal["쉬움", "보통", "어려움", "easy", "medium", "normal", "hard"] = Field(
        "보통", description="퀴즈 난이도 (쉬움/보통/어려움)"
    )
    knowledgeLevel: Optional[str] = Field(
        "학사",
        description="사용자 지식수준 (입문/학사/석사/박사/전문가)",
    )
    numQuestions: int = Field(
        3,
        ge=1,
        le=10,
        description="생성할 문항 수 (기본 3, 최대 10)",
    )
    count: Optional[int] = Field(
        None,
        ge=1,
        le=10,
        description="생성할 문항 수 (Spring 옵션 호환 필드, numQuestions보다 우선)",
    )
    questionType: Literal[
        "객관식", "주관식", "혼합",
        "multiple_choice", "short_answer", "mixed",
    ] = Field(
        "객관식",
        description="문항 유형",
    )
    language: str = Field("ko", description="응답 언어 (기본 ko)")
    sourceName: Optional[str] = Field(None, description="자료 표시명 (fileName보다 우선)")
    range: Optional[Any] = Field(None, description="자료 범위 옵션 (현재 PDF 전체 사용, 호환용 수신)")


class QuizQuestion(BaseModel):
    question: str = Field(..., description="문제 내용")
    options: List[str] = Field(default_factory=list, description="객관식 보기")
    correctAnswer: Optional[int] = Field(None, ge=0, le=3, description="객관식 정답 인덱스 (0-based)")
    answer: Optional[str] = Field(None, description="주관식 정답")
    explanation: Optional[str] = Field(None, description="정답 해설")
    questionType: Optional[str] = Field(None, description="문항 유형")
    timeLimitSeconds: int = Field(30, description="제한 시간 (초)")


class QuizGenerateResponse(BaseModel):
    quizTitle: str = Field(..., description="퀴즈 제목")
    questions: List[QuizQuestion] = Field(..., description="퀴즈 문항 목록")
    difficulty: str = Field("보통", description="적용된 난이도")
    knowledgeLevel: str = Field("학사", description="적용된 지식수준")
