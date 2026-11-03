"""response-quality.v1 — 사용자 노출 AI 생성물의 품질 게이트 입력/출력 계약.

승인 규칙(단일 소스): is_displayable() 만이 '노출 가능'을 판정한다.
  verified=True AND score>=80 AND hardFail=False AND qualityStatus=APPROVED
점수는 내부 rubric 점수이며 '정답일 확률'이 아니다(보정되지 않음).
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "response-quality.v1"
MINIMUM_SCORE = 80

_ID_RE = re.compile(r"^[A-Za-z0-9._:\-]{8,128}$")
MAX_OUTPUT_CHARS = 60000
MAX_EVIDENCE_ITEMS = 32
MAX_EVIDENCE_CHARS = 8000


class QualityStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    APPROVED = "APPROVED"
    REGENERATING = "REGENERATING"
    REJECTED = "REJECTED"
    VALIDATION_ERROR = "VALIDATION_ERROR"


class TaskType(str, Enum):
    GENERAL_EXPLANATION = "GENERAL_EXPLANATION"
    CREATIVE_EXPLORATION = "CREATIVE_EXPLORATION"
    STUDYMATE_BASIC = "STUDYMATE_BASIC"
    STUDYMATE_SOCRATIC = "STUDYMATE_SOCRATIC"
    STUDYMATE_DEBATE = "STUDYMATE_DEBATE"
    STUDYMATE_ROLEPLAY = "STUDYMATE_ROLEPLAY"
    PDF_SUMMARY = "PDF_SUMMARY"
    PDF_QA = "PDF_QA"
    PDF_QUIZ = "PDF_QUIZ"
    WRONG_NOTE_EXPLANATION = "WRONG_NOTE_EXPLANATION"
    SIMILAR_QUESTION = "SIMILAR_QUESTION"
    MATH_SOLUTION = "MATH_SOLUTION"
    PLANNER_COACHING = "PLANNER_COACHING"
    SEMANTIC_GRAPH = "SEMANTIC_GRAPH"
    VISION_CAPTION = "VISION_CAPTION"
    GROUP_STUDY_MESSAGE = "GROUP_STUDY_MESSAGE"


class OutputKind(str, Enum):
    TEXT = "text"
    QUIZ_JSON = "quiz_json"
    GRAPH_JSON = "graph_json"
    PLAN_JSON = "plan_json"
    VISION_TEXT = "vision_text"
    AGENT_MESSAGE = "agent_message"


class Severity(str, Enum):
    HARD = "HARD"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    INFO = "INFO"


class GroundingEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidenceId: Optional[str] = Field(None, description="인용 검증용 식별자(chunkId 가 없을 때)")
    sourceType: str = Field(..., max_length=32)
    materialId: Optional[int] = Field(None, ge=1)
    documentId: Optional[str] = None
    sourceRevisionHash: Optional[str] = Field(None, max_length=128)
    page: Optional[int] = Field(None, ge=1)
    chunkId: Optional[str] = None
    text: Optional[str] = Field(None, max_length=MAX_EVIDENCE_CHARS)

    def ref_id(self) -> Optional[str]:
        return self.chunkId or self.evidenceId


class QualityConstraints(BaseModel):
    """작업별 검증 제약. 모르는 키는 거부(extra=forbid)해 의미 재정의를 막는다."""
    model_config = ConfigDict(extra="forbid")
    allowedMaterialIds: Optional[List[int]] = None
    allowedDocumentIds: Optional[List[str]] = None
    expectedQuestionCount: Optional[int] = Field(None, ge=1, le=50)
    expectedOptionCount: Optional[int] = Field(None, ge=2, le=10)
    expectedAnswer: Optional[str] = Field(None, max_length=2000, description="결정적 정답(gold)이 있을 때")
    maxChars: Optional[int] = Field(None, ge=1, le=MAX_OUTPUT_CHARS)
    finishReason: Optional[str] = Field(None, max_length=32, description="생성기 종료 사유(length=잘림)")
    requireCitations: bool = False
    allowPiiEcho: bool = False
    maxDailyHours: Optional[float] = Field(None, gt=0, le=24)
    deadline: Optional[str] = Field(None, max_length=32)
    knownPrerequisites: Optional[List[str]] = None
    participants: Optional[List[str]] = None
    expectedPersona: Optional[str] = Field(None, max_length=64)
    knowledgeLevel: Optional[str] = Field(None, max_length=32)


class QualityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: str
    requestId: str
    taskType: TaskType
    outputKind: OutputKind
    modelDigest: Optional[str] = Field(None, max_length=128)
    originalRequest: str = Field(..., max_length=8000)
    proposedOutput: Any
    groundingEvidence: List[GroundingEvidence] = Field(default_factory=list, max_length=MAX_EVIDENCE_ITEMS)
    constraints: QualityConstraints = Field(default_factory=QualityConstraints)
    attemptIndex: int = Field(0, ge=0, le=2)
    evaluationProfile: Optional[str] = Field(None, max_length=64)

    @field_validator("schemaVersion")
    @classmethod
    def _version(cls, v: str) -> str:
        if v != SCHEMA_VERSION:
            raise ValueError(f"unsupported schemaVersion: {v}")
        return v

    @field_validator("requestId")
    @classmethod
    def _rid(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError("requestId must match [A-Za-z0-9._:-]{8,128}")
        return v

    @model_validator(mode="after")
    def _size(self) -> "QualityInput":
        import json
        po = self.proposedOutput
        size = len(po) if isinstance(po, str) else len(json.dumps(po, ensure_ascii=False, default=str))
        if size > MAX_OUTPUT_CHARS:
            raise ValueError("proposedOutput too large")
        return self


class Violation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    severity: Severity
    reason: str = Field(..., max_length=300)
    evidenceId: Optional[str] = None


class Dimension(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    score: Optional[float] = Field(None, description="None = 검증 불가(unverified)")
    maxScore: float
    method: str = Field(..., description="deterministic | evidence | judge | unverified | not_applicable")


class QualityOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: str = SCHEMA_VERSION
    requestId: str
    taskType: TaskType
    success: bool = Field(..., description="평가 자체가 완료됐는가(승인 여부 아님)")
    verified: bool
    qualityStatus: QualityStatus
    score: Optional[float] = None
    minimumScore: int = MINIMUM_SCORE
    hardFail: bool
    violations: List[Violation] = Field(default_factory=list)
    dimensions: List[Dimension] = Field(default_factory=list)
    regenerationHints: Optional[List[str]] = None
    evaluatorVersion: str
    modelDigest: Optional[str] = None
    latencyMs: int = 0

    @model_validator(mode="after")
    def _invariants(self) -> "QualityOutput":
        # APPROVED 는 오직 규칙을 만족할 때만 존재할 수 있다(직렬화 단계에서 한 번 더 강제).
        if self.qualityStatus == QualityStatus.APPROVED and not _approvable(self):
            raise ValueError("APPROVED violates approval invariant")
        if self.minimumScore != MINIMUM_SCORE:
            raise ValueError("minimumScore is fixed at 80 for response-quality.v1")
        return self


def _approvable(o: "QualityOutput") -> bool:
    return (o.verified is True and o.score is not None and o.score >= o.minimumScore
            and o.hardFail is False and o.success is True
            and not any(v.severity == Severity.HARD for v in o.violations))


def is_displayable(o: Optional[QualityOutput]) -> bool:
    """사용자 노출 가능 판정의 유일한 진입점."""
    return bool(o is not None and o.qualityStatus == QualityStatus.APPROVED and _approvable(o))


def output_to_dict(o: QualityOutput) -> Dict[str, Any]:
    return o.model_dump(mode="json")
