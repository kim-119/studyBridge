"""ZeroMQ 내부 이벤트 버스 + contract 스트림 래퍼 테스트.

대상: app/services/agent_event_bus.py (신규)

핵심 계약:
  - AgentEventBus.roundtrip(envelope)는 envelope를 그대로(동치) 돌려준다.
    backend=queue(기본)는 순수 passthrough. backend=zmq는 inproc 왕복.
  - bus 장애는 절대 전파되지 않는다 → roundtrip은 실패 시 입력을 그대로 반환하고
    transport를 queue로 강등(degrade)한다.
  - stream_with_contract는 raw {"event","data"} 제너레이터의 모든 이벤트에
    turnId/eventId/stage/fingerprint/createdAt/isFinal 을 부착하고,
    같은 fingerprint 재발행/ all_complete 이후 answer류를 drop한다.
  - error 이벤트에는 code/reason/turnId/stage 가 포함된다.
  - bus.roundtrip이 예외를 던져도 스트림은 끊기지 않고 모든 이벤트를 흘려보낸다.
"""
import pytest

from app.services import agent_event_bus as B


def _drain(gen):
    return [(it["event"], it["data"]) for it in gen]


# ── AgentEventBus ──────────────────────────────────────────────────────────

def test_queue_backend_is_identity_passthrough():
    bus = B.AgentEventBus(backend="queue")
    assert bus.transport == "queue"
    env = {"eventId": "e1", "turnId": "t1", "stage": "FIRST_ANSWER", "content": "본문"}
    out = bus.roundtrip(env)
    assert out == env
    assert bus.healthy is True
    bus.close()


def test_zmq_backend_roundtrip_preserves_envelope():
    pytest.importorskip("zmq")
    bus = B.AgentEventBus(backend="zmq")
    if bus.transport != "zmq":
        pytest.skip("zmq 초기화 실패 → queue 강등(환경 의존)")
    env = {"eventId": "e1", "turnId": "t1", "stage": "FIRST_ANSWER", "content": "한글 본문 ✓"}
    out = bus.roundtrip(env)
    assert out == env
    assert bus.healthy is True
    bus.close()


def test_roundtrip_failure_degrades_to_queue_without_raising():
    bus = B.AgentEventBus(backend="zmq")
    if bus.transport != "zmq":
        pytest.skip("zmq 미가용")
    # 전송 소켓을 깨뜨려 강제 실패 → passthrough + queue 강등
    bus._push = object()  # send_json 없음 → 예외
    env = {"eventId": "e1", "content": "x"}
    out = bus.roundtrip(env)        # 예외를 던지면 안 된다
    assert out == env
    assert bus.transport == "queue"
    assert bus.healthy is False
    bus.close()


def test_get_bus_returns_singleton():
    assert B.get_bus() is B.get_bus()


# ── stream_with_contract ───────────────────────────────────────────────────

def test_stream_enriches_every_event_with_envelope_keys():
    raw = [
        {"event": "turn_start", "data": {"message": "시작"}},
        {"event": "agent_answer", "data": {"agentId": "a1", "content": "첫 답변", "stageType": "FIRST_ANSWER"}},
        {"event": "all_complete", "data": {"answers": []}},
    ]
    out = _drain(B.stream_with_contract(iter(raw), mode="default", turn_id="T"))
    for _, data in out:
        for k in ("eventId", "turnId", "mode", "stage", "fingerprint", "createdAt", "isFinal"):
            assert k in data, f"missing {k}"
        assert data["turnId"] == "T"
        assert data["mode"] == "default"


def test_stream_drops_duplicate_fingerprint():
    raw = [
        {"event": "agent_answer", "data": {"agentId": "a1", "content": "같은 본문", "stageType": "FIRST_ANSWER"}},
        {"event": "agent_answer", "data": {"agentId": "a1", "content": "같은   본문", "stageType": "FIRST_ANSWER"}},
    ]
    out = _drain(B.stream_with_contract(iter(raw), mode="default", turn_id="T"))
    assert len(out) == 1  # 공백만 다른 동일 본문 → 1개만


def test_stream_preserves_stage_order_and_gates_after_all_complete():
    raw = [
        {"event": "agent_answer", "data": {"agentId": "a1", "content": "1차", "stageType": "FIRST_ANSWER"}},
        {"event": "agent_answer", "data": {"agentId": "a1", "content": "검증 요약", "stageType": "VALIDATION"}},
        {"event": "agent_answer", "data": {"agentId": "a1", "content": "상호 피드백", "stageType": "PEER_FEEDBACK"}},
        {"event": "all_complete", "data": {"answers": []}},
        {"event": "agent_answer", "data": {"agentId": "a2", "content": "늦게 온 답변", "stageType": "FIRST_ANSWER"}},
    ]
    out = _drain(B.stream_with_contract(iter(raw), mode="default", turn_id="T"))
    stages = [d["stage"] for _, d in out]
    assert stages == ["FIRST_ANSWER", "VALIDATION", "PEER_FEEDBACK", "ALL_COMPLETE"]
    # all_complete 이후 늦은 answer는 drop


def test_stream_error_event_has_code_reason_turnid_stage():
    raw = [{"event": "error", "data": {"detail": "boom", "message": "AI 오류"}}]
    out = _drain(B.stream_with_contract(iter(raw), mode="socratic", turn_id="T"))
    assert len(out) == 1
    _, data = out[0]
    assert data["stage"] == "ERROR"
    assert data["turnId"] == "T"
    assert data.get("code")            # 기본 code 부여
    assert data.get("reason")          # detail/message로부터 reason 부여


def test_stream_survives_bus_roundtrip_exception():
    class ExplodingBus:
        transport = "zmq"
        healthy = True
        def roundtrip(self, env):
            raise RuntimeError("bus down")

    raw = [
        {"event": "turn_start", "data": {}},
        {"event": "agent_answer", "data": {"agentId": "a1", "content": "본문", "stageType": "FIRST_ANSWER"}},
        {"event": "all_complete", "data": {}},
    ]
    out = _drain(B.stream_with_contract(iter(raw), mode="default", turn_id="T", bus=ExplodingBus()))
    # bus가 폭발해도 모든 이벤트가 그대로 흘러나온다(파이썬 경로 fallback)
    assert [e for e, _ in out] == ["turn_start", "agent_answer", "all_complete"]
    for _, d in out:
        assert d["turnId"] == "T"  # 그래도 envelope는 부착
