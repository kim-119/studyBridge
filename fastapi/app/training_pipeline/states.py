"""학습 후보 정규 상태와 전이 규칙."""
from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet


class CandidateState(str, Enum):
    COLLECTED = "COLLECTED"          # 수집됨(아무 검증 전)
    QUARANTINED = "QUARANTINED"      # PII/비밀/검사 오류 의심 → 마스킹 사본만 보관, 별도 검토
    NEEDS_REVIEW = "NEEDS_REVIEW"    # 사람 검수 또는 결정적 gold 검증 대기
    VERIFIED = "VERIFIED"            # 정답 검증 완료(아직 동의/권리 게이트 전)
    TRAIN_ELIGIBLE = "TRAIN_ELIGIBLE"  # 모든 학습 자격 충족
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"              # 부정 피드백/동의 철회로 학습 사용 철회
    DELETED = "DELETED"              # 사용자 자료 삭제 → 내용 파기, 해시/lineage 만 남김


S = CandidateState

ALLOWED_TRANSITIONS: Dict[CandidateState, FrozenSet[CandidateState]] = {
    S.COLLECTED: frozenset({S.QUARANTINED, S.NEEDS_REVIEW, S.REJECTED, S.REVOKED, S.DELETED}),
    S.QUARANTINED: frozenset({S.NEEDS_REVIEW, S.REJECTED, S.REVOKED, S.DELETED}),
    S.NEEDS_REVIEW: frozenset({S.VERIFIED, S.REJECTED, S.QUARANTINED, S.REVOKED, S.DELETED}),
    S.VERIFIED: frozenset({S.TRAIN_ELIGIBLE, S.NEEDS_REVIEW, S.QUARANTINED, S.REJECTED, S.REVOKED, S.DELETED}),
    # PII 가 섞인 사용자 수정 답변 등 → 격리(예전: 전이 불가 → 500, 후보는 TRAIN_ELIGIBLE 유지 — 2026-11-04 재현)
    S.TRAIN_ELIGIBLE: frozenset({S.NEEDS_REVIEW, S.QUARANTINED, S.REJECTED, S.REVOKED, S.DELETED}),
    S.REJECTED: frozenset({S.NEEDS_REVIEW, S.QUARANTINED, S.REVOKED, S.DELETED}),
    S.REVOKED: frozenset({S.DELETED}),
    S.DELETED: frozenset(),
}

# 레거시 quality_status → 정규 상태. 레거시 '승인'은 동의/권리/사실 검증 근거가 없으므로
# 절대 TRAIN_ELIGIBLE/VERIFIED 로 승격하지 않고 NEEDS_REVIEW 로 내린다.
LEGACY_STATUS_MAP: Dict[str, CandidateState] = {
    "auto_collected": S.COLLECTED,
    "auto_approved": S.NEEDS_REVIEW,
    "manual_approved": S.NEEDS_REVIEW,
    "holdout": S.NEEDS_REVIEW,
    "auto_rejected": S.REJECTED,
    "rejected": S.REJECTED,
    "duplicate": S.REJECTED,
    "unsafe": S.QUARANTINED,
}


class InvalidTransition(Exception):
    def __init__(self, src: CandidateState, dst: CandidateState):
        super().__init__(f"{src.value} -> {dst.value} not allowed")
        self.src, self.dst = src, dst


def from_legacy(status: str) -> CandidateState:
    return LEGACY_STATUS_MAP.get((status or "").strip().lower(), S.NEEDS_REVIEW)


def check_transition(src: CandidateState, dst: CandidateState) -> None:
    if dst not in ALLOWED_TRANSITIONS[src]:
        raise InvalidTransition(src, dst)
