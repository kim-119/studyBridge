"""Regression tests for realtime quiz answer/explanation consistency.

Root cause: _normalize_question overwrote `answer` with choices[0] whenever the
LLM-provided `answer` text wasn't an exact string match to a choice, silently
ignoring the (correct) `answer_index`. The explanation kept describing the real
answer -> answer/explanation mismatch shown to learners.
"""
from app.services.realtime_quiz_service import _normalize_question


def _norm(item):
    return _normalize_question(
        item,
        idx=1,
        difficulty="medium",
        fallback={},
        keywords=["문서", "핵심", "개념", "학습"],
    )


def test_answer_index_used_when_answer_text_not_exact_match():
    """LLM gives correct answer_index but slightly reworded answer text."""
    item = {
        "type": "multiple_choice",
        "question": "특징데이터를 묶는 numpy 함수는?",
        "choices": ["row_stack()", "reshape()", "concatenate()", "column_stack()"],
        # answer text not an exact match to any choice (letter-prefixed)
        "answer": "D) column_stack()",
        "answer_index": 3,
        "explanation": "column_stack()은 데이터를 열 단위로 쌓는 함수입니다.",
    }
    out = _norm(item)
    assert out["answer"] == "column_stack()"
    assert out["answer_index"] == 3
    assert out["choices"][out["answer_index"]] == out["answer"]


def test_letter_only_answer_resolved_via_index():
    """LLM returns just a letter for answer; index points to correct choice."""
    item = {
        "type": "multiple_choice",
        "question": "KNN에서 k는?",
        "choices": ["차원수", "반복 횟수", "데이터 총개수", "확인할 이웃의 개수"],
        "answer": "D",
        "answer_index": 3,
        "explanation": "k는 살펴볼 이웃의 개수입니다.",
    }
    out = _norm(item)
    assert out["answer"] == "확인할 이웃의 개수"
    assert out["answer_index"] == 3


def test_fuzzy_match_when_no_index_provided():
    """No answer_index, answer text is a near match (whitespace/punctuation)."""
    item = {
        "type": "multiple_choice",
        "question": "분류와 군집화의 차이는?",
        "choices": [
            "분류는 소속집단을 미리 안다",
            "분류는 레이블이 존재하고 군집화는 존재하지 않는다",
            "둘은 같다",
            "비교 불가",
        ],
        "answer": "분류는 레이블이 존재하고, 군집화는 존재하지 않는다.",  # punctuation differs
        "explanation": "분류는 레이블이 있는 지도학습입니다.",
    }
    out = _norm(item)
    assert out["answer"] == "분류는 레이블이 존재하고 군집화는 존재하지 않는다"
    assert out["choices"][out["answer_index"]] == out["answer"]


def test_consistent_answer_passes_through_unchanged():
    """Exact-match answer with correct index is preserved."""
    item = {
        "type": "multiple_choice",
        "question": "q",
        "choices": ["a", "b", "c", "d"],
        "answer": "c",
        "answer_index": 2,
        "explanation": "c가 정답",
    }
    out = _norm(item)
    assert out["answer"] == "c"
    assert out["answer_index"] == 2
