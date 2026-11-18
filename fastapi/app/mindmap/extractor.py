"""SemanticConceptExtractor.

Two sources of concept candidates, both followed by the same deterministic
normalize -> validate gate in graph_builder:

  * LLM structured output (primary): the model returns JSON concept phrases with a
    level/parent/relation. Every label must be grounded in the answer text, so the
    model cannot enrich the map with facts the answer never stated.
  * Deterministic noun-phrase chunking (fallback / no LLM): kiwi POS runs of noun
    tokens form one multi-word concept ("트랜잭션 격리 수준"), plus parenthetical
    aliases "의존성 주입(Dependency Injection)", markdown emphasis, Latin terms.
    Never answer.split() / top-frequency tokens.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from app.mindmap import concept_text as ct

logger = logging.getLogger(__name__)

RELATION_VOCAB: Dict[str, str] = {
    "DEFINITION": "정의",
    "PURPOSE": "목적",
    "COMPONENT": "구성 요소",
    "PERFORMS": "수행",
    "STEP": "처리 단계",
    "CAUSE": "원인",
    "EFFECT": "결과",
    "FEATURE": "특징",
    "COMPARISON": "비교",
    "EXAMPLE": "예시",
    "RELATED": "관련 개념",
}
_RELATION_BY_LABEL = {v: k for k, v in RELATION_VOCAB.items()}


def relation_key(value: Optional[str]) -> Optional[str]:
    """Map an LLM relation (key or Korean label) into the closed vocabulary, else None."""
    if not value:
        return None
    v = str(value).strip()
    if v.upper() in RELATION_VOCAB:
        return v.upper()
    v2 = v.replace(" ", "")
    for label, key in _RELATION_BY_LABEL.items():
        if label.replace(" ", "") == v2:
            return key
    return None


@dataclass
class Candidate:
    surface: str
    source: str                     # "llm" | "chunk" | "alias" | "emphasis" | "question"
    level: Optional[str] = None     # LLM hint: CORE | PRIMARY | SECONDARY
    parent: Optional[str] = None    # LLM hint (surface)
    relation: Optional[str] = None  # relation key
    aliases: List[str] = field(default_factory=list)
    emphasis: bool = False


# ── text prep ───────────────────────────────────────────────────────────────
_MD_EMPH = re.compile(r"(\*\*|__)(.+?)\1")
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.M)
_PAREN_ALIAS = re.compile(
    r"([가-힣A-Za-z][가-힣A-Za-z0-9 \-+#.]{0,30}?)\s*\(\s*([A-Za-z가-힣][A-Za-z0-9가-힣 \-+#.]{1,40}?)\s*\)"
)


def strip_markdown(text: str) -> str:
    t = str(text or "")
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = t.replace("**", "").replace("__", "").replace("`", "")
    t = re.sub(r"^\s{0,3}#{1,6}\s+", "", t, flags=re.M)
    t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", t, flags=re.M)
    t = re.sub(r"https?://\S+", " ", t)
    return t


def split_sentences(text: str) -> List[str]:
    t = strip_markdown(text)
    parts = re.split(r"(?<=[.!?。])\s+|\n+|(?<=다)\.\s*", t)
    return [p.strip() for p in parts if p and p.strip()]


# ── deterministic chunking ──────────────────────────────────────────────────
_CHUNK_TAGS = {"NNG", "NNP", "NR", "SL", "SN", "SH", "XSN", "XR"}
_JOIN_TAGS = {"SW", "SO"}   # "C++", "SYN-ACK", "3-way": only when glued (no gap)
_MAX_CHUNK_WORDS = 4


def _chunks_kiwi(line: str) -> List[str]:
    toks = ct.tokenize(line)
    if not toks:
        return []
    out: List[str] = []
    cur: List[Tuple[str, str, int, int]] = []

    def _trim():
        # drop dangling joiners ("SYN-" / "**"), but keep "C++" / "C#"
        while cur and cur[-1][1] in _JOIN_TAGS and not (
            re.fullmatch(r"[+#]+", cur[-1][0]) and len(cur) > 1 and cur[-2][1] == "SL"
        ):
            cur.pop()

    def flush(next_tag: str = ""):
        nonlocal cur
        _trim()
        # "요청합니다"/"중요합니다": a noun + 하다/되다 derivation is a predicate, not a concept.
        if cur and next_tag in ("XSV", "XSA") and cur[-1][1] in ("NNG", "XR"):
            if cur[-1][2] + cur[-1][3] == pending_start[0]:
                cur.pop()
                _trim()
        if cur and cur[0][1] != "XSN":
            s, e = cur[0][2], cur[-1][2] + cur[-1][3]
            phrase = re.sub(r"\s+", " ", line[s:e]).strip()
            words = phrase.split(" ")
            if len(words) > _MAX_CHUNK_WORDS:        # Korean is head-final: keep the head
                phrase = " ".join(words[-_MAX_CHUNK_WORDS + 1:])
            out.append(phrase)
        cur = []

    pending_start = [0]
    for tok in toks:
        form, tag, start, length = tok
        pending_start[0] = start
        if cur:
            prev = cur[-1]
            gap = line[prev[2] + prev[3]:start]
            glued = gap == ""
            if tag in _CHUNK_TAGS and (glued or gap == " "):
                cur.append(tok)
                continue
            if tag in _JOIN_TAGS and glued and form not in ("**",):
                cur.append(tok)
                continue
            flush(tag)
        if tag in _CHUNK_TAGS:
            cur.append(tok)
    flush()
    return out


_LATIN_TERM = re.compile(
    r"(?<![A-Za-z0-9])([A-Z][A-Za-z0-9+#.\-]*(?:\s+(?:\d+-?[a-z]+|[A-Za-z][A-Za-z0-9+#.\-]*)){0,3})"
)

def _chunks_rules(line: str) -> List[str]:
    """No analyzer: Latin technical terms only. Korean compounds come from the
    unambiguous sources (parenthetical aliases, markdown emphasis) in the caller."""
    out: List[str] = []
    for m in _LATIN_TERM.finditer(line):
        words = m.group(1).split()
        while words and words[-1].lower() in ct._EN_FUNCTION:
            words.pop()
        if words:
            out.append(" ".join(words))
    return out


def deterministic_candidates(question: str, answers: Sequence[str]) -> List[Candidate]:
    cands: List[Candidate] = []
    use_kiwi = ct.tokenize("테스트") is not None
    chunker = _chunks_kiwi if use_kiwi else _chunks_rules

    for text in answers:
        raw = str(text or "")
        for m in _MD_EMPH.finditer(raw):
            cands.append(Candidate(surface=m.group(2), source="emphasis", emphasis=True))
        for m in _MD_HEADING.finditer(raw):
            cands.append(Candidate(surface=m.group(1), source="emphasis", emphasis=True))
        plain = strip_markdown(raw)
        for m in _PAREN_ALIAS.finditer(plain):
            head, inner = m.group(1).strip(), m.group(2).strip()
            # keep only the trailing noun phrase of `head` ("자바에서 쓰는 JDBC" -> "JDBC")
            head_chunks = chunker(head) or [head]
            cands.append(Candidate(surface=head_chunks[-1], source="alias", aliases=[inner]))
        for line in plain.splitlines():
            for chunk in chunker(line):
                cands.append(Candidate(surface=chunk, source="chunk"))

    for chunk in chunker(strip_markdown(question)):
        cands.append(Candidate(surface=chunk, source="question"))
    return cands


# ── LLM structured extraction ───────────────────────────────────────────────
_LLM_SYSTEM = (
    "너는 학습용 개념 지도(Concept Map) 추출기다. 답변 본문에서 학습 개념만 JSON으로 뽑는다.\n"
    "규칙:\n"
    "1. label은 그 단어만 읽어도 무슨 개념인지 알 수 있는 명사구다. 예: JDBC, 데이터베이스 연결, 의존성 주입, "
    "트랜잭션 격리 수준, TCP 3-way handshake.\n"
    "2. 조사가 붙은 형태(JDBC가, JDBC의), 서술어(요청했습니다, 판단되었고), 관형어(있는, 말할), 부사(아직, 지금), "
    "대화 표현, 교수/튜터/코치 이름은 절대 label로 쓰지 않는다.\n"
    "3. 여러 단어로 된 개념은 쪼개지 않는다.\n"
    "4. 답변 본문에 실제로 등장한 개념만 쓴다. 본문에 없는 개념을 추가하지 않는다.\n"
    "5. level은 CORE(질문의 중심 개념 1~2개), PRIMARY(3~6개), SECONDARY(5~12개) 중 하나.\n"
    "6. parent는 상위 개념의 label(CORE는 null), relation은 다음 중 하나: "
    + ", ".join(RELATION_VOCAB.values()) + ".\n"
    '출력은 JSON 하나만: {"concepts":[{"label":"...","level":"CORE","parent":null,"relation":null}]}'
)


def _parse_llm_json(raw: str) -> Optional[List[dict]]:
    if not raw:
        return None
    try:
        from app.utils.json_parser import extract_json
        data = extract_json(raw)
    except Exception:  # noqa: BLE001
        data = None
    if data is None:
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            return None
    if isinstance(data, dict):
        data = data.get("concepts")
    if not isinstance(data, list):
        return None
    items = [d for d in data if isinstance(d, dict) and isinstance(d.get("label"), str)]
    return items or None


def llm_candidates(question: str, answers: Sequence[str], llm_call=None) -> Tuple[Optional[List[Candidate]], str]:
    """(candidates | None, reason). None means the LLM path failed and the caller must
    mark the result degraded — the failure is never hidden."""
    if llm_call is None:
        from app.services.ollama_client import ask_ollama

        def llm_call(system: str, user: str) -> str:
            return ask_ollama(system, user, temperature=0.0, max_tokens=900, think=False, timeout=45)

    body = "\n\n".join(strip_markdown(a)[:4000] for a in answers if a)
    user = f"질문: {question}\n\n답변 본문:\n{body}\n\nJSON만 출력하라."
    try:
        raw = llm_call(_LLM_SYSTEM, user)
    except Exception as e:  # noqa: BLE001
        logger.warning("[mindmap] llm call failed: %s", type(e).__name__)
        return None, "llm_error"
    items = _parse_llm_json(raw or "")
    if items is None:
        return None, "llm_unparseable"
    out: List[Candidate] = []
    for it in items:
        level = str(it.get("level") or "").upper() or None
        if level not in ("CORE", "PRIMARY", "SECONDARY"):
            level = None
        aliases = [a for a in (it.get("aliases") or []) if isinstance(a, str)]
        out.append(Candidate(
            surface=it["label"], source="llm", level=level,
            parent=it.get("parent") if isinstance(it.get("parent"), str) else None,
            relation=relation_key(it.get("relation")), aliases=aliases,
        ))
    return out, ""
