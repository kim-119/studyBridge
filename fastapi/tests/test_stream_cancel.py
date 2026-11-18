"""CancelToken 이 파이프라인 전 단계에서 새 LLM 호출을 막는다."""
from app.schemas.multi_chat_schema import MultiChatRequest
from app.studymate.basic_pipeline import run_basic_turn
from app.studymate.runtime_context import new_runtime
from tests.studymate_fakes import AGENTS3, FakeOllama, install


def test_cancel_before_second_agent(monkeypatch):
    monkeypatch.setenv("STUDYMATE_MIN_ANSWER_GAP_SECONDS", "0")
    fake = install(monkeypatch, FakeOllama())
    req = MultiChatRequest(message="캐시 설명해줘", agents=AGENTS3, mode="basic")
    rt = new_runtime()
    gen = run_basic_turn(req, req.agents, current_message=req.message, social=False, rt=rt)
    seen = []
    for ev in gen:
        seen.append(ev["event"])
        if ev["event"] == "agent_answer":
            rt.cancel.cancel("client_disconnected")
    assert seen.count("agent_answer") == 1
    assert "all_complete" not in seen
    assert fake.count("render") == 1


def test_validation_before_open_returns_422():
    from fastapi.testclient import TestClient
    import hotfix_main
    c = TestClient(hotfix_main.app)
    for body, code in [({"agents": []}, "MESSAGE_REQUIRED"), ({"message": "   "}, "MESSAGE_REQUIRED"),
                       ({"message": "q", "mode": "debat"}, "UNSUPPORTED_MODE"),
                       ({"message": "q", "targetAgentId": 999, "agents": [{"agentId": 1}]}, "TARGET_AGENT_NOT_FOUND"),
                       ({"message": "q", "rounds": 99}, "INVALID_REQUEST")]:
        r = c.post("/api/ai/multi-chat/stream", json=body)
        assert r.status_code == 422, body
        assert r.headers["content-type"].startswith("application/json")
        assert r.json()["detail"]["code"] == code
    r = c.post("/api/ai/multi-chat/stream", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422
