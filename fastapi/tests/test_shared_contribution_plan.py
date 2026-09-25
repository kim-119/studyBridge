"""다중 교수: planner 1회(형식=JSON schema) 후 교수별 render. 단일 교수: planner 없음(direct)."""
from app.schemas.multi_chat_schema import MultiChatRequest
from app.studymate import planner as PL
from app.studymate.basic_pipeline import run_basic_turn
from app.studymate.budget import TurnBudget
from app.studymate.profile_contract import canonicalize_agents
from app.studymate.runtime_context import new_runtime
from tests.studymate_fakes import AGENTS3, FakeOllama, install


def test_multi_agent_single_planner_call(monkeypatch):
    monkeypatch.setenv("STUDYMATE_MIN_ANSWER_GAP_SECONDS", "0")
    monkeypatch.setenv("STUDYMATE_DISCUSSION_PLANNER", "off")
    fake = install(monkeypatch, FakeOllama())
    req = MultiChatRequest(message="Redis를 왜 쓰나?", agents=AGENTS3, mode="basic")
    list(run_basic_turn(req, req.agents, current_message=req.message, social=False, rt=new_runtime()))
    planners = [c for c in fake.calls if c.task == "planner"]
    assert len(planners) == 1 and isinstance(planners[0].format, dict)
    assert set(planners[0].format["properties"]["agents"]["required"]) == {"101", "102", "103"}
    renders = [c for c in fake.calls if c.task == "render"]
    assert len(renders) == 3
    # B/C 렌더에는 A 의 원문 답변이 아니라 주장 목록만 들어간다
    first_answer_prefix = "처음 보면 헷갈리죠"
    assert all(first_answer_prefix not in r.user for r in renders[1:])
    assert "[이번 턴 기여 계획" in renders[1].user


def test_single_agent_direct_no_planner(monkeypatch):
    fake = install(monkeypatch, FakeOllama())
    req = MultiChatRequest(message="캐시", agents=[AGENTS3[0]], mode="basic")
    list(run_basic_turn(req, req.agents, current_message="캐시", social=False, rt=new_runtime()))
    assert fake.count("planner") == 0 and fake.count("render") == 1


def test_invalid_planner_output_repairs_once_then_fallback(monkeypatch):
    fake = install(monkeypatch, FakeOllama(planner_raw=["{not json", '{"question_focus": "x"}']))
    agents = canonicalize_agents(AGENTS3)
    roles = {a.agentId: "core" for a in agents}
    out = PL.plan_turn("질문이 충분히 긴 복잡한 비교 질문입니다", agents, roles, turn_id="t",
                       budget=TurnBudget.for_kind("basic_multi"))
    assert fake.count("planner") == 2 and out.source == "fallback" and out.errors
