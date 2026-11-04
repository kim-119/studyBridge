"""stream_gate(공유 스트림 경계) 강화 회귀: 버퍼/취소/재접속/동시성/중복/알 수 없는 타입/상한/오류 계약/전송 어댑터.

각 시나리오의 수정 전 동작(2026-11-04 재현): error 문구가 승인 답변에 섞여 노출, follow_up 같은 미지 타입이 답변으로 방출,
64자 이하 임의 문장이 진행 이벤트로 통과, 평가기 예외가 스트림을 죽임, 중복 2회 방출, 40MB 무제한 버퍼링, 취소 시 상류 미종료.
"""
import asyncio
import json
import random

import pytest

from app.contracts.response_quality_v1 import QualityOutput
from app.quality_gate import stream_gate as G
from app.quality_gate.stream_gate import StreamGatePolicy, gate_event_stream


def run(c):
    return asyncio.run(c)


async def _src(events):
    for e in events:
        yield e


async def _collect(g):
    return [e async for e in g]


def _q(ok: bool, codes=(), rid="req-hard-000001"):
    from app.contracts.response_quality_v1 import Severity, Violation
    return QualityOutput(schemaVersion="response-quality.v1", requestId=rid, taskType="GENERAL_EXPLANATION", success=ok, verified=ok,
                         qualityStatus="APPROVED" if ok else "REJECTED", score=90.0 if ok else 40.0, hardFail=not ok,
                         evaluatorVersion="test",
                         violations=[Violation(code=c, severity=Severity.HARD, reason="test") for c in codes])


def approve_if(pred):
    calls = []

    async def ev(key, text, msg, rid):
        calls.append((key, text))
        return _q(pred(text), () if pred(text) else ("TEST_REJECT",), rid)
    ev.calls = calls
    return ev


APPROVE = approve_if(lambda t: True)
DENY = approve_if(lambda t: False)


def gate(events, ev=None, **kw):
    return run(_collect(gate_event_stream(_src(events), ev or approve_if(lambda t: True), **kw)))


# ── 오류 계약 ────────────────────────────────────────────────────────────────
def test_error_event_text_is_dropped_and_partial_buffer_discarded():
    out = gate([{"event": "token", "data": {"agentId": "a", "delta": "부분 답변 "}},
                {"event": "error", "data": {"agentId": "a", "code": "AGENT_TIMEOUT",
                                            "message": "Traceback psycopg host=10.0.3.7 password failed"}},
                {"event": "done", "data": {}}])
    assert "10.0.3.7" not in json.dumps(out, ensure_ascii=False) and "부분 답변" not in json.dumps(out, ensure_ascii=False)
    err = [e for e in out if e["event"] == "error"]
    # 이벤트 이름과 코드 필드 이름(code)은 원 계약 그대로, 문구만 버린다
    assert err == [{"event": "error", "data": {"agentId": "a", "code": "AGENT_TIMEOUT"}}]


def test_error_code_that_is_not_a_code_is_replaced():
    out = gate([{"event": "error", "data": {"code": "DB 접속 실패: host=10.0.3.7"}}])
    assert out == [{"event": "error", "data": {"code": "UPSTREAM_ERROR"}}]


def test_evaluator_exception_is_validation_error_and_stream_continues():
    async def boom(key, text, msg, rid):
        if "첫" in text:
            raise RuntimeError("evaluator down")
        return _q(True, (), rid)
    out = gate([{"event": "agent_answer", "data": {"agentId": "a", "content": "첫 답"}},
                {"event": "agent_answer", "data": {"agentId": "b", "content": "둘째 답"}},
                {"event": "done", "data": {}}], boom)
    assert out[0]["event"] == "quality_rejected" and out[0]["data"]["qualityStatus"] == "VALIDATION_ERROR"
    assert out[0]["data"]["codes"] == ["EVALUATOR_ERROR"] and "첫 답" not in json.dumps(out, ensure_ascii=False)
    assert [e["event"] for e in out[1:]] == ["agent_answer", "done"]


def test_evaluator_timeout_is_validation_error():
    async def slow(key, text, msg, rid):
        await asyncio.sleep(5)
        return _q(True)
    out = gate([{"event": "agent_answer", "data": {"content": "답"}}], slow,
               policy=StreamGatePolicy(evaluate_timeout_s=0.05))
    assert out == [G._rejected("t:main", "VALIDATION_ERROR", ["EVALUATOR_TIMEOUT"])]


def test_source_exception_discards_truncated_body_and_reports_stable_code():
    async def broken():
        yield {"event": "token", "data": {"delta": "잘린 본문 일부"}}
        raise ConnectionResetError("upstream reset 10.0.3.7")
    out = run(_collect(gate_event_stream(broken(), APPROVE)))
    assert out == [{"event": "error", "data": {"errorCode": "STREAM_SOURCE_ERROR", "code": "STREAM_SOURCE_ERROR"}}]


# ── 알 수 없는 타입/식별자 필드 ────────────────────────────────────────────────
def test_unknown_event_never_forwarded_nor_merged_into_answers():
    out = gate([{"event": "agent_answer", "data": {"agentId": "a", "content": "답변 본문"}},
                {"event": "mystery", "data": {"agentId": "a", "text": "UNRELATED-TAIL"}},
                {"event": "done", "data": {}}])
    s = json.dumps(out, ensure_ascii=False)
    assert "UNRELATED-TAIL" not in s
    assert [e["event"] for e in out] == ["agent_answer", "quality_rejected", "done"]
    assert out[1]["data"]["codes"] == ["UNKNOWN_EVENT_TYPE"]


def test_progress_ids_only_rejects_sentences_but_keeps_ids_and_names():
    out = gate([{"event": "progress", "data": {"status": "정답은 2번이고 비밀번호는 hunter2", "stage": "STAGE_1",
                                               "agentName": "김교수", "turnId": "turn 1 has spaces",
                                               "message": "임의 문구", "answerIndex": 2}}])
    d = out[0]["data"]
    assert d == {"stage": "STAGE_1", "agentName": "김교수"}


def test_message_key_parts_are_sanitized():
    out = gate([{"event": "agent_answer", "data": {"turnId": "정답은 2번", "agentId": "a", "content": "답"}}], DENY)
    assert "정답은" not in json.dumps(out, ensure_ascii=False)
    assert out[0]["data"]["messageKey"].startswith("h")


# ── 중복/재접속/메시지 경계 ───────────────────────────────────────────────────
def test_duplicate_message_is_evaluated_and_emitted_once():
    ev = approve_if(lambda t: True)
    m = {"event": "agent_answer", "data": {"turnId": "t1", "agentId": "a", "content": "같은 답"}}
    out = gate([m, m, {"event": "agent_answer", "data": {"turnId": "t1", "agentId": "a", "content": "다른 답"}}], ev)
    assert [e["data"].get("content") for e in out] == ["같은 답", "다른 답"] and len(ev.calls) == 2


def test_reconnect_is_a_fresh_gate_and_preserves_sse_ids():
    frames = ("id: e1\nevent: agent_answer\ndata: {\"agentId\":\"a\",\"content\":\"첫 연결 답\"}\n\n"
              "id: e2\nevent: done\ndata: {}\n\n")

    async def chunks():
        yield frames

    async def go(ev):
        return [s async for s in G.wrap_sse_stream(chunks(), ev)]
    first = run(go(APPROVE))
    second = run(go(DENY))           # 재접속이 이전 승인을 재사용하지 않는다(상태는 연결마다 새로)
    assert first[0].startswith("id: e1\nevent: agent_answer") and "첫 연결 답" in first[0]
    assert "첫 연결 답" not in "".join(second) and "quality_rejected" in second[0]
    assert second[-1].startswith("id: e2\nevent: done")


def test_interleaved_agents_and_phases_keep_separate_buffers():
    ev = approve_if(lambda t: True)
    gate([{"event": "delta", "data": {"agentId": "a", "phase": "draft", "content": "A초안 "}},
          {"event": "delta", "data": {"agentId": "b", "content": "B답 "}},
          {"event": "delta", "data": {"agentId": "a", "phase": "final", "content": "A최종"}},
          {"event": "delta", "data": {"agentId": "a", "phase": "draft", "content": "계속"}},
          {"event": "done", "data": {}}], ev)
    assert sorted(t for _, t in ev.calls) == sorted(["A초안 계속", "A최종", "B답 "])


# ── 상한 ─────────────────────────────────────────────────────────────────────
def test_message_size_cap_rejects_and_bounds_memory():
    pol = StreamGatePolicy(max_message_chars=1000)
    ev = approve_if(lambda t: True)
    events = [{"event": "token", "data": {"delta": "가" * 100}} for _ in range(50)] + [{"event": "done", "data": {}}]
    out = gate(events, ev, policy=pol)
    assert out[0]["data"]["codes"] == ["STREAM_MESSAGE_TOO_LARGE"] and ev.calls == []


def test_total_buffer_cap_and_open_message_cap():
    pol = StreamGatePolicy(max_message_chars=10_000, max_total_chars=1500, max_open_messages=3)
    events = [{"event": "token", "data": {"agentId": f"a{i}", "delta": "x" * 600}} for i in range(5)]
    out = gate(events + [{"event": "done", "data": {}}], APPROVE, policy=pol)
    codes = [c for e in out if e["event"] == "quality_rejected" for c in e["data"]["codes"]]
    assert "STREAM_BUFFER_LIMIT" in codes and "STREAM_MESSAGE_TOO_LARGE" in codes
    assert sum(1 for e in out if e["event"] == "token" and "content" not in e["data"] and e["data"].get("delta")) == 2


def test_frame_without_delimiter_cannot_grow_unbounded():
    async def chunks():
        for _ in range(100):
            yield "data: " + "x" * 10_000

    async def go():
        return [s async for s in G.wrap_sse_stream(chunks(), APPROVE)]
    out = run(go())
    assert out == ['event: error\ndata: {"errorCode": "STREAM_SOURCE_ERROR", "code": "STREAM_SOURCE_ERROR"}\n\n']


# ── 취소/동시성 ───────────────────────────────────────────────────────────────
def test_consumer_close_and_task_cancel_close_the_upstream():
    state = {"closed": 0}

    async def upstream():
        try:
            for i in range(1000):
                yield {"event": "progress", "data": {"stage": i}}
                await asyncio.sleep(0)
        finally:
            state["closed"] += 1

    async def close_early():
        g = gate_event_stream(upstream(), APPROVE)
        await g.__anext__()
        await g.aclose()

    async def cancel_during_eval():
        async def hang(key, text, msg, rid):
            await asyncio.sleep(10)

        async def up2():
            try:
                yield {"event": "agent_answer", "data": {"content": "답"}}
                yield {"event": "done", "data": {}}
            finally:
                state["closed"] += 1
        t = asyncio.create_task(_collect(gate_event_stream(up2(), hang)))
        await asyncio.sleep(0.05)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
    run(close_early())
    run(cancel_during_eval())
    assert state["closed"] == 2


def test_concurrent_streams_do_not_share_state():
    async def one(i):
        evs = [{"event": "delta", "data": {"agentId": "a", "content": f"S{i}-"}} for _ in range(5)]
        evs.append({"event": "agent_answer", "data": {"agentId": "b", "content": f"S{i}-OK" if i % 2 else f"S{i}-NO"}})
        evs.append({"event": "done", "data": {}})

        async def ev(key, text, msg, rid):
            await asyncio.sleep(random.random() / 100)
            return _q(text.endswith("OK") or text.startswith(f"S{i}-S{i}"), (), rid)
        return i, await _collect(gate_event_stream(_src(evs), ev))

    async def go():
        return await asyncio.gather(*(one(i) for i in range(40)))
    for i, out in run(go()):
        s = json.dumps(out, ensure_ascii=False)
        others = [f"S{j}-" for j in range(40) if j != i]
        assert not any(o in s for o in others)
        assert (f"S{i}-OK" in s) == bool(i % 2) and f"S{i}-NO" not in s


# ── 전송 어댑터(SSE/NDJSON) ──────────────────────────────────────────────────
def test_sse_parser_handles_arbitrary_chunking_crlf_multiline_and_comments():
    raw = ("event: turn_start\r\ndata: {\"type\":\"turn_start\",\"turnId\":\"t1\"}\r\n\r\n"
           ": keepalive\n\n"
           "data: {\"type\":\"agent_answer\",\"agentId\":\"a\",\n"
           "data:  \"content\":\"여러 줄\"}\n\n"
           "data: {\"type\":\"all_complete\",\"messages\":[\"미검증 묶음\"]}\n\n")
    rnd = random.Random(7)

    async def chunks():
        i = 0
        while i < len(raw):
            n = rnd.randint(1, 7)
            yield raw[i:i + n].encode()
            i += n

    async def go():
        return [s async for s in G.wrap_sse_stream(chunks(), APPROVE)]
    out = run(go())
    assert out[0] == 'event: turn_start\ndata: {"turnId": "t1", "type": "turn_start"}\n\n'
    assert out[1] == ": keepalive\n\n"
    ans = json.loads(out[2].split("data: ", 1)[1])
    assert ans["type"] == "agent_answer" and ans["content"] == "여러 줄"        # data.type 스타일 유지
    assert "미검증 묶음" not in "".join(out) and out[-1].startswith("data: ")


def test_ndjson_partial_lines_and_non_json_line_is_gated_as_body():
    raw = '{"type":"status","phase":"p","message":"진행 문구"}\n{"type":"delta","content":"본문"}\n{"type":"done"}\nNOT JSON SECRET\n'

    async def chunks():
        for i in range(0, len(raw), 5):
            yield raw[i:i + 5]

    async def go(ev):
        return [json.loads(s) async for s in G.wrap_ndjson_stream(chunks(), ev)]
    out = run(go(approve_if(lambda t: "SECRET" not in t)))
    assert out[0] == {"phase": "p", "type": "status"}
    # delta 계약은 유지: 같은 type/필드로 '승인된 전문'을 한 번 보낸다(미승인 조각은 0회)
    assert out[1] == {"type": "delta", "content": "본문",
                      "quality": {"qualityStatus": "APPROVED", "score": 90.0, "evaluatorVersion": "test"}}
    assert out[2]["type"] == "done" and out[-1]["type"] == "quality_rejected"
    assert "SECRET" not in json.dumps(out) and out[-1]["codes"] == ["TEST_REJECT"]


def test_structured_quiz_events_are_gated_as_json_not_ui_phrase():
    qs = [{"question": "TCP 연결 단계 수는?", "choices": ["1", "2", "3", "4"], "answer": "3"}]
    ev = approve_if(lambda t: "TCP" in t)
    out = gate([{"event": "partial_validated", "data": {"message": "검증된 문제를 표시하고 있습니다.",
                                                         "questions": qs, "validatedCount": 1}},
                {"event": "complete", "data": {"success": True, "questions": qs, "message": "완료", "totalCount": 1}}], ev)
    assert all("검증된 문제" not in t for _, t in ev.calls) and len(ev.calls) == 1      # 같은 문항은 한 번만 평가
    assert out[0] == {"event": "partial_validated", "data": {"validatedCount": 1, "questions": qs,
                                                               "quality": {"qualityStatus": "APPROVED", "score": 90.0,
                                                                           "evaluatorVersion": "test"}}}
    # 최종 complete 는 같은 본문의 기존 판정을 재사용해(재평가 없이) 계약대로 questions 를 싣는다
    assert out[1] == {"event": "complete", "data": {"success": True, "totalCount": 1, "questions": qs,
                                                      "quality": out[0]["data"]["quality"]}}


def test_structured_terminal_rejected_still_terminates_without_body():
    qs = [{"question": "틀린 문항", "choices": ["a", "b"], "answer": "c"}]
    out = gate([{"event": "complete", "data": {"success": True, "questions": qs}}], DENY)
    assert [e["event"] for e in out] == ["quality_rejected", "complete"]
    assert "틀린 문항" not in json.dumps(out, ensure_ascii=False)


# ── 학습메이트(studymate-sse-2) 계약 호환 ────────────────────────────────────
def test_all_complete_answers_rebuilt_from_approved_only():
    ev = approve_if(lambda t: "OK" in t)
    out = gate([{"event": "agent_answer", "data": {"turnId": "t1", "agentId": "a1", "eventId": "e1", "content": "A OK"}},
                {"event": "agent_answer", "data": {"turnId": "t1", "agentId": "a2", "eventId": "e2", "content": "B bad"}},
                {"event": "all_complete", "data": {"turnId": "t1", "eventId": "e3",
                                                   "answers": [{"agentId": "a1", "content": "A OK", "answer": "A OK"},
                                                               {"agentId": "a2", "content": "B bad"},
                                                               {"agentId": "a3", "content": "C never streamed OK"}],
                                                   "messages": [{"agentId": "a2", "content": "B bad"}]}}], ev)
    fin = out[-1]["data"]
    assert [a["agentId"] for a in fin["answers"]] == ["a1", "a3"] and fin["messages"] == []
    assert "B bad" not in json.dumps(out, ensure_ascii=False) and fin["eventId"] == "e3"
    assert len(ev.calls) == 3          # 'A OK' 는 스트림에서 이미 판정 → 재평가 없음


def test_studymate_policy_reports_rejection_as_existing_agent_error_contract():
    pol = G.ROUTE_POLICIES["studymate"]
    out = gate([{"event": "agent_answer", "data": {"type": "agent_answer", "eventType": "agent_answer", "turnId": "t1",
                                                   "agentId": "agent-2", "agentIndex": 2, "eventId": "ev-9",
                                                   "content": "검증 실패할 답", "answer": "검증 실패할 답"}}], DENY, policy=pol)
    assert out == [{"event": "agent_error", "data": {
        "turnId": "t1", "agentId": "agent-2", "type": "agent_answer", "eventId": "ev-9", "eventType": "agent_error",
        "agentIndex": 2, "code": "QUALITY_REJECTED", "status": "FAILED", "degraded": True,
        "message": pol.reject_message, "qualityStatus": "REJECTED", "qualityCodes": ["TEST_REJECT"]}}]


def test_sidecar_text_fields_are_evaluated_with_the_message():
    ev = approve_if(lambda t: "sk-proj" not in t)
    out = gate([{"event": "agent_answer", "data": {"agentId": "a", "content": "정상 본문",
                                                   "question": "숨은 sk-proj-ABCDEFGHIJKLMNOPQRSTUV", "followUps": ["X-LIST"]}}], ev)
    assert "sk-proj" not in json.dumps(out) and "정상 본문" not in json.dumps(out, ensure_ascii=False)
    ok = gate([{"event": "agent_answer", "data": {"agentId": "a", "content": "본문", "answer": "본문",
                                                  "question": "되묻는 질문?", "followUps": ["X-LIST"]}}])
    assert ok[0]["data"]["content"] == "본문" and ok[0]["data"]["question"] == "되묻는 질문?"
    assert "X-LIST" not in json.dumps(ok)
