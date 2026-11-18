from app.studymate.trace import AgentCoverage


def test_unexpected_gap_and_degraded():
    c = AgentCoverage(selected=["1", "2", "3"])
    c.mark("emitted", "1"); c.mark("failed", "2")
    assert c.unexpected_gap() == ["3"] and c.degraded()


def test_intentional_partial_is_not_gap():
    c = AgentCoverage(selected=["1", "2"], suppressed=["2"], suppressedReason="memory_recall")
    c.mark("emitted", "1")
    assert c.unexpected_gap() == [] and not c.degraded()


def test_target_request_is_marked_targeted(monkeypatch):
    from app.schemas.multi_chat_schema import MultiChatRequest
    from app.studymate.basic_pipeline import run_basic_turn
    from app.studymate.runtime_context import new_runtime
    from tests.studymate_fakes import AGENTS3, FakeOllama, install
    install(monkeypatch, FakeOllama())
    req = MultiChatRequest(message="캐시", agents=AGENTS3, mode="basic", targetAgentId="102")
    from app.services.multi_agent_service import _filter_agents, _get_agents
    agents = _filter_agents(_get_agents(req), req.targetAgentId)
    ev = list(run_basic_turn(req, agents, current_message="캐시", social=False, rt=new_runtime()))
    cov = ev[-1]["data"]["agentCoverage"]
    assert cov["targeted"] is True and cov["selected"] == ["102"] and cov["emitted"] == ["102"]
    assert [e["data"]["agentIndex"] for e in ev if e["event"] == "agent_answer"] == [2]
