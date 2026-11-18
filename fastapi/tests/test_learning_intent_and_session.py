"""
LearningIntentGuard + 학습 세션(공통 라우팅 계약) 테스트.

  - socratic/debate/simulation 새 세션 첫 입력의 잡담은 모델 호출 없이 NON_LEARNING_INPUT.
  - 진행 중 세션의 짧은 답("모르겠어", "2번")은 절대 가드를 타지 않는다.
  - 새 세션은 이전 모드 상태/이전 주제를 끌고 오지 않는다.
"""
import pytest

from app.schemas.multi_chat_schema import MultiChatRequest
from app.services import learning_intent_guard as G
from app.services import learning_mode_dispatcher as D
from app.services import learning_session as LS


@pytest.fixture(autouse=True)
def _clean_sessions():
    LS.clear_all()
    yield
    LS.clear_all()


def _req(message, mode="socratic", room=77, **kw):
    return MultiChatRequest(message=message, mode=mode, learningMode=mode, roomId=room,
                            agents=[{"agentId": "a1", "name": "교수1"}], **kw)


# ── 학습 의도 판정 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("message", [
    "냉면 먹고 싶어", "안녕하세요", "배고파", "ㅋㅋㅋ", "치킨 먹고 싶다",
])
def test_non_learning_inputs(message):
    d = G.classify_deterministic(message)
    assert d is not None and d.intent == G.NON_LEARNING, message


@pytest.mark.parametrize("message", [
    "HashMap에서 같은 key를 두 번 넣으면 어떻게 돼?",
    "모놀리식과 마이크로서비스 중 대규모 서비스에 더 좋은 선택은 무엇인가?",
    "면접에서 JWT가 무엇인지 설명해보라는 질문을 연습하고 싶어",
    "캡스톤 발표에서 교수님이 왜 FastAPI를 따로 썼냐고 묻는 상황을 연습하고 싶어",
])
def test_learning_inputs(message):
    d = G.classify_deterministic(message)
    assert d is not None and d.intent == G.LEARNING, message


def test_ambiguous_uses_llm_and_falls_back_to_learning():
    assert G.classify_deterministic("오늘 날씨 좋다") is None
    decision = G.classify_learning_intent("오늘 날씨 좋다", "socratic", llm=lambda s, u: '{"learning": false}')
    assert decision.intent == G.NON_LEARNING and decision.used_llm
    # LLM 실패 → 학습으로 통과(진짜 질문을 막지 않는다)
    def boom(s, u):
        raise RuntimeError("down")
    assert G.classify_learning_intent("오늘 날씨 좋다", "socratic", llm=boom).intent == G.LEARNING


def test_guard_applies_only_to_dedicated_modes_and_new_sessions():
    assert G.should_guard("socratic", True)
    assert G.should_guard("debate", True)
    assert G.should_guard("simulation", True)
    assert not G.should_guard("basic", True)      # 기본 모드는 잡담도 그냥 받아준다
    assert not G.should_guard("socratic", False)  # 진행 중 세션은 가드 없음


# ── 디스패처 게이트 ─────────────────────────────────────────────────────────
def test_new_session_smalltalk_is_blocked_without_model_call(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("비학습 입력인데 모델을 호출했다")
    monkeypatch.setattr("app.services.ollama_client.ask_ollama", boom)

    events = list(D.run_learning_mode_stream(_req("냉면 먹고 싶어"), [], "socratic"))
    assert [e["event"] for e in events] == ["turn_start", "agent_answer", "all_complete"]
    final = events[-1]["data"]
    assert final["code"] == G.NON_LEARNING_CODE
    assert final["blocked"] is True
    assert final["answers"][0]["answer"] == G.NON_LEARNING_MESSAGE
    # 이전 주제(HashMap 등)가 섞이지 않는다
    assert "HashMap" not in final["answers"][0]["answer"]


def test_learning_question_reaches_mode_handler(monkeypatch):
    from app.services import socratic_mode_handler as H
    called = {}

    def fake(request, agents, llm=None):
        called["hit"] = True
        yield {"event": "all_complete", "data": {"type": "all_complete", "mode": "socratic"}}

    monkeypatch.setattr(H, "run_socratic_mode_stream", fake)
    events = list(D.run_learning_mode_stream(
        _req("HashMap에서 같은 key를 두 번 넣으면 어떻게 돼?"), [], "socratic"))
    assert called.get("hit") is True
    assert events[-1]["data"]["mode"] == "socratic"


def test_active_session_short_reply_is_not_regated(monkeypatch):
    """진행 중 세션의 '모르겠어'는 NON_LEARNING 으로 막히면 안 된다."""
    key = LS.resolve_session_id(_req("x"), "socratic")
    LS.save(key, LS.LearningSession(session_id="s1", mode="socratic",
                                    topic="HashMap에서 같은 key를 두 번 넣으면?",
                                    state="ASK", turn_index=1))
    from app.services import socratic_mode_handler as H
    seen = {}

    def fake(request, agents, llm=None):
        seen["message"] = request.message
        yield {"event": "all_complete", "data": {"type": "all_complete", "mode": "socratic"}}

    monkeypatch.setattr(H, "run_socratic_mode_stream", fake)
    events = list(D.run_learning_mode_stream(_req("모르겠어"), [], "socratic"))
    assert seen["message"] == "모르겠어"
    assert events[-1]["data"].get("code") != G.NON_LEARNING_CODE


def test_new_topic_in_active_session_starts_new_session():
    key = LS.resolve_session_id(_req("x"), "socratic")
    LS.save(key, LS.LearningSession(session_id="s1", mode="socratic",
                                    topic="HashMap에서 같은 key를 두 번 넣으면?",
                                    state="ASK", turn_index=2))
    is_new, session_id, decision = D.evaluate_gate(_req("TCP와 UDP의 차이는 무엇인가요?"), "socratic")
    assert is_new is True
    assert session_id is None
    assert decision is not None and decision.is_learning


def test_previous_topic_does_not_leak_into_new_session(monkeypatch):
    """이전 HashMap 세션이 있어도 '냉면 먹고 싶어'는 그 세션을 이어받지 않는다."""
    def boom(*a, **k):
        raise AssertionError("비학습 입력인데 모델을 호출했다")
    monkeypatch.setattr("app.services.ollama_client.ask_ollama", boom)
    key = LS.resolve_session_id(_req("x"), "socratic")
    LS.save(key, LS.LearningSession(session_id="s1", mode="socratic",
                                    topic="HashMap에서 같은 key를 두 번 넣으면?",
                                    state="ASK", turn_index=1))
    events = list(D.run_learning_mode_stream(_req("냉면 먹고 싶어"), [], "socratic"))
    blob = " ".join(str(e["data"]) for e in events)
    assert G.NON_LEARNING_CODE in blob
    assert "HashMap" not in blob


def test_memory_block_is_stripped_before_intent_check():
    injected = ("[이전 대화 기억]\n- user: HashMap이 뭐야\n- assistant: 해시 기반 자료구조입니다.\n"
                "[현재 질문]\n냉면 먹고 싶어")
    d = G.classify_deterministic(injected)
    assert d is not None and d.intent == G.NON_LEARNING


# ── 세션 저장/복원 ──────────────────────────────────────────────────────────
def test_session_hydrates_from_client_echo():
    """프로세스 재시작으로 메모리가 비어도 클라이언트 echo 로 세션이 복원된다."""
    req = _req("모르겠어", socraticState={"sessionId": "s-echo", "state": "ASK", "turnIndex": 3,
                                          "topic": "HashMap 같은 key", "data": {"hintLevel": 1}})
    key, session, is_new = LS.resolve_active_session(req, "socratic", "모르겠어",
                                                     echo=req.socraticState)
    assert is_new is False
    assert session.session_id == "s-echo"
    assert session.turn_index == 3
    assert session.data["hintLevel"] == 1


def test_mode_switch_drops_previous_mode_state():
    req = _req("HashMap이 뭐야?", mode="socratic")
    key = LS.resolve_session_id(req, "socratic")
    LS.save(key, LS.LearningSession(session_id="s1", mode="debate", topic="이전 토론", state="X"))
    _k, session, is_new = LS.resolve_active_session(req, "socratic", "HashMap이 뭐야?")
    assert is_new is True and session is None
