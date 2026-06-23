"""
기본개념모드 확률적 다중답변 피드백 스트림 통합 테스트.

planner가 켜지면(STUDYMATE_DISCUSSION_PLANNER=on, basic 모드) 에이전트 3명이라도
agent_answer가 확률적으로 답변 3~7개 + 사용자용 정리(WRAP) 1개로 나온다.
- 첫 agent_answer는 DIRECT_ANSWER, 마지막은 WRAP (사용자 중심).
- REACTION은 replyTo로 대상 에이전트를 가리킨다.
- all_complete는 정확히 1회, 마지막 이벤트.
- 재개입 칩(followUpSuggestions)이 all_complete에 실린다.
LLM은 monkeypatch로 결정화한다(실 ollama 미사용).
"""
import pytest

from app.schemas.multi_chat_schema import AgentProfile, MultiChatRequest
from app.services import orchestrator_service as orch


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(orch, "_fetch_wikipedia_context", lambda q: "")
    monkeypatch.setattr("app.services.ollama_client.ask_ollama", lambda **k: "테스트 답변 본문")
    monkeypatch.setattr(orch, "_min_gap_seconds", lambda: 0.0)


def _agents():
    return [
        AgentProfile(id=1, agentId="a1", name="전문봇", personality="전문적", knowledgeLevel="학사"),
        AgentProfile(id=2, agentId="a2", name="냉소봇", personality="냉소적", knowledgeLevel="학사"),
        AgentProfile(id=3, agentId="a3", name="친근봇", personality="친근함", knowledgeLevel="학사"),
    ]


def _run(monkeypatch, seed="5", planner="on", agents=None):
    monkeypatch.setenv("STUDYMATE_DISCUSSION_PLANNER", planner)
    monkeypatch.setenv("STUDYMATE_DISCUSSION_SEED", seed)
    req = MultiChatRequest(message="SQL JOIN이 뭐야?", agents=agents or _agents())
    return list(orch.build_orchestrator_stream(req, agents or _agents()))


def _answers(events):
    return [e for e in events if e["event"] == "agent_answer"]


def test_planner_on_event_envelope(monkeypatch):
    events = _run(monkeypatch)
    assert events[0]["event"] == "turn_start"
    assert events[-1]["event"] == "all_complete"
    assert sum(1 for e in events if e["event"] == "all_complete") == 1


def test_planner_answer_count_in_band(monkeypatch):
    # 여러 시드에서 답변(DIRECT+REACTION) 수가 [3,7], WRAP은 별도 1개.
    for seed in range(20):
        events = _run(monkeypatch, seed=str(seed))
        ans = _answers(events)
        non_wrap = [a for a in ans if a["data"]["actType"] != "WRAP"]
        wrap = [a for a in ans if a["data"]["actType"] == "WRAP"]
        assert 3 <= len(non_wrap) <= 7, f"seed={seed}: {len(non_wrap)} answers"
        assert len(wrap) == 1, f"seed={seed}: WRAP count {len(wrap)}"


def test_first_answer_direct_last_answer_wrap(monkeypatch):
    ans = _answers(_run(monkeypatch))
    assert ans[0]["data"]["actType"] == "DIRECT_ANSWER"
    assert ans[-1]["data"]["actType"] == "WRAP"


def test_every_answer_has_acttype(monkeypatch):
    for a in _answers(_run(monkeypatch)):
        assert a["data"]["actType"] in ("DIRECT_ANSWER", "REACTION", "WRAP")


def test_reaction_replyto_points_to_valid_agent(monkeypatch):
    ids = {ag.agentId for ag in _agents()}
    for a in _answers(_run(monkeypatch)):
        d = a["data"]
        if d["actType"] == "REACTION":
            assert d.get("replyTo") in ids
            assert d["replyTo"] != d["agentId"], "자기자신 반응 금지"
        else:
            assert d.get("replyTo") in (None, "")


def test_all_complete_answers_match_emitted(monkeypatch):
    events = _run(monkeypatch)
    emitted = _answers(events)
    final = events[-1]["data"]["answers"]
    assert len(final) == len(emitted)


def test_follow_up_suggestions_present(monkeypatch):
    events = _run(monkeypatch)
    sugg = events[-1]["data"].get("followUpSuggestions")
    assert isinstance(sugg, list) and len(sugg) >= 2


def test_planner_off_is_legacy_one_per_agent(monkeypatch):
    # planner off → 기존 1인1답(actType 없음, agent_answer 수 == 에이전트 수, 피드백 라운드 제외).
    monkeypatch.setenv("STUDYMATE_FEEDBACK_ROUND", "off")
    events = _run(monkeypatch, planner="off")
    ans = _answers(events)
    assert len(ans) == 3
    assert all("actType" not in a["data"] for a in ans)


def test_planner_skipped_for_non_basic_mode(monkeypatch):
    # 토론/소크라테스는 planner 미적용(기존 계약 보존).
    monkeypatch.setenv("STUDYMATE_DISCUSSION_PLANNER", "on")
    monkeypatch.setenv("STUDYMATE_DISCUSSION_SEED", "5")
    req = MultiChatRequest(message="SQL JOIN이 뭐야?", agents=_agents(), mode="socratic")
    events = list(orch.build_orchestrator_stream(req, _agents()))
    ans = _answers(events)
    assert all("actType" not in a["data"] for a in ans), "소크라테스에 planner가 새면 안 됨"
