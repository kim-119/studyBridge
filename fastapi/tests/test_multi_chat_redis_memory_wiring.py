"""라이브 경로(multi_chat_stream_compat)에 Redis 대화기억 배선 검증.

목표 동작:
  1) 요청 진입 시 attach_memory_to_request 로 이전 대화 기억이 message 에 주입되어
     build_stream_generator(→Ollama 프롬프트)로 전달된다.
  2) 스트림 종료(all_complete) 후 최종 답변 텍스트가 persist_turn 으로 저장된다.

Redis 자체는 EC2에서만 살아있으므로, 모듈 경계(attach/persist)를 fake 로 두고
compat 핸들러가 '올바른 데이터를 올바른 시점에 흘려보내는지'(통합 배선)를 검증한다.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import multi_chat_stream_compat as compat
import app.services.multi_chat_redis_memory as mem


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


def test_memory_block_injected_and_final_answer_persisted(monkeypatch):
    captured = {}

    def fake_gen(request):
        # generator(=Ollama로 가는 프롬프트 입력)가 받은 message 를 그대로 기록한다.
        captured["message"] = request.message
        yield {"event": "turn_start", "data": {"message": "시작"}}
        yield {"event": "all_complete", "data": {"answers": [
            {"agentId": "a1", "agentName": "튜터", "answer": "최종 답변 본문"},
        ]}}

    monkeypatch.setattr("app.services.multi_agent_service.build_stream_generator", fake_gen)

    async def fake_attach(request):
        augmented = request.model_copy(update={
            "message": "[이전 대화 기억]\n- user: 이전 질문이야\n\n[현재 질문]\n" + request.message
        })
        meta = mem.MemoryMeta(
            enabled=True, key="studybridge:multi-chat:memory:room:42",
            scope="room", scope_id="42", original_message=request.message,
        )
        return augmented, meta

    persisted = {}

    async def fake_persist(meta, user_message, assistant_message):
        persisted["meta"] = meta
        persisted["assistant"] = assistant_message
        return True

    monkeypatch.setattr(mem, "attach_memory_to_request", fake_attach)
    monkeypatch.setattr(mem, "persist_turn", fake_persist)

    app = FastAPI()
    app.include_router(compat.router)
    with TestClient(app) as client:
        resp = client.post(
            "/api/ai/multi-chat/stream",
            json={"message": "객체지향이 뭐야?", "mode": "default", "roomId": 42, "agents": []},
        )

    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    names = [n for n, _ in events]
    assert "all_complete" in names

    # 1) 이전 대화 기억 블록이 실제로 generator(→Ollama)에 전달됐다.
    assert "[이전 대화 기억]" in captured.get("message", "")
    assert "객체지향이 뭐야?" in captured.get("message", "")

    # 2) 스트림 종료 후 최종 답변이 persist 됐다.
    assert persisted.get("assistant"), "persist_turn 이 호출되지 않음(배선 누락)"
    assert "최종 답변 본문" in persisted["assistant"]
    assert persisted["meta"].scope == "room"


def test_persist_skipped_when_memory_disabled(monkeypatch):
    """scope 가 없으면(roomId 등 부재) attach 가 disabled meta 를 주고, persist 는 호출되되 no-op.
    배선이 meta.enabled 를 신뢰하고 흐름을 깨지 않는지(예외 없이 정상 SSE) 확인한다."""
    def fake_gen(request):
        yield {"event": "all_complete", "data": {"answers": [
            {"agentName": "튜터", "answer": "본문"},
        ]}}

    monkeypatch.setattr("app.services.multi_agent_service.build_stream_generator", fake_gen)

    calls = {"persist": 0}

    async def fake_persist(meta, user_message, assistant_message):
        calls["persist"] += 1
        return False

    monkeypatch.setattr(mem, "persist_turn", fake_persist)
    # attach 는 실제 모듈 함수 사용: scope 없으면 disabled meta + 원본 request 그대로.

    app = FastAPI()
    app.include_router(compat.router)
    with TestClient(app) as client:
        resp = client.post(
            "/api/ai/multi-chat/stream",
            json={"message": "스코프 없는 질문", "mode": "default", "agents": []},
        )

    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert "all_complete" in [n for n, _ in events]
