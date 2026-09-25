"""MemoryIntent 분류기 회귀 테스트 (스펙 케이스 1~6)."""
from app.services.memory_recall_service import (
    MemoryIntent,
    classify_memory_intent,
    is_recall_intent,
)


def test_first_message_variants():
    for msg in ["내가 처음 뭐라고 질문했어?", "맨 처음 내가 한 질문 뭐였어?", "첫 질문 알려줘"]:
        intent, _ = classify_memory_intent(msg)
        assert intent == MemoryIntent.EXACT_FIRST_MESSAGE, msg
        assert is_recall_intent(intent)


def test_first_chat_phrase():
    intent, _ = classify_memory_intent("첫 채팅 뭐야?")
    assert intent == MemoryIntent.EXACT_FIRST_MESSAGE


def test_last_message():
    for msg in ["방금 내가 뭐 물어봤지?", "마지막 질문 뭐였어?", "직전에 내가 뭐라고 했지?"]:
        intent, _ = classify_memory_intent(msg)
        assert intent == MemoryIntent.EXACT_LAST_MESSAGE, msg


def test_nth_message():
    intent, extra = classify_memory_intent("내 두 번째 질문 뭐였어?")
    assert intent == MemoryIntent.EXACT_NTH_MESSAGE
    assert extra["n"] == 2
    intent, extra = classify_memory_intent("3번째 질문 알려줘")
    assert intent == MemoryIntent.EXACT_NTH_MESSAGE
    assert extra["n"] == 3


def test_topic_recall():
    intent, extra = classify_memory_intent("내가 TCP에 대해 질문한 것 같은데?")
    assert intent == MemoryIntent.TOPIC_RECALL
    assert extra["topic"] == "TCP"
    intent, extra = classify_memory_intent("UDP 관련해서 뭐 물어봤어?")
    assert intent == MemoryIntent.TOPIC_RECALL
    assert extra["topic"] == "UDP"


def test_normal_concept_questions_not_recall():
    for msg in ["TCP가 뭐야", "UDP가 뭐야", "소켓이 뭐야", "WebSocket 설명해줘"]:
        intent, _ = classify_memory_intent(msg)
        assert intent == MemoryIntent.NORMAL, msg
        assert not is_recall_intent(intent)


def test_topic_explain_request_is_normal():
    # 설명 요청(회상어 없음)은 주제어가 있어도 NORMAL이어야 한다.
    intent, _ = classify_memory_intent("TCP에 대해 알려줘")
    assert intent == MemoryIntent.NORMAL


def test_contextual_followup():
    for msg in ["그거 더 쉽게 설명해줘", "아까 말한 거 예시 들어줘", "위 내용 표로 정리해줘"]:
        intent, _ = classify_memory_intent(msg)
        assert intent == MemoryIntent.CONTEXTUAL_FOLLOWUP, msg
        assert not is_recall_intent(intent)
