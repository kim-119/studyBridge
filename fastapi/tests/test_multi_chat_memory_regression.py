"""멀티챗 SSE 레벨 memory recall 회귀 테스트 (스펙 케이스 10~12).

회상 경로는 LLM(Ollama)을 호출하지 않으므로 외부 의존 없이 결정론적으로 검증된다.
NORMAL("TCP가 뭐야")은 우회하지 않음을 분류 레벨에서 확인한다(LLM 미호출 보장).
"""
from app.schemas.multi_chat_schema import AgentProfile, MultiChatRequest, PreviousAnswer
from app.services.memory_recall_service import MemoryIntent, classify_memory_intent, is_recall_intent
from app.services.orchestrator_service import build_orchestrator_stream


def _prev(role, answer, name="AI"):
    return PreviousAnswer(agentName=name, answer=answer, role=role)


def _agent(name):
    return AgentProfile(name=name, personality="friendly", knowledgeLevel="학사")


def _events(req):
    return list(build_orchestrator_stream(req, req.agents))


def test_socratic_recall_no_diagnosis_prefix():
    # 케이스 10: socratic 모드여도 memory recall 답변은 "진단:"으로 시작하지 않는다.
    req = MultiChatRequest(
        message="내가 처음 뭐라고 질문했어?",
        mode="socratic", learningMode="socratic",
        previousAnswers=[
            _prev("USER", "TCP가 뭐야", "사용자"),
            _prev("ASSISTANT", "TCP는 연결 지향 프로토콜입니다", "김교수"),
        ],
        agents=[_agent("김교수")],
    )
    events = _events(req)
    answers = [e for e in events if e["event"] == "agent_answer"]
    assert len(answers) == 1
    text = answers[0]["data"]["answer"]
    assert not text.strip().startswith("진단:")
    assert "처음 질문은 다음이었어" in text
    assert "TCP가 뭐야" in text
    assert answers[0]["data"]["memoryAnswer"] is True
    assert answers[0]["data"]["memoryIntent"] == MemoryIntent.EXACT_FIRST_MESSAGE.value


def test_normal_question_not_bypassed_to_recall():
    # 케이스 11: "TCP가 뭐야"는 NORMAL → memory recall 우회 대상이 아니다(LLM 경로).
    intent, _ = classify_memory_intent("TCP가 뭐야")
    assert intent == MemoryIntent.NORMAL
    assert is_recall_intent(intent) is False


def test_three_agents_recall_single_answer():
    # 케이스 12: selectedAgents 3명이어도 회상 답변은 1개만(중복 3개 금지).
    req = MultiChatRequest(
        message="방금 내가 뭐 물어봤지?",
        mode="basic", learningMode="basic",
        previousAnswers=[
            _prev("USER", "소켓이 뭐야", "사용자"),
            _prev("ASSISTANT", "소켓은 ...", "김교수"),
            _prev("USER", "UDP가 뭐야", "사용자"),
        ],
        agents=[_agent("김교수"), _agent("이교수"), _agent("박교수")],
    )
    events = _events(req)
    answers = [e for e in events if e["event"] == "agent_answer"]
    assert len(answers) == 1
    assert "UDP가 뭐야" in answers[0]["data"]["answer"]
    completes = [e for e in events if e["event"] == "all_complete"]
    assert len(completes) == 1
    assert len(completes[0]["data"]["answers"]) == 1


def test_topic_recall_sse():
    req = MultiChatRequest(
        message="내가 TCP에 대해 질문한 것 같은데?",
        mode="basic", learningMode="basic",
        previousAnswers=[
            _prev("USER", "TCP가 뭐야", "사용자"),
            _prev("USER", "TCP 혼잡제어 알려줘", "사용자"),
            _prev("USER", "파이썬 리스트 컴프리헨션", "사용자"),
        ],
        agents=[_agent("김교수")],
    )
    answers = [e for e in _events(req) if e["event"] == "agent_answer"]
    assert len(answers) == 1
    text = answers[0]["data"]["answer"]
    assert "TCP가 뭐야" in text and "TCP 혼잡제어 알려줘" in text
    assert "파이썬" not in text
