"""
멀티 에이전트 토론 API 스키마.
POST /api/ai/multi-chat — Spring Boot 계약 필드명 유지 (camelCase).
FastAPI는 동기 REST JSON만 반환한다. SSE는 Spring Boot가 처리한다.

v0.7: mode 분기(tikitaka/debate/socratic) + AgentAnswer 필드 확장.
기존 agentName/answer 필드는 유지하여 하위 호환을 보장한다.
"""
from typing import Any, Dict, List, Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class PreviousAnswer(BaseModel):
    agentName: str = Field(..., description="에이전트 이름")
    answer: str = Field(..., description="이전 답변 내용")
    role: str = Field("ASSISTANT", description="역할 (ASSISTANT / USER)")
    agentId: Optional[Any] = Field(None, description="에이전트 ID")
    processSteps: Optional[Dict[str, Any]] = Field(None, description="영속화된 구조화 처리 단계")


class AgentProfile(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: Optional[Any] = Field(None, description="DB 레코드 ID")
    agentId: Optional[Any] = Field(None, validation_alias=AliasChoices("agentId", "agent_id", "id"), description="에이전트 ID")
    name: str = Field("에이전트", validation_alias=AliasChoices("name", "agentName", "agent_name", "displayName"), description="에이전트 표시 이름")
    role: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("role", "agentRole", "agent_role"),
        description=(
            "모드별 역할 식별자. "
            "debate: supporter|critic|moderator. "
            "socratic: socratic_tutor. "
            "tikitaka/default: 생략 가능."
        ),
    )
    personality: Optional[str] = Field(None, validation_alias=AliasChoices("personality", "persona", "type"), description="성격 유형")
    personalityLabel: Optional[str] = Field(None, validation_alias=AliasChoices("personalityLabel", "personality_label"), description="성격 표시명")
    personalityStrength: Optional[str] = Field(None, validation_alias=AliasChoices("personalityStrength", "personality_strength"), description="성격 강도 (mild/moderate/extreme)")
    # 에이전트 역할/성격 프리셋 (learningMode와 별개). expert_professor/misconception_tracker 등.
    agentPreset: Optional[str] = Field(None, description="에이전트 프리셋 식별자")
    style: Optional[str] = Field(None, description="말투 스타일")
    tone: Optional[str] = Field(None, description="어조")
    knowledgeLevel: Optional[str] = Field(None, validation_alias=AliasChoices("knowledgeLevel", "knowledge_level", "level"), description="지식 수준 (입문/학사/석사/박사/전문가)")
    knowledgeLevelLabel: Optional[str] = Field(None, validation_alias=AliasChoices("knowledgeLevelLabel", "knowledge_level_label"), description="지식 수준 표시명")
    answerDepth: Optional[str] = Field(None, validation_alias=AliasChoices("answerDepth", "answer_depth", "depth"), description="답변 깊이 (basic/normal/deep/max). 미설정 시 지식수준에서 추정")
    customInstruction: Optional[str] = Field(None, validation_alias=AliasChoices("customInstruction", "custom_instruction"), description="직접 입력 지시사항")
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


class DebateConfig(BaseModel):
    """토론 모드 논제/구조 설정. 프론트 → Spring → FastAPI로 유실 없이 전달된다."""
    topicMode: Optional[str] = Field("auto", description="auto | manual")
    manualTopic: Optional[str] = Field(None, description="직접 입력 논제 (topicMode=manual)")
    motionType: Optional[str] = Field("learning_strategy", description="논제 유형")
    stancePolicy: Optional[str] = Field("agent1_con_agent2_pro_agent3_neutral", description="역할 배정 정책")
    issueAxes: List[str] = Field(default_factory=list, description="쟁점 축")
    debateDepth: Optional[str] = Field("normal", description="light | normal | deep")
    debateStyle: Optional[str] = Field("academic_practical", description="토론 스타일")
    includeExamples: bool = Field(True, description="예시 포함")
    includeCounterexamples: bool = Field(True, description="반례 포함")
    includeStudyPlan: bool = Field(True, description="학습 방향 포함")
    judgeCriteria: List[str] = Field(default_factory=list, description="판정 기준")
    outputStages: List[str] = Field(default_factory=list, description="생성할 토론 단계 키 목록")


class SocraticConfig(BaseModel):
    """소크라테스 문답 학습 설정. 프론트 → Spring → FastAPI로 유실 없이 전달된다."""
    goal: Optional[str] = "concept_understanding"
    diagnosisMode: Optional[str] = "quick"
    questionIntensity: Optional[str] = "normal"
    hintPolicy: Optional[str] = "step_by_step"
    answerRevealPolicy: Optional[str] = "final_only"
    questionTypes: List[str] = Field(default_factory=list)
    progressFlow: List[str] = Field(default_factory=list)
    feedbackStyle: Optional[str] = "concept_check"
    maxQuestionsPerTurn: int = 3
    requireUserAnswerFirst: bool = True
    includeExamples: bool = True
    includeCounterexamples: bool = True
    includeFinalSummary: bool = True
    includeNextStudyPlan: bool = True
    trackMisconceptions: bool = True


class SocraticStep(BaseModel):
    """소크라테스 문답의 단일 단계. 채팅/마인드맵/SSE/history가 공통으로 사용한다."""
    stageType: str = Field(..., description="DIAGNOSIS|CORE_CONCEPT|MISCONCEPTION_CHECK|HINT|APPLICATION|COUNTEREXAMPLE|SELF_EXPLANATION|SUMMARY|NEXT_STUDY_PLAN")
    stageTitle: str = Field(..., description="화면 표시 제목")
    role: Optional[str] = Field(None, description="질문자 | 오개념 추적자 | 정리자")
    agentIndex: Optional[int] = Field(None, description="1=질문자 2=오개념추적자 3=정리자")
    agentName: Optional[str] = None
    question: Optional[str] = None
    hint: Optional[str] = None
    feedback: Optional[str] = None
    expectedConcept: Optional[str] = None
    misconceptionDetected: Optional[bool] = None
    misconception: Optional[str] = None
    directAnswerSuppressed: bool = True
    content: Optional[str] = None


class SimulationConfig(BaseModel):
    """상황극 학습 설정. 사용자를 개념이 작동하는 가상 상황 속 참가자로 넣는다."""
    scenarioType: Optional[str] = "realistic"
    domain: Optional[str] = "auto"
    interactionStyle: Optional[str] = "choice_based"
    difficulty: Optional[str] = "normal"
    userRoleMode: Optional[str] = "auto"
    choiceCount: int = 3
    includeChoices: bool = True
    includeConsequences: bool = True
    includeConceptMapping: bool = True
    includeMisconceptionTrap: bool = True
    includeReflectionQuestion: bool = True
    includeNextScenario: bool = True
    simulationDepth: Optional[str] = "normal"
    outputStages: List[str] = Field(default_factory=list)


class SimulationChoice(BaseModel):
    choiceId: str
    label: str
    # text는 기존(스테이지형) 프론트 호환 필드. 분기형에서는 label과 동일하게 채운다.
    text: Optional[str] = None
    expectedConsequence: Optional[str] = None
    conceptLink: Optional[str] = None
    misconceptionRisk: Optional[str] = None
    # 분기형 상황극(미연시/비주얼 노벨) 확장 필드 (additive)
    action: Optional[str] = Field(None, description="선택 시 사용자가 취하는 구체 행동")
    expectedSkill: Optional[str] = Field(None, description="이 선택이 훈련하는 학습 기능")
    riskLevel: Optional[str] = Field(None, description="low | medium | high")


class SimulationNpc(BaseModel):
    """분기형 상황극의 상대 인물(교수/면접관/동료 등)."""
    name: Optional[str] = None
    role: Optional[str] = None
    emotion: Optional[str] = None


class SimulationLearningFeedback(BaseModel):
    """ENDING 단계의 학습 피드백."""
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    nextStudy: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    finalScore: Optional[int] = None


class SimulationStage(BaseModel):
    stageType: str
    stageTitle: str
    role: Optional[str] = None
    agentIndex: Optional[int] = None
    agentName: Optional[str] = None
    content: Optional[str] = None
    userRole: Optional[str] = None
    choices: List[SimulationChoice] = Field(default_factory=list)
    selectedChoiceId: Optional[str] = None
    consequence: Optional[str] = None
    conceptMapping: List[str] = Field(default_factory=list)
    misconceptionTrap: Optional[str] = None
    reflectionQuestion: Optional[str] = None
    nextScenarioPrompt: Optional[str] = None


class DebateStage(BaseModel):
    """구조화 토론의 단일 단계. 채팅/마인드맵/SSE/history가 공통으로 사용한다."""
    stageType: str = Field(..., description="TOPIC|OPENING_STATEMENT|NEUTRAL_ANALYSIS|REBUTTAL|NEUTRAL_CHECK|CLOSING_STATEMENT|JUDGEMENT")
    stageTitle: str = Field(..., description="화면 표시 제목 (반대측 입론 등)")
    side: str = Field(..., description="CON | PRO | NEUTRAL | TOPIC")
    role: str = Field(..., description="반대측 | 찬성측 | 중립 | 논제")
    agentIndex: Optional[int] = Field(None, description="1=반대 2=찬성 3=중립")
    agentId: Optional[Any] = Field(None, description="에이전트 ID")
    agentName: Optional[str] = Field(None, description="에이전트 이름")
    content: str = Field("", description="단계 본문")


class MultiChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    groupId: Optional[Any] = Field(None, validation_alias=AliasChoices("groupId", "group_id"), description="그룹 ID")
    roomId: Optional[Any] = Field(None, validation_alias=AliasChoices("roomId", "room_id"), description="방 ID")
    agentRoomId: Optional[Any] = Field(None, validation_alias=AliasChoices("agentRoomId", "agent_room_id"), description="에이전트 방 ID")
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
    strictPersona: bool = Field(True, validation_alias=AliasChoices("strictPersona", "strict_persona"), description="성격/지식수준 강제 적용")
    temperature: Optional[float] = Field(None, description="LLM temperature override")
    topP: Optional[float] = Field(None, validation_alias=AliasChoices("topP", "top_p"), description="LLM top_p override")
    maxTokens: Optional[int] = Field(None, validation_alias=AliasChoices("maxTokens", "max_tokens"), description="LLM max token override")
    model: Optional[str] = Field(None, description="LLM model override")
    showFinalSynthesis: bool = Field(True, validation_alias=AliasChoices("showFinalSynthesis", "show_final_synthesis"), description="최종 종합 의견 포함 여부 (default/tikitaka)")
    targetAgentId: Optional[Any] = Field(None, validation_alias=AliasChoices("targetAgentId", "target_agent_id"), description="특정 에이전트 지정 (null이면 전체)")
    previousAnswers: List[PreviousAnswer] = Field(
        default_factory=list, description="이전 대화 맥락 (최대 100개, 실제 사용 최근 20개)"
    )
    agents: List[AgentProfile] = Field(
        default_factory=list, description="참여 에이전트 목록"
    )
    # v0.7 추가 필드
    materialId: Optional[int] = Field(None, validation_alias=AliasChoices("materialId", "material_id"), description="RAG 자료 ID (materialId 있으면 RAG 검색)")
    userAttempt: Optional[str] = Field(
        None, description="사용자의 시도 답변 (socratic 모드에서 오개념 분석에 사용)"
    )
    knowledgeLevel: Optional[str] = Field(None, description="전역 지식 수준 (에이전트별 미설정 시 사용)")
    answerDepth: Optional[str] = Field(None, validation_alias=AliasChoices("answerDepth", "answer_depth", "depth"), description="전역 답변 깊이 (basic/normal/deep/max). 에이전트별 미설정 시 사용")
    # 프론트 학습모드(basic/socratic/debate). mode가 generic이면 이 값으로 모드를 보강한다.
    learningMode: Optional[str] = Field(None, validation_alias=AliasChoices("learningMode", "learning_mode"), description="학습 진행 모드 (basic/socratic/debate/simulation)")
    # 토론 모드 논제/구조 설정 (debate 모드에서만 사용)
    debateConfig: Optional[DebateConfig] = Field(None, description="토론 논제/구조 설정")
    # 소크라테스 모드 문답 설정 (socratic 모드에서만 사용)
    socraticConfig: Optional[SocraticConfig] = Field(None, description="소크라테스 문답 설정")
    # 상황극 모드 설정 (simulation 모드에서만 사용)
    simulationConfig: Optional[SimulationConfig] = Field(None, description="상황극 학습 설정")
    # ── 분기형 상황극(미연시/비주얼 노벨) 상태 머신 입력 (simulation 모드, additive) ──
    # 프론트가 이전 턴 응답을 그대로 되돌려 보내 상태를 이어간다.
    simulationState: Optional[Dict[str, Any]] = Field(
        None,
        validation_alias=AliasChoices("simulationState", "simulation_state"),
        description="이전 턴 상태(scenarioId/turnIndex/topic/userRole/worldState/previousChoices 등)",
    )
    selectedChoice: Optional[Dict[str, Any]] = Field(
        None,
        validation_alias=AliasChoices("selectedChoice", "selected_choice"),
        description="사용자가 이번 턴에 고른 선택지(choiceId/label/action)",
    )
    scenarioId: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("scenarioId", "scenario_id"),
        description="진행 중인 상황극 식별자",
    )
    turnIndex: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("turnIndex", "turn_index"),
        description="현재 턴 인덱스(첫 턴=0)",
    )
    phase: Optional[str] = Field(
        None,
        description="상황극 단계 강제 지정(SCENE_SETUP|CHOICE_RESULT|ENDING). 미지정 시 상태로 추론.",
    )
    endingReached: Optional[bool] = Field(
        None,
        validation_alias=AliasChoices("endingReached", "ending_reached"),
        description="true면 강제 종료(ENDING)",
    )
    enableFeedback: bool = Field(False, description="에이전트 간 피드백 활성화")
    enableFeedbackValidation: bool = Field(True, description="피드백 검증/재작성 활성화")
    # v0.8 추가 필드
    academicDomain: Optional[str] = Field(None, description="학문 도메인 (auto-detect 가능)")
    enableDepthValidation: Optional[bool] = Field(None, description="박사 수준 depth 검증 활성화")
    enableDepthRewrite: Optional[bool] = Field(None, description="박사 수준 depth 재작성 활성화")
    enableExternalSources: Optional[bool] = Field(None, description="외부 소스(Tavily/Wikipedia) 사용")
    debugMetadata: bool = Field(False, description="debug metadata 반환 여부 (관리자용)")
    # 토론 모드 논제 선택 상태 (debate 모드 turn 분기). additive — 기존 필드/계약 불변.
    # selectedTopic/topicSelected 가 없으면 TOPIC_SELECTION(논제 후보 제시), 있으면 DEBATE_ROUND(본 토론).
    selectedTopic: Optional[Any] = Field(None, validation_alias=AliasChoices("selectedTopic", "selected_topic"), description="사용자가 선택한 토론 논제 {topicId,title} 또는 문자열")
    topicSelected: Optional[bool] = Field(None, validation_alias=AliasChoices("topicSelected", "topic_selected"), description="논제 선택 완료 여부")
    debateState: Optional[Dict[str, Any]] = Field(None, validation_alias=AliasChoices("debateState", "debate_state"), description="토론 세션 상태(서버 무상태 → 클라이언트가 보존해 전달)")


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
    answerDepth: Optional[str] = None
    usedRag: bool = False
    latencyMs: Optional[int] = None
    detectedMisconception: Optional[bool] = None
    directAnswerSuppressed: Optional[bool] = None


class AgentAnswer(BaseModel):
    """에이전트 단일 답변. 하위 호환을 위해 agentName/answer는 필수 유지."""
    agentName: str = Field(..., description="에이전트 이름")
    answer: str = Field(..., description="에이전트 답변")
    senderType: str = Field("AGENT", description="저장용 발신자 타입")
    content: Optional[str] = Field(None, description="저장용 본문(answer와 동일)")
    personality: Optional[str] = Field(None, description="성격 키")
    personalityLabel: Optional[str] = Field(None, description="성격 표시명")
    knowledgeLevel: Optional[str] = Field(None, description="지식 수준 키")
    knowledgeLevelLabel: Optional[str] = Field(None, description="지식 수준 표시명")
    mode: Optional[str] = Field(None, description="생성 모드")
    round: Optional[int] = Field(None, description="라운드")
    sequence: Optional[int] = Field(None, description="표시 순서")
    createdAt: Optional[str] = Field(None, description="생성 시각")
    # v0.7 확장 필드 (optional — 기존 코드 호환)
    agentId: Optional[Any] = Field(None, description="에이전트 ID")
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
    agentId: Optional[Any] = None
    # 프론트 정렬 키 (에이전트 1→2→3 순서 확정용) + 단계 식별
    agentIndex: Optional[int] = None
    displayOrder: Optional[int] = None
    stage: Optional[int] = None
    # 카드 표시용 메타데이터 (프론트 ProcessStepsAccordion이 그대로 렌더링)
    personalityType: Optional[str] = None
    knowledgeLevel: Optional[str] = None
    provider: Optional[str] = None
    elapsedMs: Optional[int] = None


class ValidatedAnswerStep(BaseModel):
    agentName: str
    answer: str
    agentId: Optional[Any] = None
    # 프론트 정렬 키 + 단계 식별
    agentIndex: Optional[int] = None
    displayOrder: Optional[int] = None
    stage: Optional[int] = None
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
    # 프론트 정렬 키 (fromAgent 기준 1→2→3) + 단계 식별
    agentIndex: Optional[int] = None
    displayOrder: Optional[int] = None
    stage: Optional[int] = None
    # 메타데이터: fromAgentId + 피드백 대상 에이전트 ID 목록 + 성격 유형
    fromAgentId: Optional[Any] = None
    targetAgentIds: List[Any] = Field(default_factory=list)
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


class DebateInitialAnswer(BaseModel):
    agentIndex: int
    agentName: str
    displayName: str
    answer: str


class DebatePeerFeedback(BaseModel):
    fromAgentIndex: int
    fromAgentName: str
    toAgentIndex: int
    toAgentName: str
    title: str
    feedback: str


class DebateRevisedAnswer(BaseModel):
    agentIndex: int
    agentName: str
    displayName: str
    answer: str


class ProcessSteps(BaseModel):
    mode: Optional[str] = None
    initialAnswers: List[InitialAnswerStep] = Field(default_factory=list)
    validatedAnswers: List[ValidatedAnswerStep] = Field(default_factory=list)
    peerFeedback: List[PeerFeedbackStep] = Field(default_factory=list)
    personalityValidationSummary: List[PersonalityValidationItem] = Field(default_factory=list)
    # 토론 모드 전용: 피드백 반영 보완 답변 + 토론 종합 정리
    revisedAnswers: List[ValidatedAnswerStep] = Field(default_factory=list)
    debateSummary: Optional[str] = None
    # 구조화 토론 단계 (채팅/마인드맵/history 공통 SSOT) + 사용된 논제 설정
    debateStages: List[DebateStage] = Field(default_factory=list)
    debateConfig: Optional[DebateConfig] = None
    # 구조화 소크라테스 단계 + 사용된 설정 (채팅/마인드맵/history 공통 SSOT)
    socraticSteps: List[SocraticStep] = Field(default_factory=list)
    socraticConfig: Optional[SocraticConfig] = None
    # 구조화 상황극 단계 + 사용된 설정 (채팅/마인드맵/history 공통 SSOT)
    simulationStages: List[SimulationStage] = Field(default_factory=list)
    simulationConfig: Optional[SimulationConfig] = None
    scenarioTitle: Optional[str] = None
    userRole: Optional[str] = None
    choices: List[SimulationChoice] = Field(default_factory=list)
    nextScenario: Optional[str] = None
    misconceptions: List[str] = Field(default_factory=list)
    finalSummary: Optional[str] = None
    nextStudyPlan: List[str] = Field(default_factory=list)


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


class MultiChatMessage(BaseModel):
    senderType: str = "AGENT"
    agentId: Optional[Any] = None
    agentName: str
    personality: Optional[str] = None
    personalityLabel: Optional[str] = None
    knowledgeLevel: Optional[str] = None
    knowledgeLevelLabel: Optional[str] = None
    role: Optional[str] = None
    mode: str
    round: int = 1
    sequence: int = 1
    content: str
    createdAt: Optional[str] = None
    groupId: Optional[Any] = None
    roomId: Optional[Any] = None


# ── 토론 모드 turn 계약 (TOPIC_SELECTION / DEBATE_ROUND) ─────────────────────────
class DebateTopicCandidate(BaseModel):
    """TOPIC_SELECTION에서 제시하는 찬반 논제 후보. 정확히 5개(topicId A~E)."""
    topicId: Optional[str] = Field(None, description="A | B | C | D | E")
    title: str = Field(..., description="찬반이 갈릴 수 있는 논제 문장")
    axis: Optional[str] = Field(None, description="쟁점 축")
    proPosition: Optional[str] = Field(None, description="찬성 입장 한 줄")
    conPosition: Optional[str] = Field(None, description="반대 입장 한 줄")


class DebateSide(BaseModel):
    """DEBATE_ROUND의 찬성측/반대측 주장 구조."""
    speaker: Optional[str] = Field(None, description="찬성측 | 반대측")
    claim: str = Field("", description="핵심 주장 1개")
    evidence: List[str] = Field(default_factory=list, description="근거 1~3개")
    example: Optional[str] = Field(None, description="구체 예시 1개")


class DebateRebuttal(BaseModel):
    """DEBATE_ROUND의 상호 반박."""
    proRebuttal: Optional[str] = Field(None, description="찬성측 반박")
    conRebuttal: Optional[str] = Field(None, description="반대측 반박")


class MultiChatResponse(BaseModel):
    success: bool = Field(True, description="요청 성공 여부")
    groupId: Optional[Any] = Field(None, description="그룹 ID")
    roomId: Optional[Any] = Field(None, description="방 ID")
    agentRoomId: Optional[Any] = Field(None, description="에이전트 방 ID")
    mode: str = Field(..., description="응답 모드")
    learningMode: Optional[str] = Field(None, description="학습 진행 모드")
    answers: List[AgentAnswer] = Field(..., description="에이전트 답변 목록")
    messages: List[MultiChatMessage] = Field(default_factory=list, description="Spring 저장용 완성 메시지 목록")
    # v0.7 확장 필드
    status: str = Field("COMPLETED", description="COMPLETED | PARTIAL_SUCCESS | FAILED")
    question: Optional[str] = Field(None, description="원본 질문")
    validation: Optional[ValidationSummary] = Field(None, description="검증 결과")
    feedbacks: List[Dict[str, Any]] = Field(default_factory=list, description="에이전트 간 피드백")
    # 토론 모드 전용 top-level 구조. Spring/프론트가 일반 answers 나열 대신 이 구조를 우선 렌더링한다.
    initialAnswers: List[DebateInitialAnswer] = Field(default_factory=list, description="토론 1차 의견")
    peerFeedbacks: List[DebatePeerFeedback] = Field(default_factory=list, description="토론 상호 피드백")
    revisedAnswers: List[DebateRevisedAnswer] = Field(default_factory=list, description="토론 보완 답변")
    debateSummary: Optional[str] = Field(None, description="토론 정리")
    # 구조화 토론: 채팅/마인드맵/SSE/history 공통 단계 목록 + 사용된 논제 설정 (top-level 노출)
    debateStages: List[DebateStage] = Field(default_factory=list, description="구조화 토론 단계 목록")
    debateConfig: Optional[DebateConfig] = Field(None, description="토론에 사용된 설정")
    # 구조화 소크라테스: 채팅/마인드맵/SSE/history 공통 단계 목록 + 사용된 설정 (top-level 노출)
    socraticSteps: List[SocraticStep] = Field(default_factory=list, description="구조화 소크라테스 단계 목록")
    socraticConfig: Optional[SocraticConfig] = Field(None, description="소크라테스에 사용된 설정")
    # 구조화 상황극: 채팅/마인드맵/SSE/history 공통 단계 목록 + 사용된 설정 (top-level 노출)
    simulationStages: List[SimulationStage] = Field(default_factory=list, description="구조화 상황극 단계 목록")
    simulationConfig: Optional[SimulationConfig] = Field(None, description="상황극에 사용된 설정")
    # ── 분기형 상황극(미연시/비주얼 노벨) 상태 머신 응답 (additive top-level) ──
    phase: Optional[str] = Field(None, description="SCENE_SETUP | CHOICE_RESULT | ENDING")
    scenarioId: Optional[str] = Field(None, description="진행 중인 상황극 식별자")
    turnIndex: Optional[int] = Field(None, description="현재 턴 인덱스(첫 턴=0)")
    topic: Optional[str] = Field(None, description="학습 주제")
    learningObjective: Optional[str] = Field(None, description="이번 상황극의 학습 목표")
    userRole: Optional[str] = Field(None, description="사용자가 맡은 역할")
    worldState: Optional[str] = Field(None, description="세계/상황 설정")
    sceneTitle: Optional[str] = Field(None, description="현재 장면 제목")
    sceneDescription: Optional[str] = Field(None, description="현재 장면 설명")
    narratorText: Optional[str] = Field(None, description="내레이션")
    npc: Optional[SimulationNpc] = Field(None, description="상대 인물")
    npcDialogue: Optional[str] = Field(None, description="NPC 대사")
    npcInnerMonologue: Optional[str] = Field(None, description="NPC 속마음/독백")
    consequence: Optional[str] = Field(None, description="선택의 결과/상황 변화")
    choices: List[SimulationChoice] = Field(default_factory=list, description="다음 선택지(ENDING이 아니면 정확히 5개)")
    selectedChoice: Optional[Dict[str, Any]] = Field(None, description="이번 턴에 반영된 사용자 선택")
    endingReached: bool = Field(False, description="종료 여부")
    learningFeedback: Optional[SimulationLearningFeedback] = Field(None, description="ENDING 학습 피드백")
    content: Optional[str] = Field(None, description="기존 프론트 호환용 요약 텍스트")
    # 1차/2차/3차 생성 과정 (default 모드에서 생성, Spring이 그대로 패스스루)
    processSteps: Optional[ProcessSteps] = Field(None, description="1차 초안/2차 검증/3차 상호 피드백")
    # 단계별 구조 (provider/elapsedMs 포함, 프론트 stages 우선 렌더링용)
    stages: Optional[List[StageInfo]] = Field(None, description="stage1/2/3 구조 (provider, elapsedMs)")
    # v0.8 debug metadata (debugMetadata=true 요청 시에만 반환)
    debugMetadata: Optional[DebugMetadata] = Field(None, description="debug metadata (관리자용)")
    # ── 토론 모드 turn/phase 계약 (TOPIC_SELECTION / DEBATE_ROUND) — additive ──────
    # 기존 answers/messages/debateStages 계약을 유지한 채 구조화 필드를 추가로 제공한다.
    phase: Optional[str] = Field(None, description="TOPIC_SELECTION | DEBATE_ROUND")
    debateSessionId: Optional[str] = Field(None, description="토론 세션 ID")
    turnIndex: Optional[int] = Field(None, description="턴 인덱스 (0=논제선택, 1+=본 토론)")
    rawQuestion: Optional[str] = Field(None, description="원 질문")
    primaryConcept: Optional[str] = Field(None, description="추출된 핵심 개념")
    normalizedConcept: Optional[str] = Field(None, description="정규화된 개념명")
    intent: Optional[str] = Field(None, description="질문 의도")
    conceptChunks: List[str] = Field(default_factory=list, description="개념 청크")
    debateAxes: List[str] = Field(default_factory=list, description="토론 축")
    debateTopicCandidates: List[DebateTopicCandidate] = Field(default_factory=list, description="논제 후보 5개 (TOPIC_SELECTION)")
    topicSelected: Optional[bool] = Field(None, description="논제 선택 완료 여부")
    selectedTopic: Optional[Dict[str, Any]] = Field(None, description="선택된 논제 {topicId,title}")
    pro: Optional[DebateSide] = Field(None, description="찬성측 (DEBATE_ROUND)")
    con: Optional[DebateSide] = Field(None, description="반대측 (DEBATE_ROUND)")
    rebuttal: Optional[DebateRebuttal] = Field(None, description="상호 반박 (DEBATE_ROUND)")
    keyIssues: List[str] = Field(default_factory=list, description="핵심 쟁점 (DEBATE_ROUND)")
    learningTakeaway: Optional[str] = Field(None, description="학습 정리 (DEBATE_ROUND)")
    nextTopics: List[str] = Field(default_factory=list, description="이어서 토론할 논제")
    content: Optional[str] = Field(None, description="프론트 호환용 요약 텍스트")
