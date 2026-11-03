"""P0: 내부 인증 fail-closed + 학습 후보 관리 권한 분리 + 본문 제한/rate limit."""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from tests.lq_helpers import ADMIN_TOKEN, INTERNAL_KEY, admin_headers, service_headers


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_SERVER_API_KEY", INTERNAL_KEY)
    monkeypatch.setenv("TRAINING_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("AI_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("AI_TRAINING_DATASET_DIR", str(tmp_path / "datasets"))
    from app.training_pipeline.repository import InMemoryTrainingRepository, set_repository
    repo = InMemoryTrainingRepository()
    set_repository(repo)
    from app.api import training_candidate_routes as r
    r.SERVICE_RATE.reset()
    r.ADMIN_RATE.reset()
    yield repo
    set_repository(None)


def _probe_app():
    from app.core.security import verify_internal_token
    app = FastAPI()

    @app.get("/p", dependencies=[Depends(verify_internal_token)])
    def p():
        return {"ok": True}
    return app


def _training_client():
    from app.api.training_candidate_routes import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_internal_key_unset_is_fail_closed(monkeypatch):
    monkeypatch.delenv("AI_SERVER_API_KEY", raising=False)
    c = TestClient(_probe_app())
    r = c.get("/p")
    assert r.status_code == 503
    assert r.json()["detail"]["errorCode"] == "INTERNAL_AUTH_NOT_CONFIGURED"
    # 헤더를 보내도 키가 없으면 통과하지 않는다(예전: 키 미설정 = 무조건 통과).
    assert c.get("/p", headers={"Authorization": "Bearer anything"}).status_code == 503


def test_short_key_is_rejected_as_misconfiguration(monkeypatch):
    monkeypatch.setenv("AI_SERVER_API_KEY", "short")
    assert TestClient(_probe_app()).get("/p", headers={"Authorization": "Bearer short"}).status_code == 503


def test_bearer_regression_and_bad_tokens(monkeypatch):
    monkeypatch.setenv("AI_SERVER_API_KEY", INTERNAL_KEY)
    c = TestClient(_probe_app())
    assert c.get("/p", headers={"Authorization": f"Bearer {INTERNAL_KEY}"}).status_code == 200  # 기존 서버간 호출
    assert c.get("/p", headers={"Authorization": f"bearer {INTERNAL_KEY}"}).status_code == 200
    assert c.get("/p").status_code == 401
    assert c.get("/p", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/p", headers={"Authorization": f"Basic {INTERNAL_KEY}"}).status_code == 401
    # loopback 출발지라는 사실만으로는 통과하지 않는다(TestClient 출발지 = testclient/loopback 류).
    assert c.get("/p", headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 401


def test_admin_routes_reject_plain_internal_credential(env):
    c = _training_client()
    body = {"candidate_uuid": "00000000-0000-0000-0000-000000000000"}
    for path in ("/api/training-candidates/approve", "/api/training-candidates/reject"):
        r = c.post(path, json=body, headers=service_headers())
        assert r.status_code == 403, path
    assert c.get("/api/training-candidates/stats", headers=service_headers()).status_code == 403
    assert c.post("/api/training-candidates/export-jsonl", json={}, headers=service_headers()).status_code == 403


def test_admin_token_must_be_configured_and_distinct(env, monkeypatch):
    c = _training_client()
    monkeypatch.delenv("TRAINING_ADMIN_TOKEN")
    assert c.get("/api/training-candidates/stats", headers=admin_headers()).status_code == 503
    monkeypatch.setenv("TRAINING_ADMIN_TOKEN", INTERNAL_KEY)  # 내부 키와 같으면 권한 분리 불성립
    h = admin_headers()
    h["X-Training-Admin-Token"] = INTERNAL_KEY
    assert c.get("/api/training-candidates/stats", headers=h).status_code == 503


def test_admin_requires_actor_role_request_id(env):
    c = _training_client()
    h = admin_headers()
    h.pop("X-Actor-Id")
    assert c.get("/api/training-candidates/stats", headers=h).status_code == 400
    h = admin_headers(role="superuser")
    assert c.get("/api/training-candidates/stats", headers=h).status_code == 403
    h = admin_headers()
    h.pop("X-Request-Id")
    assert c.get("/api/training-candidates/stats", headers=h).status_code == 400
    assert c.get("/api/training-candidates/stats", headers=admin_headers(role="training_reviewer")).status_code == 200


def test_export_requires_admin_role_not_reviewer(env):
    c = _training_client()
    r = c.post("/api/training-candidates/export-jsonl", json={}, headers=admin_headers(role="training_reviewer"))
    assert r.status_code == 403
    assert r.json()["detail"]["errorCode"] == "ACTOR_ROLE_INSUFFICIENT"


def test_stats_does_not_disguise_repository_failure(env):
    from app.training_pipeline.repository import set_repository
    set_repository(None)
    import os
    os.environ.pop("AI_TRAINING_REPOSITORY", None)
    r = _training_client().get("/api/training-candidates/stats", headers=admin_headers())
    assert r.status_code == 503  # 예전: 200 + 0건 + error 문자열(원인 노출)
    assert r.json()["detail"]["errorCode"] == "TRAINING_REPOSITORY_UNAVAILABLE"


def test_stats_separates_collection_approval_and_training(env):
    r = _training_client().get("/api/training-candidates/stats", headers=admin_headers())
    assert r.status_code == 200
    d = r.json()
    assert set(d) >= {"states", "collection", "trainEligible", "modelTrainingExecuted"}
    assert d["modelTrainingExecuted"] is False


def test_body_size_limit_before_parsing(env):
    c = _training_client()
    big = {"question": "q", "answer": "x" * (200 * 1024)}
    r = c.post("/api/training-candidates/collect", json=big, headers=service_headers())
    assert r.status_code == 413
    assert r.json()["detail"]["errorCode"] == "PAYLOAD_TOO_LARGE"


def test_rate_limit_on_admin_routes(env):
    c = _training_client()
    codes = [c.get("/api/training-candidates/stats", headers=admin_headers()).status_code for _ in range(40)]
    assert 429 in codes


def test_audit_log_has_no_raw_content(env, tmp_path):
    c = _training_client()
    c.post("/api/training-candidates/export-jsonl", json={"output_path": "/etc/passwd"}, headers=admin_headers())
    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "OUTPUT_PATH_NOT_ALLOWED" in text
    assert "/etc/passwd" not in text
    assert ADMIN_TOKEN not in text and INTERNAL_KEY not in text
