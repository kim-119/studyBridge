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
