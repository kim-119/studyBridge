"""학습 자격(TRAIN_ELIGIBLE) 판정 — 모든 조건의 AND. 하나라도 빠지면 학습 금지.

자격 = 동의(EC2 서명 claim, MODEL_TRAINING 범위, 미철회)
     AND 자료 권리 확인(제3자 PDF 권리 미확인 금지)
     AND PII/비밀 검사 CLEAN(지금 다시 스캔 — 저장된 판정을 믿지 않음)
     AND 사실 검증(사람 검수 또는 결정적 gold; LLM judge 단독 불가)
     AND 샘플 독립성(모델 자기 출력을 모델이 승인한 자기증폭 아님)
     AND 미철회/미삭제/부정 피드백 없음
     AND (PDF 계열) 원문 근거 provenance + 원문 일치 검사 통과
'질문했다/AI가 답했다/좋아요/score>=80' 은 자격 근거가 아니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from app.contracts.training_sample_v1 import RIGHTS_OK, RightsStatus, VerificationMethod
from app.training_pipeline.records import CandidateRecord
from app.training_pipeline.states import CandidateState
from app.utils.pii_filter import scan_pii

TRAINING_CONSENT_SCOPE = "MODEL_TRAINING"
DETERMINISTIC_METHODS = {VerificationMethod.MATH_CHECK.value, VerificationMethod.CODE_TESTS.value,
                         VerificationMethod.EXACT_MATCH_GOLD.value, VerificationMethod.PDF_SPAN_MATCH.value}
PDF_KINDS = {"PDF_QA", "PDF_SUMMARY", "PDF_QUIZ"}


@dataclass
class EligibilityResult:
    eligible: bool
    reasons: List[str] = field(default_factory=list)


def evaluate_eligibility(rec: CandidateRecord) -> EligibilityResult:
    r: List[str] = []

    if rec.state in (CandidateState.REVOKED, CandidateState.DELETED, CandidateState.REJECTED,
                     CandidateState.QUARANTINED):
        r.append(f"STATE_{rec.state.value}")
    elif rec.state not in (CandidateState.VERIFIED, CandidateState.TRAIN_ELIGIBLE):
        r.append("STATE_NOT_VERIFIED")
    if rec.content_destroyed:
        r.append("CONTENT_DESTROYED")

    # 1. 동의
    if not rec.consent_version or rec.consent_timestamp is None:
        r.append("CONSENT_MISSING")
    if not rec.consent_granted:
        r.append("CONSENT_NOT_GRANTED")
    if TRAINING_CONSENT_SCOPE not in (rec.consent_scope or []):
        r.append("CONSENT_SCOPE_MISSING")
    if rec.consent_withdrawn:
        r.append("CONSENT_WITHDRAWN")

    # 2. 권리
    try:
        rights_ok = RightsStatus(rec.rights_status) in RIGHTS_OK
    except ValueError:
        rights_ok = False
    if not rights_ok:
        r.append("RIGHTS_UNVERIFIED")

    # 3. 사실 검증 + 독립성
    target = rec.verified_answer
    v = rec.verification or {}
    method = str(v.get("method") or "NONE")
    if not target or not target.strip():
        r.append("VERIFIED_ANSWER_MISSING")
    if method in DETERMINISTIC_METHODS and not v.get("goldReference"):
        r.append("GOLD_REFERENCE_MISSING")
    if method == VerificationMethod.HUMAN_REVIEW.value or method in DETERMINISTIC_METHODS:
        if not v.get("reviewerId"):
            r.append("REVIEWER_ID_MISSING")      # 결정적 검증이어도 책임 검수자 기록 필수
    else:
        # NONE / LLM_JUDGE: 모델 출력을 (같은 계열) 모델이 맞다고 한 것만으로는 학습 정답이 될 수 없다.
        r.append("VERIFICATION_INSUFFICIENT")
    if rec.quality_label in ("INCORRECT", "UNVERIFIABLE"):
        r.append(f"QUALITY_LABEL_{rec.quality_label}")

    # 4. 피드백: 학습 타깃이 '원래 AI 답변'일 때 부정 피드백이 있으면 금지.
    #    (사용자가 틀렸다고 하고 검증된 수정 답변이 타깃이면 부정 피드백은 원 답변에 대한 것)
    if rec.feedback_score is not None and rec.feedback_score < 0:
        if not target or target.strip() == (rec.candidate_answer or "").strip():
            r.append("NEGATIVE_FEEDBACK")

    # 5. PII/비밀 재검사(fail-closed)
    texts = [rec.question, target or ""] + [str(e.get("quote") or "") for e in rec.evidence or []]
    for t in texts:
        res = scan_pii(t)
        if not res.clean:
            r.append("PII_SCAN_ERROR" if res.status == "ERROR" else "PII_NOT_CLEAR")
            break
    if rec.content_masked:
        r.append("CONTENT_MASKED")

    # 6. PDF 계열: 원문 provenance + 원문 일치
    if rec.source_kind in PDF_KINDS:
        quotes = [e for e in rec.evidence or [] if e.get("quote") and e.get("page") and e.get("chunkId")]
        if not quotes or not rec.source_revision_hash:
            r.append("EVIDENCE_PROVENANCE_MISSING")
        elif target:
            from app.quality_gate.checks import source_fidelity_violations
            if source_fidelity_violations(target, [e["quote"] for e in quotes]):
                r.append("NOT_SOURCE_FAITHFUL")

    if rec.near_duplicate_of:
        r.append("NEAR_DUPLICATE_UNRESOLVED")

    return EligibilityResult(eligible=not r, reasons=sorted(set(r)))
