"""
POST /api/ai/predict/study-time API 테스트.
외부 의존성(DB, TF 모델) 없이 실행 가능.
"""
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_predict_study_time_normal():
    """정상 요청: 7개 데이터 → 200 + predictedStudySeconds 반환."""
    resp = client.post(
        "/api/ai/predict/study-time",
        json={"userId": 42, "weeklyStudySeconds": [3600, 7200, 5400, 0, 1800, 9000, 4500]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "predictedStudySeconds" in body
    assert isinstance(body["predictedStudySeconds"], (int, float))
    assert body["predictedStudySeconds"] >= 0


def test_predict_study_time_wrong_length_short():
    """6개 입력 → 400."""
    resp = client.post(
        "/api/ai/predict/study-time",
        json={"userId": 1, "weeklyStudySeconds": [3600, 7200, 5400, 0, 1800, 9000]},
    )
    assert resp.status_code == 400


def test_predict_study_time_wrong_length_long():
    """8개 입력 → 400."""
    resp = client.post(
        "/api/ai/predict/study-time",
        json={"userId": 1, "weeklyStudySeconds": [1, 2, 3, 4, 5, 6, 7, 8]},
    )
    assert resp.status_code == 400


def test_predict_study_time_negative_value():
    """음수 값 → 400."""
    resp = client.post(
        "/api/ai/predict/study-time",
        json={"userId": 1, "weeklyStudySeconds": [3600, -100, 5400, 0, 1800, 9000, 4500]},
    )
    assert resp.status_code == 400


def test_predict_study_time_all_zeros():
    """전부 0인 경우도 유효한 입력."""
    resp = client.post(
        "/api/ai/predict/study-time",
        json={"userId": 99, "weeklyStudySeconds": [0, 0, 0, 0, 0, 0, 0]},
    )
    assert resp.status_code == 200
    assert "predictedStudySeconds" in resp.json()


def test_predict_study_time_response_field_camelcase():
    """응답 필드명이 Spring 명세 camelCase와 일치한다."""
    resp = client.post(
        "/api/ai/predict/study-time",
        json={"userId": 1, "weeklyStudySeconds": [3600, 7200, 5400, 0, 1800, 9000, 4500]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "predictedStudySeconds" in body
    assert "predicted_study_seconds" not in body


def test_predict_missing_required_field():
    """필수 필드 누락 → 422."""
    resp = client.post(
        "/api/ai/predict/study-time",
        json={"userId": 1},
    )
    assert resp.status_code == 422
