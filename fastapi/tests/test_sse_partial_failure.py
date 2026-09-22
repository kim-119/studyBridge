"""일부 교수 실패: 성공 답변은 보존, 실패는 agent_error + agentErrors, answers 에 실패 문구 없음."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import multi_chat_stream_compat as compat
from app.studymate import llm_gateway as G
from tests.studymate_fakes import AGENTS3, FakeOllama, install, parse_sse, PERSONA_TEXT


def test_one_agent_fails_others_succeed(monkeypatch):
    monkeypatch.setenv("STUDYMATE_MIN_ANSWER_GAP_SECONDS", "0")
    monkeypatch.setenv("STUDYMATE_DISCUSSION_PLANNER", "off")

    def render(req):
        if "너의 이름은 '이교수'" in req.system:
            raise G.LLMTimeout("slow")
        persona = "friendly" if "[PERSONALITY: 친근함]" in req.system else "creative"
        return PERSONA_TEXT[persona].format(topic="캐시", agent=req.system[-30:] + str(id(req)))
    install(monkeypatch, FakeOllama(render=render))
    app = FastAPI(); app.include_router(compat.router)
    ev = parse_sse(TestClient(app).post("/api/ai/multi-chat/stream",
                                        json={"message": "캐시 설명", "agents": AGENTS3, "mode": "basic"}).text)
    ac = dict(ev)["all_complete"]
    assert sorted(a["agentId"] for a in ac["answers"]) == [101, 103]
    assert [e["agentId"] for e in ac["agentErrors"]] == [102] and ac["agentErrors"][0]["code"] == "LLM_TIMEOUT"
    assert ac["degraded"] is True and ac["status"] == "PARTIAL"
    assert all("시간" not in (a.get("answer") or "")[:10] for a in ac["answers"])
    assert ac["agentCoverage"]["failed"] == ["102"]
