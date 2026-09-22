from app.studymate.sse_contract import Sequencer, fingerprint


def test_fingerprint_includes_phase_act_order():
    base = {"turnId": "t", "agentId": "1", "stage": "AGENT_START", "content": ""}
    a = fingerprint("agent_start", {**base, "actType": "DIRECT_ANSWER", "displayOrder": 1, "phase": "FIRST_DRAFT"})
    b = fingerprint("agent_start", {**base, "actType": "REACTION", "displayOrder": 4, "phase": "REACTION"})
    assert a != b


def test_different_agents_same_text_not_merged():
    seq = Sequencer("r", "t", "basic")
    seq.feed("turn_start", {})
    seq.feed("agent_start", {"agentId": "1"}); seq.feed("agent_answer", {"agentId": "1", "answer": "같다"})
    seq.feed("agent_start", {"agentId": "2"}); out = seq.feed("agent_answer", {"agentId": "2", "answer": "같다"})
    assert out and seq.dedup_dropped == 0
