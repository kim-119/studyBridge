"""학습 후보 레코드/이벤트 데이터 구조(저장소 독립)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.training_pipeline.states import CandidateState


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class CandidateRecord:
    candidate_id: str
    event_id: str
    pseudonymous_user_key: str
    state: CandidateState
    source_kind: str
    question: str
    candidate_answer: str
    content_hash: str
    simhash: int
    deletion_tracking_id: str
    retention_policy: str
    model_name: str
    rights_status: str
    task_type: Optional[str] = None
    verified_answer: Optional[str] = None
    verification: Optional[Dict[str, Any]] = None
    user_correction: Optional[str] = None
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    consent_version: Optional[str] = None
    consent_timestamp: Optional[datetime] = None
    consent_granted: bool = False
    consent_scope: List[str] = field(default_factory=list)
    consent_withdrawn: bool = False
    model_digest: Optional[str] = None
    prompt_template_version: Optional[str] = None
    source_revision_hash: Optional[str] = None
    quality_label: str = "UNLABELED"
    display_quality_score: Optional[float] = None      # 80점 USER_DISPLAY_GATE 점수(학습 자격과 무관)
    display_quality_status: Optional[str] = None
    quality_evaluator_version: Optional[str] = None
    feedback_score: Optional[int] = None
    feedback_history: List[int] = field(default_factory=list)
    pii_status: str = "UNSCANNED"
    pii_categories: List[str] = field(default_factory=list)
    content_masked: bool = False
    content_destroyed: bool = False
    near_duplicate_of: Optional[str] = None
    eligibility_reasons: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    version: int = 0

    def training_target(self) -> Optional[str]:
        return self.verified_answer


@dataclass(frozen=True)
class CandidateEvent:
    """불변 이벤트. 내용 원문은 담지 않는다(id/상태/사유 코드/해시만)."""
    event_id: str
    candidate_id: str
    event_type: str
    from_state: Optional[str]
    to_state: Optional[str]
    actor: str
    actor_role: str
    request_id: Optional[str]
    reason_codes: List[str]
    at: datetime
    prev_hash: str
    event_hash: str

    @staticmethod
    def build(*, event_id: str, candidate_id: str, event_type: str, from_state: Optional[str],
              to_state: Optional[str], actor: str, actor_role: str, request_id: Optional[str],
              reason_codes: List[str], prev_hash: str, at: Optional[datetime] = None) -> "CandidateEvent":
        at = at or utcnow()
        body = json.dumps({"e": event_id, "c": candidate_id, "t": event_type, "f": from_state, "to": to_state,
                           "a": actor, "r": actor_role, "q": request_id, "rc": reason_codes,
                           "at": at.isoformat(), "p": prev_hash}, sort_keys=True)
        return CandidateEvent(event_id=event_id, candidate_id=candidate_id, event_type=event_type,
                              from_state=from_state, to_state=to_state, actor=actor, actor_role=actor_role,
                              request_id=request_id, reason_codes=list(reason_codes), at=at, prev_hash=prev_hash,
                              event_hash=hashlib.sha256(body.encode()).hexdigest())


@dataclass
class ManifestRecord:
    dataset_id: str
    status: str                       # PENDING | ACTIVE | INVALIDATED
    manifest_sha256: str
    member_hashes: List[str]
    created_at: datetime
    invalidated_reasons: List[str] = field(default_factory=list)


@dataclass
class ModelCandidateRecord:
    """오프라인 학습 산출물(어댑터) 후보 등록. 운영 모델 태그와 분리된 candidate tag 만 기록한다."""
    adapter_id: str
    dataset_id: str
    base_model: str
    status: str                       # REGISTERED | EVALUATING | REJECTED | APPROVED_FOR_CANARY | RETIREMENT_REQUIRED
    candidate_tag: Optional[str] = None
    notes: List[str] = field(default_factory=list)


def record_to_public_dict(rec: CandidateRecord) -> Dict[str, Any]:
    """관리 API 응답용: 내용 원문 없이 메타데이터만."""
    d = asdict(rec)
    for k in ("question", "candidate_answer", "verified_answer", "user_correction", "evidence"):
        d.pop(k, None)
    d["state"] = rec.state.value
    for k in ("created_at", "updated_at", "consent_timestamp"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d
