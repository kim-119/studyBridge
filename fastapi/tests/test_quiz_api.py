"""
POST /api/ai/quiz/generate API 테스트.
S3/LLM 없이도 fallback quiz 구조를 검증한다.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from main import app

client = TestClient(app)

_VALID_REQUEST = {
    "materialId": 12,
    "s3Key": "materials/user_42/test.pdf",
    "fileName": "중간고사_운영체제_요약본.pdf",
}


def test_quiz_generate_structure():
    """S3/LLM 실패해도 fallback quiz 구조(quizTitle, questions)를 유지한다."""
    resp = client.post("/api/ai/quiz/generate", json=_VALID_REQUEST)
    assert resp.status_code == 200
    body = resp.json()
    assert "quizTitle" in body
    assert "questions" in body
    assert isinstance(body["questions"], list)
    assert len(body["questions"]) > 0


def test_quiz_question_structure():
    """각 문항이 question, options, correctAnswer, timeLimitSeconds를 포함한다."""
    resp = client.post("/api/ai/quiz/generate", json=_VALID_REQUEST)
    assert resp.status_code == 200
    body = resp.json()
    for q in body["questions"]:
        assert "question" in q
        assert "options" in q
        assert "correctAnswer" in q
        assert "timeLimitSeconds" in q


def test_quiz_question_four_options():
    """각 문항의 보기는 반드시 4개여야 한다."""
    resp = client.post("/api/ai/quiz/generate", json=_VALID_REQUEST)
    assert resp.status_code == 200
    body = resp.json()
    for q in body["questions"]:
        assert len(q["options"]) == 4


def test_quiz_correct_answer_range():
    """correctAnswer는 0~3 범위여야 한다."""
    resp = client.post("/api/ai/quiz/generate", json=_VALID_REQUEST)
    assert resp.status_code == 200
    body = resp.json()
    for q in body["questions"]:
        assert 0 <= q["correctAnswer"] <= 3


def test_quiz_response_field_names():
    """응답 필드명이 Spring 명세(camelCase)와 일치한다."""
    resp = client.post("/api/ai/quiz/generate", json=_VALID_REQUEST)
    assert resp.status_code == 200
    body = resp.json()
    # Spring 명세 필드명
    assert "quizTitle" in body
    assert "questions" in body
    # snake_case 필드는 없어야 함
    assert "quiz_title" not in body


def test_quiz_missing_required_fields():
    """필수 필드 누락 시 422 반환."""
    resp = client.post("/api/ai/quiz/generate", json={"materialId": 1})
    assert resp.status_code == 422


def test_quiz_time_limit_default():
    """timeLimitSeconds 기본값은 30초다."""
    resp = client.post("/api/ai/quiz/generate", json=_VALID_REQUEST)
    assert resp.status_code == 200
    body = resp.json()
    for q in body["questions"]:
        assert q["timeLimitSeconds"] == 30
