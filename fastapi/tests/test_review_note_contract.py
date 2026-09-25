"""
자료보관함 통합 계약 단위 테스트 (LLM 불필요 — deterministic 분류 + validator).

pytest:  cd ~/capstoneLLM/fastapi && .venv/bin/python -m pytest tests/test_review_note_contract.py -q
plain :  cd ~/capstoneLLM/fastapi && .venv/bin/python -m tests.test_review_note_contract
"""
from app.api.review_note_routes import (
    ClassifyMetadata, MaterialClassifyRequest, SimilarQuestionRequest, ExplanationRequest,
    _deterministic_classify, _classify_sync, validate_classification,
    validate_similar_question, validate_explanation,
)


# ── 분류 (deterministic, LLM 없이) ────────────────────────────────────────────
def test_classify_review_note():
    req = MaterialClassifyRequest(
        requestId="t-review", title="HTTP클라이언트 오답노트", fileName="review-note.pdf",
        textPreview="HTTP클라이언트 오답노트\n틀린 문제 수: 1\n내가 고른 답: page\n정답: implementation\nAI 해설: ...",
        metadata=ClassifyMetadata(mimeType="application/pdf", pageCount=1),
    )
    det = _deterministic_classify(req)
    assert det["materialType"] == "REVIEW_NOTE", det
    assert det["confidence"] >= 0.75, det


def test_classify_planner_roadmap_title():
    req = MaterialClassifyRequest(
        requestId="t-planner", title="[로드맵 3주차 2일] Mocking 기법", fileName="roadmap.txt",
        textPreview="Mocking 기법 학습 계획",
    )
    det = _deterministic_classify(req)
    assert det["materialType"] == "PLANNER", det


def test_classify_study_pdf():
    req = MaterialClassifyRequest(
        requestId="t-pdf", title="운영체제 강의자료", fileName="lecture_ch3.pdf",
        textPreview="3장 목차 개념 설명 아키텍처 슬라이드 강의자료 이론",
        metadata=ClassifyMetadata(mimeType="application/pdf", pageCount=15),
    )
    det = _deterministic_classify(req)
    assert det["materialType"] == "STUDY_PDF", det


def test_classify_user_override():
    req = MaterialClassifyRequest(
        requestId="t-override", title="강의자료", fileName="x.pdf",
        textPreview="강의자료 목차 개념",
        metadata=ClassifyMetadata(mimeType="application/pdf", pageCount=10,
                                  userSelectedType="REVIEW_NOTE"),
    )
    res = _classify_sync(req)
    assert res["materialType"] == "REVIEW_NOTE"
    assert res["meta"].get("userOverride") is True
    assert validate_classification(res) is None


def test_classify_validator():
    assert validate_classification({"materialType": "STUDY_PDF", "confidence": 0.9, "reasons": ["x"]}) is None
    assert validate_classification({"materialType": "BAD", "confidence": 0.9, "reasons": ["x"]}) is not None
    assert validate_classification({"materialType": "STUDY_PDF", "confidence": 1.5, "reasons": ["x"]}) is not None
    assert validate_classification({"materialType": "STUDY_PDF", "confidence": 0.9, "reasons": []}) is not None


# ── 유사문제 validator ────────────────────────────────────────────────────────
def _sim_req():
    return SimilarQuestionRequest(
        requestId="t", questionText="Gradle 의존성 선언에서 라이브러리를 추가할 때 사용하는 핵심 키워드는?",
        options=["implementation", "page", "수정", "추가"], correctAnswer="implementation",
        userAnswer="page", explanation="implementation은 Gradle 의존성 선언 키워드입니다.",
        difficulty="hard",
        sourceText="Gradle dependencies 블록에서 implementation 키워드로 라이브러리 의존성을 선언한다.",
    )


def test_similar_valid():
    req = _sim_req()
    good = {
        "questionText": "안드로이드 프로젝트에서 Retrofit 라이브러리를 dependencies 블록에 추가할 때 쓰는 키워드는?",
        "options": ["implementation", "page", "compileOnly", "annotation"],
        "correctAnswer": "implementation", "explanation": "implementation은 Gradle 의존성 선언 키워드다.",
        "difficulty": "hard",
    }
    assert validate_similar_question(good, req) is None


def test_similar_reject_three_options():
    req = _sim_req()
    bad = {"questionText": "Retrofit을 추가하는 Gradle 키워드는?", "options": ["implementation", "page", "수정"],
           "correctAnswer": "implementation", "explanation": "x implementation", "difficulty": "hard"}
    assert validate_similar_question(bad, req) == "options length != 4 (got 3)"


def test_similar_reject_correct_not_in_options():
    req = _sim_req()
    bad = {"questionText": "Retrofit을 추가하는 Gradle 키워드는?", "options": ["page", "수정", "추가", "삭제"],
           "correctAnswer": "implementation", "explanation": "x implementation", "difficulty": "hard"}
    assert validate_similar_question(bad, req) == "correctAnswer not in options"


def test_similar_reject_empty_explanation():
    req = _sim_req()
    bad = {"questionText": "Retrofit을 추가하는 Gradle implementation 키워드 맥락 문제?",
           "options": ["implementation", "page", "수정", "추가"], "correctAnswer": "implementation",
           "explanation": "", "difficulty": "hard"}
    assert validate_similar_question(bad, req) == "explanation empty"


def test_similar_reject_generic():
    req = _sim_req()
    bad = {"questionText": "다음 중 올바른 것은?", "options": ["implementation", "page", "수정", "추가"],
           "correctAnswer": "implementation", "explanation": "implementation 설명", "difficulty": "hard"}
    assert validate_similar_question(bad, req) == "generic question"


def test_similar_reject_difficulty_changed():
    req = _sim_req()
    bad = {"questionText": "Retrofit dependencies 블록 implementation 키워드 맥락 문제?",
           "options": ["implementation", "page", "수정", "추가"], "correctAnswer": "implementation",
           "explanation": "implementation 설명", "difficulty": "easy"}
    assert validate_similar_question(bad, req) == "difficulty changed"


def test_similar_reject_copy_paste():
    req = _sim_req()
    bad = {"questionText": req.questionText, "options": ["implementation", "page", "수정", "추가"],
           "correctAnswer": "implementation", "explanation": "implementation 설명", "difficulty": "hard"}
    r = validate_similar_question(bad, req)
    assert r is not None and r.startswith("too similar")


# ── 해설 validator ────────────────────────────────────────────────────────────
def _exp_req():
    return ExplanationRequest(
        requestId="t", questionText="Gradle 의존성 선언 키워드는?",
        options=["implementation", "page", "수정", "추가"], correctAnswer="implementation",
        userAnswer="page", existingExplanation="implementation은 Gradle 의존성 선언 키워드입니다.",
        difficulty="hard",
        sourceText="Gradle dependencies 블록에서 implementation 키워드로 의존성을 선언한다.",
    )


def test_explanation_valid():
    req = _exp_req()
    good = {
        "feedback": "page와 implementation 개념을 혼동했습니다.",
        "whyUserAnswerWrong": "page는 문서 페이지 개념이라 Gradle 의존성 선언과 무관합니다.",
        "whyCorrectAnswerRight": "implementation은 Gradle dependencies 블록의 표준 키워드입니다.",
        "sourceConcept": "PDF의 dependencies 블록 implementation 개념과 연결됩니다.",
        "reviewPoint": "Gradle 의존성 선언 키워드 implementation을 다시 확인하세요.",
        "nextRule": "라이브러리 추가 키워드를 물으면 implementation을 떠올리세요.",
    }
    assert validate_explanation(good, req) is None


def test_explanation_reject_missing_field():
    req = _exp_req()
    bad = {"feedback": "x", "whyUserAnswerWrong": "page 설명", "whyCorrectAnswerRight": "implementation 설명",
           "sourceConcept": "", "reviewPoint": "x", "nextRule": "x"}
    assert validate_explanation(bad, req) == "sourceConcept empty"


def test_explanation_reject_no_user_answer_mention():
    req = _exp_req()
    bad = {"feedback": "implementation 설명", "whyUserAnswerWrong": "오답 설명",
           "whyCorrectAnswerRight": "implementation 정답", "sourceConcept": "implementation 개념",
           "reviewPoint": "implementation 복습", "nextRule": "implementation 기준"}
    # userAnswer 'page' 미언급 → reject
    assert validate_explanation(bad, req) == "userAnswer not mentioned"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"[ERROR] {fn.__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
