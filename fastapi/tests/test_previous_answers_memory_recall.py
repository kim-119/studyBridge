"""previousAnswers 정규화 + 결정론적 회상 답변 테스트 (스펙 케이스 7~9)."""
from app.schemas.multi_chat_schema import PreviousAnswer
from app.services.memory_recall_service import (
    MemoryIntent,
    build_recall_answer,
    normalize_previous_answers,
)


def _prev(role, answer, name="AI"):
    return PreviousAnswer(agentName=name, answer=answer, role=role)


def test_normalize_pydantic_objects():
    prev = [
        _prev("USER", "모두 유사 개념 또는 대안과 비교해 주세요", "사용자"),
        _prev("ASSISTANT", "TCP는 연결 지향 프로토콜입니다", "김교수"),
        _prev("USER", "TCP가 뭐야", "사용자"),
    ]
    turns = normalize_previous_answers(prev)
    assert [t.role for t in turns] == ["user", "assistant", "user"]
    assert turns[0].content == "모두 유사 개념 또는 대안과 비교해 주세요"


def test_normalize_dict_and_string_and_qa():
    raw = [
        {"role": "user", "content": "첫 질문"},
        {"role": "assistant", "answer": ""},          # 빈 assistant → 제외
        "Q: 두번째 질문 A: 그에 대한 답",
        "그냥 문자열",
    ]
    turns = normalize_previous_answers(raw)
    contents = [(t.role, t.content) for t in turns]
    assert ("user", "첫 질문") in contents
    assert ("user", "두번째 질문") in contents
    assert ("assistant", "그에 대한 답") in contents
    assert all(t.content for t in turns)  # 빈 콘텐츠 없음


def test_skips_error_traces():
    raw = [
        _prev("ASSISTANT", "(응답을 생성하지 못했어요. 잠시 후 다시 시도해 주세요.)"),
        _prev("USER", "정상 질문"),
    ]
    turns = normalize_previous_answers(raw)
    assert [t.content for t in turns] == ["정상 질문"]


def test_exact_first_returns_verbatim():
    # 케이스 7: 첫 user 질문 원문을 그대로 반환
    prev = [
        _prev("USER", "모두 유사 개념 또는 대안과 비교해 주세요", "사용자"),
        _prev("ASSISTANT", "네, 비교하겠습니다", "김교수"),
        _prev("USER", "TCP가 뭐야", "사용자"),
    ]
    turns = normalize_previous_answers(prev)
    res = build_recall_answer(MemoryIntent.EXACT_FIRST_MESSAGE, {}, turns)
    assert "모두 유사 개념 또는 대안과 비교해 주세요" in res.text
    assert res.text.startswith("처음 질문은 다음이었어")
    assert res.matched_count == 1


def test_last_and_nth():
    prev = [
        _prev("USER", "첫째 질문", "사용자"),
        _prev("USER", "둘째 질문", "사용자"),
        _prev("USER", "셋째 질문", "사용자"),
    ]
    turns = normalize_previous_answers(prev)
    assert "셋째 질문" in build_recall_answer(MemoryIntent.EXACT_LAST_MESSAGE, {}, turns).text
    assert "둘째 질문" in build_recall_answer(MemoryIntent.EXACT_NTH_MESSAGE, {"n": 2}, turns).text


def test_topic_recall_lists_matches():
    # 케이스 8: TCP 포함 user 질문 목록 반환
    prev = [
        _prev("USER", "TCP가 뭐야", "사용자"),
        _prev("ASSISTANT", "...", "김교수"),
        _prev("USER", "TCP와 UDP 비교해줘", "사용자"),
        _prev("USER", "파이썬 데코레이터 설명", "사용자"),
    ]
    turns = normalize_previous_answers(prev)
    res = build_recall_answer(MemoryIntent.TOPIC_RECALL, {"topic": "TCP"}, turns)
    assert "TCP가 뭐야" in res.text
    assert "TCP와 UDP 비교해줘" in res.text
    assert "파이썬" not in res.text
    assert res.matched_count == 2


def test_not_found_does_not_fabricate():
    # 케이스 9: previousAnswers에 user 질문이 없으면 지어내지 않고 "찾지 못했다"
    prev = [_prev("ASSISTANT", "AI 답변만 있음", "김교수")]
    turns = normalize_previous_answers(prev)
    res = build_recall_answer(MemoryIntent.EXACT_FIRST_MESSAGE, {}, turns)
    assert "찾지 못했" in res.text
    assert res.matched_count == 0

    res2 = build_recall_answer(MemoryIntent.TOPIC_RECALL, {"topic": "TCP"}, normalize_previous_answers([_prev("USER", "자바 질문")]))
    assert "찾지 못했" in res2.text
