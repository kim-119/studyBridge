"""화면공유 비전 API × AI Gateway 통합 테스트 (mock HTTP 백엔드, GPU 미사용).

실제 라이브 앱(hotfix_main.app)에 ASGI 로 요청하고, Ollama 대신 로컬 HTTP 가짜 서버 2개를 띄운다.
  * 텍스트 가짜(NUM_PARALLEL=1 을 lock 으로 재현) — /api/chat
  * 비전 가짜 — /api/chat (images), 이미지 바이트 해시로 답을 만들어 요청 간 답변 혼합을 검출
backend=ollama 경로라 게이트웨이 슬롯/브레이커/GPU 가드를 실제로 거친다(backend=mock 은 거치지 않음).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from PIL import Image, ImageDraw

KEY = "k-vision-test"


def _jpeg(text: str, size=(640, 360)) -> str:
    img = Image.new("RGB", size, (240, 240, 245))
    ImageDraw.Draw(img).text((20, 20), text, fill=(10, 10, 10))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


class _Fake:
    def __init__(self, parallel_lock: bool):
        self.lock = threading.Lock() if parallel_lock else None
        self.delay = 0.15
        self.mode = "ok"                   # ok | oom | loadfail
        self.calls = 0
        self.running = 0
        self.max_running = 0
        self.mu = threading.Lock()
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({"models": []}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(n) or b"{}")
                with fake.mu:
                    fake.calls += 1
                if fake.mode == "oom":
                    return self._send(500, {"error": "CUDA error: out of memory"})
                if fake.mode == "loadfail":
                    return self._send(500, {"error": "llama runner process has terminated: model failed to load"})
                if fake.lock:
                    fake.lock.acquire()
                with fake.mu:
                    fake.running += 1
                    fake.max_running = max(fake.max_running, fake.running)
                try:
                    time.sleep(fake.delay)
                finally:
                    with fake.mu:
                        fake.running -= 1
                    if fake.lock:
                        fake.lock.release()
                imgs = [m.get("images") for m in req.get("messages", []) if m.get("images")]
                if imgs:
                    digest = hashlib.sha256(base64.b64decode(imgs[0][0])).hexdigest()[:12]
                    content = f"화면에 보이는 내용: img={digest}"
                else:
                    content = "텍스트 응답"
                if req.get("stream"):
                    lines = (json.dumps({"message": {"content": content}, "done": False}) + "\n"
                             + json.dumps({"message": {"content": ""}, "done": True, "eval_count": 5}) + "\n").encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.send_header("Content-Length", str(len(lines)))
                    self.end_headers()
                    self.wfile.write(lines)
                    return
                self._send(200, {"message": {"role": "assistant", "content": content}, "done": True})

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()        # 리스닝 소켓까지 닫아 backlog 대기 연결이 남지 않게


@pytest.fixture()
def env(monkeypatch):
    text, vis = _Fake(parallel_lock=True), _Fake(parallel_lock=False)
    for k, v in {
        "AI_GATEWAY_ENABLED": "true", "AI_GW_GPU_GUARD": "false", "AI_SERVER_API_KEY": KEY,
        "VISION_API_ENABLED": "true", "VISION_BACKEND": "ollama", "VISION_OLLAMA_BASE_URL": vis.url,
        "VISION_MODEL": "qwen3-vl:4b-instruct", "OLLAMA_BASE_URL": text.url, "STUDYMATE_OLLAMA_BASE_URL": text.url,
        "OLLAMA_MODEL": "qwen3:14b", "VISION_INFERENCE_TIMEOUT_SECONDS": "5", "VISION_QUEUE_TIMEOUT_SECONDS": "20",
        "VISION_MAX_QUEUE": "8", "VISION_MAX_PER_GROUP": "2", "VISION_DUPLICATE_TTL_SECONDS": "600",
    }.items():
        monkeypatch.setenv(k, v)
    # import 시점에 고정되는 모듈 상수도 가짜 서버로 돌린다(실제 :11434 로 새지 않게).
    import app.core.config as cfg
    import app.services.ollama_client as oc
    monkeypatch.setattr(cfg, "OLLAMA_BASE_URL", text.url)
    monkeypatch.setattr(oc, "OLLAMA_BASE_URL", text.url)
    monkeypatch.setattr(oc, "OLLAMA_MODEL", "qwen3:14b")
    import app.ai_gateway as gw
    from app.vision.gate import gate
    gw.reset_for_tests(None)
    gate.__init__()                                   # 테스트마다 VisionGate 상태 초기화
    yield {"text": text, "vis": vis, "gw": gw}
    gw.reset_for_tests(None)
    gate.__init__()
    text.close()
    vis.close()


def _app():
    import hotfix_main
    return hotfix_main.app


def _body(rid, group, text, question="현재 화면의 Python 오류를 설명해 줘", **extra):
    b = {"requestId": rid, "groupId": group, "streamId": f"con_{group}", "sharerUserId": 10, "askerUserId": 20,
         "question": question, "image": _jpeg(text), "mime": "image/jpeg"}
    b.update(extra)
    return b


async def _post(client, body):
    t0 = time.perf_counter()
    r = await client.post("/api/ai/vision/analyze", json=body, headers={"Authorization": f"Bearer {KEY}"})
    return r, (time.perf_counter() - t0) * 1000


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://t", timeout=60)


def _digest(b64):
    """서버는 검증 후 RGB JPEG 로 재인코딩(EXIF 제거)해 보내므로 같은 변환을 거친 바이트로 기대값을 만든다."""
    from app.vision.config import get_settings
    from app.vision.image_validation import decode_and_validate_image
    jpeg = decode_and_validate_image(b64, "image/jpeg", get_settings()).jpeg_bytes
    return hashlib.sha256(jpeg).hexdigest()[:12]


# 1. 단건 — 응답 계약(answer/model/latencyMs + requestId/queueWaitMs/inferenceMs)
def test_single_request_contract(env):
    async def main():
        async with _client() as c:
            body = _body("r-1", 123, "Traceback ZeroDivisionError")
            r, _ = await _post(c, body)
            assert r.status_code == 200, r.text
            j = r.json()
            assert set(j) >= {"answer", "model", "latencyMs", "requestId", "queueWaitMs", "inferenceMs"}
            assert j["model"] == "qwen3-vl:4b-instruct" and j["requestId"] == "r-1"
            assert isinstance(j["latencyMs"], int) and j["latencyMs"] >= 0
    asyncio.run(main())
    snap = env["gw"].status()["scheduler"]
    assert snap["classes"]["VISION"]["completed"] == 1           # 게이트웨이를 실제로 거쳤다


# 2. 서로 다른 공유 화면 2개 동시 — 둘 다 성공, 답변이 각자 이미지에 대응(혼합 없음), GPU 는 직렬
def test_two_different_screens_concurrently(env):
    async def main():
        async with _client() as c:
            b1, b2 = _body("r-a", 1, "SCREEN ONE java NullPointerException"), _body("r-b", 2, "SCREEN TWO math integral")
            (r1, t1), (r2, t2) = await asyncio.gather(_post(c, b1), _post(c, b2))
            assert r1.status_code == 200 and r2.status_code == 200
            assert _digest(b1["image"]) in r1.json()["answer"]
            assert _digest(b2["image"]) in r2.json()["answer"]
            assert max(r1.json()["queueWaitMs"], r2.json()["queueWaitMs"]) >= 100   # 하나는 기다렸다(직렬)
    asyncio.run(main())
    assert env["vis"].max_running == 1


# 3. 일반 채팅 + 비전 동시 — 별도 백엔드라 서로를 막지 않는다
def test_chat_and_vision_concurrently(env):
    env["text"].delay = 0.6

    async def main():
        from app.services.ollama_client import ask_ollama
        async with _client() as c:
            chat = asyncio.to_thread(ask_ollama, "s", "질문", model="qwen3:14b", timeout=10)
            vis = _post(c, _body("r-c", 3, "web page naver news"))
            chat_out, (rv, tv) = await asyncio.gather(chat, vis)
            assert chat_out == "텍스트 응답"
            assert rv.status_code == 200 and tv < 600          # 텍스트 0.6s 를 기다리지 않음
    asyncio.run(main())


# 4. 멀티에이전트(에이전트 3명 순차) + 비전 동시
def test_multi_agent_and_vision_concurrently(env):
    env["text"].delay = 0.2

    def multi_agent():
        from app.ai_gateway.context import workload
        from app.ai_gateway.policy import WorkloadClass as W
        from app.studymate import llm_gateway as lg
        out = []
        with workload(W.MULTI_AGENT, "cu:7"):
            for i in range(3):
                req = lg.LLMRequest(system=f"agent{i}", user="질문", model="qwen3:14b", num_ctx=8192,
                                    num_predict=50, timeout_s=10)
                out.append(lg.generate(req).content)
        return out

    async def main():
        async with _client() as c:
            ma = asyncio.to_thread(multi_agent)
            vs = [_post(c, _body(f"r-m{i}", 10 + i, f"algorithm screen {i}")) for i in range(2)]
            res = await asyncio.gather(ma, *vs)
            assert res[0] == ["텍스트 응답"] * 3
            assert all(r.status_code == 200 for r, _ in res[1:])
    asyncio.run(main())
    cls = env["gw"].status()["scheduler"]["classes"]
    assert cls["MULTI_AGENT"]["completed"] == 3 and cls["VISION"]["completed"] == 2


# 5·6·12. 5건 동시 전원 성공 / 10건 동시: 1 실행 + 8 대기 + 1 거부(429, Retry-After)
@pytest.mark.parametrize("n,expect_ok", [(5, 5), (10, 9)])
def test_many_concurrent(env, n, expect_ok):
    env["vis"].delay = 0.1

    async def main():
        async with _client() as c:
            bodies = [_body(f"r-n{i}", 100 + i, f"screen {i}") for i in range(n)]
            res = await asyncio.gather(*[_post(c, b) for b in bodies])
            ok = [(b, r) for b, (r, _) in zip(bodies, res) if r.status_code == 200]
            rej = [r for r, _ in res if r.status_code != 200]
            assert len(ok) == expect_ok
            for b, r in ok:
                assert _digest(b["image"]) in r.json()["answer"]
            for r in rej:
                assert r.status_code == 429 and r.json()["error"]["code"] == "VISION_QUEUE_FULL"
                assert r.headers.get("retry-after")
    asyncio.run(main())


# 7. 요청 취소 — 슬롯/게이트가 즉시 회수되고 다음 요청이 처리된다
def test_cancel_releases_gateway_slot(env):
    env["vis"].delay = 2.0

    async def main():
        async with _client() as c:
            task = asyncio.create_task(_post(c, _body("r-x", 50, "long")))
            await asyncio.sleep(0.4)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0.1)
            from app.vision.gate import gate
            assert gate.running == 0 and gate.waiting == 0
            snap = env["gw"].status()["scheduler"]["backends"]["ollama_vision"]
            assert snap["inflight"] == 0 and snap["waiting"] == 0
    asyncio.run(main())


# 8. 추론 타임아웃 — 504, 슬롯 반환
def test_inference_timeout(env, monkeypatch):
    monkeypatch.setenv("VISION_INFERENCE_TIMEOUT_SECONDS", "0.5")
    env["vis"].delay = 1.5

    async def main():
        async with _client() as c:
            r, _ = await _post(c, _body("r-t", 60, "slow"))
            assert r.status_code == 504 and r.json()["error"]["code"] == "VISION_INFERENCE_TIMEOUT"
    asyncio.run(main())
    assert env["gw"].status()["scheduler"]["backends"]["ollama_vision"]["inflight"] == 0


# 9. 모델 적재 실패 반복 → 브레이커가 열려 백엔드를 더 두드리지 않고 즉시 503
def test_model_load_failure_opens_breaker(env):
    env["vis"].mode = "loadfail"

    async def main():
        async with _client() as c:
            codes = []
            for i in range(7):
                r, _ = await _post(c, _body(f"r-f{i}", 70 + i, f"x{i}"))
                codes.append((r.status_code, r.json()["error"]["code"]))
            return codes
    codes = asyncio.run(main())
    assert codes[0] == (502, "VISION_BACKEND_ERROR")
    assert codes[-1] == (503, "VISION_BACKEND_UNAVAILABLE")         # 회로 열림
    assert env["vis"].calls < 7 * 2                                  # 열린 뒤에는 백엔드 미호출
    assert env["gw"].status()["breakers"]["ollama_vision"]["state"] == "open"


# 10. GPU OOM — 비전만 503 RESOURCE_EXHAUSTED, 텍스트 기능은 영향 없음
def test_oom_is_isolated(env):
    env["vis"].mode = "oom"

    async def main():
        from app.services.ollama_client import ask_ollama
        async with _client() as c:
            r, _ = await _post(c, _body("r-o", 80, "oom"))
            assert r.status_code == 503 and r.json()["error"]["code"] == "VISION_RESOURCE_EXHAUSTED"
            assert r.json()["error"]["retryable"] is True
            out = await asyncio.to_thread(ask_ollama, "s", "질문", model="qwen3:14b", timeout=10)
            assert out == "텍스트 응답"
    asyncio.run(main())


# 11. 동일 requestId 중복 — 처리 중이면 409
def test_duplicate_request_id_inflight(env):
    env["vis"].delay = 0.5

    async def main():
        async with _client() as c:
            b = _body("dup-1", 90, "dup")
            (r1, _), (r2, _) = await asyncio.gather(_post(c, b), _post(c, dict(b)))
            assert sorted([r1.status_code, r2.status_code]) == [200, 409]
    asyncio.run(main())


# 텔레메트리 불명 + 비전 미상주 → 신규 적재 거부(대기 한도 후 503), 텍스트는 정상
def test_unknown_telemetry_denies_new_vision_load(env, monkeypatch):
    monkeypatch.setenv("AI_GW_GPU_GUARD", "true")
    monkeypatch.setenv("AI_GW_VISION_QUEUE_TIMEOUT_S", "0.5")
    monkeypatch.setenv("AI_GW_TELEMETRY_STALE_S", "0")      # 장애가 stale 허용 시간을 넘긴 상황
    gw = env["gw"]
    s = gw.get_scheduler()
    s.guard._smi_fn = lambda: None
    s.guard._ps_fn = lambda url: {}
    s.guard.refresh(force=True)

    async def main():
        from app.services.ollama_client import ask_ollama
        async with _client() as c:
            r, _ = await _post(c, _body("r-u", 95, "unknown"))
            assert r.status_code == 503 and r.json()["error"]["code"] == "VISION_QUEUE_TIMEOUT"
            out = await asyncio.to_thread(ask_ollama, "s", "질문", model="qwen3:14b", timeout=10)
            assert out == "텍스트 응답"
    asyncio.run(main())
    assert env["vis"].calls == 0
    assert gw.status()["gpu"]["unknownTelemetryDenials"] >= 1


# 기능 플래그 OFF — 게이트웨이를 거치지 않고 기존 동작(직접 호출) 그대로
def test_gateway_off_same_contract(env, monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_ENABLED", "false")

    async def main():
        async with _client() as c:
            r, _ = await _post(c, _body("r-off", 99, "off"))
            assert r.status_code == 200 and set(r.json()) >= {"answer", "model", "latencyMs"}
    asyncio.run(main())
    assert env["gw"].status()["enabled"] is False
