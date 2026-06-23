"""A3: '더 자세히/더 깊이' 후속발화가 풀답변(심화) 경로로 가는지 검증."""
import pytest

from app.schemas.multi_chat_schema import AgentProfile, MultiChatRequest, PreviousAnswer
from app.services import orchestrator_service as orch
from app.services import dialogue_act_classifier as dac


def _ctx():
    return dac.build_previous_context(
        [PreviousAnswer(agentName="전문봇", answer="JOIN은 두 테이블을 공통 키로 결합한다.", role="ASSISTANT")],
        mode="basic",
    )


@pytest.mark.parametrize("msg", ["더 자세히 설명해줘", "더 깊이 알려줘", "구체적으로 설명해줘", "자세하게 설명 부탁"])
def test_deepen_is_full_depth(msg):
    d = dac.classify_deterministic(msg, previous_context=_ctx(), mode="basic")
    assert d.act == dac.FOLLOWUP_DEEPEN, f"{msg} → {d.act}"
    assert d.answer_depth == "full"
    assert d.is_new_question is True  # 풀답변 경로 게이트 통과


def test_simplify_still_short():
    d = dac.classify_deterministic("더 쉽게 설명해줘", previous_context=_ctx(), mode="basic")
    assert d.act == dac.FOLLOWUP_SIMPLIFY
    assert d.answer_depth == "short"


def test_deepen_reaches_discussion_not_contextual_turn(monkeypatch):
    # 스트림에서 '더 자세히'가 1~2문장 contextual turn이 아니라 풀 토론(다중 답변)으로 간다.
    monkeypatch.setattr(orch, "_build_knowledge_context", lambda q: "")
    monkeypatch.setattr(orch, "_fetch_wikipedia_context", lambda q: "")
    monkeypatch.setattr("app.services.ollama_client.ask_ollama", lambda **k: "심화 설명 본문")
    monkeypatch.setattr(orch, "_min_gap_seconds", lambda: 0.0)
    monkeypatch.setenv("STUDYMATE_DISCUSSION_SEED", "5")

    agents = [
        AgentProfile(id=1, agentId="a1", name="전문봇", personality="전문적", knowledgeLevel="학사"),
        AgentProfile(id=2, agentId="a2", name="냉소봇", personality="냉소적", knowledgeLevel="학사"),
        AgentProfile(id=3, agentId="a3", name="친근봇", personality="친근함", knowledgeLevel="학사"),
    ]
    prev = [PreviousAnswer(agentName="전문봇", answer="JOIN은 두 테이블을 결합한다.", role="ASSISTANT")]
    req = MultiChatRequest(message="더 자세히 설명해줘", agents=agents, previousAnswers=prev,
                           mode="basic", learningMode="basic")
    events = list(orch.build_orchestrator_stream(req, agents))
    answers = [e for e in events if e["event"] == "agent_answer"]
    assert len(answers) >= 3, f"심화는 풀답변(다중)이어야 함, got {len(answers)}"
