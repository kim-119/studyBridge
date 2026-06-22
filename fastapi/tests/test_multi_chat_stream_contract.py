"""라이브 경로(multi_chat_stream_compat) SSE 계약 통합 테스트.

운영 hotfix_main 이 마운트하는 /api/ai/multi-chat/stream 호환 라우터가
build_stream_generator 출력을 envelope+dedup(contract) 으로 감싸는지 검증한다.

검증:
  - 모든 agent_answer 이벤트에 turnId/eventId/fingerprint/stage 가 포함된다.
  - 같은 (stage,agent,content) 중복은 1회만 나간다.
  - all_complete 이후 늦게 도착한 answer 는 drop 된다.
  - turn_start → agent_answer → all_complete 순서가 유지된다.
  - 생성 중 예외가 나도 error 이벤트에 code/reason/turnId/stage 가 포함된다.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import multi_chat_stream_compat as compat


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(compat.router)
    return TestClient(app)


def _parse_sse(text):
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        name = None
        data = {}
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                raw = line[len("data:"):].strip()
                try:
                    data = json.loads(raw)
                except Exception:
                    data = {"_raw": raw}
        if name:
            events.append((name, data))
    return events


def test_stream_envelope_dedup_and_gate(monkeypatch):
    def fake_gen(request):
        yield {"event": "turn_start", "data": {"message": "시작"}}
        yield {"event": "agent_answer", "data": {"agentId": "a1", "agentName": "튜터",
                                                  "content": "첫 답변입니다", "stageType": "FIRST_ANSWER"}}
        # 공백만 다른 동일 본문(중복) → drop 되어야 한다
        yield {"event": "agent_answer", "data": {"agentId": "a1", "agentName": "튜터",
                                                  "content": "첫  답변입니다", "stageType": "FIRST_ANSWER"}}
        yield {"event": "all_complete", "data": {"answers": [{"agentId": "a1", "agentName": "튜터",
                                                              "content": "최종"}]}}
        # all_complete 이후 늦은 answer → drop
        yield {"event": "agent_answer", "data": {"agentId": "a2", "agentName": "튜터2",
                                                  "content": "늦은 답변", "stageType": "FIRST_ANSWER"}}

    monkeypatch.setattr("app.services.multi_agent_service.build_stream_generator", fake_gen)

    app = FastAPI()
    app.include_router(compat.router)
    with TestClient(app) as client:
        resp = client.post("/api/ai/multi-chat/stream",
                           json={"message": "객체지향이 뭐야?", "mode": "default", "agents": []})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    names = [n for n, _ in events]

    # 순서: turn_start 가 첫 answer 보다 앞, all_complete 가 그 뒤
    assert "turn_start" in names
    assert names.index("turn_start") < names.index("agent_answer")
    assert names.index("agent_answer") < names.index("all_complete")

    answers = [d for n, d in events if n == "agent_answer"]
    # 중복 + 늦은 answer 제거 → 정확히 1개
    assert len(answers) == 1
    a = answers[0]
    for k in ("turnId", "eventId", "fingerprint", "stage"):
        assert k in a, f"agent_answer missing {k}"
    assert a["stage"] == "FIRST_ANSWER"
    assert a["content"] == "첫 답변입니다"

    # 늦은 답변 본문은 어디에도 agent_answer 로 노출되지 않는다
    assert all("늦은 답변" != d.get("content") for n, d in events if n == "agent_answer")

    # all_complete 에도 envelope 부착
    ac = [d for n, d in events if n == "all_complete"][0]
    assert ac.get("turnId") and ac.get("eventId")


def test_stream_error_event_has_code_and_reason(monkeypatch):
    def boom(request):
        raise RuntimeError("synthetic failure")
        yield  # pragma: no cover

    monkeypatch.setattr("app.services.multi_agent_service.build_stream_generator", boom)

    app = FastAPI()
    app.include_router(compat.router)
    with TestClient(app) as client:
        resp = client.post("/api/ai/multi-chat/stream",
                           json={"message": "x", "mode": "socratic", "learningMode": "socratic"})
    events = _parse_sse(resp.text)
    errs = [d for n, d in events if n == "error"]
    assert errs, "error 이벤트가 없음"
    e = errs[0]
    for k in ("code", "reason", "turnId", "stage"):
        assert k in e, f"error missing {k}"
    assert e["stage"] == "ERROR"
    # 내부 stacktrace 원문을 사용자 메시지로 그대로 노출하지 않는다(별도 reason 필드 사용)
    assert e.get("message")
