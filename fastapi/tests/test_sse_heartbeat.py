"""heartbeat 는 control plane: 답변/이력/커버리지에 포함되지 않고 agentName 등 메시지 필드를 싣지 않는다."""
from app.studymate.sse_contract import Sequencer


def test_heartbeat_is_control_only():
    seq = Sequencer("r", "t", "basic")
    seq.feed("turn_start", {})
    out = seq.feed("heartbeat", {"agentIndex": 2, "agentName": "김교수", "answer": "유령", "elapsedMs": 10})
    assert len(out) == 1
    name, hb = out[0]
    assert name == "heartbeat" and hb["visible"] is False
    assert hb["agentName"] is None and "answer" not in hb and hb["content"] != "유령"
    assert seq.answers == [] and seq.started_ids == []


def test_heartbeat_not_deduped_and_allowed_after_all_complete():
    seq = Sequencer("r", "t", "basic")
    seq.feed("turn_start", {})
    seq.feed("all_complete", {})
    assert seq.feed("heartbeat", {"elapsedMs": 1}) and seq.feed("heartbeat", {"elapsedMs": 1})
