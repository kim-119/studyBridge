"""사람 검수 gold 벤치마크 — 품질 게이트(평가기)의 오승인/오거절을 '실사용형 표본'으로 재는 하네스.

설계(2026-11-04, PROPOSED):
- 규모: 100~500문항. 기본 할당(DOMAIN_QUOTA, 합 300)은 10개 영역 + 안전.
- 출처: 사용자 데이터 금지. 공개 라이선스 자료(CC-BY/CC0/공공누리 1유형) 또는 자체 제작만. 문항마다 sourceLicense/sourceRef 필수.
- 문항: 요청 + 후보 답변(proposedOutput) + 근거(groundingEvidence) + 기대 판정(ACCEPT/REJECT) + 기대 하드실패 코드 +
  정답 근거(answerRationale). REJECT 문항은 오답 유형(수치 불일치/부정 모순/정답키 오류/비밀 노출/주입/범위 위반 …)을 명시.
- 검수: author 1명 + 독립 reviewer 2명(서로/author 와 달라야 함), 불일치는 adjudicator. 수학/코드/PDF 사실 문항은 expertVerified.
  reviewStatus: AI_DRAFT < HUMAN_REVIEWED < EXPERT_VERIFIED. AI_DRAFT 는 측정에 쓰지 않는다.
- 분할: documentGroup/userGroup/근접중복(SimHash) 을 union-find 로 묶어 그룹 단위 dev/test. 누출 검사(그룹·정확해시·근접중복 교차 0).
- 지표: FAR=REJECT 기대 문항 중 승인 비율, FRR=ACCEPT 기대 문항 중 거절 비율, 각 95% Wilson CI(전체/영역별).
  경계 안정성: 점수 79~81 문항을 의미 보존 변형(공백/줄바꿈/문장부호 간격/중립 맺음말)으로 재평가해 승인 뒤집힘 비율.
  judge 편향: judge 사용 시 생성 모델 계열(generatorFamily)이 judge 와 같은/다른 문항의 gold 일치율 차이.
  오승인 사례: FAR 에 해당한 문항 id·영역·기대 하드실패 코드 목록(본문 원문은 보고서에 넣지 않는다).
- 측정 인정 조건: HUMAN_REVIEWED 이상 문항 ≥ MIN_REVIEWED_ITEMS 이고 test 분할에 ACCEPT/REJECT 각 ≥ 30.
  미충족이면 measurementStatus=PREPARED_NOT_MEASURED 로만 보고한다(하네스 동작 확인용 수치는 'smoke' 로 표시).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

BENCHMARK_SCHEMA = "quality-gold.v1"
MIN_REVIEWED_ITEMS = 100
MIN_PER_LABEL_IN_TEST = 30
THRESHOLD = 80.0

DOMAIN_QUOTA = {   # 기본 300문항 할당(영역별 ACCEPT/REJECT 대략 1:1)
    "GENERAL": 30, "MATH": 30, "CODE": 30, "PDF_QA": 40, "PDF_SUMMARY": 30, "QUIZ": 30, "WRONG_NOTE": 20,
    "PLANNER": 20, "MINDMAP": 20, "VISION": 20, "SAFETY": 30,
}
ALLOWED_LICENSES = {"SELF_MADE_CC0", "CC0", "CC-BY-4.0", "CC-BY-SA-4.0", "KOGL-TYPE1", "PUBLIC_DOMAIN"}


class ReviewStatus(str, Enum):
    AI_DRAFT = "AI_DRAFT"
    HUMAN_REVIEWED = "HUMAN_REVIEWED"
    EXPERT_VERIFIED = "EXPERT_VERIFIED"


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ReviewStatus
    authorId: str = Field(..., min_length=2, max_length=64)
    reviewerIds: List[str] = Field(default_factory=list)
    adjudicatorId: Optional[str] = None
    expertVerified: bool = False
    disagreement: bool = False

    @model_validator(mode="after")
    def _independent(self):
        if self.status != ReviewStatus.AI_DRAFT:
            ids = [r for r in self.reviewerIds if r]
            if len(set(ids)) < 2 or self.authorId in ids:
                raise ValueError("HUMAN_REVIEWED 이상은 author 와 다른 독립 reviewer 2명 이상이 필요")
            if self.disagreement and not self.adjudicatorId:
                raise ValueError("검수 불일치 문항은 adjudicator 필요")
        if self.status == ReviewStatus.EXPERT_VERIFIED and not self.expertVerified:
            raise ValueError("EXPERT_VERIFIED 는 expertVerified=true")
        return self


class GoldItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: str = BENCHMARK_SCHEMA
    itemId: str = Field(..., pattern=r"^[A-Za-z0-9._\-]{4,64}$")  # pydantic(Rust regex) $ 는 끝 개행 불허
    domain: str
    taskType: str
    outputKind: str = "text"
    request: str = Field(..., min_length=1, max_length=4000)
    proposedOutput: Any
    groundingEvidence: List[Dict[str, Any]] = Field(default_factory=list)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    expectedLabel: str = Field(..., pattern=r"^(ACCEPT|REJECT)$")
    expectedHardFail: List[str] = Field(default_factory=list)
    errorType: Optional[str] = None             # REJECT 문항의 오답 유형
    answerRationale: str = Field(..., min_length=5, max_length=2000)
    sourceLicense: str
    sourceRef: str = Field(..., min_length=3, max_length=300)
    documentGroup: str = Field(..., min_length=1, max_length=64)
    userGroup: str = Field("synthetic", min_length=1, max_length=64)
    generatorFamily: Optional[str] = None       # 후보 답변을 만든 모델 계열(judge 편향 분석용), 사람 작성이면 'human'
    review: Review

    @model_validator(mode="after")
    def _rules(self):
        if self.domain not in DOMAIN_QUOTA:
            raise ValueError(f"unknown domain {self.domain}")
        if self.sourceLicense not in ALLOWED_LICENSES:
            raise ValueError("허용되지 않은 출처 라이선스(사용자 데이터/저작권 불명 금지)")
        if self.expectedLabel == "REJECT" and not (self.errorType or self.expectedHardFail):
            raise ValueError("REJECT 문항은 errorType 또는 expectedHardFail 필요")
        if self.expectedLabel == "ACCEPT" and self.expectedHardFail:
            raise ValueError("ACCEPT 문항에 expectedHardFail 불가")
        return self


def load_items(path: Path) -> List[GoldItem]:
    out = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                out.append(GoldItem.model_validate_json(line))
            except Exception as e:  # noqa: BLE001
                raise ValueError(f"{path}:{n}: {e}") from None
    ids = [i.itemId for i in out]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate itemId")
    return out


# ── 통계 ─────────────────────────────────────────────────────────────────────
def wilson(k: int, n: int, z: float = 1.959963984540054) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """(점추정, 하한, 상한). n=0 이면 (None, None, None)."""
    if n <= 0:
        return None, None, None
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, max(0.0, centre - half), min(1.0, centre + half)


# ── 분할/누출 ────────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip().lower()


def _text_of(x: Any) -> str:
    return x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, sort_keys=True)


def content_hash(it: GoldItem) -> str:
    return hashlib.sha256((_norm(it.request) + "\n" + _norm(_text_of(it.proposedOutput))).encode()).hexdigest()


def _simhash(text: str) -> int:
    from app.utils.duplicate_checker import simhash64
    return simhash64(text)


def group_split(items: List[GoldItem], *, test_fraction: float = 0.5, near_dup_bits: int = 6) -> Dict[str, str]:
    """union-find(문서/사용자 그룹 + 근접중복) → 그룹 해시로 결정적 dev/test 배정. {itemId: 'dev'|'test'}"""
    parent = {i.itemId: i.itemId for i in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    by_key: Dict[str, str] = {}
    for it in items:
        for k in (f"doc:{it.documentGroup}", f"user:{it.userGroup}" if it.userGroup != "synthetic" else None):
            if k is None:
                continue
            if k in by_key:
                union(by_key[k], it.itemId)
            else:
                by_key[k] = it.itemId
    sims = [(it.itemId, _simhash(_norm(it.request + " " + _text_of(it.proposedOutput)))) for it in items]
    for i in range(len(sims)):
        for j in range(i + 1, len(sims)):
            if bin(sims[i][1] ^ sims[j][1]).count("1") <= near_dup_bits:
                union(sims[i][0], sims[j][0])
    out = {}
    for it in items:
        g = find(it.itemId)
        h = int(hashlib.sha256(g.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        out[it.itemId] = "test" if h < test_fraction else "dev"
    return out


def leakage_report(items: List[GoldItem], split: Dict[str, str], *, near_dup_bits: int = 6) -> Dict[str, int]:
    dev = [i for i in items if split[i.itemId] == "dev"]
    test = [i for i in items if split[i.itemId] == "test"]
    docs = {i.documentGroup for i in dev} & {i.documentGroup for i in test}
    users = ({i.userGroup for i in dev} & {i.userGroup for i in test}) - {"synthetic"}
    hashes = {content_hash(i) for i in dev} & {content_hash(i) for i in test}
    sd = [_simhash(_norm(i.request + " " + _text_of(i.proposedOutput))) for i in dev]
    st = [_simhash(_norm(i.request + " " + _text_of(i.proposedOutput))) for i in test]
    near = sum(1 for a in sd for b in st if bin(a ^ b).count("1") <= near_dup_bits)
    return {"sharedDocumentGroups": len(docs), "sharedUserGroups": len(users), "sharedExactHashes": len(hashes),
            "nearDuplicatePairs": near}


# ── 평가 ─────────────────────────────────────────────────────────────────────
_PERTURB = (
    lambda s: s + "\n",
    lambda s: re.sub(r" ", "  ", s, count=1),
    lambda s: s.replace(". ", ".\n"),
    lambda s: s.rstrip() + " 이해에 도움이 되길 바랍니다.",
)


def _perturb(out: Any, k: int) -> Any:
    return _PERTURB[k](out) if isinstance(out, str) else out


@dataclass
class ItemResult:
    itemId: str
    domain: str
    split: str
    expected: str
    approved: bool
    status: str
    score: Optional[float]
    hardCodes: List[str]
    reviewStatus: str
    generatorFamily: Optional[str]
    judgeVerdict: Optional[str] = None
    boundaryFlips: Optional[int] = None
    boundaryTrials: int = 0


@dataclass
class BenchmarkReport:
    measurementStatus: str
    reasons: List[str]
    counts: Dict[str, Any]
    leakage: Dict[str, int]
    overall: Dict[str, Any]
    byDomain: Dict[str, Any]
    boundary: Dict[str, Any]
    judgeBias: Dict[str, Any]
    falseApprovals: List[Dict[str, Any]]
    quotaCoverage: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__


def _quality_input(it: GoldItem, output: Any):
    from app.contracts.response_quality_v1 import SCHEMA_VERSION, QualityInput
    return QualityInput.model_validate({
        "schemaVersion": SCHEMA_VERSION, "requestId": f"gold-{it.itemId}"[:128], "taskType": it.taskType,
        "outputKind": it.outputKind, "originalRequest": it.request, "proposedOutput": output,
        "groundingEvidence": it.groundingEvidence, "constraints": it.constraints})


def _rate(results: List[ItemResult]) -> Dict[str, Any]:
    rej = [r for r in results if r.expected == "REJECT"]
    acc = [r for r in results if r.expected == "ACCEPT"]
    fa = sum(1 for r in rej if r.approved)
    fr = sum(1 for r in acc if not r.approved)
    far, far_lo, far_hi = wilson(fa, len(rej))
    frr, frr_lo, frr_hi = wilson(fr, len(acc))
    return {"n": len(results), "expectedReject": len(rej), "expectedAccept": len(acc), "falseAccepts": fa,
            "falseRejects": fr, "FAR": far, "FAR_CI95": [far_lo, far_hi], "FRR": frr, "FRR_CI95": [frr_lo, frr_hi]}


async def run_benchmark(items: List[GoldItem], evaluate: Callable[[Any], Awaitable[Any]], *,
                        judge_enabled: bool = False, judge_family: Optional[str] = None,
                        boundary_band: Tuple[float, float] = (79.0, 81.0)) -> BenchmarkReport:
    from app.contracts.response_quality_v1 import Severity, is_displayable
    split = group_split(items)
    leak = leakage_report(items, split)
    results: List[ItemResult] = []
    for it in items:
        o = await evaluate(_quality_input(it, it.proposedOutput))
        r = ItemResult(itemId=it.itemId, domain=it.domain, split=split[it.itemId], expected=it.expectedLabel,
                       approved=bool(is_displayable(o)), status=o.qualityStatus.value, score=o.score,
                       hardCodes=sorted({v.code for v in o.violations if v.severity == Severity.HARD}),
                       reviewStatus=it.review.status.value, generatorFamily=it.generatorFamily,
                       judgeVerdict=next((d.method for d in o.dimensions if (d.method or "").startswith("judge")), None)
                       if judge_enabled else None)
        if o.score is not None and boundary_band[0] <= o.score <= boundary_band[1] and isinstance(it.proposedOutput, str):
            flips = 0
            for k in range(len(_PERTURB)):
                o2 = await evaluate(_quality_input(it, _perturb(it.proposedOutput, k)))
                flips += int(bool(is_displayable(o2)) != r.approved)
            r.boundaryFlips, r.boundaryTrials = flips, len(_PERTURB)
        results.append(r)

    reviewed = [r for r in results if r.reviewStatus != ReviewStatus.AI_DRAFT.value]
    test_rev = [r for r in reviewed if r.split == "test"]
    reasons = []
    if len(reviewed) < MIN_REVIEWED_ITEMS:
        reasons.append(f"HUMAN_REVIEWED_ITEMS {len(reviewed)} < {MIN_REVIEWED_ITEMS}")
    for lab in ("ACCEPT", "REJECT"):
        n = sum(1 for r in test_rev if r.expected == lab)
        if n < MIN_PER_LABEL_IN_TEST:
            reasons.append(f"TEST_{lab} {n} < {MIN_PER_LABEL_IN_TEST}")
    if any(v for v in leak.values()):
        reasons.append("SPLIT_LEAKAGE")
    measured = not reasons
    basis = test_rev if measured else results              # 미측정이면 전 문항으로 '하네스 smoke' 수치만
    by_domain = {d: _rate([r for r in basis if r.domain == d]) for d in sorted({r.domain for r in basis})}
    band = [r for r in results if r.boundaryTrials]
    flips = sum(r.boundaryFlips or 0 for r in band)
    trials = sum(r.boundaryTrials for r in band)
    fr_, lo, hi = wilson(flips, trials)
    jb: Dict[str, Any] = {"enabled": judge_enabled, "judgeFamily": judge_family}
    if judge_enabled and judge_family:
        for tag, grp in (("sameFamily", [r for r in basis if r.generatorFamily == judge_family]),
                         ("otherFamily", [r for r in basis if r.generatorFamily not in (None, judge_family)])):
            ok = sum(1 for r in grp if (r.approved and r.expected == "ACCEPT") or (not r.approved and r.expected == "REJECT"))
            p, l, h = wilson(ok, len(grp))
            jb[tag] = {"n": len(grp), "goldAgreement": p, "CI95": [l, h]}
    counts = {"items": len(items), "humanReviewed": len(reviewed),
              "expertVerified": sum(1 for i in items if i.review.status == ReviewStatus.EXPERT_VERIFIED),
              "aiDraft": sum(1 for i in items if i.review.status == ReviewStatus.AI_DRAFT),
              "split": {s: sum(1 for v in split.values() if v == s) for s in ("dev", "test")}}
    cov = {d: {"have": sum(1 for i in items if i.domain == d), "quota": q} for d, q in DOMAIN_QUOTA.items()}
    return BenchmarkReport(
        measurementStatus="MEASURED" if measured else "PREPARED_NOT_MEASURED", reasons=reasons, counts=counts,
        leakage=leak, overall={**_rate(basis), "basis": "test(HUMAN_REVIEWED+)" if measured else "smoke(all items)"},
        byDomain=by_domain,
        boundary={"band": list(boundary_band), "items": len(band), "trials": trials, "flips": flips,
                  "flipRate": fr_, "CI95": [lo, hi]},
        judgeBias=jb,
        falseApprovals=[{"itemId": r.itemId, "domain": r.domain, "score": r.score, "status": r.status}
                        for r in basis if r.expected == "REJECT" and r.approved],
        quotaCoverage=cov)
