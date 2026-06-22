"""StudyMate 멀티에이전트 per-agent 페이싱 + 성격 강화 검증.

- 성격 6종 coreDirective(사용자 verbatim 지시문)가 프롬프트에 주입되는지
- 스트림이 per-agent 순차로 (turn_start → agent_start/agent_answer ×N → all_complete) 나오는지
- 답변 사이 최소 간격(MIN_GAP)이 보장되는지
- 빈 LLM 응답이 가드되는지
"""
import time

import pytest

from app.schemas.multi_chat_schema import AgentProfile, MultiChatRequest
from app.services import orchestrator_service as orch
from app.services.personality_prompt_builder import build_personality_prompt


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    # 위키백과 호출(네트워크/타임아웃) 차단.
    monkeypatch.setattr(orch, "_fetch_wikipedia_context", lambda q: "")


def _agents():
    return [
        AgentProfile(id=1, agentId="a1", name="전문봇", personality="전문적", knowledgeLevel="학사"),
        AgentProfile(id=2, agentId="a2", name="냉소봇", personality="냉소적", knowledgeLevel="학사"),
    ]


@pytest.mark.parametrize("label,keyword", [
    ("전문적", "전제-근거-결론"),
    ("친근함", "유치원 선생님"),
    ("솔직함", "팩트 폭력"),
    ("독특함", "4차원"),
    ("효율적", "개조식"),
    ("냉소적", "비꼬는"),
])
def test_personality_core_directive_injected(label, keyword):
    """프론트 6종 라벨 → 사용자 verbatim coreDirective가 시스템 프롬프트에 들어간다."""
    prompt = build_personality_prompt(label)
    assert keyword in prompt, f"{label} 프롬프트에 '{keyword}'가 없음:\n{prompt}"


def test_stream_event_order_and_counts(monkeypatch):
    monkeypatch.setattr("app.services.ollama_client.ask_ollama", lambda **k: "테스트 답변")
    monkeypatch.setattr(orch, "_min_gap_seconds", lambda: 0.0)

    req = MultiChatRequest(message="SQL JOIN이 뭐야?", agents=_agents())
    events = list(orch.build_orchestrator_stream(req, _agents()))
    kinds = [e["event"] for e in events]

    assert kinds[0] == "turn_start"
    assert kinds[-1] == "all_complete"
    assert kinds.count("agent_answer") == 2
    assert kinds.count("agent_start") == 2
    assert kinds.count("all_complete") == 1
    assert len(events[-1]["data"]["answers"]) == 2


def test_stream_min_gap_enforced(monkeypatch):
    # 생성을 즉시 반환시키고 MIN_GAP만으로 간격이 보장되는지 본다.
    monkeypatch.setattr("app.services.ollama_client.ask_ollama", lambda **k: "즉답")
    monkeypatch.setattr(orch, "_min_gap_seconds", lambda: 0.3)

    req = MultiChatRequest(message="질문", agents=_agents())
    answer_times = [
        time.monotonic()
        for e in orch.build_orchestrator_stream(req, _agents())
        if e["event"] == "agent_answer"
    ]

    assert len(answer_times) == 2
    assert answer_times[1] - answer_times[0] >= 0.3 - 0.05  # 측정 오차 허용


def test_last_agent_has_no_trailing_sleep(monkeypatch):
    # 마지막 에이전트 뒤에는 대기하지 않는다 → 전체 시간이 (n-1)*gap 근방.
    monkeypatch.setattr("app.services.ollama_client.ask_ollama", lambda **k: "즉답")
    monkeypatch.setattr(orch, "_min_gap_seconds", lambda: 0.3)

    req = MultiChatRequest(message="질문", agents=_agents())
    t0 = time.monotonic()
    list(orch.build_orchestrator_stream(req, _agents()))
    elapsed = time.monotonic() - t0
    # 에이전트 2명 → 간격 1회(0.3s)만. 1회분 미만의 여유로 마지막 sleep 없음을 확인.
    assert elapsed < 0.3 * 2


def test_blank_llm_guarded(monkeypatch):
    monkeypatch.setattr("app.services.ollama_client.ask_ollama", lambda **k: "")
    monkeypatch.setattr(orch, "_min_gap_seconds", lambda: 0.0)

    one = [_agents()[0]]
    req = MultiChatRequest(message="질문", agents=one)
    out = orch.run_orchestrator(req, one)
    assert out.answers[0].answer.strip(), "빈 응답이 그대로 노출됨"


def test_single_agent_prompt_contains_personality_and_question(monkeypatch):
    agents = _agents()
    sys = orch._build_single_agent_system_prompt(agents[1], "basic", agents)
    # 냉소봇 → 냉소적 coreDirective + 다른 메이트 안내
    assert "비꼬는" in sys
    assert "전문봇" in sys  # peers 안내에 다른 에이전트 이름


def test_basic_mode_is_free_conversation():
    d = orch._mode_role_directive("basic")
    assert "자유 대화" in d and "가르치려 들지 마라" in d


@pytest.mark.parametrize("front_key,keyword", [
    ("cynical", "비꼬는"),     # 냉소적
    ("honest", "팩트 폭력"),   # 솔직함
    ("efficient", "개조식"),   # 효율적
    ("unique", "4차원"),       # 독특함
    ("professional", "전제-근거-결론"),
    ("friendly", "유치원 선생님"),
])
def test_frontend_english_keys_map_to_core_directive(front_key, keyword):
    # 프론트(personality.js)가 보내는 영문 키가 백엔드 coreDirective로 정확히 매핑돼야 한다.
    from app.services.personality_prompt_builder import build_personality_prompt
    assert keyword in build_personality_prompt(front_key)


def test_core_directive_overrides_custom_instruction():
    # 프리셋 customInstruction이 공손하게 시켜도 6종 coreDirective가 무조건 이긴다.
    from app.services.personality_prompt_builder import build_personality_prompt, build_persona_directive
    polite = "아주 공손하고 친절한 존댓말로만 설명하세요"
    sp = build_personality_prompt("냉소적", custom_instruction=polite)
    pd = build_persona_directive("냉소적", custom_instruction=polite)
    assert "비꼬는" in sp and "공손" not in sp
    assert "비꼬는" in pd and "반말로 답한다" in pd and "공손" not in pd


def _req(msg):
    return MultiChatRequest(message=msg, mode="basic", learningMode="basic", agents=_agents())


def test_cross_feedback_single_agent_off():
    one = [_agents()[0]]
    assert orch._cross_feedback_enabled(MultiChatRequest(message="객체지향이 뭐고 왜 쓰는지 설명해줘", agents=one), one) is False


def test_cross_feedback_env_off(monkeypatch):
    monkeypatch.setenv("STUDYMATE_CROSS_FEEDBACK", "off")
    assert orch._cross_feedback_enabled(_req("객체지향이 뭐고 왜 쓰는지 설명해줘"), _agents()) is False


def test_cross_feedback_env_on_ignores_casual(monkeypatch):
    monkeypatch.setenv("STUDYMATE_CROSS_FEEDBACK", "on")
    assert orch._cross_feedback_enabled(_req("안녕"), _agents()) is True  # on이면 잡담이어도 켬


def test_cross_feedback_auto_uses_router(monkeypatch):
    # 키워드 하드코딩이 아니라 guardrail 라우터로 잡담/질문을 가린다.
    monkeypatch.setenv("STUDYMATE_CROSS_FEEDBACK", "auto")
    assert orch._cross_feedback_enabled(_req("gRPC랑 REST 차이가 뭐야?"), _agents()) is True
    assert orch._cross_feedback_enabled(_req("안녕"), _agents()) is False  # 인사 → 끔


def test_peer_answers_injected_in_user_prompt():
    a = _agents()[1]
    peers = [{"agentName": "전문봇", "answer": "객체지향은 캡슐화·상속·다형성이 핵심이다."}]
    up = orch._build_single_agent_user_prompt(a, _req("객체지향이 뭐야?"), "", "", peers)
    assert "먼저 답한 메이트들" in up and "전문봇" in up and "캡슐화" in up
