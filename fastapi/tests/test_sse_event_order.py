"""실제 v2 파이프라인 + compat SSE: 정상 순서/짝/종료 이벤트 계약 (가짜 Ollama)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import multi_chat_stream_compat as compat
from tests.studymate_fakes import AGENTS3, FakeOllama, install, parse_sse


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("STUDYMATE_MIN_ANSWER_GAP_SECONDS", "0")
    monkeypatch.setenv("STUDYMATE_DISCUSSION_PLANNER", "off")
    app = FastAPI()
    app.include_router(compat.router)
    return TestClient(app)


def _post(client, **kw):
    body = {"message": "Redis를 왜 사용하는지 설명해줘", "mode": "basic", "agents": AGENTS3, "roomId": 1}
    body.update(kw)
    return client.post("/api/ai/multi-chat/stream", json=body)


def test_basic_three_agents_exact_sequence(client, monkeypatch):
    fake = install(monkeypatch, FakeOllama())
    r = _post(client)
    assert r.status_code == 200
    ev = parse_sse(r.text)
    names = [n for n, _ in ev]
    assert names[0] == "turn_start" and names.count("turn_start") == 1
    assert names[-1] == "done" and names.count("done") == 1 and names.count("all_complete") == 1
    assert names.index("all_complete") < names.index("done")
    body = [n for n in names if n not in ("heartbeat",)]
    starts = [i for i, n in enumerate(body) if n == "agent_start"]
    for i in starts:
        assert body[i + 1] in ("agent_answer", "agent_error")
    ac = dict(ev)["all_complete"]
    assert ac["agentCoverage"]["selected"] == ["101", "102", "103"]
    assert ac["agentCoverage"]["emitted"] == ["101", "102", "103"] and not ac["agentCoverage"]["unexpectedGap"]
    assert fake.count("planner") == 1 and fake.count("render") >= 3
    assert ac["sse"]["dedupDropped"] == 0 and ac["sse"]["invalidEvents"] == 0


def test_identity_is_canonical_in_all_events(client, monkeypatch):
    install(monkeypatch, FakeOllama())
    ev = parse_sse(_post(client).text)
    for name, d in ev:
        if name in ("agent_start", "agent_answer") and d.get("agentId") == 102:
            assert d["personality"] == "critical" and d["personalityLabel"] == "비판형"
            assert d["knowledgeLevel"] == "phd" and d["knowledgeLevelLabel"] == "박사"
