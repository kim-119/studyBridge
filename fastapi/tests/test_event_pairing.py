"""SSE 시퀀서 불변식: start→answer/error 짝, turn_start 1회, all_complete ≤1, done 이후 차단, dedup 계수."""
from app.studymate.sse_contract import Sequencer


def _feed(seq, events):
    out = []
    for n, d in events:
        out.extend(seq.feed(n, d))
    return out


def test_direct_and_reaction_starts_are_not_deduped():
    seq = Sequencer("r", "t", "basic")
    out = _feed(seq, [
        ("turn_start", {}),
        ("agent_start", {"agentId": "101", "actType": "DIRECT_ANSWER", "displayOrder": 1, "phase": "FIRST_DRAFT"}),
        ("agent_answer", {"agentId": "101", "answer": "A", "actType": "DIRECT_ANSWER", "displayOrder": 1}),
        ("agent_start", {"agentId": "101", "actType": "REACTION", "displayOrder": 4, "phase": "REACTION"}),
        ("agent_answer", {"agentId": "101", "answer": "B", "actType": "REACTION", "displayOrder": 4}),
    ])
    names = [n for n, _ in out]
    assert names.count("agent_start") == 2 and names.count("agent_answer") == 2
    assert seq.dedup_dropped == 0


def test_missing_start_is_injected_and_counted():
    seq = Sequencer("r", "t", "basic")
    out = _feed(seq, [("turn_start", {}), ("agent_answer", {"agentId": "7", "answer": "x"})])
    assert [n for n, _ in out] == ["turn_start", "agent_start", "agent_answer"]
    assert any(r.startswith("agent_start_injected") for r in seq.contract_repairs)


def test_open_start_gets_error_before_all_complete():
    seq = Sequencer("r", "t", "basic")
    out = _feed(seq, [("turn_start", {}), ("agent_start", {"agentId": "7"}), ("all_complete", {"answers": []})])
    names = [n for n, _ in out]
    assert names == ["turn_start", "agent_start", "agent_error", "all_complete"]
    assert out[2][1]["code"] == "AGENT_ANSWER_MISSING"


def test_single_turn_start_and_all_complete_and_done_gate():
    seq = Sequencer("r", "t", "basic")
    out = _feed(seq, [("agent_start", {"agentId": "1"}), ("turn_start", {}), ("agent_answer", {"agentId": "1", "answer": "a"}),
                      ("all_complete", {}), ("all_complete", {}), ("agent_answer", {"agentId": "1", "answer": "late"})])
    names = [n for n, _ in out]
    assert names.count("turn_start") == 1 and names[0] == "turn_start"
    assert names.count("all_complete") == 1 and "late" not in str(out)
    seq.done("done", 1)
    assert seq.feed("agent_answer", {"agentId": "1", "answer": "after"}) == []


def test_true_duplicate_is_dropped_and_counted():
    seq = Sequencer("r", "t", "basic")
    ev = {"agentId": "1", "answer": "같은 답", "displayOrder": 1, "actType": "DIRECT_ANSWER"}
    _feed(seq, [("turn_start", {}), ("agent_start", {"agentId": "1", "displayOrder": 1}), ("agent_answer", ev),
                ("agent_answer", dict(ev))])
    assert seq.dedup_dropped == 1
