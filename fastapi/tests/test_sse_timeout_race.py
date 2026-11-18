"""워치독 데드라인 초과: 열린 발화는 TURN_TIMEOUT agent_error, 성공 답변 보존 all_complete, done 1회, 늦게 온 이벤트 무시."""
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

import multi_chat_stream_compat as compat
from app.studymate import stream_runtime as SR
from tests.studymate_fakes import AGENTS3, parse_sse


def test_watchdog_closes_turn(monkeypatch):
    from app.services import multi_agent_service as mas
    monkeypatch.setattr(SR, "_grace_s", lambda: 0.5)
    monkeypatch.setattr(SR, "_heartbeat_s", lambda: 0.2)
    monkeypatch.setenv("STUDYMATE_BUDGET_BASIC_MULTI_S", "0.5")

    def gen(req):
        yield {"event": "agent_start", "data": {"agentId": 101}}
        yield {"event": "agent_answer", "data": {"agentId": 101, "answer": "먼저 온 답"}}
        yield {"event": "agent_start", "data": {"agentId": 102}}
        time.sleep(2.5)
        yield {"event": "agent_answer", "data": {"agentId": 102, "answer": "늦은 답"}}
        yield {"event": "all_complete", "data": {"answers": []}}
    monkeypatch.setattr(mas, "build_stream_generator", gen)
    app = FastAPI(); app.include_router(compat.router)
    ev = parse_sse(TestClient(app).post("/api/ai/multi-chat/stream", json={"message": "q", "agents": AGENTS3}).text)
    names = [n for n, _ in ev]
    assert names.count("all_complete") == 1 and names.count("done") == 1 and names[-1] == "done"
    assert "늦은 답" not in str(ev)
    err = [d for n, d in ev if n == "agent_error"][0]
    assert err["agentId"] == 102 and err["code"] == "TURN_TIMEOUT"
    ac = dict(ev)["all_complete"]
    assert [a["agentId"] for a in ac["answers"]] == [101] and ac["status"] == "PARTIAL"
    assert dict(ev)["done"]["status"] == "timeout"
