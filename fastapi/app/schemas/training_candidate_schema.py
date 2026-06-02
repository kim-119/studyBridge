"""학습 후보 관리 스키마."""
from typing import Optional
from pydantic import BaseModel, Field


class TrainingCandidateStatsResponse(BaseModel):
    auto_collected: int = 0
    auto_approved: int = 0
    auto_rejected: int = 0
    holdout: int = 0
    duplicate: int = 0
    unsafe: int = 0
    error: Optional[str] = None


class ExportJsonlRequest(BaseModel):
    output_path: str = Field("exported_training_data.jsonl")
    min_score: int = Field(90, ge=0, le=100)


class ExportJsonlResponse(BaseModel):
    output_path: str
    exported_count: int
    status: str
