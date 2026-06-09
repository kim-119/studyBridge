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
    # group_study_ai 모드용 봇 식별 필드 (선택)
    botType: Optional[str] = Field(
        None,
        description="그룹스터디 AI 봇 타입: summary_bot | quiz_bot | search_bot",
    )
    displayName: Optional[str] = Field(None, description="봇 표시 이름 (요약봇/퀴즈봇/검색봇)")
    modelProvider: Optional[str] = Field(
        None,
        description="모델 제공자: qwen_ollama | openai_gpt | openai_gpt_tavily",
    )


class MultiChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="사용자 메시지")
    mode: str = Field(
        "default",
        description="응답 모드: default | tikitaka | debate | socratic | group_study_ai",
    )
    runMode: Optional[str] = Field(
        None,
        description="group_study_ai 실행 모드: single | all_bots",
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


# ── 1차/2차/3차 생성 과정 (processSteps) ──────────────────────────────────────
# 프론트엔드(StudyMate.jsx extractAgentProcessSteps / ProcessStepsAccordion)와 필드명을
# 정확히 일치시킨다: initialAnswers[].{agentName,answer}, validatedAnswers[].{agentName,answer,score,issues,revised},
# peerFeedback[].{fromAgent,toAgent,feedback}.

class InitialAnswerStep(BaseModel):
    agentName: str
    answer: str
    agentId: Optional[int] = None
    # 카드 표시용 메타데이터 (프론트 ProcessStepsAccordion이 그대로 렌더링)
    personalityType: Optional[str] = None
    knowledgeLevel: Optional[str] = None
    provider: Optional[str] = None
    elapsedMs: Optional[int] = None


class ValidatedAnswerStep(BaseModel):
    agentName: str
    answer: str
    agentId: Optional[int] = None
    score: Optional[float] = None
    issues: List[str] = Field(default_factory=list)
    revised: bool = False
    personalityType: Optional[str] = None
    knowledgeLevel: Optional[str] = None
    provider: Optional[str] = None
    elapsedMs: Optional[int] = None
    # 2차 검증에 사용한 웹 근거 출처 [{title,url,source}] (Tavily/Wikipedia/OpenAlex)
    sources: List[Dict[str, Any]] = Field(default_factory=list)


class PeerFeedbackStep(BaseModel):
    fromAgent: str
    toAgent: str
    feedback: str
    personalityValidation: Optional[Dict[str, Any]] = None
    # 메타데이터: fromAgentId + 피드백 대상 에이전트 ID 목록 + 성격 유형
    fromAgentId: Optional[int] = None
    targetAgentIds: List[int] = Field(default_factory=list)
    personalityType: Optional[str] = None
    provider: Optional[str] = None
    elapsedMs: Optional[int] = None


class PersonalityValidationItem(BaseModel):
    agentName: Optional[str] = None
    personalityType: Optional[str] = None
    score: Optional[float] = None
    passed: Optional[bool] = None
    issues: List[str] = Field(default_factory=list)
    note: Optional[str] = None


class ProcessSteps(BaseModel):
    initialAnswers: List[InitialAnswerStep] = Field(default_factory=list)
    validatedAnswers: List[ValidatedAnswerStep] = Field(default_factory=list)
    peerFeedback: List[PeerFeedbackStep] = Field(default_factory=list)
    personalityValidationSummary: List[PersonalityValidationItem] = Field(default_factory=list)


class StageInfo(BaseModel):
    """프론트가 stages 우선 렌더링할 수 있는 단계별 구조."""
    stage: int
    title: str
    provider: Optional[str] = None
    status: str = "completed"
    elapsedMs: Optional[int] = None
    answers: List[Dict[str, Any]] = Field(default_factory=list)
    feedbacks: List[Dict[str, Any]] = Field(default_factory=list)
    personalityValidationSummary: List[PersonalityValidationItem] = Field(default_factory=list)
    # 2차 단계에서 공유된 웹 근거 출처 [{title,url,source}]
    sources: List[Dict[str, Any]] = Field(default_factory=list)


class MultiChatResponse(BaseModel):
    mode: str = Field(..., description="응답 모드")
    answers: List[AgentAnswer] = Field(..., description="에이전트 답변 목록")
    # v0.7 확장 필드
    status: str = Field("COMPLETED", description="COMPLETED | PARTIAL_SUCCESS | FAILED")
    question: Optional[str] = Field(None, description="원본 질문")
    validation: Optional[ValidationSummary] = Field(None, description="검증 결과")
    feedbacks: List[Dict[str, Any]] = Field(default_factory=list, description="에이전트 간 피드백")
    # 1차/2차/3차 생성 과정 (default 모드에서 생성, Spring이 그대로 패스스루)
    processSteps: Optional[ProcessSteps] = Field(None, description="1차 초안/2차 검증/3차 상호 피드백")
    # 단계별 구조 (provider/elapsedMs 포함, 프론트 stages 우선 렌더링용)
    stages: Optional[List[StageInfo]] = Field(None, description="stage1/2/3 구조 (provider, elapsedMs)")
    # v0.8 debug metadata (debugMetadata=true 요청 시에만 반환)
    debugMetadata: Optional[DebugMetadata] = Field(None, description="debug metadata (관리자용)")
