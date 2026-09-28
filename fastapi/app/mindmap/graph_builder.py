"""ConceptDeduplicator + RelationExtractor + HierarchyBuilder + GraphValidator.

Output contract (schemaVersion "mindmap.semantic.v1"):
  nodes            question node + concept nodes only (knowledge hierarchy)
  edges            question->core ("topic") and concept->concept ("semantic", closed relation vocab)
  sourceNodes      agent nodes (provenance) — never part of the concept hierarchy
  provenanceEdges  agent -> concept ("provenance")
Concept nodes carry canonicalLabel / aliases / surfaceForms / level / visible.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from app.mindmap import concept_text as ct
from app.mindmap.extractor import (
    RELATION_VOCAB,
    Candidate,
    deterministic_candidates,
    llm_candidates,
    split_sentences,
    strip_markdown,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "mindmap.semantic.v1"
BUDGET = {"CORE": 2, "PRIMARY": 6, "SECONDARY": 12}
LEVELS = ("CORE", "PRIMARY", "SECONDARY")


@dataclass
class Concept:
    key: str
    label: str
    surface_forms: Set[str] = field(default_factory=set)
    aliases: Set[str] = field(default_factory=set)
    sources: Set[str] = field(default_factory=set)        # candidate sources (llm/chunk/...)
    agents: Set[str] = field(default_factory=set)         # provenance agent keys
    count: int = 0
    emphasis: bool = False
    in_question: bool = False
    first_pos: int = 10 ** 9
    level_hint: Optional[str] = None
    parent_hint: Optional[str] = None
    relation_hint: Optional[str] = None
    level: Optional[str] = None
    parent: Optional[str] = None
    relation: Optional[str] = None
    visible: bool = True

    @property
    def id(self) -> str:
        return "c_" + hashlib.sha1(self.key.encode("utf-8")).hexdigest()[:10]


def _compact(text: str) -> str:
    return ct.concept_key(text)


def _occurrences(label_keys: Iterable[str], compact_text: str) -> int:
    return sum(compact_text.count(k) for k in label_keys if k)


# ── dedupe ──────────────────────────────────────────────────────────────────
def _collect(
    cands: Sequence[Candidate],
    answers: Sequence[Tuple[str, str]],
    question: str,
    reject_names: Sequence[str],
    rejected: List[Dict[str, str]],
) -> Dict[str, Concept]:
    all_text = " ".join(strip_markdown(t) for _, t in answers)
    compact_all = _compact(all_text)
    compact_q = _compact(question)

    # Stems attested on their own (rule analyzer uses this to prove particle boundaries).
    attested: Set[str] = set()
    for c in cands:
        if c.source != "llm":
            attested.add(ct.concept_key(c.surface))

    concepts: Dict[str, Concept] = {}
    alias_to_key: Dict[str, str] = {}
    reject_keys = {ct.concept_key(n) for n in reject_names if n}
    for c in cands:
        if ct.concept_key(ct._clean(c.surface)) in reject_keys:   # provenance, not a concept
            rejected.append({"surface": c.surface, "reason": "agent_or_source_name"})
            continue
        canonical = ct.normalize_surface(c.surface, attested)
        ok, reason = ct.validate_concept(canonical, reject_names)
        if not ok:
            rejected.append({"surface": c.surface, "reason": reason})
            continue
        key = ct.concept_key(canonical)
        # grounding: every concept (LLM ones included) must occur in the answer or question
        if key not in compact_all and key not in compact_q and not any(
            ct.concept_key(a) in compact_all for a in c.aliases
        ):
            rejected.append({"surface": c.surface, "reason": "not_in_answer"})
            continue
        key = alias_to_key.get(key, key)
        con = concepts.get(key)
        if con is None:
            con = concepts[key] = Concept(key=key, label=canonical)
        con.surface_forms.add(str(c.surface).strip())
        con.sources.add(c.source)
        con.emphasis = con.emphasis or c.emphasis
        if c.source == "llm":
            con.level_hint = con.level_hint or c.level
            con.parent_hint = con.parent_hint or c.parent
            con.relation_hint = con.relation_hint or c.relation
        for a in c.aliases:
            a_norm = ct.normalize_surface(a, attested)
            if a_norm and ct.validate_concept(a_norm, reject_names)[0]:
                a_key = ct.concept_key(a_norm)
                if a_key != key:
                    con.aliases.add(a_norm)
                    alias_to_key[a_key] = key

    # merge concepts that turned out to be aliases of each other ("Dependency Injection" node)
    for a_key, target in list(alias_to_key.items()):
        if a_key in concepts and a_key != target and target in concepts:
            src = concepts.pop(a_key)
            dst = concepts[target]
            dst.aliases.add(src.label)
            dst.surface_forms |= src.surface_forms
            dst.sources |= src.sources
            dst.emphasis = dst.emphasis or src.emphasis
            dst.level_hint = dst.level_hint or src.level_hint

    for con in concepts.values():
        keys = [con.key] + [ct.concept_key(a) for a in con.aliases]
        con.count = max(1, _occurrences(keys, compact_all))
        con.in_question = any(k and k in compact_q for k in keys)
        positions = [compact_all.find(k) for k in keys if k and compact_all.find(k) >= 0]
        con.first_pos = min(positions) if positions else 10 ** 9
        for agent_key, text in answers:
            ctext = _compact(strip_markdown(text))
            if any(k and k in ctext for k in keys):
                con.agents.add(agent_key)
    return concepts


def _drop_subsumed(concepts: Dict[str, Concept]) -> None:
    """A fragment that only ever occurs inside a longer concept is not its own concept
    ("격리" inside "트랜잭션 격리 수준"). Kept when it also occurs standalone."""
    keys = sorted(concepts, key=len, reverse=True)
    for short in list(keys):
        if short not in concepts:
            continue
        for long in keys:
            if long == short or long not in concepts or len(long) <= len(short):
                continue
            if short in long and concepts[short].count <= concepts[long].count \
                    and not concepts[short].in_question and "llm" not in concepts[short].sources:
                concepts[long].surface_forms |= concepts[short].surface_forms
                concepts.pop(short)
                break


def _score(c: Concept) -> float:
    return (
        c.count
        + (6.0 if c.in_question else 0.0)
        + (2.0 if c.emphasis else 0.0)
        + (1.5 if "alias" in c.sources or c.aliases else 0.0)
        + (1.0 if "llm" in c.sources else 0.0)
        + (0.5 if " " in c.label else 0.0)
        + 1.0 / (1.0 + c.first_pos / 200.0)
    )


# ── relation ────────────────────────────────────────────────────────────────
_RELATION_CUES: List[Tuple[str, re.Pattern]] = [
    # order matters: the most specific cue wins; connective-only cues for CAUSE/EFFECT so the
    # plain noun "결과를 받는다" does not read as a causal relation.
    ("DEFINITION", re.compile(r"약자|줄임말|stands for|정의|이란|의미한다|의미합니다|말한다|말합니다")),
    ("COMPONENT", re.compile(r"구성|요소|포함|이루어|컴포넌트|인터페이스|클래스|객체들")),
    ("PURPOSE", re.compile(r"위해|위한|목적|하려고|용도")),
    ("STEP", re.compile(r"단계|먼저|다음으로|순서|그 후|이후|→|->")),
    ("EXAMPLE", re.compile(r"예를 들어|예컨대|예시|가령|예:")),
    ("COMPARISON", re.compile(r"비교|차이|반면|달리|\bvs\b|대비")),
    ("CAUSE", re.compile(r"때문|원인|로 인해|으로 인해")),
    ("EFFECT", re.compile(r"그 결과|결과적으로|따라서|덕분에|초래")),
    ("FEATURE", re.compile(r"특징|장점|단점|특성|성질")),
    ("PERFORMS", re.compile(r"실행|수행|처리|전송|조회|호출|관리|제어|연결한다|연결합니다")),
]


def _sentence_index(sentences: Sequence[str], concepts: Dict[str, Concept]) -> Dict[str, Set[int]]:
    idx: Dict[str, Set[int]] = {k: set() for k in concepts}
    compact_sents = [_compact(s) for s in sentences]
    for key, con in concepts.items():
        keys = [key] + [ct.concept_key(a) for a in con.aliases]
        for i, cs in enumerate(compact_sents):
            if any(k and k in cs for k in keys):
                idx[key].add(i)
    return idx


def _infer_relation(child: Concept, parent: Concept, sentences: Sequence[str], sidx: Dict[str, Set[int]]) -> str:
    if child.key in {ct.concept_key(a) for a in parent.aliases} or parent.key in {
        ct.concept_key(a) for a in child.aliases
    }:
        return "DEFINITION"
    shared = sorted(sidx.get(child.key, set()) & sidx.get(parent.key, set()))
    pool = shared or sorted(sidx.get(child.key, set()))
    for i in pool:
        s = sentences[i]
        for rel, pat in _RELATION_CUES:
            if pat.search(s):
                return rel
    return "RELATED"


# ── hierarchy ───────────────────────────────────────────────────────────────
def _assign_hierarchy(concepts: Dict[str, Concept], sentences: Sequence[str]) -> None:
    ranked = sorted(concepts.values(), key=_score, reverse=True)
    if not ranked:
        return
    sidx = _sentence_index(sentences, concepts)

    by_label = {ct.concept_key(c.label): c for c in ranked}
    for c in ranked:
        for a in c.aliases:
            by_label.setdefault(ct.concept_key(a), c)

    cores = [c for c in ranked if c.level_hint == "CORE"][: BUDGET["CORE"]]
    if not cores:
        cores = [c for c in ranked if c.in_question][: BUDGET["CORE"]]
    if not cores:
        cores = ranked[:1]
    core_keys = {c.key for c in cores}
    for c in cores:
        c.level, c.parent, c.relation = "CORE", None, None

    def cooccur(a: Concept, b: Concept) -> int:
        return len(sidx.get(a.key, set()) & sidx.get(b.key, set()))

    rest = [c for c in ranked if c.key not in core_keys]
    primaries: List[Concept] = []
    secondaries: List[Concept] = []
    for c in rest:
        hinted_parent = by_label.get(ct.concept_key(c.parent_hint or ""))
        if c.level_hint == "SECONDARY" and hinted_parent is not None and hinted_parent.key != c.key:
            secondaries.append(c)
        elif c.level_hint == "PRIMARY" or (
            c.level_hint is None and len(primaries) < BUDGET["PRIMARY"]
            and (any(cooccur(c, k) for k in cores) or c.count >= 2)
        ):
            primaries.append(c)
        else:
            secondaries.append(c)

    # keep primary budget; overflow becomes secondary (never silently dropped)
    primaries.sort(key=_score, reverse=True)
    secondaries = primaries[BUDGET["PRIMARY"]:] + secondaries
    primaries = primaries[: BUDGET["PRIMARY"]]

    for c in primaries:
        parent = by_label.get(ct.concept_key(c.parent_hint or ""))
        if parent is None or parent.key not in core_keys:
            parent = max(cores, key=lambda k: (cooccur(c, k), _score(k)))
        c.level, c.parent = "PRIMARY", parent.key
        c.relation = c.relation_hint or _infer_relation(c, parent, sentences, sidx)

    for c in secondaries:
        parent = by_label.get(ct.concept_key(c.parent_hint or ""))
        if parent is None or parent.key == c.key or parent.level not in ("CORE", "PRIMARY"):
            best = max(primaries, key=lambda k: (cooccur(c, k), _score(k))) if primaries else None
            if best is None or cooccur(c, best) == 0:
                # no evidence linking it to a primary concept: hang it off the core
                best = max(cores, key=lambda k: (cooccur(c, k), _score(k)))
            parent = best
        c.level, c.parent = "SECONDARY", parent.key
        c.relation = c.relation_hint or _infer_relation(c, parent, sentences, sidx)

    # display budget: overflow stays in the payload with visible=False
    shown = 0
    for c in sorted([x for x in concepts.values() if x.level == "SECONDARY"], key=_score, reverse=True):
        shown += 1
        c.visible = shown <= BUDGET["SECONDARY"]


# ── graph validation ────────────────────────────────────────────────────────
def validate_graph(graph: dict) -> List[str]:
    """Deterministic structural checks. Empty list == valid."""
    errors: List[str] = []
    nodes = graph.get("nodes") or []
    ids = [n.get("id") for n in nodes]
    if len(ids) != len(set(ids)):
        errors.append("duplicate_node_id")
    id_set = set(ids)
    concept_nodes = [n for n in nodes if n.get("type") == "concept"]
    keys = [ct.concept_key(n.get("canonicalLabel") or n.get("label")) for n in concept_nodes]
    if len(keys) != len(set(keys)):
        errors.append("duplicate_canonical_concept")
    for n in concept_nodes:
        ok, reason = ct.validate_concept(n.get("label", ""))
        if not ok:
            errors.append(f"invalid_concept:{n.get('label')}:{reason}")
        if n.get("level") not in LEVELS:
            errors.append(f"bad_level:{n.get('id')}")
    if graph.get("status") != "FAILED" and concept_nodes and not any(n.get("level") == "CORE" for n in concept_nodes):
        errors.append("missing_core")
    allowed_rel = set(RELATION_VOCAB.values())
    for e in graph.get("edges") or []:
        if e.get("from") not in id_set or e.get("to") not in id_set:
            errors.append(f"dangling_edge:{e.get('id')}")
        if e.get("from") == e.get("to"):
            errors.append(f"self_loop:{e.get('id')}")
        if e.get("kind") == "semantic" and e.get("relation") not in allowed_rel:
            errors.append(f"relation_not_in_vocab:{e.get('relation')}")
    source_ids = {n.get("id") for n in graph.get("sourceNodes") or []}
    if source_ids & id_set:
        errors.append("agent_node_in_concept_hierarchy")
    for e in graph.get("provenanceEdges") or []:
        if e.get("from") not in source_ids or e.get("to") not in id_set:
            errors.append(f"dangling_provenance:{e.get('id')}")
    # every concept reachable from a core through semantic edges
    parent_of = {e["to"]: e["from"] for e in graph.get("edges") or [] if e.get("kind") == "semantic"}
    core_ids = {n["id"] for n in concept_nodes if n.get("level") == "CORE"}
    for n in concept_nodes:
        cur, hops = n["id"], 0
        while cur not in core_ids and cur in parent_of and hops < 10:
            cur, hops = parent_of[cur], hops + 1
        if cur not in core_ids:
            errors.append(f"orphan_concept:{n.get('label')}")
    return errors


def _edge_id(a: str, b: str, rel: str) -> str:
    return "e_" + hashlib.sha1(f"{a}|{b}|{rel}".encode("utf-8")).hexdigest()[:10]


def _agent_key(ans: dict, i: int) -> str:
    for k in ("agentId", "agent_id", "agentKey", "role"):
        if ans.get(k) not in (None, ""):
            return str(ans[k])
    return f"agent{i + 1}"


# ── public entry ────────────────────────────────────────────────────────────
def failed_graph(question: str, reason: str, validation_errors: Optional[List[str]] = None) -> dict:
    """Full-shape FAILED response (same keys as OK/DEGRADED, empty graph). Never a partial graph."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "question": str(question or "").strip(),
        "status": "FAILED",
        "degraded": True,
        "degradedReason": reason,
        "degradedReasons": [reason],
        "extractor": None,
        "analyzer": ct.analyzer_name(),
        "analyzerDetail": ct.analyzer_unavailable_reason(),
        "nodes": [], "edges": [], "sourceNodes": [], "provenanceEdges": [],
        "stats": {}, "rejected": [], "validationErrors": list(validation_errors or []),
    }


def build_semantic_graph(
    question: str,
    answers: Sequence[dict],
    use_llm: bool = True,
    llm_call=None,
) -> dict:
    """answers: [{agentId?, agentName?, role?, content}] -> mindmap.semantic.v1 dict."""
    question = str(question or "").strip()
    norm_answers: List[Tuple[str, str]] = []
    agent_names: Dict[str, str] = {}
    for i, a in enumerate(answers or []):
        if not isinstance(a, dict):
            continue
        text = str(a.get("content") or a.get("answer") or "").strip()
        if not text:
            continue
        key = _agent_key(a, i)
        norm_answers.append((key, text))
        agent_names[key] = str(a.get("agentName") or a.get("senderName") or a.get("name") or key)

    base = {
        "schemaVersion": SCHEMA_VERSION,
        "question": question,
        "analyzer": ct.analyzer_name(),
        "nodes": [], "edges": [], "sourceNodes": [], "provenanceEdges": [],
    }
    if not norm_answers:
        return failed_graph(question, "EMPTY_ANSWER")

    texts = [t for _, t in norm_answers]
    reject_names = [n for n in agent_names.values()] + list(agent_names.keys())
    rejected: List[Dict[str, str]] = []

    extractor_used = "deterministic"
    degraded_reason = None
    concepts: Dict[str, Concept] = {}
    if use_llm:
        llm_cands, why = llm_candidates(question, texts, llm_call=llm_call)
        if llm_cands is None:
            degraded_reason = why.upper()
        else:
            concepts = _collect(llm_cands, norm_answers, question, reject_names, rejected)
            if len(concepts) >= 3:
                extractor_used = "llm"
            else:
                degraded_reason = "LLM_TOO_FEW_VALID_CONCEPTS"
                concepts = {}
    if not concepts:
        concepts = _collect(deterministic_candidates(question, texts), norm_answers, question,
                            reject_names, rejected)
        _drop_subsumed(concepts)

    sentences: List[str] = []
    for t in texts:
        sentences.extend(split_sentences(t))
    _assign_hierarchy(concepts, sentences)

    q_id = "q_" + hashlib.sha1(question.encode("utf-8")).hexdigest()[:10]
    nodes = [{"id": q_id, "type": "question", "level": "QUESTION", "label": question[:60] or "질문",
              "body": question, "visible": True}]
    edges = []
    order = {"CORE": 0, "PRIMARY": 1, "SECONDARY": 2}
    ordered = sorted(concepts.values(), key=lambda c: (order.get(c.level or "SECONDARY", 3), -_score(c)))
    for c in ordered:
        nodes.append({
            "id": c.id, "type": "concept", "level": c.level,
            "label": c.label, "canonicalLabel": c.label,
            "aliases": sorted(c.aliases),
            "surfaceForms": sorted(c.surface_forms),
            "sources": sorted(c.agents),
            "extractedBy": sorted(c.sources),
            "mentions": c.count,
            "visible": c.visible,
        })
        if c.level == "CORE":
            edges.append({"id": _edge_id(q_id, c.id, "topic"), "from": q_id, "to": c.id,
                          "kind": "topic", "relation": "질문 주제", "relationKey": "TOPIC"})
        elif c.parent:
            parent_id = concepts[c.parent].id
            rel = c.relation or "RELATED"
            edges.append({"id": _edge_id(parent_id, c.id, rel), "from": parent_id, "to": c.id,
                          "kind": "semantic", "relation": RELATION_VOCAB[rel], "relationKey": rel})

    source_nodes, prov_edges = [], []
    for key, name in agent_names.items():
        sid = "s_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
        source_nodes.append({"id": sid, "type": "agent", "level": "SOURCE", "label": name, "agentKey": key})
        for c in ordered:
            if key in c.agents and c.level in ("CORE", "PRIMARY"):
                prov_edges.append({"id": _edge_id(sid, c.id, "source"), "from": sid, "to": c.id,
                                   "kind": "provenance", "relation": "출처", "relationKey": "SOURCE"})

    # A host without kiwipiepy still answers, but never as a silent OK: the rule analyzer
    # is a weaker normalizer/validator, so the graph is flagged.
    degraded_reasons = [r for r in (degraded_reason,) if r]
    if ct.analyzer_unavailable_reason() is not None:
        degraded_reasons.append("ANALYZER_UNAVAILABLE")

    levels = [c.level for c in concepts.values()]
    graph = {
        **base,
        "status": "OK" if not degraded_reasons else "DEGRADED",
        "extractor": extractor_used,
        "degraded": bool(degraded_reasons),
        "degradedReason": degraded_reasons[0] if degraded_reasons else None,
        "degradedReasons": degraded_reasons,
        "analyzerDetail": ct.analyzer_unavailable_reason(),
        "nodes": nodes, "edges": edges,
        "sourceNodes": source_nodes, "provenanceEdges": prov_edges,
        "stats": {
            "conceptCount": len(concepts),
            "visibleConceptCount": sum(1 for c in concepts.values() if c.visible),
            "core": levels.count("CORE"), "primary": levels.count("PRIMARY"),
            "secondary": levels.count("SECONDARY"), "rejectedCount": len(rejected),
        },
        "rejected": rejected[:50],
    }
    if not concepts:
        failed = failed_graph(question, "NO_VALID_CONCEPTS")
        failed["degradedReasons"] += degraded_reasons
        failed["rejected"] = graph["rejected"]
        failed["stats"] = graph["stats"]
        return failed
    errors = validate_graph(graph)
    graph["validationErrors"] = errors
    if errors:
        # a structurally broken graph is never returned as OK/DEGRADED, and never half-rendered
        logger.warning("[mindmap] graph validation failed: %s", errors[:5])
        return failed_graph(question, "GRAPH_VALIDATION_FAILED", errors)
    return graph
