"""SSE 선노출 방지 + /api/ai/quality/evaluate 내부 API(인증/플래그/크기/멱등/rate/동시성)."""
import asyncio
import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts.response_quality_v1 import SCHEMA_VERSION, QualityInput
from app.quality_gate import evaluator as E
from app.quality_gate.stream_gate import gate_event_stream
from tests.lq_helpers import INTERNAL_KEY, fixture

EV = [{"sourceType": "PDF_ORIGINAL", "materialId": 42, "page": 12, "chunkId": "m42-c7",
       "text": "3-way handshake 는 SYN, SYN-ACK, ACK 세 단계로 연결을 수립한다."}]


def run(c):
    return asyncio.run(c)


async def _collect(gen):
    return [e async for e in gen]


async def _source(events):
    for e in events:
        yield e


def _eval_factory():
    async def evaluate_message(key, text, msg, rid):
        q = QualityInput.model_validate({"schemaVersion": SCHEMA_VERSION, "requestId": rid,
                                         "taskType": "PDF_QA", "outputKind": "agent_message",
                                         "originalRequest": "3-way handshake 단계는?", "proposedOutput": text,
                                         "groundingEvidence": EV, "constraints": {"allowedMaterialIds": [42]}})
        return await E.evaluate(q)
    return evaluate_message


def test_progress_passes_content_buffered_until_approved():
    E.clear_cache()
    events = [
        {"event": "turn_start", "data": {"turnId": "t1"}},
        {"event": "token", "data": {"turnId": "t1", "agentId": "a1", "delta": "3-way handshake 는 SYN, SYN-ACK, "}},
        {"event": "progress", "data": {"stage": 1}},
        {"event": "token", "data": {"turnId": "t1", "agentId": "a1", "delta": "ACK 세 단계로 연결을 수립한다."}},
        {"event": "token", "data": {"turnId": "t1", "agentId": "a2", "delta": "3-way handshake 는 1999년에 5 단계로 바뀌었다."}},
        {"event": "all_complete", "data": {"messages": [{"content": "미검증 본문 묶음"}], "turnId": "t1"}},
    ]
    approved = []

    async def on_ok(k, t, q):
        approved.append(k)
    out = run(_collect(gate_event_stream(_source(events), _eval_factory(), on_approved=on_ok)))
    kinds = [e["event"] for e in out]
    # 진행 이벤트는 즉시. 토큰 '조각'은 한 번도 그대로 나가지 않고, 승인된 메시지만 같은 token 계약으로 전문 1회 나간다.
    assert kinds[:2] == ["turn_start", "progress"]
    ok = [e for e in out if e["event"] == "token"]
    assert [e["data"]["delta"] for e in ok] == ["3-way handshake 는 SYN, SYN-ACK, ACK 세 단계로 연결을 수립한다."]
    rej = [e for e in out if e["event"] == "quality_rejected"]
    assert len(ok) == 1 and ok[0]["data"]["quality"]["qualityStatus"] == "APPROVED"
    assert len(rej) == 1 and "content" not in rej[0]["data"] and "1999" not in str(rej[0])
    final = out[-1]
    # all_complete.messages[] 는 '승인된 항목만'으로 다시 만든다(미검증 묶음은 빠진다)
    assert final["event"] == "all_complete" and final["data"]["messages"] == []
    assert approved == ["t1:a1"]


def test_unknown_event_types_are_buffered_not_forwarded():
    E.clear_cache()
    events = [{"event": "mystery_payload", "data": {"text": "PWNED 비밀"}}, {"event": "done", "data": {}}]
    out = run(_collect(gate_event_stream(_source(events), _eval_factory())))
    assert all("PWNED" not in str(e) or e["event"] == "quality_rejected" for e in out)
    assert any(e["event"] == "quality_rejected" for e in out)


def test_collection_callback_failure_does_not_break_stream():
    E.clear_cache()

    async def on_ok(k, t, q):
        raise RuntimeError("db down")
    events = [{"event": "agent_answer", "data": {"turnId": "t", "agentId": "a",
                                                 "content": "3-way handshake 는 SYN, SYN-ACK, ACK 세 단계로 연결을 수립한다."}}]
    out = run(_collect(gate_event_stream(_source(events), _eval_factory(), on_approved=on_ok)))
    assert out[0]["event"] == "agent_answer"


# ── /api/ai/quality/evaluate ─────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AI_SERVER_API_KEY", INTERNAL_KEY)
    monkeypatch.setenv("AI_QUALITY_EVALUATE_API_ENABLED", "true")
    monkeypatch.delenv("AI_QUALITY_JUDGE", raising=False)
    from app.quality_gate import routes as R
    R.RATE.reset()
    R.IDEMPOTENCY.reset()
    E.clear_cache()
    app = FastAPI()
    app.include_router(R.router)
    return TestClient(app)


H = {"Authorization": f"Bearer {INTERNAL_KEY}"}


def test_api_fail_closed_and_feature_flag(client, monkeypatch):
    body = fixture("response-quality.v1", "input_pdf_summary_faithful.json")
    assert client.post("/api/ai/quality/evaluate", json=body).status_code == 401
    monkeypatch.delenv("AI_SERVER_API_KEY")
    assert client.post("/api/ai/quality/evaluate", json=body, headers=H).status_code == 503
    monkeypatch.setenv("AI_SERVER_API_KEY", INTERNAL_KEY)
    monkeypatch.setenv("AI_QUALITY_EVALUATE_API_ENABLED", "false")
    r = client.post("/api/ai/quality/evaluate", json=body, headers=H)
    assert r.status_code == 503 and r.json()["errorCode"] == "FEATURE_DISABLED"


def test_api_evaluates_and_is_idempotent(client):
    body = fixture("response-quality.v1", "input_pdf_summary_faithful.json")
    r1 = client.post("/api/ai/quality/evaluate", json=body, headers=H)
    assert r1.status_code == 200 and r1.json()["qualityStatus"] == "APPROVED" and r1.json()["minimumScore"] == 80
    r2 = client.post("/api/ai/quality/evaluate", json=body, headers=H)
    assert r2.headers.get("Idempotent-Replay") == "true" and r2.json() == r1.json()
    other = copy.deepcopy(body)
    other["proposedOutput"] += " 추가"
    assert client.post("/api/ai/quality/evaluate", json=other, headers=H).status_code == 409


def test_api_rejects_contradiction_unknown_fields_and_malformed(client):
    r = client.post("/api/ai/quality/evaluate", json=fixture("response-quality.v1", "input_pdf_summary_contradiction.json"), headers=H)
    assert r.status_code == 200 and r.json()["qualityStatus"] == "REJECTED" and r.json()["hardFail"] is True
    bad = client.post("/api/ai/quality/evaluate", json=fixture("response-quality.v1", "invalid_unknown_constraint.json"), headers=H)
    assert bad.status_code == 422 and bad.json()["errorCode"] == "CONTRACT_VALIDATION_FAILED"
    assert "..." not in bad.text   # 입력 원문을 되돌려주지 않는다
    mal = client.post("/api/ai/quality/evaluate", content=b"{not json", headers={**H, "Content-Type": "application/json"})
    assert mal.status_code == 422


def test_api_payload_limit(client):
    # Phase D R5-9: 바이트 상한은 계약 최대치(문자 기준)에서 유도한 값이다. 그 안에 들지만 계약(6만 자)을 넘는 본문은
    # 계약 위반 422, 바이트 상한 자체를 넘는 본문은 413(파싱 전 차단).
    from app.quality_gate.routes import MAX_BODY_BYTES
    body = fixture("response-quality.v1", "input_pdf_summary_faithful.json")
    body["proposedOutput"] = "가" * 300000
    r = client.post("/api/ai/quality/evaluate", json=body, headers=H)
    assert r.status_code == 422 and r.json()["errorCode"] == "CONTRACT_VALIDATION_FAILED"
    body["proposedOutput"] = "가" * (MAX_BODY_BYTES // 3 + 10)
    assert client.post("/api/ai/quality/evaluate", json=body, headers=H).status_code == 413


def test_api_rate_limit(client, monkeypatch):
    from app.quality_gate import routes as R
    R.RATE.capacity, R.RATE.refill = 3, 0.0
    R.RATE.reset()
    body = fixture("response-quality.v1", "input_pdf_summary_faithful.json")
    codes = []
    for i in range(5):
        b = dict(body, requestId=f"req-rate-{i:04d}")
        codes.append(client.post("/api/ai/quality/evaluate", json=b, headers=H).status_code)
    R.RATE.capacity, R.RATE.refill = 60, 2.0
    assert codes[:3] == [200, 200, 200] and 429 in codes[3:]


def test_api_concurrency_cap_returns_busy(client, monkeypatch):
    from app.quality_gate import routes as R
    monkeypatch.setenv("AI_QUALITY_EVAL_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("AI_QUALITY_EVAL_QUEUE_WAIT_SECONDS", "0.01")
    R._sem["s"] = None
    sem = R._semaphore()
    run(sem.acquire())            # 다른 평가가 슬롯을 점유 중인 상황
    body = dict(fixture("response-quality.v1", "input_pdf_summary_faithful.json"), requestId="req-busy-0001")
    r = client.post("/api/ai/quality/evaluate", json=body, headers=H)
    sem.release()
    R._sem["s"] = None
    assert r.status_code == 429 and r.json()["errorCode"] == "EVALUATOR_BUSY"
