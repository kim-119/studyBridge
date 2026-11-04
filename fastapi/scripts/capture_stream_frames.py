"""라이브 스트리밍 라우트의 '실제 생성기' 프레임 캡처(가짜 LLM, hermetic).

운영 Ollama/DB/외부 API 를 전혀 쓰지 않는다:
- 127.0.0.1 임의 포트에 가짜 Ollama(/api/chat, /api/generate, /api/tags) 를 띄우고 모든 OLLAMA_* URL 을 그쪽으로 돌린다.
- OpenAI/Tavily/Wikipedia/OpenAlex 는 플래그 off + 키 비움, Redis/DB 는 닫힌 포트(127.0.0.1:9).
- 가짜 LLM 출력에는 CANARY 표식을 넣어, 게이트 통과 후 미검증 본문이 새는지 문자열로 판정할 수 있게 한다.

hotfix_main:app(운영과 같은 엔트리포인트)을 TestClient 로 띄워 실제 라우트 → 실제 생성기 → 실제 직렬화 바이트를 받는다.
출력: tests/fixtures/stream_captures/<name>.json.gz (요청 본문, 상태, content-type, 원시 바이트 텍스트).

    cd fastapi && python -m scripts.capture_stream_frames
"""
from __future__ import annotations

import gzip
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CANARY = "CANARY7F3A"
OUT_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "stream_captures"


def _llm_text(body: dict) -> str:
    fmt = body.get("format")
    if fmt:   # 구조화 출력 요청 → 스키마를 모르므로 흔한 키에 CANARY 를 실은 JSON
        return json.dumps({"answer": f"{CANARY} 구조화 답변", "content": f"{CANARY} 본문", "summary": f"{CANARY} 요약",
                           "questions": [{"question": f"{CANARY} 문항?", "choices": ["가", "나", "다", "라"],
                                          "answer": "가", "answer_index": 0, "explanation": f"{CANARY} 해설"}]},
                          ensure_ascii=False)
    return (f"{CANARY} 객체지향 프로그래밍은 객체 단위로 상태와 동작을 묶는 방식입니다. "
            f"{CANARY} 캡슐화, 상속, 다형성이 핵심입니다. 비밀정보 sk-proj-{CANARY}ABCDEFGHIJKLMNOP 같은 문자열도 섞여 있습니다.")


class _FakeOllama(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # noqa: D401
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            return self._json({"models": [{"name": "qwen3:14b", "model": "qwen3:14b", "digest": "fake"}]})
        if self.path.startswith("/api/ps"):
            return self._json({"models": []})
        if self.path.startswith("/api/version"):
            return self._json({"version": "0.0.0-fake"})
        return self._json({}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            body = {}
        text = _llm_text(body)
        chat = self.path.startswith("/api/chat")
        if self.path.startswith("/api/embed") or self.path.startswith("/api/embeddings"):
            return self._json({"embedding": [0.0] * 8, "embeddings": [[0.0] * 8]})
        if not body.get("stream", True if not chat else True) or body.get("stream") is False:
            msg = {"message": {"role": "assistant", "content": text}} if chat else {"response": text}
            return self._json({"model": body.get("model"), "done": True, "eval_count": 10, "eval_duration": 1, **msg})
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def chunk(obj):
            b = (json.dumps(obj, ensure_ascii=False) + "\n").encode()
            self.wfile.write(f"{len(b):X}\r\n".encode() + b + b"\r\n")
        for piece in [text[i:i + 12] for i in range(0, len(text), 12)]:
            chunk({"message": {"role": "assistant", "content": piece}} if chat else {"response": piece, "done": False})
        chunk({"done": True, "eval_count": 10, "eval_duration": 1, **({"message": {"role": "assistant", "content": ""}} if chat else {"response": ""})})
        self.wfile.write(b"0\r\n\r\n")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


CASES = [
    # name, method, path, json body, needs internal auth
    ("studymate_multichat_default", "POST", "/api/ai/multi-chat/stream",
     {"message": "객체지향이 뭐야?", "mode": "default", "agents": []}),
    ("studymate_multichat_debate", "POST", "/api/ai/multi-chat/stream",
     {"message": "객체지향이 함수형보다 나은가?", "mode": "debate", "learningMode": "debate", "agents": []}),
    ("studymate_multichat_socratic", "POST", "/api/ai/multi-chat/stream",
     {"message": "객체지향을 질문으로 가르쳐줘", "mode": "socratic", "learningMode": "socratic", "agents": []}),
    ("agents_chat_fetch_stream", "POST", "/api/ai/agents/chat/fetch-stream",
     {"message": "TCP 3-way handshake 를 설명해줘"}),
    ("group_study_fetch_stream", "POST", "/api/group-study/ai/fetch-stream",
     {"roomId": 1, "message": "TCP 3-way handshake 를 설명해줘"}),
    ("material_chat_fetch_stream", "POST", "/api/materials/1/ai/fetch-stream",
     {"message": "이 자료 요약해줘"}),
    ("tasks_fetch_stream", "POST", "/api/ai/tasks/fetch-stream",
     {"message": "오늘 공부 계획 세워줘"}),
    ("quiz_generate_stream", "POST", "/api/ai/quiz/generate-stream",
     {"materialId": 1, "title": "네트워크", "text": "TCP 는 연결 지향 프로토콜이다. 3-way handshake 는 SYN, SYN-ACK, ACK 세 단계로 연결을 수립한다. " * 8,
      "count": 3, "difficulty": "medium"}),
    ("roadmap_generate_stream", "POST", "/api/ai/roadmap/generate-stream",
     {"materialId": 1, "title": "네트워크", "text": "TCP 는 연결 지향 프로토콜이다. 3-way handshake 는 SYN, SYN-ACK, ACK 세 단계로 연결을 수립한다. " * 8}),
]


def _child(port: int) -> None:
    """환경을 고정한 '새 프로세스'에서 앱을 import 한다(import-time 상수까지 가짜 URL 로)."""
    from fastapi.testclient import TestClient

    import hotfix_main
    client = TestClient(hotfix_main.app)
    headers = {"Authorization": f"Bearer {os.environ['AI_SERVER_API_KEY']}"}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, method, path, body in CASES:
        t0 = time.time()
        try:
            with client.stream(method, path, json=body, headers=headers, timeout=120) as r:
                raw = b"".join(r.iter_bytes())
                status, ctype = r.status_code, r.headers.get("content-type", "")
        except Exception as e:  # noqa: BLE001
            raw, status, ctype = f"CAPTURE_ERROR {type(e).__name__}".encode(), -1, ""
        rec = {"name": name, "method": method, "path": path, "request": body, "status": status,
               "contentType": ctype, "elapsedSec": round(time.time() - t0, 2), "canary": CANARY,
               "raw": raw.decode("utf-8", "replace")}
        with gzip.open(OUT_DIR / f"{name}.json.gz", "wt", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False)
        print(f"{name}: status={status} type={ctype} bytes={len(raw)} {rec['elapsedSec']}s", flush=True)


def main() -> int:
    if os.environ.get("_CAPTURE_CHILD") == "1":
        _child(int(os.environ["_CAPTURE_PORT"]))
        return 0
    port = _free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), _FakeOllama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fake = f"http://127.0.0.1:{port}"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI", "TAVILY", "OPENALEX_API"))}
    env.update({
        "_CAPTURE_CHILD": "1", "_CAPTURE_PORT": str(port),
        "OLLAMA_BASE_URL": fake, "AI_OLLAMA_BASE_URL": fake, "STUDYMATE_OLLAMA_BASE_URL": fake,
        "VISION_OLLAMA_BASE_URL": fake, "PDF_VL_BASE_URL": fake,
        "AI_OPENAI_ENABLED": "false", "OPENAI_API_KEY": "", "AI_TAVILY_ENABLED": "false", "TAVILY_API_KEY": "",
        "AI_WIKIPEDIA_ENABLED": "false", "OPENALEX_ENABLED": "false", "EXPERT_ANSWER_ENABLED": "false",
        "REDIS_URL": "redis://127.0.0.1:9/0", "DATABASE_URL": "postgresql://none:none@127.0.0.1:9/none",
        "AGENT_EVENT_BUS_BACKEND": "queue", "AI_SERVER_API_KEY": "capture-internal-key-0123456789abcdef",
        "AI_FIRST_TOKEN_TIMEOUT_SEC": "10", "AI_TOTAL_TIMEOUT_SEC": "30", "AI_STREAM_DEADLINE_SEC": "40",
        "AI_STREAM_FALLBACK_START_SEC": "20", "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    })
    try:
        return subprocess.call([sys.executable, "-m", "scripts.capture_stream_frames"], env=env,
                               cwd=str(Path(__file__).resolve().parents[1]), timeout=900)
    finally:
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
