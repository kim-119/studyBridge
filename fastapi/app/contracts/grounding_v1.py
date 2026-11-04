"""grounding.v1 — 생성 응답에 싣는 '원문 근거' 계약(EC2 Phase D 요청 R1, ai07 owner 제안 → EC2 합의 대상).

생성 응답(JSON)의 선택 필드 `grounding`:
    {"schemaVersion": "grounding.v1",
     "evidence": [{"evidenceId": "ev-1", "sourceType": "PDF_ORIGINAL", "materialId": 345, "documentId": "doc-…",
                   "chunkId": "m345-c12", "page": 4, "quote": "원문 그대로(≤1000자)", "charStart": 10233, "charEnd": 10410}]}

규칙(Spring 은 받은 근거를 입력 원문과 대조한 뒤에만 response-quality.v1 groundingEvidence 로 넘긴다):
- quote 는 요청에 들어온 원문 문자열의 부분 문자열 그대로다(요약·의역·정규화 금지). charStart/charEnd 가 있으면
  original[charStart:charEnd] == quote 가 성립한다(파이썬 str 인덱스 = 코드포인트. Java String 인덱스(UTF-16)와는
  BMP 밖 문자에서 다르므로 Spring 은 오프셋이 아니라 '부분 문자열 일치'로 대조한다 — 오프셋은 참고용).
- 페이지를 확정할 수 없으면 page 를 생략한다(추측 금지). 확정 근거 = 원문의 \\f(폼피드) 페이지 구분 또는 [Page N]/[페이지 N] 표식.
- 원문에서 위치를 찾지 못한 청크는 근거로 내보내지 않는다(없는 근거보다 적은 근거가 안전).
- WEB 근거는 외부 전송 정책(B-EGRESS) 결정 전에는 비어 있는 것이 정상.
- 이 모듈은 app.contracts / app.quality_gate 만 import 한다(EC2 격리 E2E 가 이 두 패키지만 추출한다).
"""
from __future__ import annotations

import bisect
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.jtypes import JInt, JLong, JStr

SCHEMA_VERSION = "grounding.v1"
MAX_EVIDENCE = 32
MAX_QUOTE_CHARS = 1000

SOURCE_PDF = "PDF_ORIGINAL"
SOURCE_WEB = "WEB"
# 비전(화면 판독) 관측: response-quality.v1 groundingEvidence.sourceType 으로 그대로 쓰인다(≤32자).
SOURCE_VISION = "VISION_OBSERVATION"
SOURCE_VISION_UNCERTAIN = "VISION_OBSERVATION_UNCERTAIN"
SOURCE_TYPES = (SOURCE_PDF, SOURCE_WEB)

_EVIDENCE_ID_RE = re.compile(r"[A-Za-z0-9._:\-]{1,64}")
_CHUNK_ID_RE = re.compile(r"[A-Za-z0-9._:\-]{1,128}")
_PAGE_MARK_RE = re.compile(r"\[(?:Page|페이지)\s*(\d{1,5})\]", re.IGNORECASE)


class EvidenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidenceId: JStr
    sourceType: JStr
    materialId: Optional[JLong] = Field(None, ge=1)
    documentId: Optional[JStr] = Field(None, max_length=128)
    chunkId: Optional[JStr] = None
    page: Optional[JInt] = Field(None, ge=1)
    quote: JStr = Field(..., min_length=1, max_length=MAX_QUOTE_CHARS)
    charStart: Optional[JInt] = Field(None, ge=0)
    charEnd: Optional[JInt] = Field(None, ge=1)
    url: Optional[JStr] = Field(None, max_length=2048)

    @field_validator("evidenceId")
    @classmethod
    def _eid(cls, v: str) -> str:
        if not _EVIDENCE_ID_RE.fullmatch(v):
            raise ValueError("evidenceId must fully match [A-Za-z0-9._:-]{1,64}")
        return v

    @field_validator("chunkId")
    @classmethod
    def _cid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _CHUNK_ID_RE.fullmatch(v):
            raise ValueError("chunkId must fully match [A-Za-z0-9._:-]{1,128}")
        return v

    @field_validator("sourceType")
    @classmethod
    def _src(cls, v: str) -> str:
        if v not in SOURCE_TYPES:
            raise ValueError(f"unsupported sourceType: {v}")
        return v

    @model_validator(mode="after")
    def _span(self) -> "EvidenceV1":
        if (self.charStart is None) != (self.charEnd is None):
            raise ValueError("charStart/charEnd must be given together")
        if self.charStart is not None and self.charEnd is not None:
            if self.charEnd <= self.charStart or self.charEnd - self.charStart != len(self.quote):
                raise ValueError("charEnd - charStart must equal len(quote)")
        if self.sourceType == SOURCE_WEB and not self.url:
            raise ValueError("WEB evidence requires url")
        if self.sourceType == SOURCE_PDF and self.materialId is None and self.documentId is None:
            raise ValueError("PDF_ORIGINAL evidence requires materialId or documentId")
        return self


class GroundingV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: JStr
    evidence: List[EvidenceV1] = Field(default_factory=list, max_length=MAX_EVIDENCE)

    @field_validator("schemaVersion")
    @classmethod
    def _version(cls, v: str) -> str:
        if v != SCHEMA_VERSION:
            raise ValueError(f"unsupported schemaVersion: {v}")
        return v

    @model_validator(mode="after")
    def _unique(self) -> "GroundingV1":
        ids = [e.evidenceId for e in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evidenceId")
        return self

    def ids(self) -> List[str]:
        return [e.evidenceId for e in self.evidence]


# ── 원문 위치·페이지 ───────────────────────────────────────────────────────────────
class PageIndex:
    """원문 오프셋 → 페이지 번호. 표식이 없으면 None(추측하지 않는다)."""

    def __init__(self, original: str) -> None:
        self._ff: Optional[List[int]] = None
        self._marks: List[Tuple[int, int]] = []
        if "\f" in original:
            self._ff = [i for i, ch in enumerate(original) if ch == "\f"]
        else:
            self._marks = [(m.start(), int(m.group(1))) for m in _PAGE_MARK_RE.finditer(original)]

    def page_at(self, offset: int) -> Optional[int]:
        if self._ff is not None:
            return 1 + bisect.bisect_left(self._ff, max(0, offset))   # offset 앞에 있는 \f 개수 + 1
        if not self._marks:
            return None
        starts = [s for s, _ in self._marks]
        i = bisect.bisect_right(starts, offset) - 1
        if i < 0:
            return None          # 첫 표식 앞(표지 등) — 페이지를 확정할 수 없다
        p = self._marks[i][1]
        return p if p >= 1 else None


def locate_span(original: str, snippet: str, *, start_hint: int = 0) -> Optional[Tuple[int, int]]:
    """snippet 이 원문 어디에서 왔는지 찾는다. 정확 일치 → 공백 차이 허용 일치 순. 못 찾으면 None.

    반환 구간의 original[s:e] 는 원문 그대로다(정규화된 snippet 이 아니라 원문 쪽 문자열이 quote 가 된다).
    """
    if not original or not snippet or not snippet.strip():
        return None
    i = original.find(snippet, max(0, start_hint))
    if i < 0 and start_hint:
        i = original.find(snippet)
    if i >= 0:
        return i, i + len(snippet)
    toks = snippet.split()
    if not toks:
        return None
    # PDF 정규화(줄바꿈·연속 공백 정리)만 허용한다. 토큰 수가 많으면 앞부분 40 토큰으로 찾고 원문 구간을 넓힌다.
    head = toks[:40]
    pat = re.compile(r"\s*".join(re.escape(t) for t in head))
    m = pat.search(original, max(0, start_hint)) or (pat.search(original) if start_hint else None)
    if not m:
        return None
    s, e = m.start(), m.end()
    if len(toks) > len(head):
        full = re.compile(r"\s*".join(re.escape(t) for t in toks))
        m2 = full.match(original, s)
        if m2:
            e = m2.end()
    return s, e


def make_chunk_id(material_id: Optional[int], chunk_index: int, document_id: Optional[str] = None) -> str:
    if material_id is not None:
        return f"m{int(material_id)}-c{int(chunk_index)}"
    if document_id and _CHUNK_ID_RE.fullmatch(f"{document_id}-c{int(chunk_index)}"):
        return f"{document_id}-c{int(chunk_index)}"
    return f"c{int(chunk_index)}"


def build_pdf_evidence(original: str, snippet: str, *, evidence_id: str, material_id: Optional[int] = None,
                       document_id: Optional[str] = None, chunk_id: Optional[str] = None,
                       pages: Optional[PageIndex] = None, start_hint: int = 0,
                       max_quote: int = MAX_QUOTE_CHARS) -> Optional[EvidenceV1]:
    """원문에서 snippet 위치를 찾아 원문 그대로의 quote(≤max_quote)·오프셋·확정 페이지로 근거를 만든다."""
    if material_id is None and document_id is None:
        return None
    span = locate_span(original, snippet, start_hint=start_hint)
    if span is None:
        return None
    s, e = span
    # 앞쪽 공백은 quote 에서 뺀다(원문 그대로를 유지하며 구간만 좁힌다).
    while s < e and original[s].isspace():
        s += 1
    e = min(e, s + max(1, min(max_quote, MAX_QUOTE_CHARS)))
    while e > s and original[e - 1].isspace():
        e -= 1
    if e <= s:
        return None
    page = (pages or PageIndex(original)).page_at(s)
    return EvidenceV1(evidenceId=evidence_id, sourceType=SOURCE_PDF, materialId=material_id, documentId=document_id,
                      chunkId=chunk_id, page=page, quote=original[s:e], charStart=s, charEnd=e)


def build_grounding(evidence: Iterable[Optional[EvidenceV1]]) -> GroundingV1:
    seen, out = set(), []
    for ev in evidence:
        if ev is None or ev.evidenceId in seen:
            continue
        seen.add(ev.evidenceId)
        out.append(ev)
        if len(out) >= MAX_EVIDENCE:
            break
    return GroundingV1(schemaVersion=SCHEMA_VERSION, evidence=out)


def grounding_dict(g: GroundingV1) -> Dict[str, Any]:
    return g.model_dump(mode="json", exclude_none=True)


def verify_against_source(original: str, grounding: GroundingV1) -> List[str]:
    """Spring 대조 규칙의 Python 참조 구현: 원문과 맞지 않는 근거의 evidenceId 목록(빈 목록 = 전부 일치)."""
    bad = []
    for ev in grounding.evidence:
        if ev.sourceType != SOURCE_PDF:
            continue
        if ev.charStart is not None and original[ev.charStart:ev.charEnd] != ev.quote:
            bad.append(ev.evidenceId)
        elif ev.quote not in original:
            bad.append(ev.evidenceId)
        elif ev.page is not None and PageIndex(original).page_at(original.find(ev.quote) if ev.charStart is None
                                                                  else ev.charStart) != ev.page:
            bad.append(ev.evidenceId)
    return bad


def to_quality_evidence(ev: EvidenceV1) -> Dict[str, Any]:
    """grounding.v1 근거 → response-quality.v1 groundingEvidence 항목(Spring 이 대조 후 넘기는 형태)."""
    d: Dict[str, Any] = {"evidenceId": ev.evidenceId, "sourceType": ev.sourceType, "text": ev.quote}
    for k in ("materialId", "documentId", "page", "chunkId"):
        v = getattr(ev, k)
        if v is not None:
            d[k] = v
    return d


def referenced_evidence_ids(text: str, evidence: Sequence[EvidenceV1], *, min_overlap: int = 12) -> List[str]:
    """생성문이 실제로 기대는 근거 id(결정적): 근거 quote 의 공백 제거 n-gram(기본 12자)이 생성문에 나타나면 참조로 본다."""
    norm = re.sub(r"\s+", "", text or "")
    out: List[str] = []
    for ev in evidence:
        q = re.sub(r"\s+", "", ev.quote)
        if len(q) < min_overlap:
            if q and q in norm:
                out.append(ev.evidenceId)
            continue
        step = max(1, min_overlap // 2)
        if any(q[i:i + min_overlap] in norm for i in range(0, len(q) - min_overlap + 1, step)):
            out.append(ev.evidenceId)
    return out
