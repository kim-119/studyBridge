"""모든 SSE 이벤트가 타입드 계약 필드를 갖는다."""
from app.studymate.sse_contract import CONTRACT_VERSION, SSEEvent, Sequencer

REQUIRED = ("contractVersion", "eventId", "requestId", "turnId", "eventType", "mode", "stage", "agentId",
            "agentIndex", "agentName", "status", "code", "degraded", "isFinal", "createdAt", "content")


def test_every_event_has_contract_fields():
    seq = Sequencer("req_1", "turn_1", "basic")
    out = []
    for n, d in [("turn_start", {}), ("agent_start", {"agentId": 5, "agentIndex": "2", "agentName": "김"}),
                 ("agent_answer", {"agentId": 5, "answer": "안녕 😀"}), ("heartbeat", {"agentIndex": 2}),
                 ("follow_up_suggestions", {"suggestions": []}), ("all_complete", {"answers": []})]:
        out.extend(seq.feed(n, d))
    out.append(seq.done("done", 10))
    for name, data in out:
        for k in REQUIRED:
            assert k in data, (name, k)
        SSEEvent(**data)
        assert data["contractVersion"] == CONTRACT_VERSION and data["requestId"] == "req_1"
    ac = [d for n, d in out if n == "all_complete"][0]
    assert ac["isFinal"] is True
    ans = [d for n, d in out if n == "agent_answer"][0]
    assert ans["agentId"] == 5 and ans["content"] == "안녕 😀"


def test_error_event_type_is_stream_error():
    from app.studymate.sse_contract import envelope
    e = envelope("error", {"code": "STREAM_ERROR"}, request_id="r", turn_id="t", mode="basic")
    assert e["eventType"] == "stream_error" and e["agentId"] is None and e["agentIndex"] is None
