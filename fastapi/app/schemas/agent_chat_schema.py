"""
AI 에이전트 채팅 API 요청/응답 스키마.
"""
from typing import Any, Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class AgentChatRequest(BaseModel):
    """POST /api/ai/chat 요청 DTO"""
    model_config = ConfigDict(populate_by_name=True)

    # 프론트/EC2가 question 대신 message/content 로 보낼 수 있어 alias 로 모두 수용한다.
    question: str = Field(
        "",
        validation_alias=AliasChoices("question", "message", "content"),
        description="사용자 질문 (message/content alias 허용)",
    )
    # 자료 맥락: context/materialContext/sourceText 로 들어오면 질문 앞에 근거로 주입한다.
    context: Optional[str] = Field(
        None,
        validation_alias=AliasChoices(
            "context", "materialContext", "material_context", "sourceText", "source_text"
        ),
        description="자료 맥락 (있으면 질문 앞 근거로 주입)",
    )
    agent_id: Optional[int] = Field(None, description="에이전트 DB ID")
    agent_name: str = Field("자바도우미", description="에이전트 표시 이름")
    material_id: Optional[int] = Field(None, description="PDF 자료 ID (RAG 검색용)")
    knowledge_level: str = Field(
        "학사",
        description="지식수준 (입문/학사/석사/박사/전문가)",
    )
    personality: str = Field(
        "친절_설명형",
        description="성격/말투 (친절_설명형/비판적_분석형/논리적_탐구형/창의적_확장형/간결_요약형/직접_입력)",
    )
    custom_instruction: Optional[str] = Field(None, description="직접_입력 성격 시 사용자 지정 지시사항")
    enable_tiki_taka: bool = Field(False, description="멀티 에이전트 티키타카 활성화")
    enable_round2: bool = Field(False, description="티키타카 Round 2 추가 발화")
    use_gpt_validation: bool = Field(True, description="GPT 비동기 검증 실행 여부")


class TikiTakaTurnDTO(BaseModel):
    """단일 티키타카 발화"""
    agent_name: str
    role_description: str
    content: str


class AgentChatResponse(BaseModel):
    """POST /api/ai/chat 응답 DTO"""
    answer: str = Field(..., description="Qwen 1차 답변 (즉시 반환)")
    tiki_taka_dialogue: list[TikiTakaTurnDTO] = Field(
        default_factory=list,
        description="티키타카 대화 목록 (비활성 시 빈 배열)",
    )
    validation_job_id: Optional[str] = Field(
        None, description="GPT 검증 작업 ID (use_gpt_validation=True 시 반환)"
    )
    status: str = Field(
        ...,
        description="pending_validation | complete | no_validation",
    )
    knowledge_level: str
    personality: str
    process_logs: list[str]


class ValidationStatusResponse(BaseModel):
    """GET /api/ai/chat/validation/{job_id} 응답 DTO"""
    job_id: str
    status: str = Field(..., description="pending | running | completed | failed")
    result: Optional[dict[str, Any]] = Field(
        None,
        description="검증 결과 (completed 시 채워짐): is_valid, score, issues, correction_needed, suggestion",
    )
    corrected_answer: Optional[str] = Field(
        None, description="GPT 보정 답변 (correction_needed=True 시 채워질 수 있음)"
    )


# ── 자료보관함 AI 스키마 ─────────────────────────────────────────────────────

class MaterialSummaryRequest(BaseModel):
    """POST /api/ai/material/summary"""
    material_id: int
    document_title: str
    text: str = Field(..., min_length=10)
    personality: str = "간결_요약형"
    agent_name: str = "요약봇"


class MaterialSummaryResponse(BaseModel):
    summary: str
    key_points: list[str]


class MaterialQuizRequest(BaseModel):
    """POST /api/ai/material/quiz"""
    material_id: int
    document_title: str
    context: str = Field(..., min_length=10)
    num_questions: int = Field(5, ge=1, le=20)
    knowledge_level: str = "학사"


class MaterialQuizResponse(BaseModel):
    quiz: str
    question_count: int


class MaterialRoadmapRequest(BaseModel):
    """POST /api/ai/material/roadmap"""
    material_id: int
    document_title: str
    context: str = Field(..., min_length=10)
    knowledge_level: str = "학사"


class MaterialRoadmapResponse(BaseModel):
    roadmap: str


class MaterialQARequest(BaseModel):
    """POST /api/ai/material/qa"""
    material_id: int
    question: str = Field(..., min_length=1)
    knowledge_level: str = "학사"
    personality: str = "친절_설명형"
    agent_name: str = "자료봇"
