"""Ollama 실패는 절대 답변 텍스트가 되지 않는다: 타입드 예외 → agent_error(FAILED) + 내부정보 비노출."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.studymate import llm_gateway as G
from app.studymate.budget import TurnBudget
from app.studymate.cancellation import CancelToken


class _Handler(BaseHTTPRequestHandler):
    behavior = "ok"

    def log_message(self, *a):
        pass

    def do_POST(self):
        b = type(self).behavior
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if b == "404":
            self.send_response(404); self.end_headers()
            self.wfile.write(b'{"error":"model \'nope:1b\' not found"}'); return
        if b == "500":
            self.send_response(500); self.end_headers(); self.wfile.write(b'{"error":"boom"}'); return
        self.send_response(200); self.send_header("Content-Type", "application/x-ndjson"); self.end_headers()
        if b == "empty":
            self.wfile.write(json.dumps({"message": {"content": ""}, "done": True, "done_reason": "length"}).encode() + b"\n"); return
        if b == "slow":
            for _ in range(40):
                self.wfile.write(json.dumps({"message": {"content": "가"}, "done": False}).encode() + b"\n"); self.wfile.flush()
                time.sleep(0.1)
            return
        self.wfile.write(json.dumps({"message": {"content": "정상 답변"}, "done": False}).encode() + b"\n")
        self.wfile.write(json.dumps({"message": {"content": ""}, "done": True, "prompt_eval_count": 10, "eval_count": 3}).encode() + b"\n")


@pytest.fixture
def stub(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    monkeypatch.setenv("STUDYMATE_OLLAMA_BASE_URL", f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setattr(G, "_TRANSPORT", None)
    yield _Handler
    srv.shutdown()


def _req(**kw):
    base = dict(system="s", user="u", model="qwen3:14b", num_ctx=8192, num_predict=50, timeout_s=10)
    base.update(kw)
    return G.LLMRequest(**base)


def test_connection_refused_is_unavailable(monkeypatch):
    monkeypatch.setattr(G, "_TRANSPORT", None)
    monkeypatch.setenv("STUDYMATE_OLLAMA_BASE_URL", "http://127.0.0.1:1")
    with pytest.raises(G.LLMUnavailable):
        G.generate(_req())


def test_model_not_found(stub):
    stub.behavior = "404"
    with pytest.raises(G.LLMModelNotFound):
        G.generate(_req(model="nope:1b"))


def test_http_error(stub):
    stub.behavior = "500"
    with pytest.raises(G.LLMHTTPError):
        G.generate(_req())


def test_empty_response(stub):
    stub.behavior = "empty"
    with pytest.raises(G.LLMEmptyResponse):
        G.generate(_req())


def test_timeout_by_deadline(stub):
    stub.behavior = "slow"
    t0 = time.time()
    with pytest.raises(G.LLMTimeout):
        G.generate(_req(timeout_s=1.5))
    assert time.time() - t0 < 4


def test_ok_and_metrics(stub):
    stub.behavior = "ok"
    r = G.generate(_req())
    assert r.content == "정상 답변" and r.prompt_eval_count == 10 and r.ttft_ms is not None


def test_cancel_stops_stream(stub):
    stub.behavior = "slow"
    tok = CancelToken()
    threading.Timer(0.4, tok.cancel).start()
    from app.studymate.cancellation import CancelledByClient
    with pytest.raises(CancelledByClient):
        G.generate(_req(timeout_s=10), cancel=tok)


def test_think_is_always_sent_explicitly():
    body = G._payload(_req(think=False))
    assert body["think"] is False and body["options"]["num_ctx"] == 8192


@pytest.mark.parametrize("exc", [G.LLMUnavailable("x"), G.LLMTimeout("x"), G.LLMModelNotFound("model qwen3:14b"),
                                 G.LLMEmptyResponse("x")])
def test_pipeline_emits_agent_error_without_leak(monkeypatch, exc):
    from tests.studymate_fakes import FakeOllama, install
    from app.schemas.multi_chat_schema import MultiChatRequest
    from app.studymate.basic_pipeline import run_basic_turn
    from app.studymate.runtime_context import new_runtime

    install(monkeypatch, FakeOllama(fail={"render": exc}))
    req = MultiChatRequest(message="Redis를 왜 써?", mode="basic",
                           agents=[{"agentId": 1, "name": "김교수", "personality": "친근함", "knowledgeLevel": "학사"}])
    rt = new_runtime()
    events = list(run_basic_turn(req, req.agents, current_message=req.message, social=False, rt=rt))
    names = [e["event"] for e in events]
    assert "agent_answer" not in names
    err = next(e["data"] for e in events if e["event"] == "agent_error")
    assert err["status"] == "FAILED" and err["code"] == exc.code and err["degraded"] is True
    blob = json.dumps(events, ensure_ascii=False)
    for leak in ("qwen3", "num_ctx", "11434", "Ollama 오류", "양자화"):
        assert leak not in blob
    done = events[-1]["data"]
    assert done["type"] == "all_complete" and done["answers"] == [] and done["status"] == "FAILED"
