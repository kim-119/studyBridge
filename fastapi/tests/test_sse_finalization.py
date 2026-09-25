"""스트림 종료 계약: 업스트림이 all_complete 없이 끝나도 all_complete+done 으로 닫는다(Spring failover 방지)."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import multi_chat_stream_compat as compat
from tests.studymate_fakes import AGENTS3, parse_sse


def _client():
    app = FastAPI()
    app.include_router(compat.router)
    return TestClient(app)


def test_missing_all_complete_is_closed(monkeypatch):
    from app.services import multi_agent_service as mas

    def gen(req):
        yield {"event": "turn_start", "data": {}}
        yield {"event": "agent_start", "data": {"agentId": 101, "agentName": "김교수"}}
        yield {"event": "agent_answer", "data": {"agentId": 101, "answer": "첫 답"}}
        yield {"event": "agent_start", "data": {"agentId": 102}}
    monkeypatch.setattr(mas, "build_stream_generator", gen)
    ev = parse_sse(_client().post("/api/ai/multi-chat/stream", json={"message": "q", "agents": AGENTS3}).text)
    names = [n for n, _ in ev]
    assert names[-2:] == ["all_complete", "done"]
    ac = dict(ev)["all_complete"]
    assert ac["code"] == "UPSTREAM_INCOMPLETE" and ac["degraded"] is True
    assert [a["agentId"] for a in ac["answers"]] == [101]
    err = [d for n, d in ev if n == "agent_error"][0]
    assert err["agentId"] == 102


def test_exception_before_any_answer_is_fatal_error_event(monkeypatch):
    from app.services import multi_agent_service as mas

    def boom(req):
        raise RuntimeError("secret internal detail")
        yield  # pragma: no cover
    monkeypatch.setattr(mas, "build_stream_generator", boom)
    r = _client().post("/api/ai/multi-chat/stream", json={"message": "q", "agents": AGENTS3})
    ev = parse_sse(r.text)
    names = [n for n, _ in ev]
    assert "error" in names and names[-1] == "done"
    err = dict(ev)["error"]
    assert err["eventType"] == "stream_error" and err["agentId"] is None and "secret" not in r.text


def test_exception_after_answer_closes_turn_without_fatal(monkeypatch):
    from app.services import multi_agent_service as mas

    def gen(req):
        yield {"event": "agent_start", "data": {"agentId": 101}}
        yield {"event": "agent_answer", "data": {"agentId": 101, "answer": "a"}}
        raise RuntimeError("boom")
    monkeypatch.setattr(mas, "build_stream_generator", gen)
    ev = parse_sse(_client().post("/api/ai/multi-chat/stream", json={"message": "q", "agents": AGENTS3}).text)
    names = [n for n, _ in ev]
    assert "error" not in names and names[-2:] == ["all_complete", "done"]
    assert dict(ev)["all_complete"]["code"] == "STREAM_INTERNAL_ERROR"
