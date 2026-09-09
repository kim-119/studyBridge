"""
소크라테스 세션 상태 머신 테스트 (LLM 은 fake 주입).

  - 첫 턴은 '질문 1개'. 정답/정의/요약을 먼저 주면 재생성한다.
  - 사용자 답변 평가(correct/partial/wrong/unknown)에 따라 다음 행동이 달라진다.
  - 질문 강도/힌트 방식이 실제 생성 로직에 영향을 준다.
  - 연속 실패가 쌓이면 VERIFY(자기 말로 재구성) → SUMMARY 로 수렴한다.
"""
import json

import pytest

from app.schemas.multi_chat_schema import MultiChatRequest
from app.services import learning_session as LS
from app.services import socratic_mode_handler as H
from app.services import socratic_session_engine as SE

TOPIC = "HashMap에서 같은 key를 두 번 넣으면 어떻게 돼?"
EXPECTED = "같은 key 로 put 하면 기존 value 가 새 value 로 덮어써진다"


@pytest.fixture(autouse=True)
def _clean():
    LS.clear_all()
    yield
    LS.clear_all()


class FakeLLM:
    """지시된 JSON 스키마를 보고 계약을 지키는 응답을 만든다."""

    def __init__(self, assessment="unknown"):
        self.calls = []
        self.assessment = assessment

    def __call__(self, system, user, *, max_tokens, temperature):
        self.calls.append({"user": user, "max_tokens": max_tokens})
        if '"expectedIdea"' in user:
            return json.dumps({
                "expectedIdea": EXPECTED,
                "probe": "지금 떠오르는 대로 먼저 생각해보자.",
                "question": "같은 key 를 두 번 넣었을 때, 그 key 가 가리키는 자리가 새로 생길까 아니면 원래 자리가 쓰일까?",
            }, ensure_ascii=False)
        if '"assessment"' in user:
            return json.dumps({
                "assessment": self.assessment,
                "acknowledge": "방향은 잡았어.",
                "hint": "자리를 정하는 기준이 무엇인지 떠올려봐.",
                "question": "그렇다면 그 자리가 이미 차 있을 때는 무슨 일이 벌어질까?",
            }, ensure_ascii=False)
        if '"userConclusion"' in user:
            return json.dumps({
                "userConclusion": "같은 key 면 원래 자리가 새 값으로 바뀐다.",
                "verified": True,
                "correction": "",
                "nextStep": "put 이 반환하는 값이 무엇인지 확인해보기.",
            }, ensure_ascii=False)
        return "{}"


def _req(message, room=101, intensity="normal", hint="concept", state=None):
    return MultiChatRequest(
        message=message, mode="socratic", learningMode="socratic", roomId=room,
        socraticConfig={"questionIntensity": intensity, "hintPolicy": hint},
        socraticState=state,
        agents=[{"agentId": "a1", "name": "김교수", "personality": "논리", "knowledgeLevel": "학사"}],
    )


# ── 첫 턴 계약 ──────────────────────────────────────────────────────────────
def test_first_turn_is_a_single_question_without_the_answer():
    turn, issues = SE.generate_first_turn(TOPIC, SE.NORMAL, SE.HINT_CONCEPT, "김교수", llm=FakeLLM())
    assert issues == []
    assert turn.state == SE.ASK
    assert turn.text.count("?") == 1
    assert turn.question.endswith("?")
    assert "덮어" not in turn.text          # 정답 문장을 먼저 주지 않는다


def test_first_turn_answer_leak_is_regenerated():
    class Leaky(FakeLLM):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def __call__(self, system, user, *, max_tokens, temperature):
            if '"expectedIdea"' in user:
                self.attempts += 1
                if "[재작성 지시" not in user:
                    return json.dumps({
                        "expectedIdea": EXPECTED,
                        "probe": "정리하면 같은 key 로 put 하면 기존 value 가 새 value 로 덮어써진다.",
                        "question": "그렇지?",
                    }, ensure_ascii=False)
            return super().__call__(system, user, max_tokens=max_tokens, temperature=temperature)

    llm = Leaky()
    turn, issues = SE.generate_first_turn(TOPIC, SE.NORMAL, SE.HINT_CONCEPT, "김교수", llm=llm)
    assert llm.attempts >= 2                # 정답 노출 → 그 턴만 재생성
    assert issues == []


def test_lecture_style_first_turn_is_rejected():
    turn = SE.SocraticTurn(state=SE.ASK, text="핵심 개념 정리: 이것은 이렇다. 그럼 어떻게 될까?",
                           question="그럼 어떻게 될까?")
    assert "lecture_style" in SE.validate_first_turn(turn, "무관한 내용")


def test_multiple_questions_are_rejected():
    turn = SE.SocraticTurn(state=SE.ASK, text="이건 뭘까? 그리고 저건 뭘까?", question="이건 뭘까?")
    assert "not_single_question" in SE.validate_first_turn(turn, "")


# ── 평가 분기 ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("assessment,expected_state", [
    (SE.CORRECT, SE.DEEPEN),
    (SE.PARTIAL, SE.ASK),
    (SE.WRONG, SE.HINT),
    (SE.UNKNOWN, SE.HINT),
])
def test_assessment_drives_next_state(assessment, expected_state):
    turn, issues = SE.generate_followup(TOPIC, "잘 모르겠어", [], SE.NORMAL, SE.HINT_CONCEPT,
                                        0, 0, EXPECTED, llm=FakeLLM(assessment))
    assert issues == []
    assert turn.state == expected_state
    assert turn.text.count("?") == 1


def test_intensive_withholds_hint_on_first_failure():
    turn, _ = SE.generate_followup(TOPIC, "모르겠어", [], SE.INTENSIVE, SE.HINT_CONCEPT,
                                   0, 0, EXPECTED, llm=FakeLLM(SE.UNKNOWN))
    assert turn.hint == ""


def test_gentle_always_gives_a_hint_when_stuck():
    turn, _ = SE.generate_followup(TOPIC, "모르겠어", [], SE.GENTLE, SE.HINT_CONCEPT,
                                   0, 0, EXPECTED, llm=FakeLLM(SE.UNKNOWN))
    assert turn.hint


def test_intensity_and_hint_style_reach_the_prompt():
    llm = FakeLLM(SE.UNKNOWN)
    SE.generate_followup(TOPIC, "모르겠어", [], SE.INTENSIVE, SE.HINT_COUNTER, 0, 0, EXPECTED, llm=llm)
    prompt = llm.calls[-1]["user"]
    assert "질문 강도: 강하게" in prompt
    assert "반례" in prompt


def test_consecutive_failure_escalates_to_verify():
    turn, _ = SE.generate_followup(TOPIC, "모르겠어", [], SE.NORMAL, SE.HINT_CONCEPT,
                                   2, SE.FAIL_ESCALATION - 1, EXPECTED, llm=FakeLLM(SE.UNKNOWN))
    assert turn.state == SE.VERIFY


def test_config_normalization_reuses_existing_dto():
    req = _req("x", intensity="강하게", hint="step_by_step")
    assert SE.resolve_config(req) == (SE.INTENSIVE, SE.HINT_STEP)
    assert SE.resolve_config(_req("x")) == (SE.NORMAL, SE.HINT_CONCEPT)


# ── 세션 흐름(핸들러) ───────────────────────────────────────────────────────
def _events(request, llm):
    return list(H.run_socratic_mode_stream(request, list(request.agents), llm=llm))


def test_session_first_turn_creates_state_and_single_answer():
    llm = FakeLLM()
    events = _events(_req(TOPIC), llm)
    assert [e["event"] for e in events] == ["turn_start", "agent_start", "agent_answer", "all_complete"]
    final = events[-1]["data"]
    assert final["socraticState"]["state"] == SE.ASK
    assert final["turnIndex"] == 1
    assert len(final["answers"]) == 1                      # 한 턴에 한 명, 질문 1개
    assert final["socraticSteps"][0]["stageType"] == "DIAGNOSIS"
    assert final["socraticValidation"]["passed"]


def test_second_turn_continues_same_session_and_evaluates():
    llm = FakeLLM(SE.PARTIAL)
    first = _events(_req(TOPIC), llm)
    sid = first[-1]["data"]["sessionId"]
    second = _events(_req("기존 게 바뀔 것 같은데"), llm)
    final = second[-1]["data"]
    assert final["sessionId"] == sid                       # 같은 세션
    assert final["turnIndex"] == 2
    assert final["answers"][0]["assessment"] == SE.PARTIAL


def test_short_replies_do_not_start_a_new_session():
    llm = FakeLLM(SE.UNKNOWN)
    first = _events(_req(TOPIC), llm)
    sid = first[-1]["data"]["sessionId"]
    for short in ("모르겠어", "하나만?", "왜?"):
        out = _events(_req(short), llm)
        assert out[-1]["data"]["sessionId"] == sid, short


def test_session_survives_restart_via_client_echo():
    llm = FakeLLM(SE.PARTIAL)
    first = _events(_req(TOPIC), llm)
    state = first[-1]["data"]["socraticState"]
    LS.clear_all()                                        # 프로세스 재시작 상황
    resumed = _events(_req("기존 게 바뀔 것 같은데", state=state), llm)
    assert resumed[-1]["data"]["sessionId"] == state["sessionId"]
    assert resumed[-1]["data"]["turnIndex"] == state["turnIndex"] + 1


def test_wrap_up_produces_summary_of_user_conclusion():
    llm = FakeLLM(SE.CORRECT)
    _events(_req(TOPIC), llm)
    # VERIFY 상태로 밀어넣고 다음 턴이 SUMMARY 가 되는지 본다
    key = LS.resolve_session_id(_req("x"), "socratic")
    session = LS.get(key)
    session.state = SE.VERIFY
    LS.save(key, session)
    out = _events(_req("기존 값이 새 값으로 바뀌는 것 같아"), llm)
    final = out[-1]["data"]
    assert final["socraticState"]["state"] == SE.SUMMARY
    assert "네가 정리한 결론" in final["answers"][0]["answer"]


def test_generation_failure_returns_mode_specific_error_not_basic_answer():
    def broken(system, user, *, max_tokens, temperature):
        raise RuntimeError("llm down")

    events = _events(_req(TOPIC), broken)
    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["code"] == "SOCRATIC_TURN_FAILED"
    assert not any(e["event"] == "agent_answer" for e in events)


def test_new_session_ignores_previous_topic_context():
    llm = FakeLLM()
    _events(_req(TOPIC), llm)
    other = _events(_req("TCP와 UDP의 차이는 무엇인가요?"), llm)
    prompt = llm.calls[-1]["user"]
    assert "TCP" in prompt
    assert "HashMap" not in prompt              # 이전 주제가 새 세션 프롬프트에 섞이지 않는다
    assert other[-1]["data"]["turnIndex"] == 1


# ── 재생성 상한 이후의 결정론적 복구 ────────────────────────────────────────
def test_uncooperative_model_output_is_repaired_not_leaked():
    """모델이 계속 정답을 붙이고 질문을 여러 개 던져도 사용자에게는 계약대로 나간다."""
    class Stubborn:
        def __call__(self, system, user, *, max_tokens, temperature):
            if '"assessment"' in user:
                return json.dumps({
                    "assessment": "partial",
                    "acknowledge": "방향은 맞다.",
                    "hint": f"{EXPECTED}. 그럼 이건 어떨까?",
                    "question": "그럼 다음은 뭘까? 또 이건 어떨까?",
                }, ensure_ascii=False)
            return "{}"

    turn, issues = SE.generate_followup(TOPIC, "모르겠어", [], SE.NORMAL, SE.HINT_CONCEPT,
                                        0, 0, EXPECTED, llm=Stubborn())
    assert turn.structured.get("repaired") is True
    assert turn.hint == ""                      # 정답이 섞인 힌트는 제거
    assert turn.text.count("?") == 1            # 질문 1개로 축소
    assert "덮어써진다" not in turn.text
    assert issues == []


def test_answer_leak_is_rejected_for_every_assessment():
    turn = SE.SocraticTurn(state=SE.ASK, text=f"{EXPECTED}. 그럼 어떻게 될까?",
                           question="그럼 어떻게 될까?", assessment=SE.PARTIAL)
    assert SE.leaks_answer(turn.text, EXPECTED)


def test_repair_replaces_leaking_question_with_content_free_probe():
    turn = SE.SocraticTurn(state=SE.HINT, text="x", question=f"{EXPECTED}?",
                           hint="", structured={"acknowledge": ""})
    repaired = SE.repair_turn(turn, EXPECTED)
    assert repaired.question == SE._FALLBACK_QUESTION
    assert repaired.text.count("?") == 1


def test_leak_detector_ignores_topic_vocabulary():
    """질문이 주제 어휘를 공유하는 것만으로 '정답 노출'로 오판하면 안 된다."""
    question = "같은 key 를 두 번 넣으면 기존 value 는 어떻게 될까?"
    assert not SE.leaks_answer(question, EXPECTED, TOPIC)
    # 정답에만 있는 어휘(덮어써진다)가 나오면 노출로 본다
    assert SE.leaks_answer("기존 value 가 새 value 로 덮어써진다는 뜻이야", EXPECTED, TOPIC)


def test_topic_anchored_fallback_question_quotes_user_topic():
    q = SE.topic_anchored_question(TOPIC)
    assert q.endswith("?") and "HashMap" in q


def test_repeated_question_is_rejected():
    """직전과 같은 질문을 다시 던지면 그 턴만 재생성한다."""
    llm = FakeLLM(SE.PARTIAL)
    prev = "그렇다면 그 자리가 이미 차 있을 때는 무슨 일이 벌어질까?"
    turn, issues = SE.generate_followup(TOPIC, "잘 모르겠어", [], SE.NORMAL, SE.HINT_CONCEPT,
                                        0, 0, EXPECTED, llm=llm, previous_questions=[prev])
    # fake 는 항상 같은 질문을 준다 → 재생성 시도 후 복구로 '다른' 질문이 나가야 한다.
    # (repaired 플래그만 서고 같은 질문이 그대로 나가면 사용자에겐 반복으로 보인다.)
    assert turn.question != prev


def test_repair_replaces_repeated_question_even_when_it_is_contract_valid():
    """정답 노출도 없고 물음표로 끝나도, 이미 한 질문이면 다른 질문으로 바꾼다."""
    used = ["'HashMap' 이 질문에서, 지금 확실하다고 말할 수 있는 건 무엇일까?"]
    turn = SE.SocraticTurn(state=SE.ASK, text=used[0], question=used[0], hint="",
                           assessment=SE.PARTIAL, hint_level=0, structured={"acknowledge": ""})
    repaired = SE.repair_turn(turn, EXPECTED, known_text=TOPIC, topic=TOPIC, used_questions=used)
    assert repaired.question not in used
    assert repaired.question.endswith("?")


def test_probe_with_question_mark_is_dropped_at_build_time():
    """probe 에 질문이 섞여도 사용자에게는 질문이 1개만 나간다."""
    class ProbeQuestion:
        def __call__(self, system, user, *, max_tokens, temperature):
            return json.dumps({
                "expectedIdea": EXPECTED, "answerKeywords": ["덮어써진다"],
                "probe": "지금 어떻게 생각해?",
                "question": "같은 key 를 다시 넣으면 자리에서 무슨 일이 생길까?",
            }, ensure_ascii=False)

    turn, issues = SE.generate_first_turn(TOPIC, SE.NORMAL, SE.HINT_CONCEPT, "김교수", llm=ProbeQuestion())
    assert issues == []
    assert turn.text.count("?") == 1
    assert "지금 어떻게 생각해" not in turn.text


def test_short_generic_keyword_does_not_trigger_leak():
    """'선택' 같은 두 글자 일반어 하나로 정답 노출 판정하지 않는다."""
    topic = "인덱스가 있는데도 풀스캔이 나오는 이유는?"
    assert not SE.leaks_answer("인덱스가 있어도 풀스캔이 나오는 경우는 언제일까?",
                               "선택성 때문에 옵티마이저가 풀스캔을 고른다",
                               topic, ["인덱스 선택"])
    assert SE.leaks_answer("옵티마이저가 선택성을 보고 풀스캔을 고른다",
                           "선택성 때문에 옵티마이저가 풀스캔을 고른다",
                           topic, ["옵티마이저 선택성"])


def test_assertive_hint_that_states_answer_is_dropped():
    """'기존 값이 새 값으로 대체됩니다' 같은 단정형 힌트는 사용자에게 나가지 않는다."""
    class AssertiveHint:
        def __call__(self, system, user, *, max_tokens, temperature):
            return json.dumps({
                "assessment": "partial",
                "acknowledge": "방향은 맞아.",
                "hint": "HashMap은 같은 키가 존재하면 기존 value 가 새 value 로 대체됩니다.",
                "question": "그렇다면 그 자리는 새로 생길까, 원래 자리가 쓰일까?",
            }, ensure_ascii=False)

    turn, issues = SE.generate_followup(TOPIC, "기존 게 바뀔 것 같은데", [], SE.NORMAL,
                                        SE.HINT_CONCEPT, 0, 0, EXPECTED, llm=AssertiveHint())
    assert turn.hint == ""
    assert "대체됩니다" not in turn.text
    assert turn.text.count("?") == 1


def test_guiding_hint_is_kept():
    class GuidingHint:
        def __call__(self, system, user, *, max_tokens, temperature):
            return json.dumps({
                "assessment": "unknown",
                "acknowledge": "괜찮아.",
                "hint": "자리를 정하는 기준이 무엇인지 먼저 떠올려봐",
                "question": "그 기준이 같으면 어떤 일이 생길까?",
            }, ensure_ascii=False)

    turn, _ = SE.generate_followup(TOPIC, "모르겠어", [], SE.NORMAL, SE.HINT_CONCEPT,
                                   0, 0, EXPECTED, llm=GuidingHint())
    assert "떠올려봐" in turn.hint


def test_fallback_question_does_not_repeat_itself():
    first = SE.topic_anchored_question(TOPIC)
    second = SE.topic_anchored_question(TOPIC, [first])
    third = SE.topic_anchored_question(TOPIC, [first, second])
    assert len({first, second, third}) == 3
    assert all(q.endswith("?") for q in (first, second, third))
