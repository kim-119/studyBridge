"""
비동기 멀티에이전트 답변 생성 스키마.
POST /api/ai/multi-chat/async — Spring Boot 계약 필드명 유지 (camelCase).
3명 에이전트가 asyncio.gather()로 병렬 생성한다.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class AsyncAgentProfile(BaseModel):
    agentId: int = Field(..., description="에이전트 ID")
    name: str = Field(..., description="에이전트 표시 이름")
    personality: str = Field("친절_설명형", description="성격 유형")
    knowledgeLevel: str = Field("학사", description="지식 수준")


class MultiAgentAsyncRequest(BaseModel):
    roomId: Optional[int] = Field(None, description="채팅방 ID")
    question: str = Field(..., min_length=1, description="사용자 질문")
    materialId: Optional[int] = Field(None, description="PDF 자료 ID (RAG 검색)")
    agents: List[AsyncAgentProfile] = Field(
        default_factory=list,
        description="참여 에이전트 목록 (비어있으면 기본 3명 사용)",
    )
    delayBetweenDisplayMs: int = Field(700, ge=0, description="에이전트 간 표시 딜레이 (ms)")
    timeoutSecondsPerAgent: int = Field(45, ge=5, le=120, description="에이전트별 타임아웃 (초)")
    enableFeedback: bool = Field(False, description="에이전트 간 피드백 활성화")
    enableFeedbackValidation: bool = Field(True, description="피드백 검증/재작성 활성화")
    shareRagContext: bool = Field(True, description="RAG 컨텍스트를 3명이 공유할지 여부")


class AgentAnswerMetadata(BaseModel):
    knowledgeLevel: str
    personality: str
    usedRag: bool
    latencyMs: int


class AsyncAgentAnswer(BaseModel):
    agentId: int
    agentName: str
    status: str = Field(..., description="SUCCESS | FAILED | TIMEOUT")
    displayOrder: int
    displayDelayMs: int
    answer: str
    metadata: AgentAnswerMetadata


class FeedbackValidationSummary(BaseModel):
    passed: bool
    blockedFeedbackCount: int
    rewrittenFeedbackCount: int


class MultiAgentAsyncResponse(BaseModel):
    status: str = Field(..., description="COMPLETED | PARTIAL_SUCCESS | FAILED")
    question: str
    answers: List[AsyncAgentAnswer]
    feedbacks: List[dict] = Field(default_factory=list)
    validation: FeedbackValidationSummary
