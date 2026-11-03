"""학습 후보 관리 스키마."""
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

LEGACY_DEFAULT_OUTPUT_PATH = "exported_training_data.jsonl"


class TrainingCandidateStatsResponse(BaseModel):
    """[레거시] 상태별 통계. 저장소 장애 시 0 으로 위장하지 않는다(→ 503)."""
    auto_collected: int = 0
    auto_approved:  int = 0
    auto_rejected:  int = 0
    holdout:        int = 0
    duplicate:      int = 0
    unsafe:         int = 0
    error: Optional[str] = None


class TrainingPipelineStatsResponse(BaseModel):
    """정규 상태 기반 통계. '수집 성공/실패' · '승인(TRAIN_ELIGIBLE) 건수' · '모델 학습 실행 여부' 를 분리한다."""
    states: Dict[str, int]
    collection: Dict[str, int] = Field(default_factory=dict, description="응답 경로 수집 훅 처리 구분별 건수(프로세스 기동 이후)")
    trainEligible: int = 0
    modelTrainingExecuted: bool = False
    modelTrainingNote: str = "이 파이프라인에는 학습 실행 경로가 없다. 오프라인 QLoRA 는 별도 승인 후 수동 실행."


class ExportJsonlRequest(BaseModel):
    # output_path 는 하위 호환을 위해 받기만 한다. 기본값 이외의 경로는 거부한다(임의 경로 쓰기 방지).
    output_path: Optional[str] = Field(None, description="[deprecated] 지정 불가 — 서버 고정 비공개 디렉터리에만 쓴다")
    min_score:   int = Field(90, ge=0, le=100, description="[deprecated] 무시됨 — 학습 자격은 점수가 아니라 TRAIN_ELIGIBLE")


class ExportJsonlResponse(BaseModel):
    """POST /api/training-candidates/export-jsonl 응답."""
    dataset_version: Optional[str] = Field(None, description="고유 데이터셋 ID (train_vYYYYMMDD_NNN_xxxxxxxx)")
    sample_count:    int = Field(..., description="내보낸 샘플 수(train+validation+test)")
    output_file_path: Optional[str] = Field(None, description="데이터셋 루트 기준 상대 경로(절대 경로 비노출)")
    status:          str = Field(..., description="completed | empty | busy | failed")
    exported_count:  Optional[int] = Field(None, description="sample_count와 동일 (하위 호환)")
    split_counts: Dict[str, int] = Field(default_factory=dict)
    excluded: Dict[str, int] = Field(default_factory=dict)
    manifest_sha256: Optional[str] = None
    error_code: Optional[str] = None
    split_warnings: List[str] = Field(default_factory=list)


class CollectCandidateRequest(BaseModel):
    """
    [레거시] POST /api/training-candidates/collect.
    동의/권리 정보가 없으므로 이 payload 로는 새 후보를 저장하지 않는다(training-sample.v1 /collect-v1 사용).
    단, 부정 피드백(userFeedbackScore<0)은 기존 후보 철회에 반영한다.
    """
    question: str = Field(..., min_length=1, max_length=4000)
    answer: str = Field(..., min_length=1, max_length=12000)
    systemPrompt: str = Field("", max_length=8000, description="답변 생성에 쓰인 system prompt (저장하지 않음)")
    agentName: Optional[str] = None
    personality: str = Field("친절_설명형")
    knowledgeLevel: str = Field("학사")
    mode: Optional[str] = Field(None, description="default | debate | socratic 등")
    materialId: Optional[int] = None
    ragContextPreview: Optional[str] = Field(None, max_length=4000, description="사용한 RAG 근거 미리보기")
    ragChunkIds: Optional[list[int]] = Field(None, description="사용한 RAG 청크 ID")
    ragGroundingScore: Optional[float] = Field(None, ge=0.0, le=1.0)
    userFeedbackScore: Optional[int] = Field(None, description="양수=좋아요 / 음수=싫어요·오류신고")
    userFeedbackText: Optional[str] = Field(None, max_length=2000)
    createdAt: Optional[str] = None


class CollectCandidateResponse(BaseModel):
    candidate_uuid: Optional[str] = None
    quality_status: str
    quality_score: int = 0
    stored: bool = False
    auto_approved: bool = False            # 항상 False — 자동 학습 승인은 존재하지 않는다
    safety_status: str = "safe"
    duplicate_status: str = "unknown"
    reason: Optional[str] = None
    state: Optional[str] = None


class ReviewCandidateRequest(BaseModel):
    """검수자가 후보를 확인(VERIFY)/거절할 때."""
    candidate_uuid: str = Field(..., min_length=1, max_length=64)
    note: Optional[str] = Field(None, max_length=500)
    use: str = Field("candidate", pattern="^(candidate|correction|reviewer)$",
                     description="정답으로 확인할 대상: 원 답변 | 사용자 수정 답변 | 검수자 작성 답변")
    reviewerAnswer: Optional[str] = Field(None, max_length=12000)
    # 결정적 gold 검증(MATH_CHECK 등)은 실제 검증기를 실행하는 내부 경로가 생기기 전까지 API 로 주장할 수 없다.
    method: str = Field("HUMAN_REVIEW", pattern="^HUMAN_REVIEW$")
    goldReference: Optional[str] = Field(None, max_length=256)


class ReviewCandidateResponse(BaseModel):
    candidate_uuid: str
    status: str
    state: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)
    invalidated_datasets: List[str] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    candidateId: Optional[str] = Field(None, max_length=64)
    contentHash: Optional[str] = Field(None, pattern="^[0-9a-f]{64}$")
    score: int = Field(..., ge=-1, le=1)
    reasonCode: Optional[str] = Field(None, max_length=64)


class CorrectionRequest(BaseModel):
    candidateId: str = Field(..., max_length=64)
    correctedAnswer: str = Field(..., min_length=1, max_length=12000)


class ConsentWithdrawalRequest(BaseModel):
    pseudonymousUserKey: str = Field(..., pattern=r"^[A-Za-z0-9_\-]{16,128}$")


class DeletionRequest(BaseModel):
    deletionTrackingId: str = Field(..., pattern=r"^[A-Za-z0-9._:\-]{8,128}$")


class LineageResponse(BaseModel):
    status: str
    candidate_uuid: Optional[str] = None
    state: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)
    invalidated_datasets: List[str] = Field(default_factory=list)
    retirement_required_adapters: List[str] = Field(default_factory=list)
