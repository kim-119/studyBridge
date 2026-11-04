"""response-quality.v1 — 사용자 노출 AI 생성물의 품질 게이트 입력/출력 계약(EC2 canonical 정합).

승인 규칙(단일 소스): is_displayable(o, expected_request_id) 만이 '노출 가능'을 판정한다(EC2 ResponseQualityV1.isDisplayable 과 동일).
  success AND verified AND qualityStatus=APPROVED AND score!=None AND 80<=score<=100 AND minimumScore∈{None,80}
  AND hardFail=False AND HARD 위반 0 AND mandatoryValidatorsPassed!=False AND schemaVersion 일치 AND requestId 일치
점수는 내부 rubric 점수이며 '정답일 확률'이 아니다(보정되지 않음).

필드 타입/null 규칙은 Java record + ContractJson.STRICT 와 같다(app.contracts.jtypes): 암묵 변환 금지(C-TYPE-1),
식별자 전체 일치(C-ID-1), score 100 초과 APPROVED 거부(C-RQ-2), mandatoryValidatorsPassed 선택 bool(C-RQ-1).
수신 JSON 은 parse_input_json/parse_output_json(원시 바이트 → Jackson 동등 파서)으로만 해석한다.
"""
from __future__ import annotations

import json
import math
import re
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.jtypes import JBool, JDouble, JInt, JLong, JStr, drop_nulls, loads_contract

SCHEMA_VERSION = "response-quality.v1"
MINIMUM_SCORE = 80
MAXIMUM_SCORE = 100

_ID_RE = re.compile(r"[A-Za-z0-9._:\-]{8,128}")
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
    evidenceId: Optional[JStr] = Field(None, description="인용 검증용 식별자(chunkId 가 없을 때)")
    sourceType: JStr = Field(..., max_length=32)
    materialId: Optional[JLong] = Field(None, ge=1)
    documentId: Optional[JStr] = None
    sourceRevisionHash: Optional[JStr] = Field(None, max_length=128)
    page: Optional[JInt] = Field(None, ge=1)
    chunkId: Optional[JStr] = None
    text: Optional[JStr] = Field(None, max_length=MAX_EVIDENCE_CHARS)

    def ref_id(self) -> Optional[str]:
        return self.chunkId or self.evidenceId


class QualityConstraints(BaseModel):
    """작업별 검증 제약. 모르는 키는 거부(extra=forbid)해 의미 재정의를 막는다. 모든 필드는 Java 와 같이 null 허용."""
    model_config = ConfigDict(extra="forbid")
    allowedMaterialIds: Optional[List[Optional[JLong]]] = None
    allowedDocumentIds: Optional[List[Optional[JStr]]] = None
    expectedQuestionCount: Optional[JInt] = Field(None, ge=1, le=50)
    expectedOptionCount: Optional[JInt] = Field(None, ge=2, le=10)
    expectedAnswer: Optional[JStr] = Field(None, max_length=2000, description="결정적 정답(gold)이 있을 때")
    maxChars: Optional[JInt] = Field(None, ge=1, le=MAX_OUTPUT_CHARS)
    finishReason: Optional[JStr] = Field(None, max_length=32, description="생성기 종료 사유(length=잘림)")
    requireCitations: Optional[JBool] = False
    allowPiiEcho: Optional[JBool] = False
    maxDailyHours: Optional[JDouble] = Field(None, gt=0, le=24)
    deadline: Optional[JStr] = Field(None, max_length=32)
    knownPrerequisites: Optional[List[Optional[JStr]]] = None
    participants: Optional[List[Optional[JStr]]] = None
    expectedPersona: Optional[JStr] = Field(None, max_length=64)
    knowledgeLevel: Optional[JStr] = Field(None, max_length=32)

    @field_validator("requireCitations", "allowPiiEcho", mode="after")
    @classmethod
    def _flag(cls, v: Optional[bool]) -> bool:
        return bool(v)

    @field_validator("allowedMaterialIds", "allowedDocumentIds", "knownPrerequisites", "participants", mode="after")
    @classmethod
    def _lists(cls, v):
        return drop_nulls(v)


class QualityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: JStr
    requestId: JStr
    taskType: TaskType
    outputKind: OutputKind
    modelDigest: Optional[JStr] = Field(None, max_length=128)
    originalRequest: JStr = Field(..., max_length=8000)
    proposedOutput: Any = None  # Java JsonNode: 누락/null 허용(평가기는 EMPTY_OUTPUT 으로 거절)
    groundingEvidence: List[GroundingEvidence] = Field(default_factory=list, max_length=MAX_EVIDENCE_ITEMS)
    constraints: QualityConstraints = Field(default_factory=QualityConstraints)
    attemptIndex: Optional[JInt] = Field(0, ge=0, le=2)
    evaluationProfile: Optional[JStr] = Field(None, max_length=64)

    @field_validator("groundingEvidence", mode="before")
    @classmethod
    def _null_evidence(cls, v):
        return [] if v is None else v

    @field_validator("constraints", mode="before")
    @classmethod
    def _null_constraints(cls, v):
        return {} if v is None else v

    @field_validator("attemptIndex", mode="after")
    @classmethod
    def _null_attempt(cls, v):
        return 0 if v is None else v

    @field_validator("schemaVersion")
    @classmethod
    def _version(cls, v: str) -> str:
        if v != SCHEMA_VERSION:
            raise ValueError(f"unsupported schemaVersion: {v}")
        return v

    @field_validator("requestId")
    @classmethod
    def _rid(cls, v: str) -> str:
        if not _ID_RE.fullmatch(v):
            raise ValueError("requestId must fully match [A-Za-z0-9._:-]{8,128}")
        return v

    @model_validator(mode="after")
    def _size(self) -> "QualityInput":
        po = self.proposedOutput
        # Java: 텍스트면 코드포인트 수, 아니면 JsonNode.toString()(compact, 비 ASCII 그대로) 길이.
        size = 0 if po is None else len(po) if isinstance(po, str) else len(
            json.dumps(po, ensure_ascii=False, separators=(",", ":"), default=str))
        if size > MAX_OUTPUT_CHARS:
            raise ValueError("proposedOutput too large")
        return self


class Violation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: JStr
    severity: Severity
    reason: JStr = Field(..., max_length=300)
    evidenceId: Optional[JStr] = None


class Dimension(BaseModel):
    """Java record Dimension 은 필드 검증을 하지 않는다 → 모두 선택(null 허용). 평가기는 항상 채워서 보낸다."""
    model_config = ConfigDict(extra="forbid")
    name: Optional[JStr] = None
    score: Optional[JDouble] = Field(None, description="None = 검증 불가(unverified)")
    maxScore: Optional[JDouble] = None
    method: Optional[JStr] = Field(None, description="deterministic | evidence | judge | unverified | not_applicable")


class QualityOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: JStr
    requestId: JStr
    taskType: TaskType
    success: JBool = Field(..., description="평가 자체가 완료됐는가(승인 여부 아님)")
    verified: JBool
    qualityStatus: QualityStatus
    score: Optional[JDouble] = None
    minimumScore: Optional[JInt] = MINIMUM_SCORE
    hardFail: JBool
    violations: List[Violation] = Field(default_factory=list)
    dimensions: List[Optional[Dimension]] = Field(default_factory=list)
    regenerationHints: Optional[List[Optional[JStr]]] = None
    evaluatorVersion: JStr
    modelDigest: Optional[JStr] = None
    latencyMs: Optional[JInt] = 0
    mandatoryValidatorsPassed: Optional[JBool] = Field(
        None, description="필수 검증기(안전/PII/스키마/범위 등) 전부 통과 여부. false 면 승인 불가(C-RQ-1)")

    @field_validator("violations", "dimensions", mode="before")
    @classmethod
    def _null_lists(cls, v):
        return [] if v is None else v

    @field_validator("dimensions", mode="after")
    @classmethod
    def _drop_dims(cls, v):
        return drop_nulls(v)

    @field_validator("schemaVersion")
    @classmethod
    def _version(cls, v: str) -> str:
        if v != SCHEMA_VERSION:
            raise ValueError(f"unsupported schemaVersion: {v}")
        return v

    @model_validator(mode="after")
    def _invariants(self) -> "QualityOutput":
        if self.minimumScore is not None and self.minimumScore != MINIMUM_SCORE:
            raise ValueError("minimumScore is fixed at 80 for response-quality.v1")
        # APPROVED 는 오직 규칙을 만족할 때만 존재할 수 있다(Java validate(Output) 와 같은 계약 위반).
        if self.qualityStatus == QualityStatus.APPROVED and not _approvable(self):
            raise ValueError("APPROVED violates approval invariant")
        return self


def _approvable(o: "QualityOutput") -> bool:
    s = o.score
    return (o.success is True and o.verified is True
            and s is not None and not math.isnan(s) and not math.isinf(s) and MINIMUM_SCORE <= s <= MAXIMUM_SCORE
            and (o.minimumScore is None or o.minimumScore == MINIMUM_SCORE)
            and o.hardFail is False
            and not any(v.severity == Severity.HARD for v in o.violations)
            and o.mandatoryValidatorsPassed is not False)


def is_displayable(o: Optional[QualityOutput], expected_request_id: Optional[str]) -> bool:
    """사용자 노출 가능 판정의 유일한 진입점(EC2 isDisplayable 과 동일). 다른 요청의 판정 재사용·None 은 모두 False."""
    return bool(o is not None
                and o.schemaVersion == SCHEMA_VERSION
                and expected_request_id is not None and o.requestId == expected_request_id
                and o.qualityStatus == QualityStatus.APPROVED
                and _approvable(o))


def parse_input_json(raw: bytes | str) -> QualityInput:
    """원시 본문 → QualityInput (Jackson STRICT 동등 파서. 실패는 ValueError 계열)."""
    return QualityInput.model_validate(loads_contract(raw))


def parse_output_json(raw: bytes | str) -> QualityOutput:
    return QualityOutput.model_validate(loads_contract(raw))


def output_to_dict(o: QualityOutput) -> Dict[str, Any]:
    return o.model_dump(mode="json")
