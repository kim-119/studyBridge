"""
멀티 에이전트 토론 API 스키마.
POST /api/ai/multi-chat — Spring Boot 계약 필드명 유지 (camelCase).
FastAPI는 동기 REST JSON만 반환한다. SSE는 Spring Boot가 처리한다.

v0.7: mode 분기(tikitaka/debate/socratic) + AgentAnswer 필드 확장.
기존 agentName/answer 필드는 유지하여 하위 호환을 보장한다.
"""
from typing import Any, Dict, List, Optional
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
    role: Optional[str] = Field(
        None,
        description=(
            "모드별 역할 식별자. "
            "debate: supporter|critic|moderator. "
            "socratic: socratic_tutor. "
            "tikitaka/default: 생략 가능."
        ),
    )
    personality: Optional[str] = Field(None, description="성격 유형")
    personalityStrength: Optional[str] = Field(None, description="성격 강도 (mild/moderate/extreme)")
    style: Optional[str] = Field(None, description="말투 스타일")
    tone: Optional[str] = Field(None, description="어조")
    knowledgeLevel: Optional[str] = Field(None, description="지식 수준 (입문/학사/석사/박사/전문가)")
    customInstruction: Optional[str] = Field(None, description="직접 입력 지시사항")


class MultiChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="사용자 메시지")
    mode: str = Field(
        "default",
        description="응답 모드: default | tikitaka | debate | socratic",
    )
    rounds: int = Field(3, ge=1, le=5, description="토론 라운드 수 (tikitaka 모드)")
    showFinalSynthesis: bool = Field(True, description="최종 종합 의견 포함 여부 (default/tikitaka)")
    targetAgentId: Optional[int] = Field(None, description="특정 에이전트 지정 (null이면 전체)")
    previousAnswers: List[PreviousAnswer] = Field(
        default_factory=list, description="이전 대화 맥락 (최대 100개, 실제 사용 최근 20개)"
    )
    agents: List[AgentProfile] = Field(
        default_factory=list, description="참여 에이전트 목록"
    )
    # v0.7 추가 필드
    materialId: Optional[int] = Field(None, description="RAG 자료 ID (materialId 있으면 RAG 검색)")
    userAttempt: Optional[str] = Field(
        None, description="사용자의 시도 답변 (socratic 모드에서 오개념 분석에 사용)"
    )
    knowledgeLevel: Optional[str] = Field(None, description="전역 지식 수준 (에이전트별 미설정 시 사용)")
    enableFeedback: bool = Field(False, description="에이전트 간 피드백 활성화")
    enableFeedbackValidation: bool = Field(True, description="피드백 검증/재작성 활성화")
    # v0.8 추가 필드
    academicDomain: Optional[str] = Field(None, description="학문 도메인 (auto-detect 가능)")
    enableDepthValidation: Optional[bool] = Field(None, description="박사 수준 depth 검증 활성화")
    enableDepthRewrite: Optional[bool] = Field(None, description="박사 수준 depth 재작성 활성화")
    enableExternalSources: Optional[bool] = Field(None, description="외부 소스(Tavily/Wikipedia) 사용")
    debugMetadata: bool = Field(False, description="debug metadata 반환 여부 (관리자용)")


class GenerationConfigMetadata(BaseModel):
    temperature: Optional[float] = None
    topP: Optional[float] = None
    topK: Optional[int] = None
    maxTokens: Optional[int] = None
    reasoningOrThinkingLevel: Optional[str] = None


class RetrievalMetadata(BaseModel):
    usedRag: bool = False
    usedWikipedia: bool = False
    usedTavily: bool = False
    usedOpenAlex: bool = False
    openAlexMinPublicationDate: Optional[str] = None
    openAlexResultCount: Optional[int] = None


class DepthValidationMetadata(BaseModel):
    domainDepthCoverage: Optional[float] = None
    rewriteApplied: bool = False
    sourceLeakageDetected: bool = False
    warningMessage: Optional[str] = None


class PromptingMetadata(BaseModel):
    strategy: Optional[str] = None
    exampleSet: Optional[str] = None


class DebugMetadata(BaseModel):
    domain: Optional[str] = None
    domainConfidence: Optional[float] = None
    requestedKnowledgeLevel: Optional[str] = None
    effectiveKnowledgeLevel: Optional[str] = None
    generationConfig: Optional[GenerationConfigMetadata] = None
    retrieval: Optional[RetrievalMetadata] = None
    prompting: Optional[PromptingMetadata] = None
    depthValidation: Optional[DepthValidationMetadata] = None


class AgentAnswerMetadata(BaseModel):
    knowledgeLevel: Optional[str] = None
    personality: Optional[str] = None
    usedRag: bool = False
    latencyMs: Optional[int] = None
    detectedMisconception: Optional[bool] = None
    directAnswerSuppressed: Optional[bool] = None


class AgentAnswer(BaseModel):
    """에이전트 단일 답변. 하위 호환을 위해 agentName/answer는 필수 유지."""
    agentName: str = Field(..., description="에이전트 이름")
    answer: str = Field(..., description="에이전트 답변")
    # v0.7 확장 필드 (optional — 기존 코드 호환)
    agentId: Optional[int] = Field(None, description="에이전트 ID")
    role: Optional[str] = Field(
        None,
        description="역할: supporter | critic | moderator | socratic_tutor | default",
    )
    speechType: Optional[str] = Field(
        None,
        description=(
            "발화 유형: support_argument | counter_argument | moderation_summary "
            "| follow_up_question | initial_answer | critique | rebuttal_or_refinement"
        ),
    )
    displayOrder: Optional[int] = Field(None, description="표시 순서 (1부터 시작)")
    displayDelayMs: Optional[int] = Field(None, description="표시 딜레이 (ms, Spring 타이핑 연출용)")
    status: str = Field("SUCCESS", description="SUCCESS | FAILED | TIMEOUT | BLOCKED | REWRITTEN | SKIPPED")
    metadata: Optional[AgentAnswerMetadata] = Field(None, description="생성 메타데이터")


class ValidationSummary(BaseModel):
    passed: bool = True
    issues: List[str] = Field(default_factory=list)
    directAnswerBlocked: Optional[bool] = None
    blockedFeedbackCount: int = 0
    rewrittenFeedbackCount: int = 0


class MultiChatResponse(BaseModel):
    mode: str = Field(..., description="응답 모드")
    answers: List[AgentAnswer] = Field(..., description="에이전트 답변 목록")
    # v0.7 확장 필드
    status: str = Field("COMPLETED", description="COMPLETED | PARTIAL_SUCCESS | FAILED")
    question: Optional[str] = Field(None, description="원본 질문")
    validation: Optional[ValidationSummary] = Field(None, description="검증 결과")
    feedbacks: List[Dict[str, Any]] = Field(default_factory=list, description="에이전트 간 피드백")
    # v0.8 debug metadata (debugMetadata=true 요청 시에만 반환)
    debugMetadata: Optional[DebugMetadata] = Field(None, description="debug metadata (관리자용)")
