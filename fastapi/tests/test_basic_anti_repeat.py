"""
basic 컨텍스트 턴의 반복 방지(anti-repeat) 가드 전용 테스트.

핵심 계약:
  - 직전 답변(주제어 포함)을 그대로 되풀이하는 reply 는 가드로 교체된다.
  - 폴백은 직전 답변의 내용(주제어)을 본문에 박지 않는다(그 단어가 반복을 유발하므로).
  - 세 에이전트가 서로 같은 문장을 베끼지 않는다.
"""
from types import SimpleNamespace

from app.services import dialogue_act_classifier as D
from app.services.basic_contextual_turn import (
    run_basic_contextual_turn_stream,
    is_repetitive_reply,
    _compact_fallback,
)

# 직전 답변에 등장하는 임의의 "주제어"(특정 기술명에 의존하지 않음을 보이는 더미)
_TOPIC_WORD = "포자나선체"
_PREV_ANSWER = f"{_TOPIC_WORD}는 단순 작업에 적합하고, 다른 방식은 내부 고성능 통신에 유리합니다."


def _agents():
    return [
        SimpleNamespace(name="친절 교수", agentId="a1", id=1, personality="friendly"),
        SimpleNamespace(name="냉철 교수", agentId="a2", id=2, personality="critical"),
        SimpleNamespace(name="창의 교수", agentId="a3", id=3, personality="creative"),
    ]


def _ctx():
    return D.build_previous_context(
        [{"role": "USER", "answer": "둘 차이?"},
         {"role": "ASSISTANT", "answer": _PREV_ANSWER}],
        mode="basic",
    )


def _run(reply_fn):
    decision = D.classify_dialogue_act("아니왜?", previous_context=_ctx(), mode="basic")
    req = SimpleNamespace(message="아니왜?", previousAnswers=[], mode="basic", learningMode="basic")
    evts = list(run_basic_contextual_turn_stream(req, _agents(), decision, _ctx(), reply_fn=reply_fn))
    return [e["data"]["answer"] for e in evts if e["event"] == "agent_answer"]


def test_repeated_full_answer_is_replaced():
    answers = _run(lambda *a, **k: _PREV_ANSWER)  # 매번 직전 답변 전문 반복
    assert len(answers) == 3
    for a in answers:
        assert not is_repetitive_reply(a, [_PREV_ANSWER]), f"전문 반복 미차단: {a!r}"


def test_fallback_is_content_free_no_topic_word():
    # 폴백 본문에 직전 답변의 주제어가 박히면 안 된다(그 단어가 반복을 유발).
    decision = D.classify_dialogue_act("아니왜?", previous_context=_ctx(), mode="basic")
    for ag in _agents():
        fb = _compact_fallback(ag, decision, _ctx())
        assert fb.strip()
        assert _TOPIC_WORD not in fb, f"폴백에 주제어 누출: {fb!r}"
        assert not is_repetitive_reply(fb, [_PREV_ANSWER])


def test_blank_reply_falls_back_non_empty():
    answers = _run(lambda *a, **k: "")  # LLM 빈 응답
    assert len(answers) == 3
    assert all(a.strip() for a in answers)


def test_three_agents_do_not_copy_each_other_on_fallback():
    answers = _run(lambda *a, **k: _PREV_ANSWER)  # 전부 폴백으로 떨어짐
    # 에이전트별 변형이 적용되어 세 답변이 모두 동일하진 않아야 한다.
    assert len(set(answers)) >= 2, f"세 답변이 서로 베낌: {answers}"
