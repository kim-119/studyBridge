"""
WRAP 온디맨드 검증.

- 기본 턴(정리 요청 없음): 스트림에 WRAP actType 발화가 자동으로 붙지 않는다.
- 사용자가 '정리/요약' 요청 + 직전 대화 있음: 구조화된 🧩 정리(WRAP) 한 장만 나온다.
LLM은 monkeypatch로 결정화.
"""
import pytest

from app.schemas.multi_chat_schema import AgentProfile, MultiChatRequest, PreviousAnswer
from app.services import orchestrator_service as orch


@pytest.fixture(autouse=True)
def _no_net(monkeypatch):
    monkeypatch.setattr(orch, "_build_knowledge_context", lambda q: "")
    monkeypatch.setattr(orch, "_fetch_wikipedia_context", lambda q: "")
    monkeypatch.setattr("app.services.ollama_client.ask_ollama", lambda **k: "구조화된 정리 본문")
    monkeypatch.setattr(orch, "_min_gap_seconds", lambda: 0.0)


def _agents():
    return [
        AgentProfile(id=1, agentId="a1", name="전문봇", personality="전문적", knowledgeLevel="학사"),
        AgentProfile(id=2, agentId="a2", name="냉소봇", personality="냉소적", knowledgeLevel="학사"),
        AgentProfile(id=3, agentId="a3", name="친근봇", personality="친근함", knowledgeLevel="학사"),
    ]


def test_default_turn_has_no_auto_wrap(monkeypatch):
    monkeypatch.setenv("STUDYMATE_DISCUSSION_SEED", "5")
    req = MultiChatRequest(message="SQL JOIN이 뭐야?", agents=_agents())
    events = list(orch.build_orchestrator_stream(req, _agents()))
    answers = [e for e in events if e["event"] == "agent_answer"]
    assert answers, "답변이 비어있음"
    assert all(a["data"].get("actType") != "WRAP" for a in answers), "기본 턴에 자동 WRAP가 붙음"


def test_summary_request_yields_single_wrap(monkeypatch):
    prev = [
        PreviousAnswer(agentName="전문봇", answer="JOIN은 두 테이블을 결합한다.", role="ASSISTANT"),
        PreviousAnswer(agentName="냉소봇", answer="ON 조건이 핵심이다.", role="ASSISTANT"),
    ]
    req = MultiChatRequest(message="지금까지 내용 3줄로 정리해줘", agents=_agents(), previousAnswers=prev)
    events = list(orch.build_orchestrator_stream(req, _agents()))
    answers = [e for e in events if e["event"] == "agent_answer"]
    assert len(answers) == 1, f"정리는 한 장이어야 함, got {len(answers)}"
    assert answers[0]["data"]["actType"] == "WRAP"
    assert events[-1]["event"] == "all_complete"
    assert "구조화된 정리 본문" in answers[0]["data"]["answer"]


def test_summary_request_without_history_does_not_shortcircuit(monkeypatch):
    # 직전 대화가 없으면 정리 단독 분기로 빠지지 않고 일반 경로(여러 답변)로 간다.
    monkeypatch.setenv("STUDYMATE_DISCUSSION_SEED", "5")
    req = MultiChatRequest(message="요약 좀", agents=_agents())
    events = list(orch.build_orchestrator_stream(req, _agents()))
    answers = [e for e in events if e["event"] == "agent_answer"]
    assert len(answers) >= 3


def test_summary_detector():
    mk = lambda m: MultiChatRequest(message=m, agents=_agents())
    assert orch._summary_requested(mk("정리해줘"))
    assert orch._summary_requested(mk("3줄 요약 부탁"))
    assert orch._summary_requested(mk("핵심만 알려줘"))
    assert not orch._summary_requested(mk("SQL JOIN이 뭐야?"))
