"""
Fetch Streaming(NDJSON) 테스트.

검증 포인트:
  - 각 줄이 독립 JSON, 마지막에 done. SSE의 "data:" 접두어 없음.
  - 한글이 깨지지 않음(UTF-8, ensure_ascii=False 동등).
  - deterministic fast path: 인사→즉시 응답(LLM 없음), 위협→차단.
  - LLM/RAG는 mock — 외부 의존 없이 검증.
  - 비활성화(503), 에러 시에도 done으로 정상 종료.
"""
import json

import app.services.ai_fetch_stream_service as svc


def _parse_ndjson(body: bytes):
    lines = [l for l in body.decode("utf-8").split("\n") if l.strip()]
    objs = []
    for l in lines:
        assert not l.startswith("data:"), f"SSE 접두어 발견: {l!r}"
        objs.append(json.loads(l))  # 각 줄 독립 JSON
    return objs


def _collect(gen) -> bytes:
    return b"".join(gen)


# ── NDJSON 직렬화 / 한글 ──────────────────────────────────────────────────────
def test_line_is_utf8_ndjson_no_ascii_escape():
    b = svc.line({"msg": "한글 테스트", "n": 1})
    assert b.endswith(b"\n")
    assert "한글 테스트" in b.decode("utf-8")  # 깨지지 않음
    obj = json.loads(b.decode("utf-8"))
    assert obj["msg"] == "한글 테스트"


def test_event_helpers_shape():
    assert json.loads(svc.ev_status("agent_chat", "draft_start", "생성 중"))["type"] == "status"
    assert json.loads(svc.ev_delta("agent_chat", "draft", "내용"))["type"] == "delta"
    assert json.loads(svc.ev_done("agent_chat"))["type"] == "done"
    assert json.loads(svc.ev_error("agent_chat", "draft", "에러"))["type"] == "error"


# ── deterministic fast path ───────────────────────────────────────────────────
def test_fast_path_greeting_no_llm(monkeypatch):
    # LLM이 호출되면 실패하도록 — fast path는 LLM을 부르면 안 됨
    def boom(*a, **k):
        raise AssertionError("fast path에서 LLM 호출됨")
    monkeypatch.setattr(svc, "stream_ollama", boom)
    objs = _parse_ndjson(_collect(svc.agent_chat_stream({"message": "안녕"})))
    assert objs[-1]["type"] == "done"
    assert objs[-1].get("fastPath") is True
    assert any(o["type"] == "delta" and o["content"] for o in objs)


def test_fast_path_threat_blocks(monkeypatch):
    monkeypatch.setattr(svc, "stream_ollama", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM 호출 안 됨")))
    objs = _parse_ndjson(_collect(svc.group_study_stream({"roomId": 1, "message": "너 죽여버린다"})))
    assert any(o["type"] == "error" for o in objs)
    assert objs[-1]["type"] == "done"


# ── 그룹스터디: roomId 검증 ───────────────────────────────────────────────────
def test_group_study_requires_room_id():
    objs = _parse_ndjson(_collect(svc.group_study_stream({"message": "설명해줘"})))
    assert objs[0]["type"] == "error"
    assert "roomId" in objs[0]["message"]
    assert objs[-1]["type"] == "done"


# ── 자료보관함 RAG 채팅 (RAG + LLM mock) ──────────────────────────────────────
def test_material_chat_uses_rag_and_streams(monkeypatch):
    import app.services.rag_retriever as rr
    monkeypatch.setattr(rr, "retrieve_similar_chunks",
                        lambda q, material_id=None, top_k=5: [{"chunk_index": 0, "content": "OOP는 객체지향"}])
    monkeypatch.setattr(svc, "stream_ollama", lambda *a, **k: iter(["객체", "지향 ", "프로그래밍입니다."]))
    objs = _parse_ndjson(_collect(svc.material_chat_stream(42, {"message": "OOP 설명해줘", "level": "학사"})))
    types = [o["type"] for o in objs]
    assert "status" in types and "delta" in types
    assert objs[-1]["type"] == "done"
    assert objs[-1]["materialId"] == 42
    # RAG 청크 수 status에 노출
    assert any(o.get("phase") == "rag_done" for o in objs)
    # 델타 본문이 한글 그대로
    joined = "".join(o["content"] for o in objs if o["type"] == "delta")
    assert "프로그래밍입니다" in joined


def test_material_chat_llm_timeout_emits_error_then_done(monkeypatch):
    import requests
    import app.services.rag_retriever as rr
    monkeypatch.setattr(rr, "retrieve_similar_chunks", lambda *a, **k: [])
    def timeout(*a, **k):
        raise requests.Timeout("boom")
    monkeypatch.setattr(svc, "stream_ollama", timeout)
    objs = _parse_ndjson(_collect(svc.material_chat_stream(7, {"message": "질문"})))
    assert any(o["type"] == "error" and "timeout" in o["message"].lower() for o in objs)
    assert objs[-1]["type"] == "done"


# ── 멀티에이전트: build_stream_generator 이벤트 → NDJSON 번역 ─────────────────
def test_agent_chat_translates_generator_events(monkeypatch):
    import app.services.multi_agent_service as mas

    def fake_gen(request):
        yield {"event": "turn_start", "data": {"message": "시작"}}
        yield {"event": "agent_start", "data": {"agentId": "a1", "agentName": "도우미"}}
        yield {"event": "agent_answer", "data": {"agentId": "a1", "content": "Spring Boot는 Java 프레임워크입니다.", "stage": "draft"}}
        yield {"event": "all_complete", "data": {"success": True, "mode": "default"}}

    monkeypatch.setattr(mas, "build_stream_generator", fake_gen)
    # MultiChatRequest 검증 우회: 최소 필드
    payload = {"message": "Spring Boot 설명", "agents": [{"id": "a1", "name": "도우미"}]}
    objs = _parse_ndjson(_collect(svc.agent_chat_stream(payload)))
    assert objs[0]["type"] == "status"  # intent_routing
    assert any(o["type"] == "delta" and "Spring Boot" in o["content"] for o in objs)
    assert objs[-1]["type"] == "done"


def test_tasks_stream_dispatches_group_study(monkeypatch):
    monkeypatch.setattr(svc, "stream_ollama", lambda *a, **k: iter(["답변"]))
    objs = _parse_ndjson(_collect(svc.tasks_stream({"feature": "group_study", "roomId": 3, "message": "토론하자"})))
    assert objs[-1]["type"] == "done"
    assert any(o.get("feature") == "group_study" for o in objs)


# ── 엔드포인트 레벨 (StreamingResponse + 비활성화) ────────────────────────────
def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.fetch_stream_routes import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_endpoint_media_type_is_ndjson(monkeypatch):
    monkeypatch.setattr(svc, "stream_ollama", boom_iter := (lambda *a, **k: iter(["x"])))
    c = _client()
    r = c.post("/api/ai/agents/chat/fetch-stream", json={"message": "안녕"})
    assert r.status_code == 200
    assert "application/x-ndjson" in r.headers["content-type"]
    assert "text/event-stream" not in r.headers["content-type"]


def test_endpoint_disabled_returns_503(monkeypatch):
    monkeypatch.setattr(svc, "is_fetch_stream_enabled", lambda: False)
    c = _client()
    r = c.post("/api/ai/tasks/fetch-stream", json={"message": "안녕"})
    assert r.status_code == 503
