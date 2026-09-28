"""AI07 production handoff v2 — live-app contract tests.

MindMap  M1-M6 : POST /api/ai/mindmap/semantic-graph on the live entrypoint (hotfix_main:app)
Material Q1-Q12: POST /api/ai/quiz (ArchiveDetail -> Spring AiIntegrationService.generateQuiz)
Dependency D1-D3: kiwipiepy is declared/pinned, active here, and its absence is DEGRADED, not OK.

No network / Ollama: every LLM call is replaced by a deterministic fake.
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import hotfix_main
from app.mindmap import concept_text as ct
from app.mindmap import graph_builder as gb
from app.services import quiz_contract as qc

APP = hotfix_main.app
CLIENT = TestClient(APP)
MINDMAP = "/api/ai/mindmap/semantic-graph"
QUIZ = "/api/ai/quiz"


# ════════════════════════════════════════════════════════════════════════════
# MindMap
# ════════════════════════════════════════════════════════════════════════════
JDBC_Q = "JDBC가 뭐야?"
JDBC_ANSWERS = [
    {"agentId": 1, "agentName": "개념 정리 교수", "content":
        "**JDBC**(Java Database Connectivity)는 자바 애플리케이션에서 데이터베이스 연결을 담당하는 표준 API입니다. "
        "JDBC의 핵심 구성 요소는 Connection, Statement, ResultSet 인터페이스입니다. "
        "JDBC가 SQL 실행을 수행하고 ResultSet으로 결과를 받습니다."},
    {"agentId": "2", "agentName": "쉬운 풀이 튜터", "content":
        "JDBC는 자바 플랫폼에서의 데이터베이스 연결 통로예요. 먼저 DriverManager로 Connection을 얻고, "
        "다음으로 Statement로 SQL 실행을 요청합니다. JDBC에 드라이버가 필요합니다."},
]


@pytest.fixture(autouse=True)
def _kiwi_default():
    ct.set_rules_only(False)
    yield
    ct.set_rules_only(False)


def _post_mindmap(body):
    return CLIENT.post(MINDMAP, json=body)


def _concept_labels(body):
    return [n["label"] for n in body["nodes"] if n["type"] == "concept"]


def test_m1_live_entrypoint_registers_semantic_graph_once():
    import main
    assert main.app is APP, "hotfix_main must extend main.app (systemd: uvicorn hotfix_main:app)"
    posts = Counter(r.path for r in APP.routes if "POST" in (getattr(r, "methods", None) or set()))
    assert posts[MINDMAP] == 1
    assert posts[QUIZ] == 1 and posts["/api/ai/quiz/generate"] == 1
    assert MINDMAP in APP.openapi()["paths"]


def test_m2_jdbc_semantic_graph_ok():
    r = _post_mindmap({"question": JDBC_Q, "answers": JDBC_ANSWERS, "useLlm": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schemaVersion"] == "mindmap.semantic.v1"
    assert body["status"] == "OK" and body["degraded"] is False and body["degradedReasons"] == []
    assert body["validationErrors"] == [] and body["analyzer"] == "kiwi"
    core = [n for n in body["nodes"] if n.get("level") == "CORE"]
    assert [n["label"] for n in core] == ["JDBC"]
    assert {s["label"] for s in body["sourceNodes"]} == {"개념 정리 교수", "쉬운 풀이 튜터"}
    assert all(e["kind"] == "provenance" for e in body["provenanceEdges"])


def test_m3_no_particle_garbage():
    body = _post_mindmap({"question": JDBC_Q, "answers": JDBC_ANSWERS, "useLlm": False}).json()
    labels = _concept_labels(body)
    for bad in ("JDBC가", "JDBC의", "JDBC는", "JDBC에", "플랫폼에서의", "요청합니다"):
        assert bad not in labels
    assert labels.count("JDBC") == 1


def test_m4_llm_failure_is_degraded_fallback(monkeypatch):
    import app.services.ollama_client as oc

    def boom(*a, **k):
        raise TimeoutError("ollama down")
    monkeypatch.setattr(oc, "ask_ollama", boom)
    r = _post_mindmap({"question": JDBC_Q, "answers": JDBC_ANSWERS, "useLlm": True})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "DEGRADED" and body["degraded"] is True
    assert body["degradedReason"] == "LLM_ERROR" and body["extractor"] == "deterministic"
    assert body["validationErrors"] == [] and "JDBC" in _concept_labels(body)


@pytest.mark.parametrize("payload", [
    {"question": "x"},                                                      # answers missing
    {"question": "x", "answers": []},                                       # min 1
    {"question": "x", "answers": "JDBC는 API"},                             # not a list
    {"question": "x", "answers": [{"content": 123}]},                       # content must be str
    {"question": "x" * 2001, "answers": [{"content": "JDBC"}]},             # question max 2000
    {"question": "x", "answers": [{"content": "a" * 20001}]},               # content max 20000
    {"question": "x", "answers": [{"content": "JDBC"}] * 13},               # answers max 12
], ids=["missing", "empty", "not-list", "content-int", "q-too-long", "a-too-long", "too-many"])
def test_m5_malformed_request_is_422(payload):
    r = _post_mindmap(payload)
    assert r.status_code == 422
    assert "detail" in r.json()


def test_m5_blank_answers_is_422_failed_contract():
    r = _post_mindmap({"question": "x", "answers": [{"content": "  "}], "useLlm": False})
    assert r.status_code == 422
    body = r.json()
    assert body["status"] == "FAILED" and body["degradedReason"] == "EMPTY_ANSWER"
    assert body["nodes"] == [] and body["edges"] == [] and body["schemaVersion"] == "mindmap.semantic.v1"


def test_m5_no_concepts_is_422_failed():
    r = _post_mindmap({"question": "음", "answers": [{"content": "네 그렇습니다. 좋아요."}], "useLlm": False})
    assert r.status_code == 422
    assert r.json()["status"] == "FAILED" and r.json()["degradedReason"] == "NO_VALID_CONCEPTS"


def test_m_broken_graph_is_500_failed_never_ok(monkeypatch):
    monkeypatch.setattr(gb, "validate_graph", lambda g: ["dangling_edge:e_x"])
    r = _post_mindmap({"question": JDBC_Q, "answers": JDBC_ANSWERS, "useLlm": False})
    assert r.status_code == 500
    body = r.json()
    assert body["status"] == "FAILED" and body["degradedReason"] == "GRAPH_VALIDATION_FAILED"
    assert body["nodes"] == [] and body["validationErrors"] == ["dangling_edge:e_x"]


def test_m_timeout_is_504_failed(monkeypatch):
    import app.api.mindmap_routes as mr
    monkeypatch.setattr(mr, "MINDMAP_TIMEOUT_SECONDS", 0.05)
    real = gb.build_semantic_graph

    def slow(*a, **k):
        time.sleep(0.3)
        return real(*a, **k)
    monkeypatch.setattr(gb, "build_semantic_graph", slow)
    r = _post_mindmap({"question": JDBC_Q, "answers": JDBC_ANSWERS, "useLlm": False})
    assert r.status_code == 504
    body = r.json()
    assert body["status"] == "FAILED" and body["degradedReason"] == "TIMEOUT"
    for key in ("nodes", "edges", "sourceNodes", "provenanceEdges", "validationErrors", "rejected", "extractor"):
        assert key in body


@pytest.mark.parametrize("name", ["Java", "Kafka", "CUDA"])
def test_m6_tech_names_preserved(name):
    text = f"{name}는 널리 쓰이는 기술입니다. {name}의 핵심 개념을 이해하면 {name}를 활용한 시스템 설계가 쉬워집니다."
    r = _post_mindmap({"question": f"{name}가 뭐야?", "answers": [{"content": text}], "useLlm": False})
    assert r.status_code == 200, r.text
    labels = _concept_labels(r.json())
    assert name in labels
    assert not any(label != name and label.startswith(name) and len(label) <= len(name) + 1 for label in labels)


# ════════════════════════════════════════════════════════════════════════════
# Dependency (kiwipiepy)
# ════════════════════════════════════════════════════════════════════════════
REQ = Path(__file__).resolve().parents[1] / "requirements.txt"


def test_d1_kiwipiepy_pinned_in_production_requirements():
    import importlib.metadata as md
    lines = [l.split("#")[0].strip() for l in REQ.read_text(encoding="utf-8").splitlines()]
    pins = dict(l.split("==", 1) for l in lines if "==" in l)
    assert pins.get("kiwipiepy") == md.version("kiwipiepy")
    assert pins.get("kiwipiepy_model") == md.version("kiwipiepy_model")


def test_d2_kiwi_active_in_this_environment():
    assert ct.analyzer_name() == "kiwi" and ct.analyzer_unavailable_reason() is None


def test_d3_missing_kiwipiepy_is_degraded_not_silent_ok(monkeypatch):
    monkeypatch.setattr(ct, "_KIWI", None)
    monkeypatch.setattr(ct, "_KIWI_FAILED", False)
    monkeypatch.setattr(ct, "_KIWI_ERROR", None)
    monkeypatch.setitem(sys.modules, "kiwipiepy", None)       # import -> ImportError, like a fresh host
    r = _post_mindmap({"question": JDBC_Q, "answers": JDBC_ANSWERS, "useLlm": False})
    assert r.status_code == 200
    body = r.json()
    assert body["analyzer"] == "rules"
    assert body["status"] == "DEGRADED" and body["degraded"] is True
    assert body["degradedReasons"] == ["ANALYZER_UNAVAILABLE"]
    assert "ImportError" in (body["analyzerDetail"] or "") or "ModuleNotFound" in (body["analyzerDetail"] or "")
    assert "JDBC가" not in _concept_labels(body)


# ════════════════════════════════════════════════════════════════════════════
# Material quiz  POST /api/ai/quiz
# ════════════════════════════════════════════════════════════════════════════
PDF_TEXT = (
    "JDBC(Java Database Connectivity)는 자바 애플리케이션이 관계형 데이터베이스에 접근하기 위한 표준 API이다. "
    "DriverManager는 JDBC 드라이버를 관리하고 Connection 객체를 생성한다. Connection은 데이터베이스와의 세션을 나타낸다. "
    "Statement는 SQL 문을 실행하며, PreparedStatement는 미리 컴파일된 SQL을 사용해 SQL 인젝션을 방지한다. "
    "ResultSet은 SELECT 쿼리의 결과를 행 단위로 읽는 커서 역할을 한다. 트랜잭션은 commit과 rollback으로 제어한다. "
    "커넥션 풀은 Connection 생성 비용을 줄이기 위해 미리 만들어 둔 연결을 재사용한다. "
    "JDBC 사용 후에는 ResultSet, Statement, Connection 순서로 자원을 닫아야 한다.\n"
) * 2


def _item(q="DriverManager의 역할은 무엇인가?", choices=None, ca="JDBC 드라이버를 관리하고 Connection을 생성한다", **extra):
    choices = choices if choices is not None else [
        "JDBC 드라이버를 관리하고 Connection을 생성한다", "SQL 결과를 행 단위로 읽는다",
        "트랜잭션을 롤백한다", "SQL 인젝션을 방지한다"]
    d = {"question": q, "choices": choices, "correct_answer": ca,
         "explanation": "자료에 따르면 DriverManager는 드라이버를 관리하고 Connection을 만든다.",
         "wrong_explanations": ["a", "b", "c"], "concept": "DriverManager"}
    d.update(extra)
    return d


GOOD_ITEMS = [
    _item(),
    _item(q="ResultSet은 무엇을 하는가?", choices=["SELECT 결과를 행 단위로 읽는다", "Connection을 생성한다",
                                                  "SQL을 미리 컴파일한다", "드라이버를 등록한다"],
          ca="SELECT 결과를 행 단위로 읽는다", concept="ResultSet"),
    _item(q="PreparedStatement를 쓰는 이유는?", choices=["화면을 그린다", "SQL 인젝션을 방지한다",
                                                      "파일을 압축한다", "로그를 남긴다"],
          ca="SQL 인젝션을 방지한다", concept="PreparedStatement"),
]


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace Qwen/OpenAI with a scripted raw string (goes through the real JSON parser)."""
    import app.services.study_action_router as sar

    def use(raw):
        calls = {"n": 0}

        def fake(system, user, max_tokens=None):
            calls["n"] += 1
            return raw() if callable(raw) else raw
        monkeypatch.setattr(sar, "primary_llm", fake)
        monkeypatch.setattr(sar, "refiner_llm", lambda s, u, max_tokens=None: "")
        return calls
    return use


def _quiz(count=3, difficulty="easy", material_id=11):
    return CLIENT.post(QUIZ, json={"material_id": material_id, "document_title": "JDBC 기초", "difficulty": difficulty,
                                   "count": count, "questionCount": count, "document_text": PDF_TEXT, "text": PDF_TEXT})


def _raw(items):
    return json.dumps({"questions": items}, ensure_ascii=False)


def _assert_integrity(body):
    qs = body["quizzes"]
    assert qc.validate_quiz_contract(qs) == []
    assert json.loads(body["quizData"]) == qs
    for q in qs:
        assert q["question"].strip() and len(set(q["options"])) == len(q["options"]) and all(o.strip() for o in q["options"])
        idx = q["correctAnswer"]
        assert type(idx) is int and 0 <= idx < len(q["options"])
        assert q["answer"] == q["answerIndex"] == idx
        assert q["optionIds"][idx] == q["correctOptionIds"][0] and len(q["correctOptionIds"]) == 1
        assert q["answerType"] == "SINGLE_CHOICE"
    assert len({q["questionId"] for q in qs}) == len(qs)
    assert len({re.sub(r"\W", "", q["question"]) for q in qs}) == len(qs)


def test_q1_normal_quiz_ok(fake_llm):
    fake_llm(_raw(GOOD_ITEMS))
    r = _quiz()
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and body["status"] == "OK"
    assert body["degraded"] is False and body["fallbackUsed"] is False and body["fallbackQuestionCount"] == 0
    assert body["schemaVersion"] == "quiz.v2" and body["quizId"].startswith("quiz_")
    assert body["source"] == "AI_REPAIRED" and body["generatedCount"] == 3 and body["partial"] is False
    _assert_integrity(body)
    assert [q["correctAnswer"] for q in body["quizzes"]] == [0, 0, 1]


@pytest.mark.parametrize("bad,reason", [
    (_item(choices=["A안", "A안", "B안", "C안"], ca="A안"), "DUPLICATE_OPTION"),
    (_item(choices=["Connection 생성", " connection  생성 ", "B안", "C안"], ca="B안"), "DUPLICATE_OPTION"),
    (_item(choices=["Connection 생성", "", "B안", "C안"], ca="B안"), "EMPTY_OPTION"),
    (_item(choices=["Connection 생성", "   ", "B안", "C안"], ca="B안"), "EMPTY_OPTION"),
], ids=["dup", "dup-normalized", "empty", "blank"])
def test_q2_q3_broken_options_rejected_unit(bad, reason):
    valid, rejects = qc.harden_material_questions([bad])
    assert valid == [] and rejects[0]["reason"] == reason


def test_q2_duplicate_options_repaired_by_pdf_fallback_not_served(fake_llm):
    items = [dict(GOOD_ITEMS[0], choices=["같은 보기", "같은 보기", "다른 보기", "또 다른 보기"], correct_answer="같은 보기"),
             GOOD_ITEMS[1], GOOD_ITEMS[2]]
    fake_llm(_raw(items))
    body = _quiz().json()
    assert body["success"] is True
    _assert_integrity(body)
    assert all("같은 보기" not in q["options"] for q in body["quizzes"])
    assert body["status"] == "DEGRADED_FALLBACK" and body["fallbackUsed"] is True and body["fallbackQuestionCount"] == 1


def test_q3_empty_option_never_served(fake_llm):
    items = [dict(GOOD_ITEMS[0], choices=["", "b", "c", "d"], correct_answer="b"), GOOD_ITEMS[1], GOOD_ITEMS[2]]
    fake_llm(_raw(items))
    body = _quiz().json()
    _assert_integrity(body)
    assert body["fallbackUsed"] is True


def test_q4_duplicate_question_rejected_not_padded(fake_llm):
    items = [GOOD_ITEMS[0], dict(GOOD_ITEMS[0], question="DriverManager의  역할은 무엇인가 ?"), GOOD_ITEMS[1]]
    fake_llm(_raw(items))
    body = _quiz().json()
    assert body["success"] is True
    _assert_integrity(body)
    assert body["generatedCount"] == 2 and body["requestedCount"] == 3
    assert body["status"] == "PARTIAL" and body["partial"] is True and body["rejectedCount"] == 1
    assert body["degraded"] is False and body["fallbackUsed"] is False


def test_q4_duplicate_question_unit():
    valid, rejects = qc.harden_material_questions([GOOD_ITEMS[0], dict(GOOD_ITEMS[0])])
    assert len(valid) == 1 and rejects == [{"index": "1", "reason": "DUPLICATE_QUESTION"}]


@pytest.mark.parametrize("key", [True, False])
def test_q5_boolean_answer_is_not_an_index_unit(key):
    valid, rejects = qc.harden_material_questions([_item(ca=key)])
    assert valid == [] and rejects[0]["reason"] == "ANSWER_MISSING"
    assert qc.resolve_single_answer_index(True, None, ["a", "b", "c", "d"]) == "ANSWER_MISSING"


def test_q5_boolean_answer_from_llm_never_becomes_option_b(fake_llm):
    items = [dict(GOOD_ITEMS[0], correct_answer=True), GOOD_ITEMS[1], GOOD_ITEMS[2]]
    fake_llm(_raw(items))
    body = _quiz().json()
    _assert_integrity(body)
    assert all(q["question"] != GOOD_ITEMS[0]["question"] for q in body["quizzes"])
    assert body["fallbackUsed"] is True


def test_q5b_index_zero_is_not_dropped_as_falsy(fake_llm):
    items = [dict(GOOD_ITEMS[0], correct_answer=0), GOOD_ITEMS[1], GOOD_ITEMS[2]]
    fake_llm(_raw(items))
    body = _quiz().json()
    assert body["status"] == "OK" and body["quizzes"][0]["correctAnswer"] == 0


def test_q6_answer_index_text_mismatch_rejected(fake_llm):
    valid, rejects = qc.harden_material_questions([_item(answerIndex=2)])
    assert valid == [] and rejects[0]["reason"] == "ANSWER_INDEX_TEXT_MISMATCH"
    items = [dict(GOOD_ITEMS[0], answer_index=2), GOOD_ITEMS[1], GOOD_ITEMS[2]]
    fake_llm(_raw(items))
    body = _quiz().json()
    _assert_integrity(body)
    assert all(q["question"] != GOOD_ITEMS[0]["question"] for q in body["quizzes"])


def test_q7_answer_not_in_options_rejected(fake_llm):
    valid, rejects = qc.harden_material_questions([_item(ca="보기에 없는 정답")])
    assert valid == [] and rejects[0]["reason"] == "ANSWER_NOT_IN_OPTIONS"
    items = [dict(GOOD_ITEMS[0], correct_answer="보기에 없는 정답"), GOOD_ITEMS[1], GOOD_ITEMS[2]]
    fake_llm(_raw(items))
    body = _quiz().json()
    _assert_integrity(body)
    assert all(q["question"] != GOOD_ITEMS[0]["question"] for q in body["quizzes"])


@pytest.mark.parametrize("raw", [
    "죄송합니다. 퀴즈를 만들 수 없습니다.",
    '{"questions": [{"question": "JDBC는", "choices": ["a"',
    "",
    '{"questions": "none"}',
], ids=["prose", "truncated", "empty", "wrong-type"])
def test_q8_malformed_llm_json_is_explicit_fallback(fake_llm, raw):
    fake_llm(raw)
    body = _quiz().json()
    assert body["success"] is True
    _assert_integrity(body)
    assert body["status"] == "DEGRADED_FALLBACK" and body["degraded"] is True and body["fallbackUsed"] is True
    assert body["degradedReason"] == "LLM_OUTPUT_REJECTED" and body["source"] == "DETERMINISTIC_PDF"
    assert body["fallbackQuestionCount"] >= 1 and body["metadata"]["fallbackUsed"] is True


def test_q9_question_ids_stable_and_unique(fake_llm):
    fake_llm(_raw(GOOD_ITEMS))
    a, b = _quiz().json(), _quiz().json()
    ids_a = [q["questionId"] for q in a["quizzes"]]
    assert ids_a == [q["questionId"] for q in b["quizzes"]] and len(set(ids_a)) == 3
    assert a["quizId"] == b["quizId"]
    assert [q["optionIds"] for q in a["quizzes"]] == [["A", "B", "C", "D"]] * 3
    fake_llm(_raw(list(reversed(GOOD_ITEMS))))
    c = _quiz().json()
    assert sorted(ids_a) == sorted(q["questionId"] for q in c["quizzes"])   # content-derived, not positional


def test_q10_public_projection_has_no_answer_leakage(fake_llm):
    fake_llm(_raw(GOOD_ITEMS))
    body = _quiz().json()
    assert set(body["answerKeyFields"]) == set(qc.MATERIAL_ANSWER_KEY_FIELDS)
    public = qc.to_public_quiz(body)
    for q in public["quizzes"] + json.loads(public["quizData"]):
        assert not set(q) & set(body["answerKeyFields"])
        assert {"questionId", "question", "options", "optionIds", "answerType"} <= set(q)
    assert "source_trace" not in public and "answerKeyFields" not in public
    blob = json.dumps(public, ensure_ascii=False)
    assert "correctOptionIds" not in blob and "answerIndex" not in blob and "explanation" not in blob
    # reference projection must not mutate the internal (Spring-side) copy
    assert "correctAnswer" in body["quizzes"][0]


def test_q11_timeout_fallback_is_marked(fake_llm, monkeypatch):
    import app.api.material_legacy_routes as mlr
    monkeypatch.setattr(mlr, "QUIZ_TIMEOUT", 0.2)

    def slow():
        time.sleep(1.0)
        return _raw(GOOD_ITEMS)
    fake_llm(slow)
    body = _quiz().json()
    assert body["success"] is True
    assert body["status"] == "DEGRADED_FALLBACK" and body["degradedReason"] == "LLM_TIMEOUT"
    assert body["degraded"] is True and body["fallbackUsed"] is True
    _assert_integrity(body)


def test_q11_legacy_non_strict_fallback_marked():
    import main
    fb = main.build_fallback_quiz("x.pdf", "test")
    assert fb["status"] == "DEGRADED_FALLBACK" and fb["degraded"] is True and fb["fallbackUsed"] is True


LEGACY_TOP = {"success", "errorCode", "quizData", "quizzes", "warnings", "difficulty_requested", "difficulty_applied",
              "difficulty_policy", "difficulty_validation", "source", "fallbackUsed", "source_trace", "textStatus",
              "metadata"}
LEGACY_Q = {"question", "options", "answer", "answerIndex", "correctAnswer", "explanation", "difficulty",
            "wrongExplanations", "sourceTrace"}
LEGACY_META = {"provider", "source", "fallbackUsed", "validated", "requestId", "materialId", "requestedDifficulty",
               "appliedDifficulty", "requestedCount", "generatedCount", "documentType", "elapsedMs"}


def test_q12_ec2_legacy_fields_preserved(fake_llm):
    fake_llm(_raw(GOOD_ITEMS))
    body = _quiz().json()
    assert LEGACY_TOP <= set(body)
    assert LEGACY_META <= set(body["metadata"])
    assert isinstance(body["quizData"], str) and isinstance(json.loads(body["quizData"]), list)
    for q in json.loads(body["quizData"]):
        assert LEGACY_Q <= set(q)
        assert type(q["answer"]) is int          # frontend parseQuizQuestions reads a numeric index
    assert body["difficulty_requested"] == body["difficulty_applied"] == "easy"


def test_q12_failure_shape_kept_and_marked():
    r = CLIENT.post(QUIZ, json={"material_id": 1, "document_text": "", "text": ""})
    body = r.json()
    assert r.status_code == 200 and body["success"] is False       # Spring isAiFailure(success == false)
    for key in ("errorCode", "message", "retryable", "textStatus", "warnings", "requestId", "metadata"):
        assert key in body
    assert body["status"] == "FAILED" and body["schemaVersion"] == "quiz.v2" and body["fallbackUsed"] is False
    short = CLIENT.post(QUIZ, json={"material_id": 1, "document_text": "짧은 텍스트"}).json()
    assert short["success"] is False and short["errorCode"] == "PDF_TEXT_INSUFFICIENT" and short["status"] == "FAILED"


def test_q_all_questions_invalid_is_failed_not_empty_success(monkeypatch):
    import app.services.pdf_quiz_service as pq
    real = pq.generate_pdf_quiz

    def broken(req):
        r = real(req)
        for q in r.get("questions", []):
            q["choices"] = ["같음", "같음", "같음", "같음"]
            q["correct_answer"] = "같음"
        return r
    monkeypatch.setattr(pq, "generate_pdf_quiz", broken)
    monkeypatch.setattr(pq, "_llm_generate", lambda *a, **k: [])
    body = _quiz().json()
    assert body["success"] is False and body["status"] == "FAILED" and body["errorCode"] == "QUIZ_CONTRACT_INVALID"
    assert body["rejectedCount"] == 3
