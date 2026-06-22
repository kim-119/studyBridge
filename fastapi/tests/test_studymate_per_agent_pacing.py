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
    ("솔직함", "직설적"),
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


def test_single_agent_prompt_hides_peer_names(monkeypatch):
    # 다른 메이트 안내는 있되, 이름은 노출하지 않는다(모델이 'X:' 머리표로 호명하는 것 방지).
    agents = _agents()  # [전문봇, 냉소봇]
    sys = orch._build_single_agent_system_prompt(agents[1], "basic", agents)
    assert "다른 메이트" in sys          # peers 안내 존재
    assert "전문봇" not in sys           # 다른 에이전트 이름은 미노출
    assert "머리표" in sys               # 'OOO:' 머리표 금지 지시 존재


def test_position_roles_differ():
    # 위치별 역할 분담: 1번=설명, 중간=심화, 마지막=검증 (같은 비판 반복 방지)
    assert "첫 설명자" in orch._position_role(0, 3)
    assert "심화" in orch._position_role(1, 3)
    assert "검증" in orch._position_role(2, 3)
    assert orch._position_role(0, 1) == ""  # 단독이면 역할 분담 없음


def test_first_agent_does_not_critique():
    # 첫 설명자는 (깔 앞 답변이 없으므로) 비판/반박하지 않고 설명만 한다.
    agents = _agents()
    sp = orch._build_single_agent_system_prompt(agents[0], "basic", agents, position=0, total=3)
    assert "비판·반박하지 말고" in sp


def test_socratic_mode_is_question_driven_not_explanation():
    # 소크라테스: 질문/힌트 위주 + '설명·정의·요약 금지'가 박혀야 하고, basic 프레이밍/설명지침이 없어야 한다.
    a = AgentProfile(id=1, agentId="a1", name="X", personality="효율적",
                     customInstruction="개념을 구조적으로 설명해줘.")
    soc = orch._build_single_agent_system_prompt(a, "socratic", [a], position=0, total=3)
    assert "단계별 힌트" in soc and "나열 금지" in soc   # 질문/힌트 주도 + 설명 금지
    assert "첫 설명자" not in soc                        # basic 역할분담 미적용
    assert "구조적으로 설명" not in soc                  # customInstruction의 '설명' 지침이 모드를 덮지 않음
    bas = orch._build_single_agent_system_prompt(a, "basic", [a], position=0, total=3)
    assert "첫 설명자" in bas                            # basic엔 적용


def test_persona_custom_instruction_shapes_format():
    # 사용자 지침(페르소나 정의)이 답변 형식 지시로 프롬프트에 반영돼야 한다(성격 톤은 별개 유지).
    a = AgentProfile(id=1, agentId="a1", name="X", personality="효율적",
                     customInstruction="개념 정의, 핵심 원리, 예시, 주의점을 구조적으로 설명해줘.")
    sp = orch._build_single_agent_system_prompt(a, "basic", [a], position=0, total=1)
    assert "사용자 지침" in sp and "구조적으로 설명" in sp


def test_feedback_round_flag(monkeypatch):
    monkeypatch.setattr("app.services.ollama_client.ask_ollama", lambda **k: "피드백 답")
    monkeypatch.setattr(orch, "_min_gap_seconds", lambda: 0.0)
    req = MultiChatRequest(message="gRPC가 뭐고 왜 쓰나 설명해줘", mode="basic", learningMode="basic", agents=_agents())

    monkeypatch.setenv("STUDYMATE_FEEDBACK_ROUND", "off")
    off = [e for e in orch.build_orchestrator_stream(req, _agents())
           if e["event"] == "agent_answer" and e["data"].get("phase") == "FEEDBACK"]
    monkeypatch.setenv("STUDYMATE_FEEDBACK_ROUND", "on")
    on = [e for e in orch.build_orchestrator_stream(req, _agents())
          if e["event"] == "agent_answer" and e["data"].get("phase") == "FEEDBACK"]
    assert len(off) == 0 and len(on) == 2  # 플래그 off=라운드2 없음, on=에이전트당 1개


def test_socratic_self_explanation_only_on_last_agent():
    # '네 말로 설명해볼래?' 자기설명 마무리는 마지막 에이전트만. 앞 에이전트는 중복 금지.
    a3 = [AgentProfile(id=i, agentId=f"a{i}", name=f"A{i}", personality="친근함") for i in range(3)]
    last = orch._build_single_agent_system_prompt(a3[2], "socratic", a3, position=2, total=3)
    first = orch._build_single_agent_system_prompt(a3[0], "socratic", a3, position=0, total=3)
    assert "네 말로 설명" in last          # 마지막 에이전트는 자기설명 유도
    assert "네 말로 설명" not in first      # 앞 에이전트는 그 문구 금지(중복 방지)
    assert "힌트" in first                  # 그래도 힌트/질문은 함


def test_debate_defines_topic_and_splits_sides():
    agents = [AgentProfile(id=i, agentId=f"a{i}", name=f"A{i}", personality="논리형") for i in range(3)]
    d0 = orch._build_single_agent_system_prompt(agents[0], "debate", agents, position=0, total=3)
    d1 = orch._build_single_agent_system_prompt(agents[1], "debate", agents, position=1, total=3)
    d2 = orch._build_single_agent_system_prompt(agents[2], "debate", agents, position=2, total=3)
    assert "논제" in d0 and "찬성" in d0     # 첫 에이전트가 논제 정의 + 찬성
    assert "반대" in d1                       # 둘째 반대
    assert "중립" in d2                       # 셋째 중립/정리


def test_social_input_gets_light_prompt():
    # 인사/잡담이면 공격적 비판 대신 가볍게 받는 프롬프트가 나와야 한다.
    agents = _agents()
    sp = orch._build_single_agent_system_prompt(agents[1], "basic", agents, social=True)
    assert "인사/잡담" in sp and "가볍게" in sp


def test_question_prompt_forbids_mockery():
    # 질문(비-social) 프롬프트엔 사실기반·조롱금지 규칙이 들어가야 한다.
    agents = _agents()
    sp = orch._build_single_agent_system_prompt(agents[1], "basic", agents, social=False)
    assert "조롱" in sp and "근거" in sp


@pytest.mark.parametrize("front_key,expected", [
    ("cynical", "냉소적"),
    ("honest", "비판적_분석형"),
    ("efficient", "간결_요약형"),
    ("unique", "창의적_확장형"),
    ("professional", "전문적"),
    ("friendly", "친절_설명형"),
])
def test_frontend_english_keys_map(front_key, expected):
    # 프론트(personality.js) 영문 키가 백엔드 성격 타입으로 정확히 매핑돼야 한다(친절형 폴백 금지).
    from app.services.personality_prompt_builder import normalize_personality
    assert normalize_personality(front_key).value == expected


def test_core_directive_overrides_custom_instruction():
    # 프리셋 customInstruction(공손)이 와도 6종 성격이 이긴다(공손 지침이 그대로 노출되면 안 됨).
    from app.services.personality_prompt_builder import build_personality_prompt, normalize_personality, PersonalityType
    sp = build_personality_prompt("냉소적", custom_instruction="아주 공손하고 친절한 존댓말로만 설명하세요")
    assert "공손" not in sp
    assert normalize_personality("냉소적") == PersonalityType.SARDONIC


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


def test_peer_answers_injected_without_forced_naming():
    # 앞 답변 내용은 주입하되, 닉네임 호명을 강제하지 않고 내용(논점) 중심으로 이어가게 한다.
    a = _agents()[1]
    peers = [{"agentName": "전문봇", "answer": "객체지향은 캡슐화·상속·다형성이 핵심이다."}]
    up = orch._build_single_agent_user_prompt(a, _req("객체지향이 뭐야?"), "", "", peers)
    assert "캡슐화" in up                      # 앞 내용은 주입됨(중복 방지용)
    assert "이름" in up and "내용 중심" in up    # 이름 호명 자제 + 내용 중심 지시
    assert "전문봇" not in up                   # 닉네임을 프롬프트에 박아 호명을 유도하지 않음
