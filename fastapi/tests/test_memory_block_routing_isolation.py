"""
Redis 대화기억이 기본(basic) 모드 라우팅을 오염시키지 않는지 검증한다.

계약:
    current user input
        ├─ routing / intent / summary / social / dialogue-act 판정   ← 기억 금지
        └─ memory 와 합쳐져 최종 LLM generation context 로 사용       ← 기억 허용

즉 Memory 는 '생성 컨텍스트'이지 'Router 의 현재 의도 입력값'이 아니다.

증상(2026-09-11 라이브): 과거 대화에 '정리'/교수 이름이 있으면 현재 질문이
summary-only(WRAP) 경로로 새고, 교수 1명만 실제 실행된 뒤 나머지 슬롯을
compat 가 "{agentName} 관점에서 핵심을 정리하면…" 필러로 합성했다.
"""
import pytest

from app.schemas.multi_chat_schema import AgentProfile, MultiChatRequest, PreviousAnswer
from app.services import orchestrator_service as orch


MEMORY_HEAD = (
    "[이전 대화 기억]\n"
    "아래 내용은 같은 방/세션의 최근 대화 맥락이다. 현재 질문에 필요한 경우에만 반영하고, 불필요하면 무시한다.\n"
)


def _augment(memory_lines: str, current: str) -> str:
    """multi_chat_redis_memory.attach_memory_to_request 가 만드는 형태 그대로."""
    return f"{MEMORY_HEAD}{memory_lines}\n\n[현재 질문]\n{current}"


@pytest.fixture(autouse=True)
def _no_net(monkeypatch):
    monkeypatch.setattr(orch, "_build_knowledge_context", lambda q: "")
    monkeypatch.setattr(orch, "_fetch_wikipedia_context", lambda q: "")
    monkeypatch.setattr("app.services.ollama_client.ask_ollama", lambda **k: "결정론 스텁 본문")
    monkeypatch.setattr(orch, "_min_gap_seconds", lambda: 0.0)
    monkeypatch.setenv("STUDYMATE_DISCUSSION_SEED", "5")
    monkeypatch.setenv("DIALOGUE_ACT_USE_LLM", "0")


def _agents():
    return [
        AgentProfile(id=1, agentId="a1", name="김교수", personality="전문적", knowledgeLevel="학사"),
        AgentProfile(id=2, agentId="a2", name="이교수", personality="냉소적", knowledgeLevel="학사"),
        AgentProfile(id=3, agentId="a3", name="박교수", personality="친근함", knowledgeLevel="학사"),
    ]


def _prev():
    return [
        PreviousAnswer(agentName="김교수", answer="지금까지 내용을 정리하면 매핑은 계층 간 변환이다.", role="ASSISTANT"),
        PreviousAnswer(agentName="이교수", answer="ORM 매핑은 스키마와 객체를 잇는다.", role="ASSISTANT"),
    ]


# ── canonical current message 헬퍼 ────────────────────────────────────────────

def test_current_user_message_strips_memory_block():
    req = MultiChatRequest(
        message=_augment("- user: 지금까지 내용 정리해줘", "TCP가 뭐야?"), agents=_agents())
    assert orch.current_user_message(req) == "TCP가 뭐야?"


def test_current_user_message_passthrough_without_memory():
    req = MultiChatRequest(message="TCP가 뭐야?", agents=_agents())
    assert orch.current_user_message(req) == "TCP가 뭐야?"


# ── gate 1: summary ──────────────────────────────────────────────────────────

def test_summary_word_in_memory_does_not_trigger_summary_route():
    """과거 대화에 '정리'가 있어도 현재 질문이 정리 요청이 아니면 WRAP 로 가면 안 된다."""
    req = MultiChatRequest(
        message=_augment(
            "- user: 지금까지 내용 정리해줘\n- assistant: 핵심만 요약하면 …",
            "FastAPI나 Spring에서 mapping이 중요한 이유가 뭐야?",
        ),
        agents=_agents(),
        previousAnswers=_prev(),
    )
    assert orch._summary_requested(req) is False


def test_explicit_summary_request_still_routes_to_summary():
    """현재 질문 자체가 정리 요청이면 기억 블록이 붙어 있어도 summary route 로 간다."""
    req = MultiChatRequest(
        message=_augment("- user: mapping이 뭐야?", "지금까지 내용 정리해줘"),
        agents=_agents(),
        previousAnswers=_prev(),
    )
    assert orch._summary_requested(req) is True

    events = list(orch.build_orchestrator_stream(req, _agents()))
    complete = [e for e in events if e["event"] == "all_complete"]
    assert len(complete) == 1
    assert complete[0]["data"]["route"] == "summary_only"
    assert complete[0]["data"]["suppressAgentFill"] is True


def test_memory_polluted_question_runs_full_multi_agent():
    """기억에 '정리'가 있는 상태의 새 질문은 교수 전원이 실제로 답해야 한다."""
    req = MultiChatRequest(
        message=_augment(
            "- user: 지금까지 내용 정리해줘\n- assistant: 김교수가 핵심만 요약했다.",
            "FastAPI나 Spring에서 mapping이 중요한 이유가 뭐야?",
        ),
        agents=_agents(),
        previousAnswers=_prev(),
    )
    events = list(orch.build_orchestrator_stream(req, _agents()))
    answers = [e for e in events if e["event"] == "agent_answer"]
    complete = [e for e in events if e["event"] == "all_complete"][0]["data"]

    assert complete["route"] != "summary_only", "기억의 '정리' 때문에 WRAP 로 샜다"
    speakers = {a["data"]["agentId"] for a in answers}
    assert speakers == {"a1", "a2", "a3"}, f"교수 전원이 답하지 않음: {speakers}"
    assert complete["suppressAgentFill"] is False


# ── gate 2: social ───────────────────────────────────────────────────────────

def test_professor_name_in_memory_does_not_make_input_social():
    """기억 속 교수 이름/인사말이 현재 학습 질문을 사회적 입력으로 만들면 안 된다."""
    req = MultiChatRequest(
        message=_augment(
            "- user: 안녕하세요 저는 학생이에요\n- assistant: 반가워요! 김교수입니다.",
            "FastAPI나 Spring에서 mapping이 중요한 이유가 뭐야?",
        ),
        agents=_agents(),
        previousAnswers=_prev(),
    )
    assert orch._is_social_input(req) is False


def test_social_input_still_detected_without_memory():
    req = MultiChatRequest(message="안녕하세요", agents=_agents())
    assert orch._is_social_input(req) is True


# ── gate 3: dialogue act ─────────────────────────────────────────────────────

def test_dialogue_act_uses_current_message_only(monkeypatch):
    """classify_dialogue_act 에 넘어가는 문자열에 기억 블록이 없어야 한다."""
    seen = {}

    from app.services import dialogue_act_classifier as dac
    real = dac.classify_dialogue_act

    def _spy(message, **kwargs):
        seen["message"] = message
        return real(message, **kwargs)

    monkeypatch.setattr(dac, "classify_dialogue_act", _spy)

    req = MultiChatRequest(
        message=_augment(
            "- user: 지금까지 내용 정리해줘\n- assistant: 김교수가 정리했다.",
            "FastAPI나 Spring에서 mapping이 중요한 이유가 뭐야?",
        ),
        agents=_agents(),
        previousAnswers=_prev(),
    )
    list(orch.build_orchestrator_stream(req, _agents()))

    assert "message" in seen, "dialogue-act 게이트가 호출되지 않음"
    assert seen["message"] == "FastAPI나 Spring에서 mapping이 중요한 이유가 뭐야?"
    assert "[이전 대화 기억]" not in seen["message"]


def test_generation_context_still_receives_memory(monkeypatch):
    """Router 에서는 기억을 벗기지만, 생성 프롬프트에는 기억이 그대로 들어가야 한다."""
    captured = {}

    def _fake_ask(**kwargs):
        captured.setdefault("user_prompt", kwargs.get("user_prompt", ""))
        return "결정론 스텁 본문"

    monkeypatch.setattr("app.services.ollama_client.ask_ollama", _fake_ask)

    req = MultiChatRequest(
        message=_augment("- user: mapping이 뭐야?", "그럼 ORM은?"),
        agents=_agents()[:1],
    )
    list(orch.build_orchestrator_stream(req, _agents()[:1]))
    assert "[이전 대화 기억]" in captured["user_prompt"], "생성 컨텍스트에서 기억이 사라졌다"
