"""학습 후보 관리 스키마."""
from typing import Optional
from pydantic import BaseModel, Field


class TrainingCandidateStatsResponse(BaseModel):
    auto_collected: int = 0
    auto_approved:  int = 0
    auto_rejected:  int = 0
    holdout:        int = 0
    duplicate:      int = 0
    unsafe:         int = 0
    error: Optional[str] = None


class ExportJsonlRequest(BaseModel):
    output_path: str = Field("exported_training_data.jsonl")
    min_score:   int = Field(90, ge=0, le=100)


class ExportJsonlResponse(BaseModel):
    """POST /api/training-candidates/export-jsonl 응답."""
    dataset_version: str = Field(..., description="데이터셋 버전 (train_vYYYYMMDD_NNN)")
    sample_count:    int = Field(..., description="내보낸 샘플 수")
    output_file_path: str = Field(..., description="내보낸 파일 경로")
    status:          str = Field(..., description="completed | failed")
    # 하위 호환 필드
    exported_count:  Optional[int] = Field(None, description="sample_count와 동일 (하위 호환)")


class CollectCandidateRequest(BaseModel):
    """
    POST /api/training-candidates/collect — Spring/Frontend가 AI 답변 생성 후 호출한다.
    즉시 학습이 아니라 '학습 후보'로만 수집하며, 검수 게이트(품질/중복/안전/피드백)를 거친다.
    """
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    systemPrompt: str = Field("", description="답변 생성에 쓰인 system prompt")
    agentName: Optional[str] = None
    personality: str = Field("친절_설명형")
    knowledgeLevel: str = Field("학사")
    mode: Optional[str] = Field(None, description="default | debate | socratic 등")
    materialId: Optional[int] = None
    ragContextPreview: Optional[str] = Field(None, description="사용한 RAG 근거 미리보기")
    ragChunkIds: Optional[list[int]] = Field(None, description="사용한 RAG 청크 ID")
    ragGroundingScore: Optional[float] = Field(None, ge=0.0, le=1.0)
    # 사용자 피드백: 음수(싫어요/오류 신고)면 auto_approved 금지
    userFeedbackScore: Optional[int] = Field(None, description="양수=좋아요 / 음수=싫어요·오류신고")
    userFeedbackText: Optional[str] = None
    createdAt: Optional[str] = None


class CollectCandidateResponse(BaseModel):
    candidate_uuid: Optional[str] = None
    quality_status: str
    quality_score: int = 0
    stored: bool = False
    auto_approved: bool = False
    safety_status: str = "safe"
    duplicate_status: str = "unique"
    reason: Optional[str] = None


class ReviewCandidateRequest(BaseModel):
    """검수자가 후보를 수동 승인/거절할 때."""
    candidate_uuid: str = Field(..., min_length=1)
    note: Optional[str] = None
