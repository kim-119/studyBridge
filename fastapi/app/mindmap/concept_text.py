"""ConceptNormalizer + ConceptValidator (deterministic).

Invariant enforced here:
    "해당 label 하나만 독립적으로 읽어도 학습자가 무슨 개념인지 이해할 수 있다."

Two analyzers, same contract:
  * kiwi  — kiwipiepy POS tags (primary when importable). A concept must be a noun
            phrase: noun-like head, no verbal endings/predicates, not an adverb/filler.
  * rules — no morphological analyzer. Particles are stripped only where the boundary
            is unambiguous (non-Hangul stem, multi-syllable particle) or the bare stem is
            attested elsewhere in the same answer. Never blind suffix chopping, so
            "Java", "Kafka", "CUDA", "전문가", "정확도" stay intact.

Both are pure functions of their input (no LLM, no randomness).
"""
from __future__ import annotations

import logging
import os
import re
import threading
from typing import Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ── analyzer selection ──────────────────────────────────────────────────────
_KIWI = None
_KIWI_LOCK = threading.Lock()
_KIWI_FAILED = False
_KIWI_ERROR: Optional[str] = None
_FORCE_RULES = os.getenv("MINDMAP_DISABLE_KIWI", "").strip().lower() in ("1", "true", "yes")


def set_rules_only(value: bool) -> None:
    """Test hook: force the rule analyzer (simulates a host without kiwipiepy)."""
    global _FORCE_RULES
    _FORCE_RULES = bool(value)


def _kiwi():
    global _KIWI, _KIWI_FAILED, _KIWI_ERROR
    if _FORCE_RULES or _KIWI_FAILED:
        return None
    if _KIWI is None:
        with _KIWI_LOCK:
            if _KIWI is None and not _KIWI_FAILED:
                try:
                    from kiwipiepy import Kiwi
                    _KIWI = Kiwi()
                except Exception as e:  # noqa: BLE001 — declared in requirements.txt; absence is degraded
                    _KIWI_FAILED = True
                    _KIWI_ERROR = f"{type(e).__name__}: {e}"[:200]
                    logger.error("[mindmap] kiwipiepy unavailable -> rules analyzer, graphs are DEGRADED: %s",
                                 _KIWI_ERROR)
                    return None
    return _KIWI


def analyzer_name() -> str:
    return "kiwi" if _kiwi() is not None else "rules"


def analyzer_unavailable_reason() -> Optional[str]:
    """None when kiwi is active; else why the rule analyzer is in use."""
    if _kiwi() is not None:
        return None
    if _FORCE_RULES:
        return "MINDMAP_DISABLE_KIWI"
    return _KIWI_ERROR or "KIWIPIEPY_NOT_IMPORTABLE"


def tokenize(text: str):
    """[(form, tag, start, length)] or None when kiwi is unavailable."""
    kiwi = _kiwi()
    if kiwi is None:
        return None
    with _KIWI_LOCK:
        toks = kiwi.tokenize(text)
    return [(t.form, t.tag, t.start, t.len) for t in toks]


# ── shared lexical constants ────────────────────────────────────────────────
_HANGUL = re.compile(r"[가-힣]")
_ALLOWED_CHARS = re.compile(r"^[가-힣A-Za-z0-9 \-+#./()&'·:_]+$")
_ARTIFACT = re.compile(r"(\*\*|`|#{2,}|^#|\||https?:|://|\[|\]|\{|\}|<|>|^[-*•]\s|\.\.\.)")
_EDGE_PUNCT = " \t\r\n\"'“”‘’`*_~#>|:;,.!?·-•[]{}<>"

# Particles by length. Multi-syllable particles never end a Korean noun, so they are
# safe to strip after any stem. Single-syllable ones (이/가/도/의 ...) collide with real
# nouns (고양이, 전문가, 정확도, 결과) and are stripped only when the boundary is proven.
_MULTI_PARTICLES = (
    "에서부터", "으로부터", "에서의", "에서는", "에서도", "으로서", "으로써", "으로는", "으로도",
    "이라는", "이라고", "이란", "에게서", "한테서",
    "에서", "에게", "한테", "으로", "로서", "로써", "로는", "로도", "까지", "부터", "처럼", "보다",
    "라는", "라고", "에는", "에도", "와의", "과의", "와는", "과는", "이나", "이며", "만의", "마다",
)
_SINGLE_PARTICLES = ("은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "로", "만", "란", "랑")

# Copula/predicate tails that sometimes stick to a technical term ("API입니다").
_COPULA_TAIL = re.compile(r"(이다|입니다|이에요|예요|이며|이고|였다|이었다)$")

# Rule-mode predicate endings (last eojeol). Only endings that virtually never close a noun.
_PREDICATE_ENDINGS = re.compile(
    r"(습니다|습니까|니다|었다|았다|였다|했다|한다|된다|었고|았고|였고|하고|하며|되며|해서|되어|하여|"
    r"하면|되면|하는|되는|있는|없는|했던|였던|는데|지만|면서|도록|려면|으며|으면|어요|아요|해요|세요|"
    r"겠다|겠고|었던|았던|는|은|할|될)$"
)
# Closed word classes used by the rule analyzer (adverbs, conjunctions, fillers, determiners).
_CLOSED_CLASS = {
    "아직", "지금", "이미", "매우", "정말", "그냥", "먼저", "다시", "바로", "특히", "또한", "즉", "결국",
    "항상", "자주", "가끔", "조금", "너무", "아주", "더", "덜", "잘", "곧", "이제", "그래서", "그러나",
    "하지만", "그리고", "따라서", "또는", "혹은", "그러면", "그런데", "이렇게", "그렇게", "어떻게", "왜",
    "뭐", "음", "네", "아", "좀", "대체로", "보통", "주로", "각각", "함께", "모두", "직접", "쉽게",
    "이", "그", "저", "이것", "그것", "저것", "여기", "거기", "저기", "이런", "그런", "저런", "어떤",
    "무슨", "모든", "각", "여러", "이러한", "그러한",
}
_DETERMINERS = {"이", "그", "저", "이런", "그런", "저런", "어떤", "무슨", "모든", "각", "여러", "이러한", "그러한", "해당"}

# Dialogue/meta vocabulary: words about the conversation, not about the subject matter.
_META_TERMS = {
    "답변", "질문", "설명", "내용", "부분", "정리", "요약", "예시", "예", "경우", "사용자", "학습자",
    "교수", "튜터", "코치", "개념", "의미", "이해", "생각", "이야기", "말", "것", "수", "등", "때", "점",
    "측면", "관점", "결론", "핵심", "다음", "이전", "위", "아래", "정도", "사실", "부분적", "관련",
    "answer", "question", "example", "note", "summary",
}
# Relation vocabulary words are edge labels, not concepts.
_RELATION_WORDS = {"정의", "목적", "구성 요소", "수행", "처리 단계", "원인", "결과", "특징", "비교", "예시", "관련 개념"}
_LEADING_MODIFIERS = {"주요", "기본", "중요한", "다양한", "여러", "각종", "일반적인", "대표적인"}
_EN_FUNCTION = {"the", "a", "an", "of", "and", "or", "to", "is", "are", "was", "in", "on", "for",
                "with", "by", "this", "that", "it", "as", "be", "at", "from"}

# kiwi tag groups
_NOUNISH = {"NNG", "NNP", "NR", "SL", "SN", "SH", "XSN", "XR"}
_ALLOWED_INNER = _NOUNISH | {"SO", "SP", "SSO", "SSC", "SW", "SS", "JKG", "NNB", "XPN"}
_FILLER_TAGS = {"MAG", "MAJ", "MM", "IC", "NP", "NNB"}


def _clean(surface: str) -> str:
    s = re.sub(r"\s+", " ", str(surface or "")).strip()
    s = s.strip(_EDGE_PUNCT)
    # unmatched parenthesis at the end/start ("JDBC(Java" / "Connectivity)")
    if s.count("(") != s.count(")"):
        s = s.replace("(", " ").replace(")", " ")
        s = re.sub(r"\s+", " ", s).strip()
    return s


def concept_key(label: str) -> str:
    """Dedup key: case/space/hyphen-insensitive ("REST API" == "rest-api" == "RESTAPI")."""
    return re.sub(r"[\s\-_·]+", "", str(label or "")).casefold()


# ── Normalizer ──────────────────────────────────────────────────────────────
def normalize_surface(surface: str, attested: Optional[Set[str]] = None) -> str:
    """Surface form -> canonical concept label ('' if nothing meaningful remains).

    attested: concept_keys of bare stems seen elsewhere in the same answer. The rule
    analyzer uses it to prove a single-syllable particle boundary ("시스템이" -> "시스템"
    only if "시스템" also occurs on its own).
    """
    s = _clean(surface)
    if not s:
        return ""
    attested = attested or set()
    # Non-Hangul stem + particle ("JDBC가", "C++는", "REST API의") is an unambiguous boundary
    # in either analyzer (kiwi mis-segments "C++는" as a verb).
    last = s.split(" ")[-1]
    if re.search(r"[A-Za-z0-9)+#][가-힣]{1,3}$", last) and _strip_particle_rules(last, attested) != last:
        s = _normalize_rules(s, attested)
    toks = tokenize(s)
    out = _normalize_kiwi(s, toks, attested) if toks is not None else _normalize_rules(s, attested)
    # leading dialogue/meta modifier ("핵심 구성 요소" -> "구성 요소", "주요 특징" -> "특징")
    words = out.split(" ")
    while len(words) > 1 and (words[0] in _META_TERMS or words[0] in _LEADING_MODIFIERS):
        words = words[1:]
    return " ".join(words)


# Single-syllable particles that double as noun suffixes: 복잡도/유사도 (-도 "degree"),
# 전문가/작곡가 (-가 "person"). In isolation kiwi may tag them as particles.
_SUFFIX_LIKE_PARTICLES = {"도", "가"}


def _is_ambiguous_particle(prev, tok) -> bool:
    glued = prev[2] + prev[3] == tok[2]
    if not glued or len(tok[0]) != 1 or not _HANGUL.match(prev[0][-1:] or "a"):
        return False
    return prev[1] == "XR" or tok[0] in _SUFFIX_LIKE_PARTICLES


def _normalize_kiwi(s: str, toks, attested: Set[str]) -> str:
    toks = list(toks)
    changed = True
    while toks and changed:
        changed = False
        # trailing particles (JKS/JKG/JKB/JX/JC/JKO ...)
        while toks and toks[-1][1].startswith("J"):
            if len(toks) >= 2 and _is_ambiguous_particle(toks[-2], toks[-1]):
                stem = s[: toks[-2][2] + toks[-2][3]]
                if concept_key(stem) not in attested:
                    return _clean(s)          # "복잡도" stays whole unless bare "복잡" is attested
            toks.pop()
            changed = True
        # trailing copula chain: <term> + VCP + E* ("API입니다")
        if toks and toks[-1][1].startswith("E"):
            j = len(toks) - 1
            while j >= 0 and toks[j][1].startswith("E"):
                j -= 1
            if j >= 0 and toks[j][1] == "VCP":
                toks = toks[:j]
                changed = True
    if not toks:
        return ""
    end = toks[-1][2] + toks[-1][3]
    return _clean(s[:end])


def _strip_particle_rules(word: str, attested: Set[str]) -> str:
    m = _COPULA_TAIL.search(word)
    if m and m.start() > 0 and not _HANGUL.match(word[m.start() - 1]):
        return word[: m.start()]
    for p in _MULTI_PARTICLES:
        if word.endswith(p) and len(word) > len(p):
            stem = word[: -len(p)]
            if not _HANGUL.match(stem[-1]) or len(stem) >= 2:
                return stem
    for p in _SINGLE_PARTICLES:
        if word.endswith(p) and len(word) > len(p):
            stem = word[: -len(p)]
            if not _HANGUL.match(stem[-1]):          # JDBC가, API는, TCP의, C++를
                return stem
            if concept_key(stem) in attested:        # 시스템이 (bare 시스템 seen elsewhere)
                return stem
    return word


def _normalize_rules(s: str, attested: Set[str]) -> str:
    words = s.split(" ")
    words[-1] = _strip_particle_rules(words[-1], attested)
    return _clean(" ".join(w for w in words if w))


# ── Validator ───────────────────────────────────────────────────────────────
def validate_concept(label: str, extra_reject: Iterable[str] = ()) -> Tuple[bool, str]:
    """(ok, reason). reason is '' when ok. Deterministic."""
    raw = str(label or "")
    if _ARTIFACT.search(raw):
        return False, "format_artifact"
    s = _clean(raw)
    if not s:
        return False, "empty"
    if not _ALLOWED_CHARS.match(s):
        return False, "format_artifact"
    if len(s) > 40 or len(s.split(" ")) > 6:
        return False, "sentence_like"
    if re.fullmatch(r"[\d\s.,:%+\-/()]+", s):
        return False, "numeric"
    key = concept_key(s)
    if key in {concept_key(x) for x in extra_reject if x}:
        return False, "agent_or_source_name"
    if key in {concept_key(x) for x in _META_TERMS}:
        return False, "meta_term"
    if key in {concept_key(x) for x in _RELATION_WORDS}:
        return False, "relation_word"
    compact = s.replace(" ", "")
    if _HANGUL.search(compact):
        if len(compact) < 2:
            return False, "too_short"
    elif len(compact) < 2:
        return False, "too_short"

    words = s.split(" ")
    latin_words = [w for w in words if re.fullmatch(r"[A-Za-z][A-Za-z0-9+#.\-/]*", w)]
    if latin_words and len(latin_words) == len(words):
        low = [w.lower() for w in words]
        if all(w in _EN_FUNCTION for w in low):
            return False, "function_words"
        if low[0] in _EN_FUNCTION or low[-1] in _EN_FUNCTION:
            return False, "phrase_fragment"

    toks = tokenize(s)
    if toks is not None:
        return _validate_kiwi(s, toks)
    return _validate_rules(s, words)


def _validate_kiwi(s: str, toks) -> Tuple[bool, str]:
    tags = [t[1] for t in toks]
    if not tags:
        return False, "empty"
    if tags[-1].startswith("J"):
        return False, "particle_attached"
    if any(t.startswith("E") for t in tags):
        return False, "predicate_fragment"
    if any(t.startswith("V") or t in ("XSV", "XSA") for t in tags):
        return False, "predicate_fragment"
    if all(t in _FILLER_TAGS for t in tags):
        return False, "adverb_or_filler"
    if tags[0] == "MM" or (tags[0] == "NP" and len(tags) > 1):
        return False, "determiner_fragment"
    if tags[-1] not in _NOUNISH:
        # allow closing bracket after a noun ("Big-O(표기법)") and "C++"/"C#"
        glued_symbol = tags[-1] == "SW" and len(tags) > 1 and tags[-2] == "SL" and re.fullmatch(r"[+#]+", toks[-1][0])
        if not glued_symbol and not (tags[-1] == "SSC" and len(tags) > 1 and tags[-2] in _NOUNISH):
            return False, "not_noun_head"
    if any(t not in _ALLOWED_INNER for t in tags):
        return False, "not_noun_phrase"
    if all(t in ("NNB", "NP") for t in tags):
        return False, "dependent_noun"
    return True, ""


def _validate_rules(s: str, words: List[str]) -> Tuple[bool, str]:
    if s in _CLOSED_CLASS:
        return False, "adverb_or_filler"
    if words[0] in _DETERMINERS and len(words) > 1:
        return False, "determiner_fragment"
    for i, w in enumerate(words):
        last = i == len(words) - 1
        if w in _CLOSED_CLASS:
            return False, "adverb_or_filler"
        if not _HANGUL.search(w):
            continue
        if _PREDICATE_ENDINGS.search(w) and not re.search(r"[A-Za-z0-9]", w):
            return False, "predicate_fragment"
        if re.search(r"[가-힣](하|되|있|없|쓸|볼|갈|올)$", w) and len(w) >= 2 and not last:
            return False, "predicate_fragment"
        if re.search(r"(하|되)$", w) and len(w) >= 3:
            return False, "predicate_fragment"
        for p in _MULTI_PARTICLES:
            if w.endswith(p) and len(w) > len(p):
                return False, "particle_attached"
        if re.search(r"[A-Za-z0-9)+#]([은는이가을를의에와과도로만])$", w):
            return False, "particle_attached"
    return True, ""


def is_valid_concept(label: str, extra_reject: Iterable[str] = ()) -> bool:
    return validate_concept(label, extra_reject)[0]
