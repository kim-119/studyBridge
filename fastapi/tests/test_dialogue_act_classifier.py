"""
dialogue_act_classifier 결정론 분류 테스트 (LLM 비호출, 재현 가능).

핵심 계약:
  - 직전 답변 맥락이 있을 때 "아니왜?","왜?"는 NEW_STUDY_QUERY 가 아니라 FOLLOWUP_*.
  - 맥락이 없으면 "왜?"는 애매(UNKNOWN) — 무조건 FOLLOWUP 으로 강등하지 않는다.
  - 명확한 새 질문("gRPC가 뭐야? REST와 차이까지")은 맥락이 있어도 NEW_STUDY_QUERY.
  - FOLLOWUP/CASUAL 계열은 suppress_validation/suppress_peer_feedback = True.
"""
import pytest

from app.services import dialogue_act_classifier as D


def _ctx(user="REST랑 gRPC 차이 알려줘",
         answer="REST는 단순 CRUD API에 적합하고, gRPC는 내부 서비스 간 고성능 통신에 유리합니다."):
    prev = [
        {"role": "USER", "answer": user},
        {"role": "ASSISTANT", "agentName": "친절 교수", "answer": answer},
    ]
    return D.build_previous_context(prev, mode="basic")


# ── build_previous_context ────────────────────────────────────────────────────
def test_build_previous_context_extracts_user_and_answers():
    ctx = _ctx()
    assert ctx.has_context is True
    assert "gRPC" in ctx.last_user_message or "REST" in ctx.last_user_message
    assert ctx.last_agent_answers and "REST" in ctx.last_agent_answers[-1]
    assert ctx.last_claims  # 핵심 주장 추출


def test_build_previous_context_empty():
    ctx = D.build_previous_context([], mode="basic")
    assert ctx.has_context is False


# ── 1) "아니왜?" with context → FOLLOWUP_WHY/CHALLENGE, short, not new ──────────
@pytest.mark.parametrize("msg", ["아니왜?", "아니 왜?", "왜 그렇게 됨?", "근데 왜?"])
def test_aniwhy_with_context_is_followup(msg):
    d = D.classify_dialogue_act(msg, previous_context=_ctx(), mode="basic")
    assert d.act in (D.FOLLOWUP_WHY, D.FOLLOWUP_CHALLENGE)
    assert d.is_new_question is False
    assert d.answer_depth == "short"
    assert d.suppress_validation is True
    assert d.suppress_peer_feedback is True
    assert d.anti_repeat is True
    assert d.requires_three_agents is True


# ── 2) "왜?" — 맥락 있으면 FOLLOWUP_WHY, 없으면 UNKNOWN ────────────────────────
def test_why_with_context_is_followup_why():
    d = D.classify_dialogue_act("왜?", previous_context=_ctx(), mode="basic")
    assert d.act == D.FOLLOWUP_WHY
    assert d.is_new_question is False


def test_why_without_context_is_unknown():
    d = D.classify_dialogue_act("왜?", previous_context=None, mode="basic")
    assert d.act == D.UNKNOWN
    assert d.answer_depth == "ask_clarification"
    assert d.is_new_question is False


# ── 3) "그게 맞아?" → FOLLOWUP_CHALLENGE, full 금지 ───────────────────────────
@pytest.mark.parametrize("msg", ["그게 맞아?", "정말?", "틀린 거 아님?", "그게 진짜야?"])
def test_challenge_with_context(msg):
    d = D.classify_dialogue_act(msg, previous_context=_ctx(), mode="basic")
    assert d.act in (D.FOLLOWUP_CHALLENGE, D.DISAGREEMENT)
    assert d.answer_depth != "full"
    assert d.is_new_question is False


# ── 4) "ㅇㅇ" → BACKCHANNEL/AGREEMENT, micro ──────────────────────────────────
@pytest.mark.parametrize("msg", ["ㅇㅇ", "그렇구나", "오오", "음"])
def test_backchannel_micro(msg):
    d = D.classify_dialogue_act(msg, previous_context=_ctx(), mode="basic")
    assert d.act in (D.BACKCHANNEL, D.AGREEMENT)
    assert d.answer_depth == "micro"
    assert d.is_new_question is False


# ── 5) "예시로" → FOLLOWUP_EXAMPLE ────────────────────────────────────────────
@pytest.mark.parametrize("msg", ["예시로", "예를 들어봐", "코드 예시 줘", "사례 좀"])
def test_example_request(msg):
    d = D.classify_dialogue_act(msg, previous_context=_ctx(), mode="basic")
    assert d.act == D.FOLLOWUP_EXAMPLE
    assert d.answer_depth == "short"


# ── 6) "더 쉽게" → FOLLOWUP_SIMPLIFY ──────────────────────────────────────────
@pytest.mark.parametrize("msg", ["더 쉽게", "초딩도 알게 설명해줘", "간단히", "쉽게 말해줘"])
def test_simplify_request(msg):
    d = D.classify_dialogue_act(msg, previous_context=_ctx(), mode="basic")
    assert d.act == D.FOLLOWUP_SIMPLIFY
    assert d.answer_depth == "short"
    assert d.is_new_question is False


# ── 7) 명확한 새 질문 → NEW_STUDY_QUERY (맥락 유무 무관) ──────────────────────
@pytest.mark.parametrize("msg", [
    "gRPC가 뭐야? REST와 차이까지 알려줘",
    "트랜잭션 격리 수준이 뭐야?",
    "HTTP/2와 HTTP/3 차이 설명해줘",
])
def test_new_study_query_stays_full(msg):
    d_no = D.classify_dialogue_act(msg, previous_context=None, mode="basic")
    d_ctx = D.classify_dialogue_act(msg, previous_context=_ctx(), mode="basic")
    assert d_no.act == D.NEW_STUDY_QUERY and d_no.answer_depth == "full"
    assert d_ctx.act == D.NEW_STUDY_QUERY and d_ctx.answer_depth == "full"


# ── 8) "왜" 키워드가 든 긴 새 질문은 FOLLOWUP 으로 강등되지 않는다 ──────────────
def test_why_inside_long_new_question_is_not_followup():
    d = D.classify_dialogue_act(
        "왜 REST보다 gRPC가 내부 통신에서 더 빠른지 원리까지 설명해줘",
        previous_context=_ctx(), mode="basic",
    )
    assert d.act == D.NEW_STUDY_QUERY


# ── 보조: 계속/명확화/반박/인사/감사 ─────────────────────────────────────────
def test_continue_request():
    d = D.classify_dialogue_act("계속", previous_context=_ctx(), mode="basic")
    assert d.act == D.FOLLOWUP_CONTINUE


def test_clarify_request():
    d = D.classify_dialogue_act("무슨 말이야?", previous_context=_ctx(), mode="basic")
    assert d.act == D.FOLLOWUP_CLARIFY


def test_bare_disagreement_asks_clarification_without_claim():
    # 핵심주장이 비면 ask_clarification, 있으면 short.
    d = D.classify_dialogue_act("아닌데", previous_context=_ctx(), mode="basic")
    assert d.act == D.DISAGREEMENT
    assert d.answer_depth in ("short", "ask_clarification")


@pytest.mark.parametrize("msg", ["안녕", "하이", "ㅎㅇ"])
def test_greeting(msg):
    d = D.classify_dialogue_act(msg, previous_context=None, mode="basic")
    assert d.act == D.GREETING
    assert d.answer_depth == "micro"


@pytest.mark.parametrize("msg", ["고마워", "감사합니다"])
def test_thanks(msg):
    d = D.classify_dialogue_act(msg, previous_context=_ctx(), mode="basic")
    assert d.act == D.THANKS


def test_target_previous_claim_set_for_why():
    d = D.classify_dialogue_act("왜?", previous_context=_ctx(), mode="basic")
    assert d.target_previous_claim  # 직전 핵심 주장이 실린다
