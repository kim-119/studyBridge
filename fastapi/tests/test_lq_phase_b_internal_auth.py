"""Phase B2 — 경로 단위 내부 인증(deny-by-default). IP/loopback 은 인증을 대체하지 않는다."""
import asyncio
import json
import os

import pytest

from app.core import internal_auth as IA

KEY = "k" * 40
PREV = "p" * 40


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("AI_SERVER_API_KEY", KEY)
    monkeypatch.delenv("AI_SERVER_API_KEY_PREVIOUS", raising=False)
    monkeypatch.delenv("AI_INTERNAL_AUTH_MODE", raising=False)
    monkeypatch.delenv("AI_INTERNAL_AUTH_UNAUTH_ALLOWLIST", raising=False)
    monkeypatch.delenv("AI_DOCS_ENABLED", raising=False)


B = f"Bearer {KEY}"


def test_classification_is_deny_by_default():
    assert IA.classify("GET", "/health") == IA.PUBLIC and IA.classify("HEAD", "/api/ai/health") == IA.PUBLIC
    assert IA.classify("POST", "/health") == IA.PROTECTED                     # 공개는 GET/HEAD 정확 일치만
    assert IA.classify("GET", "/openapi.json") == IA.COMPAT
    assert IA.classify("POST", "/api/ai/multi-chat") == IA.COMPAT
    assert IA.classify("GET", "/api/ai/multi-chat") == IA.PROTECTED
    for p in ("/api/ai/agents/chat/fetch-stream", "/api/ai/gateway/status", "/api/ai/learning-mate/chat",
              "/api/quiz/generate", "/api/unknown/new-route", "/api/ai/multi-chat/", "//api/ai/multi-chat",
              "/api/ai/multi-chat/stream/../stream"):
        assert IA.classify("POST", p) == IA.PROTECTED, p
    assert len(IA.SPRING_COMPAT_POST) == 21


@pytest.mark.parametrize("mode", ["report", "enforce"])
def test_protected_requires_bearer_in_every_mode(monkeypatch, mode):
    monkeypatch.setenv("AI_INTERNAL_AUTH_MODE", mode)
    p = "/api/ai/agents/chat/fetch-stream"
    assert IA.decide("POST", p, None)[:3] == (False, 401, "AUTH_HEADER_MISSING")
    assert IA.decide("POST", p, "Bearer wrong")[:3] == (False, 401, "AUTH_TOKEN_INVALID")
    assert IA.decide("POST", p, "Basic " + KEY)[:3] == (False, 401, "AUTH_TOKEN_INVALID")
    assert IA.decide("POST", p, B)[0] is True


def test_report_mode_tolerates_only_spring_compat_and_counts_it(monkeypatch):
    monkeypatch.setenv("AI_INTERNAL_AUTH_MODE", "report")
    assert IA.decide("POST", "/api/ai/summary", None)[:3] == (True, 200, "COMPAT_TOLERATED_MISSING")
    assert IA.decide("POST", "/api/ai/summary", "Bearer old-secondary-key")[:3] == (True, 200, "COMPAT_TOLERATED_INVALID")
    assert IA.decide("GET", "/openapi.json", None)[0] is True


def test_enforce_mode_requires_bearer_on_compat_except_explicit_unauth_allowlist(monkeypatch):
    monkeypatch.setenv("AI_INTERNAL_AUTH_MODE", "enforce")
    assert IA.decide("POST", "/api/ai/summary", None)[:2] == (False, 401)
    assert IA.decide("GET", "/openapi.json", None)[:2] == (False, 401)
    assert IA.decide("GET", "/openapi.json", B)[0] is True
    # EC2 RestTemplate(/api/extract)·intentRouterWebClient 는 아직 Bearer 를 안 보냄 → '없음'만 허용, 틀린 토큰은 거부
    assert IA.decide("POST", "/api/extract", None)[:3] == (True, 200, "LEGACY_UNAUTH_ALLOWLISTED")
    assert IA.decide("POST", "/api/extract", "Bearer wrong")[:2] == (False, 401)
    monkeypatch.setenv("AI_INTERNAL_AUTH_UNAUTH_ALLOWLIST", "")           # EC2 수정 후 예외 0
    assert IA.decide("POST", "/api/extract", None)[:2] == (False, 401)


def test_unauth_allowlist_cannot_open_protected_or_wildcard_paths(monkeypatch):
    monkeypatch.setenv("AI_INTERNAL_AUTH_MODE", "enforce")
    monkeypatch.setenv("AI_INTERNAL_AUTH_UNAUTH_ALLOWLIST",
                       "POST /api/ai/agents/chat/fetch-stream,POST /api/*,GET /openapi.json,POST /api/ai/summary")
    assert IA.decide("POST", "/api/ai/agents/chat/fetch-stream", None)[0] is False
    assert IA.decide("GET", "/openapi.json", None)[0] is False
    assert IA.decide("POST", "/api/ai/summary", None)[0] is True             # compat 범위 안 정확 경로만 유효


def test_unknown_mode_is_strictest(monkeypatch):
    monkeypatch.setenv("AI_INTERNAL_AUTH_MODE", "off")
    assert IA.mode() == "enforce" and IA.decide("POST", "/api/ai/summary", None)[0] is False


def test_fail_closed_when_server_key_missing_or_short(monkeypatch):
    monkeypatch.setenv("AI_SERVER_API_KEY", "short")
    for mode in ("report", "enforce"):
        monkeypatch.setenv("AI_INTERNAL_AUTH_MODE", mode)
        assert IA.decide("POST", "/api/ai/summary", None)[:3] == (False, 503, "INTERNAL_AUTH_NOT_CONFIGURED")
        assert IA.decide("GET", "/health", None)[0] is True
    monkeypatch.setenv("AI_SERVER_API_KEY_PREVIOUS", PREV)                    # 이전 키만 있어도 현재 키 없으면 거부
    assert IA.decide("POST", "/api/ai/summary", f"Bearer {PREV}")[1] == 503


def test_previous_key_accepted_during_rotation(monkeypatch):
    monkeypatch.setenv("AI_INTERNAL_AUTH_MODE", "enforce")
    monkeypatch.setenv("AI_SERVER_API_KEY_PREVIOUS", PREV)
    assert IA.decide("POST", "/api/ai/gateway/status", f"Bearer {PREV}")[0] is True


def test_docs_disabled_by_default_and_protected_when_enabled(monkeypatch):
    assert IA.decide("GET", "/docs", B)[:2] == (False, 404)
    monkeypatch.setenv("AI_DOCS_ENABLED", "true")
    assert IA.decide("GET", "/docs", None)[:2] == (False, 401) and IA.decide("GET", "/redoc", B)[0] is True


def _asgi_app():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream")]})
        for i in range(3):
            await send({"type": "http.response.body", "body": f"data: {i}\n\n".encode(), "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})
    return app


def _call(mw, method, path, headers=(), client=("127.0.0.1", 5555)):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(m):
        sent.append(m)
    scope = {"type": "http", "method": method, "path": path, "headers": list(headers), "client": client}
    asyncio.run(mw(scope, receive, send))
    return sent


def test_middleware_does_not_trust_loopback_and_streams_unbuffered():
    mw = IA.InternalAuthMiddleware(_asgi_app())
    denied = _call(mw, "POST", "/api/ai/tasks/fetch-stream", client=("127.0.0.1", 1))     # reverse SSH 출발지
    assert denied[0]["status"] == 401 and json.loads(denied[1]["body"])["detail"]["errorCode"] == "AUTH_HEADER_MISSING"
    ok = _call(mw, "POST", "/api/ai/tasks/fetch-stream", headers=[(b"authorization", B.encode())])
    assert ok[0]["status"] == 200 and [m.get("more_body") for m in ok[1:]] == [True, True, True, False]


def test_hotfix_app_registers_middleware_and_compat_paths_exist():
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
    from hotfix_main import app
    assert any(getattr(m, "cls", None) is IA.InternalAuthMiddleware for m in app.user_middleware)
    paths = app.openapi()["paths"]
    missing = [p for p in IA.SPRING_COMPAT_POST if p not in paths or "post" not in paths[p]]
    assert missing == [], missing
    for p in IA.PUBLIC_PATHS:
        assert p in paths or p == "/api/native-engine/health" and "/api/native-engine/health" in paths


def test_hotfix_app_rejects_before_handler_runs(monkeypatch):
    monkeypatch.setenv("AI_INTERNAL_AUTH_MODE", "report")
    from fastapi.testclient import TestClient
    from hotfix_main import app
    c = TestClient(app)
    assert c.get("/health").status_code == 200
    r = c.post("/api/ai/tasks/fetch-stream", json={"message": "x"})
    assert r.status_code == 401 and r.json()["detail"]["errorCode"] == "AUTH_HEADER_MISSING"
    assert c.get("/docs").status_code == 404 and c.get("/redoc").status_code == 404
    r = c.post("/api/ai/%6Cearning-mate/chat", json={})                       # %인코딩 우회 시도 → 같은 경로로 디코딩되어 차단
    assert r.status_code == 401
    assert c.post("/api/ai/gateway/status").status_code == 401
