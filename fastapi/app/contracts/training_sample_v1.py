"""training-sample.v1 — EC2 가 동의/권리 확인을 거쳐 ai07 에 넘기는 학습 후보 샘플 계약.

- EC2 가 동의·권리의 최종 소스다. 그러나 ai07 은 trainingEligibility 주장을 그대로 믿지 않고
  app.training_pipeline.eligibility 로 다시 판정한다.
- 서명된 내부 계약으로만 수집한다(본문 HMAC: X-AI-Contract-Signature, app.contracts.signing).
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "training-sample.v1"

_ID_RE = re.compile(r"^[A-Za-z0-9._:\-]{8,128}\Z")
_PSEUDO_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{16,128}\Z")
_HEX64 = re.compile(r"^[0-9a-f]{64}\Z")  # \Z: 끝 개행 불허(예전 $ 는 허용)


class SourceKind(str, Enum):
    PDF_QA = "PDF_QA"
    PDF_SUMMARY = "PDF_SUMMARY"
    PDF_QUIZ = "PDF_QUIZ"
    GENERAL_QA = "GENERAL_QA"
    MATH = "MATH"
    CODE = "CODE"
    WRONG_NOTE = "WRONG_NOTE"
    FREE_RESPONSE = "FREE_RESPONSE"


class RightsStatus(str, Enum):
    USER_OWNED_VERIFIED = "USER_OWNED_VERIFIED"
    LICENSED_VERIFIED = "LICENSED_VERIFIED"
    PUBLIC_DOMAIN_VERIFIED = "PUBLIC_DOMAIN_VERIFIED"
    NO_THIRD_PARTY_CONTENT = "NO_THIRD_PARTY_CONTENT"
    THIRD_PARTY_UNVERIFIED = "THIRD_PARTY_UNVERIFIED"
    UNKNOWN = "UNKNOWN"


RIGHTS_OK = {RightsStatus.USER_OWNED_VERIFIED, RightsStatus.LICENSED_VERIFIED,
             RightsStatus.PUBLIC_DOMAIN_VERIFIED, RightsStatus.NO_THIRD_PARTY_CONTENT}


class QualityLabel(str, Enum):
    UNLABELED = "UNLABELED"
    REVIEWER_VERIFIED = "REVIEWER_VERIFIED"
    DETERMINISTIC_GOLD = "DETERMINISTIC_GOLD"
    UNVERIFIABLE = "UNVERIFIABLE"
    INCORRECT = "INCORRECT"


class VerificationMethod(str, Enum):
    HUMAN_REVIEW = "HUMAN_REVIEW"
    MATH_CHECK = "MATH_CHECK"
    CODE_TESTS = "CODE_TESTS"
    EXACT_MATCH_GOLD = "EXACT_MATCH_GOLD"
    PDF_SPAN_MATCH = "PDF_SPAN_MATCH"
    LLM_JUDGE = "LLM_JUDGE"   # 단독으로는 학습 자격 근거가 되지 않는다(자기증폭/편향)
    NONE = "NONE"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sourceType: str = Field(..., max_length=32)
    materialId: Optional[int] = Field(None, ge=1)
    documentId: Optional[str] = Field(None, max_length=128)
    sourceRevisionHash: Optional[str] = Field(None, max_length=128)
    page: Optional[int] = Field(None, ge=1)
    chunkId: Optional[str] = Field(None, max_length=128)
    quote: Optional[str] = Field(None, max_length=4000)


class Feedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: int = Field(..., ge=-1, le=1, description="-1 싫어요/오류신고, 0 중립, 1 좋아요")
    reasonCode: Optional[str] = Field(None, max_length=64)
    updatedAt: datetime
    history: List[int] = Field(default_factory=list, max_length=64, description="과거 score 변경 이력")


class TrainingEligibilityClaim(BaseModel):
    """EC2 의 동의/권리 판단(주장). ai07 은 이것과 자체 게이트를 AND 로 결합한다."""
    model_config = ConfigDict(extra="forbid")
    consentGranted: bool
    consentScope: List[str] = Field(default_factory=list, max_length=8)
    consentWithdrawn: bool = False
    decidedAt: datetime


class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: VerificationMethod
    reviewerId: Optional[str] = Field(None, max_length=64)
    verifiedAt: Optional[datetime] = None
    goldReference: Optional[str] = Field(None, max_length=256, description="gold 문제 ID/테스트 해시 등")


class TrainingSampleV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: str
    eventId: str
    pseudonymousUserKey: str
    consentVersion: Optional[str] = Field(None, max_length=32)
    consentTimestamp: Optional[datetime] = None
    sourceKind: SourceKind
    sourceRevisionHash: Optional[str] = Field(None, max_length=128)
    rightsStatus: RightsStatus
    question: str = Field(..., min_length=1, max_length=4000)
    candidateAnswer: str = Field(..., min_length=1, max_length=12000)
    verifiedAnswer: Optional[str] = Field(None, max_length=12000)
    verification: Optional[Verification] = None
    evidence: List[Evidence] = Field(default_factory=list, max_length=16)
    feedback: Optional[Feedback] = None
    qualityLabel: QualityLabel = QualityLabel.UNLABELED
    qualityEvaluatorVersion: Optional[str] = Field(None, max_length=64)
    modelName: str = Field(..., max_length=64)
    modelDigest: Optional[str] = Field(None, max_length=128)
    promptTemplateVersion: Optional[str] = Field(None, max_length=64)
    contentHash: str
    createdAt: datetime
    deletionTrackingId: str
    retentionPolicy: str = Field(..., max_length=64)
    trainingEligibility: TrainingEligibilityClaim

    @field_validator("schemaVersion")
    @classmethod
    def _version(cls, v: str) -> str:
        if v != SCHEMA_VERSION:
            raise ValueError(f"unsupported schemaVersion: {v}")
        return v

    @field_validator("eventId", "deletionTrackingId")
    @classmethod
    def _ids(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError("invalid identifier")
        return v

    @field_validator("pseudonymousUserKey")
    @classmethod
    def _pseudo(cls, v: str) -> str:
        if not _PSEUDO_KEY_RE.match(v) or v.isdigit():
            raise ValueError("pseudonymousUserKey must be an opaque pseudonymous token")
        return v

    @model_validator(mode="after")
    def _hash(self) -> "TrainingSampleV1":
        if not _HEX64.match(self.contentHash):
            raise ValueError("contentHash must be lowercase sha256 hex")
        if self.contentHash != compute_content_hash(self.question, self.candidateAnswer):
            raise ValueError("contentHash mismatch (question+candidateAnswer)")
        return self


def normalize_for_hash(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", " ", t).strip()


def compute_content_hash(question: str, answer: str) -> str:
    """EC2/ai07 공통 해시 규칙: NFKC + 공백 정규화 후 question + '\\n' + answer 의 SHA-256."""
    return hashlib.sha256(
        (normalize_for_hash(question) + "\n" + normalize_for_hash(answer)).encode("utf-8")
    ).hexdigest()
