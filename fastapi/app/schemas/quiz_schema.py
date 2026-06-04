"""
PDF 기반 퀴즈 생성 API 스키마.
POST /api/ai/quiz/generate — Spring Boot 계약 필드명 유지 (camelCase).
"""
from typing import List
from pydantic import BaseModel, Field


class QuizGenerateRequest(BaseModel):
    materialId: int = Field(..., description="자료 ID")
    s3Key: str = Field(..., description="S3 오브젝트 키 (경로)")
    fileName: str = Field(..., description="원본 파일명")


class QuizQuestion(BaseModel):
    question: str = Field(..., description="문제 내용")
    options: List[str] = Field(..., min_length=4, max_length=4, description="4지선다 보기")
    correctAnswer: int = Field(..., ge=0, le=3, description="정답 인덱스 (0-based)")
    timeLimitSeconds: int = Field(30, description="제한 시간 (초)")


class QuizGenerateResponse(BaseModel):
    quizTitle: str = Field(..., description="퀴즈 제목")
    questions: List[QuizQuestion] = Field(..., description="퀴즈 문항 목록")
