"""stream 과 non-stream 이 같은 도메인 결과(identity/status/agentId)를 낸다."""
from fastapi.testclient import TestClient

from tests.studymate_fakes import AGENTS3, FakeOllama, install, parse_sse

KEYS = ("agentId", "agentName", "personality", "personalityLabel", "knowledgeLevel", "knowledgeLevelLabel", "status")


def test_stream_and_non_stream_identity_parity(monkeypatch):
    monkeypatch.setenv("STUDYMATE_MIN_ANSWER_GAP_SECONDS", "0")
    monkeypatch.setenv("STUDYMATE_DISCUSSION_PLANNER", "off")
    install(monkeypatch, FakeOllama())
    import hotfix_main
    c = TestClient(hotfix_main.app)
    body = {"message": "Redis를 왜 사용하는지 설명해줘", "mode": "basic", "agents": AGENTS3}
    s = dict(parse_sse(c.post("/api/ai/multi-chat/stream", json=body).text))["all_complete"]
    n = c.post("/api/ai/multi-chat", json=body)
    assert n.status_code == 200
    nb = n.json()
    proj = lambda rows: sorted(tuple(r.get(k) for k in KEYS) for r in rows)
    assert proj(s["answers"]) == proj(nb["answers"])
    assert {r["personality"] for r in nb["answers"]} == {"friendly", "critical", "creative"}
    assert {r["personalityLabel"] for r in nb["answers"]} == {"친근함", "비판형", "독특함"}
    assert nb["agentCoverage"]["emitted"] == ["101", "102", "103"]


def test_non_stream_all_failed_is_not_200(monkeypatch):
    from app.studymate import llm_gateway as G
    install(monkeypatch, FakeOllama(fail={"render": G.LLMUnavailable("down"), "planner": G.LLMUnavailable("down")}))
    import hotfix_main
    r = TestClient(hotfix_main.app).post("/api/ai/multi-chat", json={"message": "q", "mode": "basic", "agents": AGENTS3})
    assert r.status_code == 503
    assert r.json()["answers"] == [] and r.json()["success"] is False
