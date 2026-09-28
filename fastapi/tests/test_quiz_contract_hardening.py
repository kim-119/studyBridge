"""Quiz contract hardening — live group-study path (main.generate_quiz_from_pdf).

Spring (GroupStudyMaterialService) calls POST /api/ai/quiz/generate and persists
question/options/correctAnswer; it grades server-side. These tests pin:
  questionId uniqueness/stability, option integrity, answer ∈ options,
  SINGLE_CHOICE answer count == 1, malformed output rejection (no silent fallback),
  schema stability across repeated generation, answer-key/public DTO separation.
"""
import copy
import json

import pytest

import main
from app.services import quiz_contract as qc

PDF_TEXT = (
    "JDBC는 자바에서 데이터베이스에 연결하기 위한 표준 API이다. Connection 객체로 연결을 맺고 "
    "Statement 객체로 SQL을 실행하며 ResultSet으로 결과를 읽는다. PreparedStatement는 SQL 인젝션을 막는다. "
) * 3


def _item(q="JDBC의 역할은?", options=None, correct=1, **extra):
    d = {
        "question": q,
        "options": options if options is not None else ["파일 압축", "데이터베이스 연결", "화면 렌더링", "메모리 해제"],
        "correctAnswer": correct,
        "explanation": "JDBC는 데이터베이스 연결 표준 API이다.",
        "sourceSnippet": "JDBC는 자바에서 데이터베이스에 연결하기 위한 표준 API이다.",
    }
    d.update(extra)
    return d


def _validate(items, count=5):
    return main.validate_grounded_quiz_questions(items, PDF_TEXT, count, "multiple_choice")


# ── per-item validation ─────────────────────────────────────────────────────
def test_valid_item_passes():
    valid, rejected = _validate([_item()])
    assert rejected == 0 and valid[0]["correctAnswer"] == 1 and valid[0]["answer"] == "데이터베이스 연결"


@pytest.mark.parametrize("bad", [
    _item(options=["A안", "A안", "B안", "C안"]),                        # duplicate option
    _item(options=["파일 압축", " 파일  압축 ", "화면", "메모리"]),       # duplicate after normalisation
    _item(options=["파일 압축", "", "화면 렌더링", "메모리 해제"]),        # empty option
    _item(options=["파일 압축", "데이터베이스 연결", "화면 렌더링"]),      # wrong option count
    _item(options="데이터베이스 연결"),                                   # options not a list
    _item(correct=4),                                                     # index out of range
    _item(correct=None),                                                  # no answer defined
    _item(correct=None, answer="존재하지 않는 보기"),                       # answer not in options
    _item(correct=[0, 2]),                                                # multiple answers
    _item(correct="A, C"),                                                # multiple answers as text
    _item(correct=True),                                                  # bool (int(True)==1 trap)
    _item(correct=2, answer="데이터베이스 연결"),                          # index/text disagree (1-based bug)
    _item(q="   "),                                                       # empty question
    _item(explanation=""),                                                # no explanation
], ids=["dup-opt", "dup-opt-norm", "empty-opt", "3-opts", "opts-str", "idx-range", "no-answer",
        "answer-not-in-opts", "multi-list", "multi-text", "bool", "idx-text-mismatch", "empty-q", "no-expl"])
def test_invalid_items_rejected(bad):
    valid, rejected = _validate([bad])
    assert valid == [] and rejected == 1


@pytest.mark.parametrize("correct,answer,expected", [
    ("B", None, 1), ("1", None, 1), ([1], None, 1), (None, "데이터베이스 연결", 1), (None, "b", 1),
    (1, "데이터베이스  연결.", 1),
])
def test_answer_resolution_accepts_unambiguous_forms(correct, answer, expected):
    valid, _ = _validate([_item(correct=correct, answer=answer)])
    assert valid and valid[0]["correctAnswer"] == expected


def test_duplicate_question_rejected():
    valid, rejected = _validate([_item(), _item(q="JDBC의  역할은?", correct=1)])
    assert len(valid) == 1 and rejected == 1


# ── whole-quiz contract ─────────────────────────────────────────────────────
def _final(items):
    valid, _ = _validate(items, count=len(items))
    return qc.attach_contract_fields(valid)


def test_question_ids_unique_and_stable():
    items = [_item(), _item(q="ResultSet의 용도는?", options=["결과 읽기", "연결", "압축", "렌더링"], correct=0)]
    a, b = _final(copy.deepcopy(items)), _final(copy.deepcopy(items))
    ids = [q["questionId"] for q in a]
    assert len(set(ids)) == len(ids)
    assert ids == [q["questionId"] for q in b]                  # same content -> same id
    assert qc.validate_quiz_contract(a) == []


def test_option_ids_align_with_correct_answer():
    q = _final([_item()])[0]
    assert q["answerType"] == "SINGLE_CHOICE"
    assert q["optionIds"] == ["A", "B", "C", "D"]
    assert q["correctOptionIds"] == ["B"]
    assert q["optionIds"][q["correctAnswer"]] == q["correctOptionIds"][0]


@pytest.mark.parametrize("mutate,code", [
    (lambda qs: qs[1].update(questionId=qs[0]["questionId"]), "DUPLICATE_QUESTION_ID"),
    (lambda qs: qs[0].update(correctOptionIds=["A", "B"]), "SINGLE_CHOICE_ANSWER_COUNT_2"),
    (lambda qs: qs[0].update(correctOptionIds=[]), "SINGLE_CHOICE_ANSWER_COUNT_0"),
    (lambda qs: qs[0].update(correctAnswer=7), "ANSWER_NOT_IN_OPTIONS"),
    (lambda qs: qs[0].update(options=["x", "x", "y", "z"]), "DUPLICATE_OPTION"),
    (lambda qs: qs[0].update(question=""), "EMPTY_QUESTION"),
    (lambda qs: qs[0].pop("questionId"), "MISSING_QUESTION_ID"),
])
def test_contract_validator_catches(mutate, code):
    qs = _final([_item(), _item(q="ResultSet의 용도는?", options=["결과 읽기", "연결", "압축", "렌더링"], correct=0)])
    mutate(qs)
    assert any(e.endswith(code) for e in qc.validate_quiz_contract(qs)), qc.validate_quiz_contract(qs)


def test_empty_quiz_is_invalid():
    assert qc.validate_quiz_contract([]) == ["NO_QUESTIONS"]


# ── end-to-end generate_quiz_from_pdf with a fake LLM ───────────────────────
@pytest.fixture
def fake_pdf(monkeypatch):
    monkeypatch.setattr(main, "_load_pdf_from_s3", lambda key: b"%PDF-fake")
    monkeypatch.setattr(main, "_extract_pdf_text", lambda b: (PDF_TEXT, "test"))

    def use(outputs):
        it = iter(outputs)
        monkeypatch.setattr(main, "_call_quiz_llm", lambda s, u, c: next(it, ""))
    return use


GOOD = json.dumps({"questions": [
    _item(),
    _item(q="ResultSet의 용도는?", options=["결과 읽기", "연결 생성", "파일 압축", "화면 렌더링"], correct=0),
    _item(q="SQL 인젝션을 막는 것은?", options=["Statement", "PreparedStatement", "ResultSet", "DriverManager"], correct=1),
]}, ensure_ascii=False)


def _gen(count=3, strict=True):
    return main.generate_quiz_from_pdf(material_id=7, s3_key="k.pdf", file_name="jdbc.pdf", count=count,
                                       question_type="multiple_choice", group_id=3, strict_grounding=strict)


def test_generate_success_contract(fake_pdf):
    fake_pdf([GOOD])
    r = _gen()
    assert r["success"] is True and r["status"] == "OK" and r["degraded"] is False
    assert r["schemaVersion"] == "quiz.v2" and r["quizId"].startswith("quiz_")
    assert qc.validate_quiz_contract(r["questions"]) == []
    # Spring GroupStudyQuizDTO.AIQuestion legacy fields preserved
    for q in r["questions"]:
        assert isinstance(q["question"], str) and isinstance(q["options"], list)
        assert all(isinstance(o, str) for o in q["options"])
        assert isinstance(q["correctAnswer"], int) and 0 <= q["correctAnswer"] < len(q["options"])
        assert isinstance(q["timeLimitSeconds"], int)
    assert set(r["answerKeyFields"]) == set(qc.ANSWER_KEY_FIELDS)


@pytest.mark.parametrize("raw", [
    "죄송합니다. 문제를 만들 수 없습니다.",
    '{"questions": [{"question": "JDBC의 역할은?", "options": ["a", "b"',
    "",
    json.dumps({"questions": [_item(correct=None), _item(options=["x", "x", "y", "z"])]}),
    json.dumps({"quiz": "not a list"}),
], ids=["prose", "truncated", "empty", "all-invalid-items", "wrong-shape"])
def test_malformed_output_is_failure_not_fallback(fake_pdf, raw):
    fake_pdf([raw, raw])
    r = _gen()
    assert r["success"] is False and r["status"] == "FAILED"
    assert r["errorCode"] == "QUIZ_GROUNDING_FAILED"
    assert r["questions"] == []
    assert "기본 안내형" not in json.dumps(r, ensure_ascii=False)


def test_partial_result_is_labelled(fake_pdf):
    one = json.dumps({"questions": [_item()]}, ensure_ascii=False)
    fake_pdf([one, one])
    r = _gen(count=3)
    assert r["success"] is True and r["status"] == "PARTIAL" and len(r["questions"]) == 1 and r["warning"]


def test_repeated_generation_keeps_schema(fake_pdf):
    other = json.dumps({"questions": [
        _item(q="Connection 객체의 역할은?", options=["연결 유지", "SQL 파싱", "압축", "렌더링"], correct=0),
        _item(q="Statement로 하는 일은?", options=["SQL 실행", "파일 저장", "화면 출력", "메모리 해제"], correct=0),
        _item(q="JDBC는 어떤 언어의 API인가?", options=["자바", "파이썬", "C", "Go"], correct=0),
    ]}, ensure_ascii=False)
    fake_pdf([GOOD, other, GOOD])
    runs = [_gen(), _gen(), _gen()]
    top_keys = {frozenset(r) for r in runs}
    q_keys = {frozenset(q) for r in runs for q in r["questions"]}
    assert len(top_keys) == 1 and len(q_keys) == 1
    assert [q["questionId"] for q in runs[0]["questions"]] == [q["questionId"] for q in runs[2]["questions"]]
    assert runs[0]["quizId"] == runs[2]["quizId"] != runs[1]["quizId"]


def test_non_strict_fallback_is_explicitly_degraded(monkeypatch):
    def boom(key):
        raise RuntimeError("s3 down")
    monkeypatch.setattr(main, "_load_pdf_from_s3", boom)
    r = _gen(count=5, strict=False)
    assert r["degraded"] is True and r["status"] == "DEGRADED_FALLBACK" and r["fallbackUsed"] is True
    ids = [q["questionId"] for q in r["questions"]]
    assert len(ids) == len(set(ids)) == len(r["questions"])       # never padded with repeats
    assert qc.validate_quiz_contract(r["questions"]) == []


def test_strict_load_failure_returns_failed(monkeypatch):
    monkeypatch.setattr(main, "_load_pdf_from_s3", lambda k: (_ for _ in ()).throw(RuntimeError("x")))
    r = _gen()
    assert r["success"] is False and r["status"] == "FAILED" and r["errorCode"] == "PDF_LOAD_FAILED"


# ── answer-key boundary ─────────────────────────────────────────────────────
def test_public_view_strips_answer_key(fake_pdf):
    fake_pdf([GOOD])
    r = _gen()
    public = qc.to_public_quiz(r)
    blob = json.dumps(public, ensure_ascii=False)
    for q in public["questions"]:
        for f in qc.ANSWER_KEY_FIELDS:
            assert f not in q
        assert q["questionId"] and q["optionIds"] and q["options"]
    assert "correctAnswer" not in blob and "answerKeyFields" not in public
    assert r["questions"][0]["correctAnswer"] is not None      # original untouched


# ── HTTP: response_model must not drop the new fields ───────────────────────
def test_endpoint_serializes_contract_fields(fake_pdf):
    from fastapi.testclient import TestClient
    fake_pdf([GOOD])
    resp = TestClient(main.app).post("/api/ai/quiz/generate", json={
        "materialId": 7, "s3Key": "k.pdf", "fileName": "jdbc.pdf", "numQuestions": 3,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] and body["schemaVersion"] == "quiz.v2" and body["status"] == "OK"
    q = body["questions"][0]
    for key in ("questionId", "answerType", "optionIds", "correctOptionIds", "question", "options",
                "correctAnswer", "timeLimitSeconds"):
        assert key in q
