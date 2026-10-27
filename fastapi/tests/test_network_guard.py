"""출발지 네트워크 가드 + (게이트웨이 fail-open 이 인증·출발지 검사를 우회하지 않는지) 테스트. 외부 I/O 없음."""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI

from app.core import network_guard as ng
from app.core.network_guard import NetworkGuardMiddleware, is_trusted_host

KEY = "k-guard-test"
NETS = ng._parse_networks(ng._DEFAULT_TRUSTED)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("AI_SERVER_API_KEY", KEY)
    monkeypatch.delenv("AI_NETWORK_GUARD", raising=False)
    monkeypatch.delenv("AI_TRUSTED_NETWORKS", raising=False)


@pytest.mark.parametrize("host,ok", [
    ("127.0.0.1", True), ("::1", True), ("172.18.0.7", True), ("172.17.0.1", True), ("10.0.1.215", True),
    ("192.168.0.5", True), ("::ffff:127.0.0.1", True), ("fd00::1", True), ("testclient", True), (None, True),
    ("8.8.8.8", False), ("43.202.211.123", False), ("61.132.217.130", False), ("::ffff:8.8.8.8", False),
    ("172.32.0.1", False), ("2001:db8::1", False), ("not-an-ip", False),
])
def test_trusted_host_classification(host, ok):
    assert is_trusted_host(host, NETS) is ok


def _spy_app():
    calls = []
    app = FastAPI()

    @app.post("/api/ai/multi-chat/stream")
    async def mc(body: dict):
        calls.append(body)
        return {"ok": True}

    @app.get("/health")
    async def h():
        return {"ok": True}

    @app.get("/openapi-like")
    async def o():
        return {"paths": 75}
    app.add_middleware(NetworkGuardMiddleware)
    return app, calls


def _req(app, method, path, client=("8.8.8.8", 4444), **kw):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=client), base_url="http://t") as c:
            return await c.request(method, path, **kw)
    return asyncio.run(go())


def test_external_blocked_before_handler_runs():
    app, calls = _spy_app()
    r = _req(app, "POST", "/api/ai/multi-chat/stream", json={"message": "x"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "AI_NETWORK_FORBIDDEN"
    assert calls == []                                            # 핸들러(=LLM 호출) 미도달


def test_internal_sources_pass_unchanged():
    app, calls = _spy_app()
    for client in (("127.0.0.1", 1), ("172.18.0.7", 2), ("testclient", 3)):
        r = _req(app, "POST", "/api/ai/multi-chat/stream", client=client, json={"message": "x"})
        assert r.status_code == 200
    assert len(calls) == 3


def test_external_with_valid_bearer_passes_wrong_bearer_blocked():
    app, calls = _spy_app()
    ok = _req(app, "POST", "/api/ai/multi-chat/stream", json={"m": 1}, headers={"Authorization": f"Bearer {KEY}"})
    bad = _req(app, "POST", "/api/ai/multi-chat/stream", json={"m": 1}, headers={"Authorization": "Bearer nope"})
    assert ok.status_code == 200 and bad.status_code == 403 and len(calls) == 1


def test_health_exempt_but_docs_blocked():
    app, _ = _spy_app()
    assert _req(app, "GET", "/health").status_code == 200
    assert _req(app, "GET", "/openapi-like").status_code == 403
    assert _req(app, "GET", "/openapi.json").status_code == 403


def test_forwarded_header_cannot_spoof_source():
    app, calls = _spy_app()
    r = _req(app, "POST", "/api/ai/multi-chat/stream", json={},
             headers={"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"})
    assert r.status_code == 403 and calls == []


def test_modes_log_off_strict(monkeypatch):
    app, calls = _spy_app()
    monkeypatch.setenv("AI_NETWORK_GUARD", "log")
    assert _req(app, "POST", "/api/ai/multi-chat/stream", json={}).status_code == 200
    monkeypatch.setenv("AI_NETWORK_GUARD", "off")
    assert _req(app, "POST", "/api/ai/multi-chat/stream", json={}).status_code == 200
    monkeypatch.setenv("AI_NETWORK_GUARD", "strict")
    assert _req(app, "POST", "/api/ai/multi-chat/stream", client=("127.0.0.1", 1), json={}).status_code == 403
    assert _req(app, "POST", "/api/ai/multi-chat/stream", client=("127.0.0.1", 1), json={},
                headers={"Authorization": f"Bearer {KEY}"}).status_code == 200
    assert _req(app, "GET", "/health", client=("127.0.0.1", 1)).status_code == 200


def test_no_key_configured_means_no_bearer_bypass(monkeypatch):
    monkeypatch.delenv("AI_SERVER_API_KEY")
    app, calls = _spy_app()
    r = _req(app, "POST", "/api/ai/multi-chat/stream", json={}, headers={"Authorization": "Bearer "})
    assert r.status_code == 403 and calls == []


def test_evaluation_error_fails_closed(monkeypatch):
    app, calls = _spy_app()
    monkeypatch.setattr(ng, "_parse_networks", lambda spec: (_ for _ in ()).throw(RuntimeError("boom")))
    r = _req(app, "POST", "/api/ai/multi-chat/stream", client=("127.0.0.1", 1), json={})
    assert r.status_code == 403 and calls == []


def test_custom_trusted_networks(monkeypatch):
    monkeypatch.setenv("AI_TRUSTED_NETWORKS", "127.0.0.0/8")
    app, calls = _spy_app()
    assert _req(app, "POST", "/api/ai/multi-chat/stream", client=("172.18.0.7", 1), json={}).status_code == 403
    assert _req(app, "POST", "/api/ai/multi-chat/stream", client=("127.0.0.1", 1), json={}).status_code == 200


# ── 라이브 앱(hotfix_main): 가드가 가장 바깥이고, 게이트웨이 fail-open 이 인증을 우회하지 않는다 ─────
@pytest.fixture()
def live(monkeypatch):
    monkeypatch.setenv("VISION_API_ENABLED", "true")
    monkeypatch.setenv("VISION_BACKEND", "mock")
    monkeypatch.setenv("AI_GATEWAY_ENABLED", "true")
    monkeypatch.setenv("AI_GW_GPU_GUARD", "false")
    import hotfix_main
    import app.ai_gateway as gw
    gw.reset_for_tests(None)
    yield hotfix_main.app, gw
    gw.reset_for_tests(None)


def test_live_app_guard_is_outermost(live):
    app, _ = live
    assert app.user_middleware[0].cls is NetworkGuardMiddleware


def test_live_app_external_blocked_internal_ok(live):
    app, _ = live
    r = _req(app, "POST", "/api/ai/multi-chat/stream", json={"message": "안녕"})
    assert r.status_code == 403
    r = _req(app, "GET", "/api/ai/gateway/status")
    assert r.status_code == 403                                   # 내부 상태도 외부 비공개
    r = _req(app, "GET", "/api/ai/gateway/status", client=("172.18.0.2", 5))
    assert r.status_code == 200
    assert _req(app, "GET", "/health").status_code == 200


def test_gateway_fail_open_does_not_bypass_auth(live, monkeypatch):
    """스케줄러가 고장 나도(fail-open) 출발지 차단과 비전 내부 인증은 그대로 적용된다."""
    app, gw = live
    s = gw.get_scheduler()
    monkeypatch.setattr(s, "acquire_async", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("scheduler bug")))
    body = {"requestId": "r1", "groupId": 1, "question": "q", "image": "AAAA", "mime": "image/jpeg"}
    ext = _req(app, "POST", "/api/ai/vision/analyze", json=body)
    assert ext.status_code == 403 and ext.json()["error"]["code"] == "AI_NETWORK_FORBIDDEN"
    internal_noauth = _req(app, "POST", "/api/ai/vision/analyze", client=("127.0.0.1", 1), json=body)
    assert internal_noauth.status_code == 401 and internal_noauth.json()["error"]["code"] == "VISION_UNAUTHORIZED"
    internal_badauth = _req(app, "POST", "/api/ai/vision/analyze", client=("127.0.0.1", 1), json=body,
                            headers={"Authorization": "Bearer wrong"})
    assert internal_badauth.status_code == 401
