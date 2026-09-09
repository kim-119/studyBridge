"""
모드 라우팅(SSOT) + 모드별 전용 핸들러 디스패치 테스트.

  - 알 수 없는 mode 가 basic 으로 silent fallback 되지 않는다(422).
  - mode 가 없는 legacy 요청만 basic 이다.
  - debate 는 전용 핸들러(run_debate_mode_stream)를 타고, 기본 경로로 내려가지 않는다.
  - basic/socratic/roleplay 는 서로 다른 핸들러 함수로 진입한다.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.schemas.multi_chat_schema import MultiChatRequest
from app.services import mode_router as R
MR = R
from app.services import orchestrator_service as O


# ── 1) 모드 정규화 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("mode,learning,expected", [
    (None, None, R.BASIC),                 # mode 자체가 없는 legacy 요청 → basic
    ("default", None, R.BASIC),
    ("multi_agent_discussion", None, R.BASIC),
    ("debate", None, R.DEBATE),
    (None, "debate", R.DEBATE),
    ("default", "debate", R.DEBATE),       # learningMode 우선
    ("socratic", None, R.SOCRATIC),
    ("simulation", None, R.ROLEPLAY),
    ("roleplay", None, R.ROLEPLAY),
    ("group_study_ai", "basic", R.GROUP_STUDY_AI),
    ("토론", None, R.DEBATE),
])
def test_resolve_mode(mode, learning, expected):
    assert R.resolve_mode(mode, learning) == expected


@pytest.mark.parametrize("mode,learning", [("debat", None), ("토론모드", None), (None, "dabate"), ("nonsense", None)])
def test_unknown_mode_raises(mode, learning):
    with pytest.raises(R.UnsupportedModeError):
        R.resolve_mode(mode, learning)


def test_unknown_mode_falls_back_only_when_strict_disabled(monkeypatch):
    monkeypatch.setenv("AI_STRICT_MODE_VALIDATION", "off")
    assert R.resolve_mode("debat", None) == R.BASIC


def test_error_detail_shape():
    try:
        R.resolve_mode("debat", None)
    except R.UnsupportedModeError as exc:
        detail = R.error_detail(exc)
    assert detail["code"] == "UNSUPPORTED_MODE"
    assert detail["field"] == "mode"
    assert "debate" in detail["supportedModes"]


# ── 2) 스트림 디스패치 ───────────────────────────────────────────────────────
def _req(mode=None, learning=None):
    return MultiChatRequest(
        message="모놀리식과 마이크로서비스 중 대규모 서비스에 더 좋은 선택은?",
        mode=mode or "default", learningMode=learning,
        agents=[{"agentId": "a1", "name": "교수1"}, {"agentId": "a2", "name": "교수2"}],
    )


def _no_llm(monkeypatch):
    """basic 계열 경로가 실제 LLM을 부르지 않도록 막는다."""
    monkeypatch.setattr(O, "_generate_single_agent_answer", lambda *a, **k: "테스트 답변")
    monkeypatch.setattr(O, "_min_gap_seconds", lambda: 0.0)
    monkeypatch.setenv("STUDYMATE_DISCUSSION_PLANNER", "off")


def test_debate_mode_uses_debate_handler(monkeypatch):
    from app.services import debate_mode_handler as H
    called = {}

    def fake_stream(request, agents, llm=None):
        called["mode"] = "debate"
        called["agents"] = len(agents)
        yield {"event": "all_complete", "data": {"type": "all_complete", "mode": "debate"}}

    monkeypatch.setattr(H, "run_debate_mode_stream", fake_stream)
    events = list(O.build_orchestrator_stream(_req(learning="debate"), []))
    assert called["mode"] == "debate"
    assert events[-1]["data"]["mode"] == "debate"


def test_simulation_mode_value_is_not_renamed():
    """UI 명칭이 '상황극'이어도 backend 코드값은 simulation 이어야 한다."""
    assert R.SIMULATION == "simulation"
    assert R.resolve_mode(None, "상황극") == "simulation"
    assert R.resolve_mode("roleplay", None) == "simulation"


def test_debate_mode_never_enters_generic_agent_turn(monkeypatch):
    from app.services import debate_mode_handler as H

    def boom(*a, **k):
        raise AssertionError("debate 가 기본(per-agent) 경로로 내려갔다")

    monkeypatch.setattr(O, "_run_agent_turn_stream", boom)
    monkeypatch.setattr(H, "run_debate_mode_stream",
                        lambda request, agents, llm=None: iter([{"event": "all_complete", "data": {}}]))
    list(O.build_orchestrator_stream(_req(learning="debate"), []))


@pytest.mark.parametrize("learning,module_name,func_name", [
    ("debate", "app.services.debate_mode_handler", "run_debate_mode_stream"),
    ("socratic", "app.services.socratic_mode_handler", "run_socratic_mode_stream"),
    ("simulation", "app.services.simulation_mode_handler", "run_simulation_mode_stream"),
])
def test_each_dedicated_mode_has_its_own_handler(monkeypatch, learning, module_name, func_name):
    """각 모드가 서로 다른 실행 함수를 탄다(공통 ask_ollama 1회 + 프롬프트 교체가 아니다)."""
    import importlib
    module = importlib.import_module(module_name)
    called = {}

    def fake(request, agents, llm=None):
        called["func"] = func_name
        yield {"event": "all_complete", "data": {"type": "all_complete", "mode": learning}}

    monkeypatch.setattr(module, func_name, fake)
    monkeypatch.setattr(O, "_run_agent_turn_stream",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("basic 경로로 폴백")))
    events = list(O.build_orchestrator_stream(_req(learning=learning), _req().agents))
    assert called["func"] == func_name
    assert events[-1]["event"] == "all_complete"


def test_basic_mode_uses_basic_handler(monkeypatch):
    _no_llm(monkeypatch)
    seen = {}
    original = O._run_agent_turn_stream

    def spy(request, agents, effective_mode, *a, **k):
        seen["mode"] = effective_mode
        return original(request, agents, effective_mode, *a, **k)

    monkeypatch.setattr(O, "_run_agent_turn_stream", spy)
    assert callable(O.run_basic_mode_stream)
    events = list(O.build_orchestrator_stream(_req(learning="basic"), _req().agents))
    assert seen["mode"] == "basic"
    assert events[-1]["event"] == "all_complete"


# ── 3) HTTP 계약: 알 수 없는 mode → 422 ──────────────────────────────────────
@pytest.fixture()
def stream_client():
    from multi_chat_stream_compat import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_stream_rejects_unknown_mode(stream_client):
    resp = stream_client.post("/api/ai/multi-chat/stream",
                              json={"message": "테스트", "mode": "debat", "agents": []})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "UNSUPPORTED_MODE"


def test_stream_accepts_missing_mode(stream_client, monkeypatch):
    """mode 없는 legacy 요청은 basic 으로 통과(스트림이 열린다)."""
    from app.services import multi_agent_service as M
    monkeypatch.setattr(M, "build_stream_generator",
                        lambda req: iter([{"event": "all_complete", "data": {"type": "all_complete"}}]))
    resp = stream_client.post("/api/ai/multi-chat/stream", json={"message": "테스트", "agents": []})
    assert resp.status_code == 200


def test_legacy_spring_stage_mode_is_not_rejected():
    """Spring ChatService 의 3단계 흐름은 mode='single_answer' 로 multi-chat 을 부른다.
    STRICT MODE 가 이 값을 422 로 막으면 라이브 기본 답변 흐름이 통째로 죽는다."""
    assert MR.resolve_mode("single_answer", "basic") == MR.BASIC
    assert MR.resolve_mode("single-answer", None) == MR.BASIC
    # 그룹스터디/협업 레거시 값도 basic 파이프라인으로 통과해야 한다.
    for legacy in ("validation", "collaboration", "single", "non-stream", "stage"):
        assert MR.resolve_mode(legacy, None) == MR.BASIC
