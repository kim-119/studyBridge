"""training-control.v1 — 학습 데이터 동의 철회·자료 삭제·피드백 제어 메시지(Phase B3, 인계 C-SIG-2).

내부 Bearer 만으로는 받지 않는다. 모든 제어 메시지는 다음을 전부 통과해야 처리한다:
  1) 본문 HMAC: X-AI-Contract-Signature / X-AI-Contract-Timestamp (AI_TRAINING_SAMPLE_SIGNING_KEY, ±300s) — 원시 바이트 그대로
  2) 본문 계약: schemaVersion=training-control.v1, typ=training-control, messageType 이 라우트와 일치(용도 간 재사용 차단),
     eventId 형식, 가명 사용자 키 형식(직접 식별자 거부), scope ⊆ {MODEL_TRAINING}, issuedAt 타임존 필수·미래 금지
  3) X-Request-Id == eventId (요청-메시지 바인딩)
  4) 재전송: eventId 는 DB 원장(ai.training_processed_event)에 한 번만 처리된다. 같은 본문 재전송 = 이전 결과 재생,
     다른 본문 = 409, 다른 워커가 처리 중 = 503(재시도). 프로세스 메모리에 의존하지 않는다.

EC2 가 보내야 하는 본문(필드 순서 무관, 모르는 필드 거부):
  CONSENT_WITHDRAWAL {schemaVersion, typ, messageType, eventId, issuedAt, pseudonymousUserKey, scope:["MODEL_TRAINING"]}
  DELETION           {schemaVersion, typ, messageType, eventId, issuedAt, deletionTrackingId, pseudonymousUserKey?}
  FEEDBACK           {schemaVersion, typ, messageType, eventId, issuedAt, pseudonymousUserKey,
                      candidateEventId | contentHash, score(-1|0|1), reasonCode?}
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.contracts.jtypes import JInt, JOffsetDateTime, JStr, loads_contract

SCHEMA_VERSION = "training-control.v1"
CONTROL_TYP = "training-control"
ALLOWED_SCOPES = frozenset({"MODEL_TRAINING"})
_ID_RE = re.compile(r"[A-Za-z0-9._:\-]{8,128}")
_PK_RE = re.compile(r"[A-Za-z0-9_\-]{16,128}")
_HEX64 = re.compile(r"[0-9a-f]{64}")


class MessageType(str, Enum):
    CONSENT_WITHDRAWAL = "CONSENT_WITHDRAWAL"
    DELETION = "DELETION"
    FEEDBACK = "FEEDBACK"


class ControlError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status, self.code = status, code


def _pk_ok(v: Optional[str]) -> bool:
    return v is not None and _PK_RE.fullmatch(v) is not None and not v.isdigit()


class TrainingControlV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: JStr
    typ: JStr
    messageType: MessageType
    eventId: JStr
    issuedAt: JOffsetDateTime
    pseudonymousUserKey: Optional[JStr] = None
    deletionTrackingId: Optional[JStr] = None
    scope: List[JStr] = Field(default_factory=list, max_length=8)
    candidateEventId: Optional[JStr] = None
    contentHash: Optional[JStr] = None
    score: Optional[JInt] = Field(None, ge=-1, le=1)
    reasonCode: Optional[JStr] = Field(None, max_length=64)

    @field_validator("schemaVersion")
    @classmethod
    def _v(cls, v):
        if v != SCHEMA_VERSION:
            raise ValueError("unsupported schemaVersion")
        return v

    @field_validator("typ")
    @classmethod
    def _typ(cls, v):
        if v != CONTROL_TYP:
            raise ValueError("typ must be training-control")
        return v

    @field_validator("eventId", "deletionTrackingId", "candidateEventId")
    @classmethod
    def _ids(cls, v):
        if v is not None and not _ID_RE.fullmatch(v):
            raise ValueError("invalid identifier")
        return v

    @field_validator("pseudonymousUserKey")
    @classmethod
    def _pk(cls, v):
        if v is not None and not _pk_ok(v):
            raise ValueError("pseudonymousUserKey must be an opaque pseudonymous token")
        return v

    @field_validator("contentHash")
    @classmethod
    def _hash(cls, v):
        if v is not None and not _HEX64.fullmatch(v):
            raise ValueError("contentHash must be lowercase sha256 hex")
        return v

    @model_validator(mode="after")
    def _per_type(self):
        if not set(self.scope) <= ALLOWED_SCOPES:
            raise ValueError("scope outside allowed set")
        t = self.messageType
        if t == MessageType.CONSENT_WITHDRAWAL:
            if self.pseudonymousUserKey is None or "MODEL_TRAINING" not in self.scope:
                raise ValueError("withdrawal requires pseudonymousUserKey and scope MODEL_TRAINING")
            if any(x is not None for x in (self.deletionTrackingId, self.candidateEventId, self.contentHash, self.score)):
                raise ValueError("withdrawal carries only user key and scope")
        elif t == MessageType.DELETION:
            if self.deletionTrackingId is None:
                raise ValueError("deletion requires deletionTrackingId")
            if any(x is not None for x in (self.candidateEventId, self.contentHash, self.score)):
                raise ValueError("deletion carries no feedback fields")
        elif t == MessageType.FEEDBACK:
            if self.pseudonymousUserKey is None or self.score is None:
                raise ValueError("feedback requires pseudonymousUserKey and score")
            if (self.candidateEventId is None) == (self.contentHash is None):
                raise ValueError("feedback requires exactly one of candidateEventId / contentHash")
            if self.deletionTrackingId is not None:
                raise ValueError("feedback carries no deletionTrackingId")
        return self


def body_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def verify_control(raw: bytes, *, signature: Optional[str], timestamp: Optional[str], request_id: Optional[str],
                   expected: MessageType, now: Optional[datetime] = None) -> TrainingControlV1:
    """서명 → 계약 → 바인딩 순서로 검증. 실패는 ControlError(status, code). 원문/키는 오류에 싣지 않는다."""
    from app.contracts.signing import SignatureError, verify_body
    try:
        verify_body(raw, signature, timestamp, env_name="AI_TRAINING_SAMPLE_SIGNING_KEY",
                    now=None if now is None else now.timestamp())
    except SignatureError as e:
        raise ControlError(503 if e.code in ("SIGNING_KEY_NOT_CONFIGURED", "SIGNING_KEY_REUSED") else 401, e.code)
    try:
        msg = TrainingControlV1.model_validate(loads_contract(raw))
    except (ValidationError, ValueError):
        raise ControlError(422, "CONTROL_CONTRACT_INVALID")
    if msg.messageType != expected:
        raise ControlError(422, "CONTROL_MESSAGE_TYPE_MISMATCH")
    if not request_id or request_id != msg.eventId:
        raise ControlError(400, "REQUEST_ID_EVENT_MISMATCH")
    t = now or datetime.now(timezone.utc)
    if msg.issuedAt > t + timedelta(seconds=30):
        raise ControlError(422, "CONTROL_ISSUED_IN_FUTURE")
    return msg
