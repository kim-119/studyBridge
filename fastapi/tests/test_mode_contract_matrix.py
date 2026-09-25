"""모드별 SSE 계약 매트릭스: 각 모드 handler 가 내보내는 실제 이벤트 형태를 compat 시퀀서가 계약대로 닫는다."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import multi_chat_stream_compat as compat
from tests.studymate_fakes import AGENTS3, FakeOllama, install, parse_sse


def _client():
    app = FastAPI(); app.include_router(compat.router)
    return TestClient(app)


def _check(ev):
    names = [n for n, _ in ev]
    assert names[0] == "turn_start" and names.count("turn_start") == 1
    assert names.count("all_complete") == 1 and names[-1] == "done" and names.count("done") == 1
    open_ = {}
    for n, d in ev:
        if n == "agent_start":
            open_[d["agentId"]] = open_.get(d["agentId"], 0) + 1
        elif n in ("agent_answer", "agent_error"):
            assert open_.get(d["agentId"], 0) > 0, ("result without start", d.get("agentId"))
            open_[d["agentId"]] -= 1
    assert all(v == 0 for v in open_.values())
    for n, d in ev:
        assert d["contractVersion"] and d["requestId"] and d["turnId"]
    return dict(ev)["all_complete"]


@pytest.mark.parametrize("mode,handler_path,events", [
    ("socratic", "app.services.socratic_mode_handler.run_socratic_mode_stream", [
        ("turn_start", {"mode": "socratic"}),
        ("agent_start", {"agentId": 101}), ("agent_answer", {"agentId": 101, "answer": "진단과 질문?", "stageType": "DIAGNOSIS"}),
        ("agent_start", {"agentId": 102}), ("agent_answer", {"agentId": 102, "answer": "반례 질문?", "stageType": "COUNTEREXAMPLE"}),
        ("agent_start", {"agentId": 103}), ("agent_answer", {"agentId": 103, "answer": "검증 질문?", "stageType": "MISCONCEPTION_CHECK"}),
        ("all_complete", {"answers": [{"agentId": 101, "answer": "진단과 질문?"}], "suppressAgentFill": True})]),
    ("simulation", "app.services.simulation_mode_handler.run_simulation_mode_stream", [
        ("turn_start", {}), ("agent_start", {"agentId": 101}), ("agent_answer", {"agentId": 101, "answer": "장면"}),
        ("agent_start", {"agentId": 102}), ("agent_answer", {"agentId": 102, "answer": "도전"}),
        ("agent_start", {"agentId": 103}), ("agent_answer", {"agentId": 103, "answer": "코치"}),
        ("all_complete", {"answers": [], "suppressAgentFill": True, "choices": [{"label": "a"}]})]),
    ("debate", "app.services.debate_mode_handler.run_debate_mode_stream", [
        ("turn_start", {}), ("phase_progress", {"stageKey": "OPENING"}),
        ("agent_start", {"agentId": 101}), ("agent_answer", {"agentId": 101, "answer": "주장A", "stageType": "DEBATE_OPENING"}),
        ("agent_start", {"agentId": 102}), ("agent_answer", {"agentId": 102, "answer": "주장B", "stageType": "DEBATE_OPENING"}),
        ("agent_start", {"agentId": "debate-consensus"}), ("agent_answer", {"agentId": "debate-consensus", "answer": "합의"}),
        ("all_complete", {"answers": [], "suppressAgentFill": True})]),
    ("debate", "app.services.debate_mode_handler.run_debate_mode_stream", [
        ("turn_start", {}), ("agent_start", {"agentId": 101}),
        ("error", {"code": "DEBATE_LLM_TIMEOUT", "agentId": None})]),
])
def test_mode_stream_contract(monkeypatch, mode, handler_path, events):
    import importlib
    mod, fn = handler_path.rsplit(".", 1)
    monkeypatch.setattr(importlib.import_module(mod), fn,
                        lambda request, agents, **kw: iter([{"event": n, "data": dict(d)} for n, d in events]))
    from app.services import learning_mode_dispatcher as D
    monkeypatch.setattr(D, "evaluate_gate", lambda request, mode: (True, None, None))
    r = _client().post("/api/ai/multi-chat/stream", json={"message": "캐시가 왜 필요한가?", "mode": mode, "agents": AGENTS3})
    ac = _check(parse_sse(r.text))
    assert ac["mode"] == mode and "agentCoverage" in ac


def test_basic_mode_contract_real_pipeline(monkeypatch):
    monkeypatch.setenv("STUDYMATE_MIN_ANSWER_GAP_SECONDS", "0")
    install(monkeypatch, FakeOllama())
    r = _client().post("/api/ai/multi-chat/stream", json={"message": "캐시가 왜 필요한가?", "mode": "basic", "agents": AGENTS3})
    ac = _check(parse_sse(r.text))
    assert ac["route"] == "basic_v2" and ac["plan"]["source"] == "shared"


def test_mode_error_code_is_spring_terminal():
    import re
    pattern = re.compile(r"^(DEBATE|SOCRATIC|SIMULATION)_[A-Z_]+$")
    for code in ("DEBATE_LLM_TIMEOUT", "SOCRATIC_LLM_UNAVAILABLE", "SIMULATION_LLM_MODEL_NOT_FOUND"):
        assert pattern.match(code)
