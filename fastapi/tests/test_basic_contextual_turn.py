"""
basic 모드 컨텍스트 턴 스트림 + 반복 방지 가드 테스트.

계약:
  - agent_answer 정확히 3개(3명 유지).
  - validation / peer_feedback 이벤트 없음.
  - all_complete.suppressValidation/suppressPeerFeedback = True.
  - turn_start.dialogueAct 가 분류 결과를 싣는다.
  - 직전 답변과 동일/유사한 답변은 anti-repeat 가드로 교체된다(전문 반복 금지).
  - reply_fn 주입으로 Ollama 비호출(재현 가능).
"""
from types import SimpleNamespace

from app.services import dialogue_act_classifier as D
from app.services.basic_contextual_turn import (
    run_basic_contextual_turn,
    run_basic_contextual_turn_stream,
    is_repetitive_reply,
)


def _agents():
    return [
        SimpleNamespace(name="친절 교수", agentId="a1", id=1, personality="friendly", knowledgeLevel="doctor"),
        SimpleNamespace(name="냉철 교수", agentId="a2", id=2, personality="critical", knowledgeLevel="doctor"),
        SimpleNamespace(name="창의 교수", agentId="a3", id=3, personality="creative", knowledgeLevel="doctor"),
    ]


def _ctx():
    prev = [
        {"role": "USER", "answer": "REST랑 gRPC 차이?"},
        {"role": "ASSISTANT", "answer": "REST는 단순 CRUD API에 적합하고, gRPC는 내부 서비스 간 고성능 통신에 유리합니다."},
    ]
    return D.build_previous_context(prev, mode="basic")


def _collect(decision, reply_fn):
    req = SimpleNamespace(message="아니왜?", previousAnswers=[], mode="basic", learningMode="basic")
    return list(run_basic_contextual_turn_stream(req, _agents(), decision, _ctx(), reply_fn=reply_fn))


def _events_by(evts, name):
    return [e for e in evts if e["event"] == name]


# ── 3명 유지 + validation/peer_feedback 없음 ──────────────────────────────────
def test_three_agent_answers_and_no_validation():
    decision = D.classify_dialogue_act("아니왜?", previous_context=_ctx(), mode="basic")

    calls = {"n": 0}
    def reply_fn(message, agent, dec, ctx, regenerate=False):
        calls["n"] += 1
        return f"{agent.name}: {calls['n']}번째 짧은 이유 설명."

    evts = _collect(decision, reply_fn)
    names = [e["event"] for e in evts]

    assert len(_events_by(evts, "agent_answer")) == 3
    assert len(_events_by(evts, "turn_start")) == 1
    assert len(_events_by(evts, "all_complete")) == 1
    # validation / peer_feedback 이벤트가 절대 없어야 한다.
    assert "validation" not in names
    assert "peer_feedback" not in names
    assert "validation_result" not in names


def test_turn_start_and_all_complete_flags():
    decision = D.classify_dialogue_act("아니왜?", previous_context=_ctx(), mode="basic")
    evts = _collect(decision, lambda m, a, d, c, regenerate=False: f"{a.name} 짧은 답")

    ts = _events_by(evts, "turn_start")[0]["data"]
    ac = _events_by(evts, "all_complete")[0]["data"]
    assert ts["dialogueAct"] in (D.FOLLOWUP_WHY, D.FOLLOWUP_CHALLENGE)
    assert ts["answerDepth"] == "short"
    assert ac["suppressValidation"] is True
    assert ac["suppressPeerFeedback"] is True
    assert ac["agentCount"] == 3
    assert len(ac["answers"]) == 3


def test_each_answer_has_dialogue_act_and_short_content():
    decision = D.classify_dialogue_act("아니왜?", previous_context=_ctx(), mode="basic")
    evts = _collect(decision, lambda m, a, d, c, regenerate=False: f"{a.name}: 한 문장 이유.")
    for ev in _events_by(evts, "agent_answer"):
        data = ev["data"]
        assert data["answer"].strip()
        assert data["dialogueAct"] in (D.FOLLOWUP_WHY, D.FOLLOWUP_CHALLENGE)
        assert data["phase"] == "CONTEXTUAL_FOLLOWUP"


# ── anti-repeat: 직전 답변을 그대로 반복하면 가드가 교체한다 ───────────────────
def test_anti_repeat_replaces_repeated_previous_answer():
    decision = D.classify_dialogue_act("아니왜?", previous_context=_ctx(), mode="basic")
    repeated = "REST는 단순 CRUD API에 적합하고, gRPC는 내부 서비스 간 고성능 통신에 유리합니다."

    # reply_fn 이 매번 직전 답변을 그대로 반복(regenerate 시에도 반복) → 폴백으로 교체돼야 함.
    def reply_fn(message, agent, dec, ctx, regenerate=False):
        return repeated

    evts = _collect(decision, reply_fn)
    answers = [e["data"]["answer"] for e in _events_by(evts, "agent_answer")]
    assert len(answers) == 3
    for a in answers:
        assert a.strip()
        assert not is_repetitive_reply(a, [repeated]), f"직전 답변 전문이 반복됨: {a!r}"


def test_is_repetitive_reply_basic():
    prev = ["REST는 단순 CRUD API에 적합하고, gRPC는 내부 서비스 간 고성능 통신에 유리합니다."]
    assert is_repetitive_reply(prev[0], prev) is True
    assert is_repetitive_reply("쉽게 말하면 REST는 설명서, gRPC는 무전기 같은 거야.", prev) is False
    assert is_repetitive_reply("", prev) is True  # 빈 답변은 반복 취급(폴백 유도)


# ── micro depth(백채널)도 3명 유지하되 짧게 ──────────────────────────────────
def test_micro_depth_backchannel_keeps_three():
    decision = D.classify_dialogue_act("ㅇㅇ", previous_context=_ctx(), mode="basic")
    assert decision.answer_depth == "micro"
    evts = _collect(decision, lambda m, a, d, c, regenerate=False: f"{a.name}: 응.")
    assert len(_events_by(evts, "agent_answer")) == 3


# ── 비스트림 패리티: run_basic_contextual_turn 도 3명·반복방지 동일 정책 ────────
def test_non_stream_contextual_turn_keeps_three_and_no_repeat():
    decision = D.classify_dialogue_act("아니왜?", previous_context=_ctx(), mode="basic")
    req = SimpleNamespace(message="아니왜?", previousAnswers=[], mode="basic", learningMode="basic")
    repeated = "REST는 단순 CRUD API에 적합하고, gRPC는 내부 서비스 간 고성능 통신에 유리합니다."

    answers = run_basic_contextual_turn(
        req, _agents(), decision, _ctx(),
        reply_fn=lambda m, a, d, c, regenerate=False: repeated,  # 매번 직전 답변 반복
    )
    assert len(answers) == 3
    for a in answers:
        assert a["status"] == "SUCCESS"
        assert a["answer"].strip()
        # 직전 답변 전문이 그대로 반복되면 안 된다(anti-repeat 폴백).
        assert not is_repetitive_reply(a["answer"], [repeated])
        assert a["agentName"] and a["agentId"]
