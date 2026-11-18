"""GPT 검증 작업 스키마."""
from typing import Any, Optional
from pydantic import BaseModel


class ValidationStatusResponse(BaseModel):
    job_id: str
    status: str  # pending | running | completed | failed
    result: Optional[dict[str, Any]] = None
    corrected_answer: Optional[str] = None
