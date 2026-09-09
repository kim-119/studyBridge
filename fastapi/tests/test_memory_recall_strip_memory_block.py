"""기억 블록([이전 대화 기억]…[현재 질문]…)이 주입된 message 는 원문만 분류해야 한다.
2026-09-09 ai07 라이브 회귀 재현: 이전 답변에 '처음/최근/마지막'이 있고 마커에 '질문'이 있어
모든 후속 질문이 EXACT 회상으로 오판돼 LLM 을 우회했다."""
from app.services.memory_recall_service import MemoryIntent, classify_memory_intent, strip_memory_block


def _augmented(question: str) -> str:
    return (
        "[이전 대화 기억]\n"
        "user: 자바의 인터페이스와 추상 클래스 차이를 설명해줘\n"
        "assistant: 이론교수: 처음에는 인터페이스가 낯설지만 최근에는 기본 메서드도 지원합니다.\n"
        "assistant: 이론교수: 마지막 질문은 다음이었어.\n"
        f"\n\n[현재 질문]\n{question}"
    )


def test_strip_memory_block_returns_original_question():
    assert strip_memory_block(_augmented("HTTP와 HTTPS의 차이는?")) == "HTTP와 HTTPS의 차이는?"
    assert strip_memory_block("  TCP가 뭐야 ") == "TCP가 뭐야"
    assert strip_memory_block(None) == ""


def test_plain_concept_question_with_memory_block_is_normal():
    for q in ("HTTP와 HTTPS의 차이를 두 문장으로 설명해줘", "자바 제네릭이 필요한 이유가 뭐야", "TCP 3-way handshake 과정을 설명해줘"):
        intent, _ = classify_memory_intent(_augmented(q))
        assert intent == MemoryIntent.NORMAL, q


def test_real_recall_still_detected_inside_memory_block():
    intent, _ = classify_memory_intent(_augmented("내가 마지막에 뭐라고 질문했어?"))
    assert intent == MemoryIntent.EXACT_LAST_MESSAGE
    intent, _ = classify_memory_intent(_augmented("처음 질문이 뭐였지?"))
    assert intent == MemoryIntent.EXACT_FIRST_MESSAGE


def test_without_memory_block_behaviour_unchanged():
    assert classify_memory_intent("TCP가 뭐야")[0] == MemoryIntent.NORMAL
    assert classify_memory_intent("방금 내가 뭐라고 물어봤지?")[0] == MemoryIntent.EXACT_LAST_MESSAGE
