"""
멀티 에이전트 토론 API 스키마.
POST /api/ai/multi-chat — Spring Boot 계약 필드명 유지 (camelCase).
FastAPI는 동기 REST JSON만 반환한다. SSE는 Spring Boot가 처리한다.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class PreviousAnswer(BaseModel):
    agentName: str = Field(..., description="에이전트 이름")
    answer: str = Field(..., description="이전 답변 내용")
    role: str = Field("ASSISTANT", description="역할 (ASSISTANT / USER)")
    agentId: Optional[int] = Field(None, description="에이전트 ID")


class AgentProfile(BaseModel):
    id: Optional[int] = Field(None, description="DB 레코드 ID")
    agentId: Optional[int] = Field(None, description="에이전트 ID")
    name: str = Field(..., description="에이전트 표시 이름")
    role: Optional[str] = Field(None, description="역할 설명 (예: 요약봇)")
    personality: Optional[str] = Field(None, description="성격 유형")
    personalityStrength: Optional[str] = Field(None, description="성격 강도 (mild/moderate/extreme)")
    style: Optional[str] = Field(None, description="말투 스타일")
    tone: Optional[str] = Field(None, description="어조")
    knowledgeLevel: Optional[str] = Field(None, description="지식 수준 (입문/학사/석사/박사/전문가)")
    customInstruction: Optional[str] = Field(None, description="직접 입력 지시사항")


class MultiChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="사용자 메시지")
    mode: str = Field("multi_agent_discussion", description="응답 모드")
    rounds: int = Field(3, ge=1, le=5, description="토론 라운드 수 (최대 5)")
    showFinalSynthesis: bool = Field(True, description="최종 종합 의견 포함 여부")
    targetAgentId: Optional[int] = Field(None, description="특정 에이전트 지정 (null이면 전체)")
    previousAnswers: List[PreviousAnswer] = Field(
        default_factory=list, description="이전 대화 맥락 (최대 100개, 실제 사용 최근 20개)"
    )
    agents: List[AgentProfile] = Field(
        default_factory=list, description="참여 에이전트 목록"
    )


class AgentAnswer(BaseModel):
    agentName: str = Field(..., description="에이전트 이름")
    answer: str = Field(..., description="에이전트 답변")


class MultiChatResponse(BaseModel):
    mode: str = Field(..., description="응답 모드")
    answers: List[AgentAnswer] = Field(..., description="에이전트 답변 목록")
