"""Semantic Learning Concept Map — AI07 mindmap contract tests.

Every test runs twice: with the kiwi POS analyzer and with the rule analyzer
(a host without kiwipiepy), so the deterministic gate holds on both.
"""
import json
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.mindmap import concept_text as ct
from app.mindmap.extractor import RELATION_VOCAB
from app.mindmap.graph_builder import build_semantic_graph, validate_graph


@pytest.fixture(params=["kiwi", "rules"], autouse=True)
def analyzer(request):
    if request.param == "kiwi":
        pytest.importorskip("kiwipiepy")
    ct.set_rules_only(request.param == "rules")
    yield request.param
    ct.set_rules_only(False)


AGENTS = ("개념 정리 교수", "쉬운 풀이 튜터", "논점 검증 코치")


def _answers(*texts):
    return [{"agentId": str(i + 1), "agentName": AGENTS[i % 3], "content": t} for i, t in enumerate(texts)]


def _assert_valid_status(g):
    """kiwi -> OK. rules (kiwipiepy missing) -> never a silent OK: DEGRADED/ANALYZER_UNAVAILABLE."""
    assert g["validationErrors"] == [], g["validationErrors"]
    if ct.analyzer_name() == "kiwi":
        assert g["status"] == "OK" and g["degraded"] is False and g["degradedReasons"] == []
    else:
        assert g["status"] == "DEGRADED" and g["degraded"] is True
        assert g["degradedReasons"] == ["ANALYZER_UNAVAILABLE"] and g["degradedReason"] == "ANALYZER_UNAVAILABLE"


def _concepts(graph):
    return [n for n in graph["nodes"] if n["type"] == "concept"]


def _labels(graph):
    return [n["label"] for n in _concepts(graph)]


JDBC_Q = "JDBC가 뭐야?"
JDBC_A = _answers(
    "**JDBC**(Java Database Connectivity)는 자바 애플리케이션에서 데이터베이스 연결을 담당하는 표준 API입니다. "
    "JDBC의 핵심 구성 요소는 Connection, Statement, ResultSet 인터페이스입니다. "
    "JDBC가 SQL 실행을 수행하고 ResultSet으로 결과를 받습니다. "
    "지금 말할 수 있는 것은 아직 판단되었고 요청했습니다.",
    "JDBC는 자바 플랫폼에서의 데이터베이스 연결 통로예요. 먼저 DriverManager로 Connection을 얻고, "
    "다음으로 Statement로 SQL 실행을 요청합니다. 있는 그대로 말하면 JDBC에 드라이버가 필요합니다.",
    "JDBC를 쓸 때는 트랜잭션 관리가 중요합니다. 예를 들어 PreparedStatement를 쓰면 SQL 인젝션을 막을 수 있습니다.",
)

FORBIDDEN = ["JDBC가", "JDBC의", "JDBC에", "JDBC는", "JDBC를", "있는", "말할", "요청했습니다",
             "판단되었고", "아직", "지금", "플랫폼에서의"]


# ── Test 1: "JDBC가 뭐야?" ───────────────────────────────────────────────────
def test_jdbc_no_fragment_nodes_and_single_canonical():
    g = build_semantic_graph(JDBC_Q, JDBC_A, use_llm=False)
    _assert_valid_status(g)
    labels = _labels(g)
    for bad in FORBIDDEN:
        assert bad not in labels, f"fragment {bad!r} leaked as concept: {labels}"
    jdbc = [n for n in _concepts(g) if ct.concept_key(n["label"]) == "jdbc"]
    assert len(jdbc) == 1, labels
    assert jdbc[0]["level"] == "CORE"
    assert "Java Database Connectivity" in jdbc[0]["aliases"]


@pytest.mark.parametrize("surface", ["JDBC가", "JDBC의", "JDBC는", "JDBC를", "JDBC에서", "JDBC에", "JDBC입니다"])
def test_surface_forms_normalize_to_canonical(surface):
    assert ct.normalize_surface(surface) == "JDBC"


@pytest.mark.parametrize("fragment,reason_prefix", [
    ("JDBC가", "particle"), ("플랫폼에서의", "particle"), ("요청했습니다", "predicate"),
    ("판단되었고", "predicate"), ("있는", ""), ("말할", "predicate"), ("아직", "adverb"),
    ("지금", "adverb"), ("**JDBC**", "format"), ("- 목록", "format"), ("1.", ""),
    ("JDBC는 자바에서 데이터베이스에 연결하기 위한 표준 인터페이스이며 SQL을 실행한다", "sentence"),
])
def test_validator_rejects_non_concepts(fragment, reason_prefix):
    ok, reason = ct.validate_concept(fragment)
    assert not ok, fragment
    assert reason.startswith(reason_prefix), (fragment, reason)


@pytest.mark.parametrize("concept", [
    "JDBC", "데이터베이스 연결", "SQL 실행", "Connection", "ResultSet", "의존성 주입",
    "객체 지향 프로그래밍", "트랜잭션 격리 수준", "Gradient Descent", "TCP 3-way handshake",
])
def test_validator_accepts_learning_concepts(concept):
    assert ct.validate_concept(concept) == (True, "")


def test_rules_are_general_not_a_blacklist():
    # same failure classes with words that never appeared on screen
    for frag in ("분석했습니다", "처리되었고", "없는", "Kafka가", "Redis의", "서버에서의", "또한"):
        assert not ct.validate_concept(ct._clean(frag))[0] or ct.normalize_surface(frag) != frag, frag
    for frag in ("분석했습니다", "처리되었고", "없는", "또한"):
        assert not ct.validate_concept(frag)[0], frag
    assert ct.normalize_surface("Kafka가") == "Kafka"
    assert ct.normalize_surface("Redis의") == "Redis"


# ── Test 2: compound concepts stay whole ─────────────────────────────────────
COMPOUND_A = _answers(
    "의존성 주입(Dependency Injection)은 **객체 지향 프로그래밍**에서 결합도를 낮추는 설계 기법입니다. "
    "스프링 컨테이너가 의존성 주입을 담당합니다.",
    "**트랜잭션 격리 수준**은 동시에 실행되는 트랜잭션 사이의 간섭을 제어합니다. "
    "객체 지향 프로그래밍과 달리 트랜잭션 격리 수준은 데이터베이스의 개념입니다.",
)


def test_compound_concepts_not_split():
    g = build_semantic_graph("의존성 주입과 트랜잭션 격리 수준을 설명해줘", COMPOUND_A, use_llm=False)
    _assert_valid_status(g)
    labels = _labels(g)
    for whole in ("의존성 주입", "객체 지향 프로그래밍", "트랜잭션 격리 수준"):
        assert whole in labels, labels
    for piece in ("의존성", "주입", "지향", "격리", "수준", "객체 지향", "격리 수준"):
        assert piece not in labels, f"{piece!r} split out of a compound: {labels}"
    di = next(n for n in _concepts(g) if n["label"] == "의존성 주입")
    assert "Dependency Injection" in di["aliases"]


# ── Test 3: technical names are never damaged ────────────────────────────────
@pytest.mark.parametrize("name", ["Java", "Kafka", "CUDA", "C++", "Node.js", "REST API", "Big-O"])
def test_tech_names_untouched(name):
    assert ct.normalize_surface(name) == name
    assert ct.validate_concept(name) == (True, "")


@pytest.mark.parametrize("surface,expected", [
    ("Java는", "Java"), ("Kafka를", "Kafka"), ("CUDA에서", "CUDA"), ("C++는", "C++"),
])
def test_tech_names_particles_removed(surface, expected):
    assert ct.normalize_surface(surface) == expected


@pytest.mark.parametrize("noun", ["전문가", "정확도", "복잡도", "유사도", "시간 복잡도", "고양이", "평가", "국가"])
def test_korean_nouns_with_particle_like_endings_untouched(noun):
    assert ct.normalize_surface(noun) == noun


def test_particle_stripped_when_stem_is_attested():
    assert ct.normalize_surface("유사도", attested={ct.concept_key("유사")}) == "유사"


# ── Test 4: cross-domain regression ──────────────────────────────────────────
DOMAINS = [
    ("REST API가 뭐야?", "REST API",
     "REST API는 HTTP 메서드로 자원을 다루는 아키텍처 스타일입니다. REST API에서 URI는 자원을 식별하고, "
     "GET, POST, PUT, DELETE 메서드가 행위를 표현합니다. 예를 들어 GET 요청은 자원을 조회합니다."),
    ("Transaction이 뭐야?", "Transaction",
     "Transaction은 데이터베이스 작업의 논리적 단위입니다. Transaction은 ACID 특성을 가지며, "
     "원자성(Atomicity)은 모두 성공하거나 모두 실패함을 보장합니다. COMMIT과 ROLLBACK으로 종료됩니다."),
    ("Gradient Descent가 뭐야?", "Gradient Descent",
     "Gradient Descent는 손실 함수의 기울기를 따라 파라미터를 갱신하는 최적화 알고리즘입니다. "
     "Gradient Descent에서 학습률이 너무 크면 발산하고, 너무 작으면 수렴이 느립니다. "
     "Stochastic Gradient Descent는 미니배치를 사용합니다."),
    ("Transformer Attention이 뭐야?", "Transformer Attention",
     "Transformer Attention은 Query, Key, Value 벡터로 토큰 사이의 관련도를 계산합니다. "
     "Transformer Attention의 Self-Attention은 같은 시퀀스 안의 토큰끼리 가중치를 부여합니다. "
     "Multi-Head Attention은 여러 관점의 표현을 병렬로 학습합니다."),
    ("Virtual Memory가 뭐야?", "Virtual Memory",
     "Virtual Memory는 물리 메모리보다 큰 주소 공간을 제공하는 운영체제 기법입니다. "
     "Virtual Memory는 페이지 테이블로 가상 주소를 물리 주소로 변환합니다. "
     "필요한 페이지가 없으면 페이지 폴트가 발생합니다."),
    ("TCP 3-way handshake가 뭐야?", "TCP 3-way handshake",
     "TCP 3-way handshake는 연결을 수립하는 과정입니다. 먼저 클라이언트가 SYN을 보내고, "
     "다음으로 서버가 SYN-ACK으로 응답하며, 마지막으로 클라이언트가 ACK을 보냅니다. "
     "TCP 3-way handshake 덕분에 양쪽의 시퀀스 번호가 동기화됩니다."),
    ("JDBC가 뭐야?", "JDBC", JDBC_A[0]["content"]),
]
_PARTICLE_TAIL = re.compile(r"[A-Za-z0-9)+#][은는이가을를의에와과도로]$")


@pytest.mark.parametrize("question,core,answer", DOMAINS, ids=[d[1] for d in DOMAINS])
def test_domain_regression(question, core, answer):
    g = build_semantic_graph(question, _answers(answer), use_llm=False)
    _assert_valid_status(g)
    assert validate_graph(g) == []
    concepts = _concepts(g)
    cores = [n["label"] for n in concepts if n["level"] == "CORE"]
    assert core in cores, (cores, _labels(g))
    for n in concepts:
        assert ct.validate_concept(n["label"])[0], n["label"]
        assert not _PARTICLE_TAIL.search(n["label"]), n["label"]
    keys = [ct.concept_key(n["label"]) for n in concepts]
    assert len(keys) == len(set(keys))
    assert 1 <= g["stats"]["core"] <= 2
    assert g["stats"]["primary"] <= 6
    assert sum(1 for n in concepts if n["visible"] and n["level"] == "SECONDARY") <= 12


# ── hierarchy / relation / provenance ────────────────────────────────────────
def test_relations_use_closed_vocabulary_and_are_not_all_contains():
    g = build_semantic_graph(JDBC_Q, JDBC_A, use_llm=False)
    semantic = [e for e in g["edges"] if e["kind"] == "semantic"]
    assert semantic
    assert {e["relation"] for e in semantic} <= set(RELATION_VOCAB.values())
    assert "포함 개념" not in {e["relation"] for e in g["edges"]}
    by_id = {n["id"]: n["label"] for n in g["nodes"]}
    triples = {(by_id[e["from"]], e["relation"], by_id[e["to"]]) for e in semantic}
    assert ("JDBC", "구성 요소", "Connection") in triples, triples


def test_hierarchy_question_core_primary_secondary():
    g = build_semantic_graph(JDBC_Q, JDBC_A, use_llm=False)
    q = [n for n in g["nodes"] if n["type"] == "question"]
    assert len(q) == 1
    topic = [e for e in g["edges"] if e["kind"] == "topic"]
    assert topic and all(e["from"] == q[0]["id"] for e in topic)
    levels = {n["id"]: n["level"] for n in g["nodes"]}
    for e in g["edges"]:
        if e["kind"] == "semantic":
            assert (levels[e["from"]], levels[e["to"]]) in {("CORE", "PRIMARY"), ("CORE", "SECONDARY"),
                                                            ("PRIMARY", "SECONDARY")}
    # no "answer" hub node radiating sentence fragments
    assert not [n for n in g["nodes"] if n["type"] == "answer"]


def test_agents_are_provenance_not_concepts():
    g = build_semantic_graph(JDBC_Q, JDBC_A, use_llm=False)
    labels = _labels(g)
    for name in AGENTS:
        assert name not in labels
    assert {n["label"] for n in g["sourceNodes"]} == set(AGENTS)
    assert all(n["type"] == "agent" for n in g["sourceNodes"])
    concept_ids = {n["id"] for n in _concepts(g)}
    for e in g["provenanceEdges"]:
        assert e["kind"] == "provenance" and e["to"] in concept_ids
    jdbc = next(n for n in _concepts(g) if n["label"] == "JDBC")
    assert set(jdbc["sources"]) == {"1", "2", "3"}


def test_agent_name_rejected_even_if_llm_emits_it():
    fake = lambda s, u: json.dumps({"concepts": [
        {"label": "JDBC", "level": "CORE"},
        {"label": "개념 정리 교수", "level": "PRIMARY", "parent": "JDBC", "relation": "관련 개념"},
        {"label": "Connection", "level": "PRIMARY", "parent": "JDBC", "relation": "구성 요소"},
        {"label": "Statement", "level": "PRIMARY", "parent": "JDBC", "relation": "구성 요소"},
    ]})
    g = build_semantic_graph(JDBC_Q, JDBC_A, use_llm=True, llm_call=fake)
    assert "개념 정리 교수" not in _labels(g)
    assert any(r["reason"] == "agent_or_source_name" for r in g["rejected"])


# ── LLM structured path ─────────────────────────────────────────────────────
def test_llm_path_grounds_and_validates():
    fake = lambda s, u: json.dumps({"concepts": [
        {"label": "JDBC", "level": "CORE", "parent": None, "relation": None},
        {"label": "JDBC가", "level": "PRIMARY", "parent": "JDBC", "relation": "정의"},
        {"label": "데이터베이스 연결", "level": "PRIMARY", "parent": "JDBC", "relation": "목적"},
        {"label": "SQL 실행", "level": "PRIMARY", "parent": "JDBC", "relation": "수행"},
        {"label": "Connection", "level": "PRIMARY", "parent": "JDBC", "relation": "구성 요소"},
        {"label": "ResultSet", "level": "SECONDARY", "parent": "Connection", "relation": "구성 요소"},
        {"label": "있는", "level": "SECONDARY", "parent": "JDBC", "relation": "관련 개념"},
        {"label": "Hibernate", "level": "SECONDARY", "parent": "JDBC", "relation": "비교"},
        {"label": "SQL 실행", "level": "PRIMARY", "parent": "JDBC", "relation": "unknown-rel"},
    ]}, ensure_ascii=False)
    g = build_semantic_graph(JDBC_Q, JDBC_A, use_llm=True, llm_call=fake)
    assert g["extractor"] == "llm"
    _assert_valid_status(g)
    labels = _labels(g)
    assert labels.count("JDBC") == 1 and "있는" not in labels
    assert "Hibernate" not in labels                           # not in the answer -> no hallucination
    assert any(r["reason"] == "not_in_answer" for r in g["rejected"])
    by_id = {n["id"]: n["label"] for n in g["nodes"]}
    triples = {(by_id[e["from"]], e["relation"], by_id[e["to"]]) for e in g["edges"] if e["kind"] == "semantic"}
    assert ("JDBC", "목적", "데이터베이스 연결") in triples
    assert ("Connection", "구성 요소", "ResultSet") in triples


@pytest.mark.parametrize("llm", [
    lambda s, u: "죄송합니다. JSON을 만들 수 없습니다.",
    lambda s, u: '{"concepts": [{"label": "JDBC"',
    lambda s, u: "",
    lambda s, u: (_ for _ in ()).throw(TimeoutError("ollama")),
], ids=["prose", "truncated", "empty", "exception"])
def test_llm_failure_is_explicitly_degraded_not_hidden(llm):
    g = build_semantic_graph(JDBC_Q, JDBC_A, use_llm=True, llm_call=llm)
    assert g["status"] == "DEGRADED" and g["degraded"] is True
    assert g["degradedReason"] in {"LLM_UNPARSEABLE", "LLM_ERROR", "LLM_TOO_FEW_VALID_CONCEPTS"}
    assert g["degradedReasons"][0] == g["degradedReason"]
    assert g["extractor"] == "deterministic"
    assert validate_graph(g) == []
    assert "JDBC가" not in _labels(g)


def test_empty_answer_fails_explicitly():
    g = build_semantic_graph("JDBC가 뭐야?", [{"content": "   "}], use_llm=False)
    assert g["status"] == "FAILED" and g["degraded"] and g["nodes"] == []


def test_deterministic_same_input_same_output():
    a = build_semantic_graph(JDBC_Q, JDBC_A, use_llm=False)
    b = build_semantic_graph(JDBC_Q, JDBC_A, use_llm=False)
    assert json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)


def test_graph_validator_catches_structural_defects():
    g = build_semantic_graph(JDBC_Q, JDBC_A, use_llm=False)
    broken = json.loads(json.dumps(g))
    broken["nodes"].append(dict(broken["nodes"][1]))
    broken["edges"].append({"id": "x", "from": "nope", "to": broken["nodes"][1]["id"], "kind": "semantic",
                            "relation": "포함 개념"})
    broken["nodes"].append({"id": "c_bad", "type": "concept", "level": "PRIMARY", "label": "JDBC가"})
    errs = validate_graph(broken)
    assert "duplicate_node_id" in errs
    assert any(e.startswith("dangling_edge") for e in errs)
    assert any(e.startswith("relation_not_in_vocab") for e in errs)
    assert any(e.startswith("invalid_concept:JDBC가") for e in errs)
    assert any(e.startswith("orphan_concept") for e in errs)


# ── HTTP contract ───────────────────────────────────────────────────────────
def test_endpoint_contract():
    from app.api.mindmap_routes import router
    app = FastAPI()
    app.include_router(router)
    r = TestClient(app).post("/api/ai/mindmap/semantic-graph", json={
        "question": JDBC_Q, "useLlm": False,
        "answers": [{"agentId": 1, "agentName": AGENTS[0], "content": JDBC_A[0]["content"]}],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("OK", "DEGRADED")
    assert body["schemaVersion"] == "mindmap.semantic.v1"
    for key in ("status", "degraded", "nodes", "edges", "sourceNodes", "provenanceEdges", "stats"):
        assert key in body
    node = next(n for n in body["nodes"] if n["type"] == "concept")
    for key in ("id", "label", "canonicalLabel", "aliases", "surfaceForms", "level", "visible", "sources"):
        assert key in node
    r2 = TestClient(app).post("/api/ai/mindmap/semantic-graph",
                              json={"question": "x", "answers": [{"content": "   "}], "useLlm": False})
    assert r2.status_code == 422 and r2.json()["status"] == "FAILED"
    assert r2.json()["degradedReason"] == "EMPTY_ANSWER" and r2.json()["nodes"] == []
