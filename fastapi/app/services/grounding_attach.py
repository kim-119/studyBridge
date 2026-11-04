"""생성 응답에 grounding.v1 근거를 붙이는 라우트 공용 헬퍼(Phase D R1 / R5-5).

- 근거 quote 는 항상 '요청 원문'(Spring 이 보낸 문자열)의 부분 문자열 그대로다. 생성기가 본 텍스트(view)는
  정규화돼 있을 수 있으므로 view 에서 고른 구간은 반드시 원문에서 다시 찾아(locate_span) 원문 쪽 문자열을 쓴다.
  원문에서 찾지 못한 구간은 버린다(없는 근거를 만들지 않는다).
- 문항별 근거(결정적): ① 생성기가 남긴 근거 스니펫(sourceSnippet / sourceTrace.evidence) → ② 문항+정답+해설과
  글자 3-gram 이 가장 많이 겹치는 view 문장(임계값 미달이면 없음). 문항당 최대 2개, 전체 최대 32개.
- 원문/문항 텍스트는 로그에 남기지 않는다(예외 타입만).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from app.contracts.grounding_v1 import (
    MAX_EVIDENCE,
    SCHEMA_VERSION,
    EvidenceV1,
    PageIndex,
    build_grounding,
    build_pdf_evidence,
    grounding_dict,
    locate_span,
    make_chunk_id,
)

logger = logging.getLogger(__name__)

PER_QUESTION_MAX = 2
MIN_SNIPPET_CHARS = 10          # 공백 제외 글자 수 — 이보다 짧은 스니펫은 근거로 쓰지 않는다
MIN_PARTIAL_CHUNK_CHARS = 20    # 프롬프트 상한에서 잘린 청크 조각의 최소 길이
SEGMENT_MAX_CHARS = 400
_GRAM = 3
_MIN_OVERLAP = 8                # 겹치는 3-gram 최소 개수
_MIN_RATIO = 0.25               # 문장 3-gram 중 겹치는 비율 하한

# 문장 경계: 빈 줄, 문장부호 뒤 공백, 프롬프트 골격 줄([chunk N] 머리표·--- 구분선)
_BOUNDARY_RE = re.compile(r"\n\s*\n|(?<=[.!?。])\s+|(?m:^\s*(?:\[chunk \d+\]|-{3,})\s*$)")
_WS_RE = re.compile(r"\s+")


def empty_grounding() -> Dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "evidence": []}


def _compact(text: str) -> str:
    return _WS_RE.sub("", text or "").lower()


def _grams(text: str) -> set:
    c = _compact(text)
    return {c[i:i + _GRAM] for i in range(len(c) - _GRAM + 1)}


def _segments(view: str) -> List[str]:
    out: List[str] = []
    pos = 0
    pieces: List[str] = []
    for m in _BOUNDARY_RE.finditer(view or ""):
        pieces.append(view[pos:m.start()])
        pos = m.end()
    pieces.append((view or "")[pos:])
    for p in pieces:
        p = p.strip()
        while p:
            if len(p) <= SEGMENT_MAX_CHARS:
                head, p = p, ""
            else:
                cut = p.rfind(" ", SEGMENT_MAX_CHARS // 2, SEGMENT_MAX_CHARS)
                cut = cut if cut > 0 else SEGMENT_MAX_CHARS
                head, p = p[:cut].strip(), p[cut:].strip()
            if len(_compact(head)) >= MIN_SNIPPET_CHARS:
                out.append(head)
    return out


def _best_segment(target: str, segments: Sequence[Tuple[str, set]]) -> Optional[str]:
    tg = _grams(target)
    if not tg:
        return None
    best: Optional[Tuple[int, float, int]] = None
    best_seg: Optional[str] = None
    for i, (seg, sg) in enumerate(segments):
        if not sg:
            continue
        ov = len(sg & tg)
        ratio = ov / len(sg)
        if ov < _MIN_OVERLAP or ratio < _MIN_RATIO:
            continue
        key = (ov, ratio, -i)
        if best is None or key > best:
            best, best_seg = key, seg
    return best_seg


class _EvidencePool:
    """원문 구간 → evidenceId(ev-1, ev-2, … 첫 참조 순). 같은 구간은 같은 id 를 재사용한다."""

    def __init__(self, original: str, material_id: Optional[int], document_id: Optional[str]) -> None:
        self.original = original or ""
        self.material_id = material_id
        self.document_id = document_id
        self.pages = PageIndex(self.original)
        self.items: List[EvidenceV1] = []
        self._by_span: Dict[Tuple[int, int], str] = {}

    def add(self, snippet: Optional[str], *, chunk_id: Optional[str] = None, start_hint: int = 0) -> Optional[str]:
        if not snippet or len(_compact(snippet)) < MIN_SNIPPET_CHARS:
            return None
        ev = build_pdf_evidence(self.original, snippet, evidence_id="tmp", material_id=self.material_id,
                                document_id=self.document_id, chunk_id=chunk_id, pages=self.pages,
                                start_hint=start_hint)
        if ev is None:
            return None
        span = (ev.charStart, ev.charEnd)
        if span in self._by_span:
            return self._by_span[span]
        if len(self.items) >= MAX_EVIDENCE:
            return None
        eid = f"ev-{len(self.items) + 1}"
        self.items.append(ev.model_copy(update={"evidenceId": eid}))
        self._by_span[span] = eid
        return eid

    def grounding(self) -> Dict[str, Any]:
        return grounding_dict(build_grounding(self.items))


def _material_id(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return v if v >= 1 else None


# ── 퀴즈 문항 ────────────────────────────────────────────────────────────────────
def question_snippet(q: Dict[str, Any]) -> Optional[str]:
    """생성기가 남긴 근거 스니펫. sourceTrace.evidence 는 개념어가 들어 있을 때만(아니면 문서 머리 fallback 이다)."""
    s = q.get("sourceSnippet")
    if isinstance(s, str) and s.strip():
        return s
    st = q.get("sourceTrace") or q.get("source_trace")
    if isinstance(st, dict) and isinstance(st.get("evidence"), str):
        ev = st["evidence"]
        concepts = [c for c in (st.get("concepts") or []) if isinstance(c, str) and c.strip()]
        if not concepts or any(c in ev for c in concepts):
            return ev
    return None


def question_support_text(q: Dict[str, Any]) -> str:
    """문항이 '근거로 기대는' 텍스트: 질문 + 정답 보기 + 정답 텍스트 + 해설(오답 보기는 제외)."""
    parts: List[Any] = [q.get("question")]
    opts = q.get("options") if isinstance(q.get("options"), list) else q.get("choices")
    opts = opts if isinstance(opts, list) else []
    idx = q.get("correctAnswer")
    if idx is None:
        idx = q.get("answerIndex")
    if isinstance(idx, int) and not isinstance(idx, bool) and 0 <= idx < len(opts):
        parts.append(opts[idx])
    if isinstance(q.get("answer"), str):
        parts.append(q["answer"])
    parts.append(q.get("explanation"))
    return "\n".join(p for p in parts if isinstance(p, str) and p.strip())


def ground_questions(questions: Sequence[Dict[str, Any]], original: Optional[str], *, material_id: Any = None,
                     document_id: Optional[str] = None, view: Optional[str] = None,
                     snippet_fn: Callable[[Dict[str, Any]], Optional[str]] = question_snippet,
                     text_fn: Callable[[Dict[str, Any]], str] = question_support_text,
                     ) -> Tuple[List[List[str]], Dict[str, Any]]:
    """문항별 evidenceIds 목록과 grounding dict. 근거를 찾을 수 없는 문항은 [].

    original: 요청 원문(Spring 이 보낸 문자열 그대로). view: 생성기가 실제로 본 텍스트(없으면 original).
    1차 패스에서 모든 문항의 대표 근거를 먼저 배정하고, 남은 용량으로 보조 근거를 더한다(상한 32 공정 배분).
    """
    ids: List[List[str]] = [[] for _ in questions]
    pool = _EvidencePool(original or "", _material_id(material_id), document_id)
    if not (original or "").strip() or (pool.material_id is None and not document_id):
        return ids, pool.grounding()
    if view is None or view == original:
        seg_texts = _segments(original)                  # 원문 조각 — 항상 원문에서 찾을 수 있다
    else:                                                # 정규화·요약이 섞인 view — 원문에 있는 문장만 후보
        seg_texts = [s for s in _segments(view) if locate_span(original, s) is not None]
    segs = [(s, _grams(s)) for s in seg_texts]
    cands: List[List[str]] = []
    for q in questions:
        c: List[str] = []
        sn = snippet_fn(q) if isinstance(q, dict) else None
        if sn:
            c.append(sn)
        best = _best_segment(text_fn(q), segs) if isinstance(q, dict) else None
        if best:
            c.append(best)
        cands.append(c)
    # 1차: 문항마다 첫 번째로 원문에서 찾은 후보 / 2차: 남은 후보(문항당 최대 2개)
    for i, c in enumerate(cands):
        for j, sn in enumerate(c):
            eid = pool.add(sn)
            if eid:
                ids[i].append(eid)
                cands[i] = c[j + 1:]
                break
        else:
            cands[i] = []
    for i, c in enumerate(cands):
        for sn in c:
            if len(ids[i]) >= PER_QUESTION_MAX:
                break
            eid = pool.add(sn)
            if eid and eid not in ids[i]:
                ids[i].append(eid)
    return ids, pool.grounding()


def attach_question_grounding(questions: Sequence[Dict[str, Any]], original: Optional[str], *,
                              material_id: Any = None, document_id: Optional[str] = None,
                              view: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """문항 사본에 evidenceIds 를 붙여 돌려준다(입력 dict 는 바꾸지 않는다). 실패해도 응답을 깨지 않는다."""
    try:
        ids, g = ground_questions(questions, original, material_id=material_id, document_id=document_id, view=view)
    except Exception as e:  # noqa: BLE001 — 근거 첨부 실패가 생성 응답을 실패시키면 안 된다
        logger.warning("grounding attach failed: %s", type(e).__name__)
        ids, g = [[] for _ in questions], empty_grounding()
    return [dict(q, evidenceIds=list(i)) if isinstance(q, dict) else q for q, i in zip(questions, ids)], g


# ── 자료 질문(/api/ai/question) ───────────────────────────────────────────────────
def prompt_chunk_parts(relevant: Sequence[Dict[str, Any]], context_limit: int) -> List[Tuple[int, str]]:
    """material_legacy_routes.ai_question 의 문맥 규칙과 같다:
    context = "\\n\\n".join(f"[chunk {i}] {content}") 를 context_limit 자로 자른 것이 프롬프트에 들어간다.
    → (chunkIndex, 실제로 프롬프트에 들어간 content 부분) 목록(프롬프트 순서)."""
    out: List[Tuple[int, str]] = []
    pos = 0
    for n, c in enumerate(relevant):
        if n:
            pos += 2                                  # "\n\n"
        idx = c.get("chunkIndex")
        content = str(c.get("content") or "")
        head = f"[chunk {idx}] "
        start = pos + len(head)
        pos = start + len(content)
        remaining = context_limit - start
        if remaining <= 0:
            break
        part = content[:remaining]
        if len(part) < len(content) and len(_compact(part)) < MIN_PARTIAL_CHUNK_CHARS:
            continue
        if isinstance(idx, int) and not isinstance(idx, bool):
            out.append((idx, part))
    return out


def chunk_grounding(parts: Sequence[Tuple[int, str]], original: Optional[str], *, material_id: Any = None,
                    document_id: Optional[str] = None) -> Dict[str, Any]:
    """프롬프트에 들어간 청크(부분)를 원문에서 찾아 근거로 만든다(프롬프트 순서로 ev-1…). 못 찾은 청크는 버린다."""
    try:
        mid = _material_id(material_id)
        pool = _EvidencePool(original or "", mid, document_id)
        if not (original or "").strip() or (mid is None and not document_id):
            return pool.grounding()
        # 원문 위치는 청크 순서대로 찾는다(중복 문장이 있어도 앞 청크 뒤에서 찾도록 start_hint 를 넘긴다).
        located: Dict[int, EvidenceV1] = {}
        hint = 0
        for k in sorted(range(len(parts)), key=lambda k: parts[k][0]):
            idx, part = parts[k]
            if len(_compact(part)) < MIN_SNIPPET_CHARS:
                continue
            ev = build_pdf_evidence(pool.original, part, evidence_id="tmp", material_id=mid, document_id=document_id,
                                    chunk_id=make_chunk_id(mid, idx, document_id), pages=pool.pages, start_hint=hint)
            if ev is not None:
                located[k] = ev
                hint = ev.charStart or 0
        items = [located[k].model_copy(update={"evidenceId": f"ev-{n + 1}"})
                 for n, k in enumerate(k for k in range(len(parts)) if k in located)]
        return grounding_dict(build_grounding(items))
    except Exception as e:  # noqa: BLE001
        logger.warning("chunk grounding failed: %s", type(e).__name__)
        return empty_grounding()
