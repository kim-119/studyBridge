"""사용자 요청 내부 재시도는 bounded: 발화당 최대 1+repair1+regen1, 예산 부족 시 시작 금지."""
import time

from app.studymate.agent_executor import RenderSpec, execute
from app.studymate.budget import TurnBudget
from app.studymate.cancellation import CancelToken
from app.studymate.profile_contract import canonicalize_agent
from tests.studymate_fakes import FakeOllama, install


def _spec():
    a = canonicalize_agent({"agentId": 1, "name": "k", "personality": "logical", "knowledgeLevel": "bachelor"}, 0)
    return RenderSpec(agent=a, mode="basic", role="solo", question="q", turn_id="t", request_id="r")


def test_worst_case_llm_calls_bounded(monkeypatch):
    monkeypatch.setenv("STUDYMATE_JUDGE", "always")
    fake = install(monkeypatch, FakeOllama(render=lambda req: "짧음", judge_value=False))
    out = execute(_spec(), cancel=CancelToken(), budget=TurnBudget.for_kind("basic_single"))
    gen_calls = fake.count("render") + fake.count("repair")
    assert gen_calls <= 3 and fake.count("judge") <= 2
    assert out.status == "FAILED"


def test_no_retry_when_budget_low(monkeypatch):
    fake = install(monkeypatch, FakeOllama(render=lambda req: "짧음"))
    b = TurnBudget(kind="basic_single", total_s=13.0)
    out = execute(_spec(), cancel=CancelToken(), budget=b)
    assert fake.count("render") == 1 and fake.count("repair") == 0
    assert out.status == "FAILED" and "regenerate" in b.skipped


def test_gateway_refuses_call_without_budget():
    from app.studymate import llm_gateway as G
    import pytest
    with pytest.raises(G.LLMTimeout):
        G.generate(G.LLMRequest(system="s", user="u", model="m", num_ctx=8192, num_predict=5),
                   deadline=time.time() + 0.2)
