"""
answer_intent_gate 결정론 분류 테스트.

계약:
  - 일반 질문("gRPC가 뭐야")은 절대 선택지 생성(REQUEST_OPTIONS)으로 분류되지 않는다.
  - "토론 주제 추천해줘"류만 REQUEST_OPTIONS.
  - 짧은 단일 토큰("A","1번")만 OPTION_SELECTION(debate/simulation 모드).
  - 여러 질문은 MULTI_QUESTION + atomic_questions 분해.
  - LLM 호출 없음(순수 결정론).
"""
import pytest

from app.services import answer_intent_gate as G


# ── 선택지 생성 금지: 일반 질문은 DIRECT/MULTI 여야 한다 ────────────────────────
@pytest.mark.parametrize("msg", [
    "gRPC가 뭐야",
    "SSH가 뭐야",
    "이거 설명해줘",
    "A와 B 차이 알려줘",
    "장단점 비교해줘",
    "왜 그런지 알려줘",
])
def test_normal_questions_never_request_options(msg):
    r = G.classify_intent(msg, mode="debate")
    assert r.intent != G.REQUEST_OPTIONS
    assert r.intent != G.OPTION_SELECTION


def test_three_explain_all_is_not_options():
    r = G.classify_intent("3개 다 설명해줘", mode="debate")
    assert r.intent in (G.DIRECT_QUESTION, G.MULTI_QUESTION)
    assert r.intent != G.REQUEST_OPTIONS


def test_direct_question_grpc():
    r = G.classify_intent("gRPC가 뭐야", mode="debate")
    assert r.intent == G.DIRECT_QUESTION
    assert r.atomic_questions == ["gRPC가 뭐야"]


# ── REQUEST_OPTIONS: 명시적 추천/선택지 요청만 ─────────────────────────────────
@pytest.mark.parametrize("msg", [
    "토론 주제 추천해줘",
    "A~E 선택지로 만들어줘",
    "퀴즈 내줘",
    "주제 골라줘",
    "선택지 줘",
])
def test_explicit_option_requests(msg):
    r = G.classify_intent(msg, mode="debate")
    assert r.intent == G.REQUEST_OPTIONS


# ── OPTION_SELECTION: 짧은 단일 토큰만 ────────────────────────────────────────
@pytest.mark.parametrize("msg,expected", [
    ("A", "A"),
    ("a", "A"),
    ("B 선택", "B"),
    ("1번", "A"),
    ("2", "B"),
    ("C로", "C"),
])
def test_option_selection_tokens(msg, expected):
    r = G.classify_intent(msg, mode="debate")
    assert r.intent == G.OPTION_SELECTION
    assert r.option_token == expected


def test_option_selection_not_for_phrases():
    # "A와 B 차이 알려줘"는 토큰이 아니라 일반 질문이다
    r = G.classify_intent("A와 B 차이 알려줘", mode="debate")
    assert r.intent != G.OPTION_SELECTION


def test_option_selection_only_in_choice_modes():
    # default 모드에서 'A'는 옵션 선택이 아니다
    r = G.classify_intent("A", mode="default")
    assert r.intent != G.OPTION_SELECTION


# ── MULTI_QUESTION: 여러 질문 분해 ────────────────────────────────────────────
def test_multi_question_decomposition():
    r = G.classify_intent("SSH가 뭐고 gRPC가 뭐고 둘 차이가 뭐야?", mode="default")
    assert r.intent == G.MULTI_QUESTION
    assert len(r.atomic_questions) >= 2
    joined = " ".join(r.atomic_questions)
    assert "SSH" in joined and "gRPC" in joined


def test_multi_question_two_marks():
    r = G.classify_intent("SSH가 뭐야? gRPC는 뭐야?", mode="default")
    assert r.intent == G.MULTI_QUESTION
    assert len(r.atomic_questions) == 2


# ── pending_choice_context 생성/해석 ──────────────────────────────────────────
def test_make_pending_choice_context_shape():
    candidates = [
        {"topicId": "A", "title": "gRPC를 먼저 배워야 하는가?", "axis": "학습 우선순위"},
        {"topicId": "B", "title": "gRPC는 REST보다 항상 나은가?", "axis": "성능"},
    ]
    ctx = G.make_pending_choice_context(
        turn_id="turn_x", mode="debate",
        original_user_message="토론 주제 추천해줘", candidates=candidates,
    )
    assert ctx["turnId"] == "turn_x"
    assert ctx["mode"] == "debate"
    assert ctx["originalUserMessage"] == "토론 주제 추천해줘"
    assert len(ctx["options"]) == 2
    assert ctx["options"][0]["optionId"] == "A"
    assert ctx["options"][0]["optionText"] == "gRPC를 먼저 배워야 하는가?"


def test_resolve_option_with_context():
    ctx = G.make_pending_choice_context(
        turn_id="t", mode="debate", original_user_message="토론 주제 추천해줘",
        candidates=[{"topicId": "A", "title": "T-A"}, {"topicId": "B", "title": "T-B"}],
    )
    opt = G.resolve_option("B", ctx)
    assert opt is not None
    assert opt["optionId"] == "B"
    assert opt["optionText"] == "T-B"


def test_resolve_option_without_context_returns_none():
    assert G.resolve_option("A", None) is None
    assert G.resolve_option("A", {"options": []}) is None
    assert G.resolve_option("Z", {"options": [{"optionId": "A", "optionText": "x"}]}) is None


# ── GUARDRAIL_DIRECT: 인사/잡담 ───────────────────────────────────────────────
@pytest.mark.parametrize("msg", ["안녕", "ㅎㅇ", "고마워"])
def test_greetings_guardrail(msg):
    r = G.classify_intent(msg, mode="default")
    assert r.intent == G.GUARDRAIL_DIRECT
