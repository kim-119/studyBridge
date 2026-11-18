"""
오답노트 '복습 필요' 분석 테스트.

전제: 힌트 기능 없음, 다시풀기는 문제당 정확히 1회.
  CASE A 최초 오답 + 재풀이 오답
  CASE B 최초 미응답 + 재풀이 오답
  CASE C 최초 오답 + 재풀이 정답 (기계적 '복습 불필요' 금지)
  CASE D 최초 정답 (AI 호출 없음)
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import review_needed_routes as R
from app.services import review_needed_analyzer as RA


def _q(**kw):
    base = {
        "question": "ConcurrentHashMap이 HashMap과 다른 점은?",
        "choices": ["동시성 제어를 제공한다", "정렬을 보장한다", "null 키를 허용한다"],
        "correctAnswer": "동시성 제어를 제공한다",
        "explanation": "ConcurrentHashMap은 세그먼트/버킷 단위 잠금으로 동시 접근을 제어한다.",
        "concept": "ConcurrentHashMap 동시성 제어",
    }
    base.update(kw)
    return base


def _payload(*questions, **kw):
    body = {"reviewNoteId": 1, "subject": "자바", "materialTitle": "자바 강의자료", "questions": list(questions)}
    body.update(kw)
    return body


# ── 케이스 판정 ─────────────────────────────────────────────────────────────
def test_case_a_wrong_then_wrong():
    qs = RA.parse_questions(_payload(_q(firstAnswer="정렬을 보장한다", firstCorrect=False,
                                        retryAnswer="null 키를 허용한다", retryCorrect=False)))
    assert qs[0].case() == RA.WRONG_THEN_WRONG
    assert RA.decide(qs).review_needed is True


def test_case_b_unanswered_then_wrong():
    qs = RA.parse_questions(_payload(_q(firstAnswer="미응답", firstCorrect=False,
                                        retryAnswer="정렬을 보장한다", retryCorrect=False)))
    assert qs[0].case() == RA.UNANSWERED_THEN_WRONG
    assert qs[0].first_unanswered is True


def test_case_c_wrong_then_correct_is_still_analyzed():
    qs = RA.parse_questions(_payload(_q(firstAnswer="정렬을 보장한다", firstCorrect=False,
                                        retryAnswer="동시성 제어를 제공한다", retryCorrect=True)))
    decision = RA.decide(qs)
    assert qs[0].case() == RA.WRONG_THEN_CORRECT
    # 재풀이 정답이라고 기계적으로 '복습 불필요' 처리하지 않는다
    assert decision.review_needed is True


def test_case_d_first_correct_needs_no_review():
    qs = RA.parse_questions(_payload(_q(firstAnswer="동시성 제어를 제공한다", firstCorrect=True)))
    decision = RA.decide(qs)
    assert qs[0].case() == RA.FIRST_CORRECT
    assert decision.review_needed is False


def test_no_retry_record_uses_first_result_only():
    qs = RA.parse_questions(_payload(_q(firstAnswer="정렬을 보장한다", firstCorrect=False)))
    assert qs[0].case() == RA.WRONG_NO_RETRY
    assert qs[0].has_retry is False


def test_correctness_inferred_when_flag_missing():
    """레거시 payload(정오 플래그 없음)도 정답 문자열 비교로 판정한다."""
    qs = RA.parse_questions(_payload(_q(firstAnswer="정렬을 보장한다",
                                        retryAnswer="동시성 제어를 제공한다")))
    assert qs[0].case() == RA.WRONG_THEN_CORRECT


def test_empty_answer_counts_as_unanswered():
    qs = RA.parse_questions(_payload(_q(firstAnswer="", retryAnswer="정렬을 보장한다", retryCorrect=False)))
    assert qs[0].case() == RA.UNANSWERED_THEN_WRONG


def test_legacy_flat_payload_still_parsed():
    body = {"reviewNoteId": 3, "question": "무엇인가?", "correctAnswer": "A", "userAnswer": "B",
            "explanation": "해설"}
    qs = RA.parse_questions(body)
    assert len(qs) == 1 and qs[0].case() == RA.WRONG_NO_RETRY


# ── 프롬프트 / 폴백 ─────────────────────────────────────────────────────────
def test_prompt_contains_first_and_retry_results():
    qs = RA.parse_questions(_payload(_q(firstAnswer="정렬을 보장한다", firstCorrect=False,
                                        retryAnswer="null 키를 허용한다", retryCorrect=False)))
    prompt = RA.build_prompt(RA.decide(qs), "자바", "자바 강의자료", "보통")
    assert "최초 답: 정렬을 보장한다" in prompt
    assert "재풀이 답: null 키를 허용한다" in prompt
    assert "최초 오답, 다시풀기에서도 오답" in prompt
    # 존재하지 않는 데이터(힌트/재시도 횟수)를 프롬프트에 넣지 않는다
    assert "힌트" not in prompt and "retryCount" not in prompt


def test_fallback_is_not_a_generic_sentence():
    qs = RA.parse_questions(_payload(_q(firstAnswer="정렬을 보장한다", firstCorrect=False,
                                        retryAnswer="null 키를 허용한다", retryCorrect=False)))
    text = RA.build_fallback(RA.decide(qs), "자바 강의자료")
    assert text.startswith("ConcurrentHashMap 동시성 제어" + RA.FIRST_SENTENCE_SUFFIX)
    assert "다시풀기" in text
    assert "자바 강의자료" in text
    assert len(text) > 120
    assert text.strip() != "복습이 필요합니다."


def test_unanswered_fallback_mentions_missing_answer():
    qs = RA.parse_questions(_payload(_q(firstAnswer="미응답", retryAnswer="정렬을 보장한다", retryCorrect=False)))
    text = RA.build_fallback(RA.decide(qs), "자바 강의자료")
    assert "답을 고르지 못했" in text


def test_recovered_case_fallback_mentions_recovery():
    qs = RA.parse_questions(_payload(_q(firstAnswer="정렬을 보장한다", firstCorrect=False,
                                        retryAnswer="동시성 제어를 제공한다", retryCorrect=True)))
    text = RA.build_fallback(RA.decide(qs), "자바 강의자료")
    assert "다시풀기에서는 정답" in text


def test_validate_rejects_text_ignoring_retry():
    qs = RA.parse_questions(_payload(_q(firstAnswer="정렬을 보장한다", firstCorrect=False,
                                        retryAnswer="null 키를 허용한다", retryCorrect=False)))
    decision = RA.decide(qs)
    bad = "ConcurrentHashMap 동시성 제어" + RA.FIRST_SENTENCE_SUFFIX + " " + ("개념을 다시 확인하세요. " * 8)
    assert "retry_not_reflected" in RA.validate_text(bad, decision)


# ── 엔드포인트 ──────────────────────────────────────────────────────────────
@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(R.router)
    return TestClient(app)


def test_endpoint_case_d_skips_ai(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("최초 정답인데 AI를 호출했다")
    monkeypatch.setattr("app.services.ai_pipeline.qwen_draft", boom)

    resp = client.post("/api/ai/review-needed",
                       json=_payload(_q(firstAnswer="동시성 제어를 제공한다", firstCorrect=True)))
    assert resp.status_code == 200
    body = resp.json()
    assert body["reviewNeeded"] is False
    assert body["cases"] == [RA.FIRST_CORRECT]
    assert body["reviewNeededText"]


def test_endpoint_ai_failure_returns_deterministic_text(client, monkeypatch):
    monkeypatch.setattr("app.services.ai_pipeline.qwen_draft", lambda *a, **k: "")
    monkeypatch.setattr("app.services.ai_pipeline.openai_refine", lambda *a, **k: None)

    resp = client.post("/api/ai/review-needed",
                       json=_payload(_q(firstAnswer="정렬을 보장한다", firstCorrect=False,
                                        retryAnswer="null 키를 허용한다", retryCorrect=False)))
    body = resp.json()
    assert resp.status_code == 200
    assert body["generatedBy"] == "deterministic"
    assert "ConcurrentHashMap" in body["reviewNeededText"]
    assert len(body["reviewNeededText"]) > 120


def test_endpoint_uses_only_current_note_data(client, monkeypatch):
    """이전 문제(HashMap)를 분석하고 곧바로 다른 문제(JPA)를 분석해도 섞이지 않는다."""
    seen = {}

    def fake_draft(system, user, max_tokens=None):
        seen["prompt"] = user
        return ("JPA 영속성 컨텍스트" + RA.FIRST_SENTENCE_SUFFIX +
                " 최초 풀이와 다시풀기에서 모두 정답에 도달하지 못했고, 영속성 컨텍스트의 "
                "1차 캐시와 flush 시점을 구분하지 못한 것으로 보입니다. 자료의 해당 절을 다시 읽고 "
                "정답과 내가 고른 답의 차이를 정리해 보세요.")
    monkeypatch.setattr("app.services.ai_pipeline.qwen_draft", fake_draft)

    client.post("/api/ai/review-needed",
                json=_payload(_q(firstAnswer="정렬을 보장한다", firstCorrect=False,
                                 retryAnswer="null 키를 허용한다", retryCorrect=False)))
    resp = client.post("/api/ai/review-needed", json=_payload(
        _q(question="JPA 영속성 컨텍스트의 1차 캐시는 언제 비워지는가?",
           choices=["flush 시", "commit 시", "detach 시"],
           correctAnswer="commit 시", explanation="영속성 컨텍스트는 트랜잭션 커밋 시 정리된다.",
           concept="JPA 영속성 컨텍스트", firstAnswer="flush 시", firstCorrect=False,
           retryAnswer="detach 시", retryCorrect=False)))
    body = resp.json()
    assert "ConcurrentHashMap" not in seen["prompt"]
    assert "ConcurrentHashMap" not in body["reviewNeededText"]
    assert "JPA" in body["reviewNeededText"]


def test_endpoint_never_returns_empty_text(client, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("ollama down")
    monkeypatch.setattr("app.services.ai_pipeline.qwen_draft", broken)
    monkeypatch.setattr("app.services.ai_pipeline.openai_refine", lambda *a, **k: None)

    resp = client.post("/api/ai/review-needed",
                       json=_payload(_q(firstAnswer="미응답", retryAnswer="정렬을 보장한다",
                                        retryCorrect=False)))
    body = resp.json()
    assert resp.status_code == 200
    assert body["reviewNeededText"].strip()
    assert body["generatedBy"] == "deterministic"


def test_validate_requires_unanswered_mention():
    qs = RA.parse_questions(_payload(_q(firstAnswer="미응답", retryAnswer="정렬을 보장한다", retryCorrect=False)))
    decision = RA.decide(qs)
    text = ("ConcurrentHashMap 동시성 제어" + RA.FIRST_SENTENCE_SUFFIX +
            " 다시풀기에서도 오답이었습니다. " + ("개념을 다시 확인하세요. " * 5))
    assert "unanswered_not_reflected" in RA.validate_text(text, decision)
    ok = ("ConcurrentHashMap 동시성 제어" + RA.FIRST_SENTENCE_SUFFIX +
          " 최초에는 미응답이었고 다시풀기에서도 오답이었습니다. " + ("개념을 다시 확인하세요. " * 5))
    assert RA.validate_text(ok, decision) == []


def test_first_sentence_quotes_are_stripped():
    quoted = '"ConcurrentHashMap에 대한 개념이 부족하여 복습이 필요합니다." 이어지는 설명입니다.'
    assert R._unquote_first_sentence(quoted).startswith("ConcurrentHashMap에 대한")
