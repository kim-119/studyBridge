"""부하 테스트용 가짜 Ollama — 실측 성능 모델로 NUM_PARALLEL 슬롯/FIFO 를 재현한다(GPU 미사용).

성능 모델(2026-09-16 ~/ollama-bench 실측, qwen3:14b Q4_K_M, RTX 5070 Ti):
  parallel=1: 78 tok/s/stream, parallel=2: 65 tok/s/stream, parallel=3: 52 tok/s/stream
  prefill ~0.3s(콜드 시스템프롬프트), TTFT warm ~0.07s
vision(qwen3-vl:4b-instruct, 2026-10-27 실측): 단건 ~1.5s

usage: python fake_ollama.py PORT PARALLEL KIND(text|vision) SCALE
SCALE: 시간 축척(0.2 → 실제 시간의 20%로 재생). /stats 로 최대 동시 실행/대기 길이를 돌려준다.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

PORT, PAR, KIND, SCALE = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], float(sys.argv[4])
TPS = {1: 78.0, 2: 65.0, 3: 52.0, 4: 45.0}.get(PAR, 40.0)
MODEL = "qwen3:14b" if KIND == "text" else "qwen3-vl:4b-instruct"
sem = asyncio.Semaphore(PAR)
st = {"running": 0, "waiting": 0, "max_running": 0, "max_waiting": 0, "served": 0, "cancelled": 0}


def _service_s(body: dict) -> tuple[float, int]:
    if KIND == "vision":
        return 1.5, 120
    n = int(((body.get("options") or {}).get("num_predict")) or 256)
    return 0.3 + n / TPS, n


async def _run(body: dict):
    st["waiting"] += 1
    st["max_waiting"] = max(st["max_waiting"], st["waiting"])
    try:
        await sem.acquire()
    finally:
        st["waiting"] -= 1
    st["running"] += 1
    st["max_running"] = max(st["max_running"], st["running"])
    return time.monotonic()


def _done():
    st["running"] -= 1
    st["served"] += 1
    sem.release()


async def chat(request: Request):
    body = await request.json()
    secs, n = _service_s(body)
    await _run(body)
    if not body.get("stream", True) or request.url.path.endswith("/generate"):
        try:
            await asyncio.sleep(secs * SCALE)
        except asyncio.CancelledError:
            st["cancelled"] += 1
            raise
        finally:
            _done()
        key = "response" if request.url.path.endswith("/generate") else "message"
        payload = {"done": True, "eval_count": n, "prompt_eval_count": 500, "done_reason": "stop"}
        payload[key] = "가짜 응답 " * 4 if key == "response" else {"role": "assistant", "content": "가짜 응답 " * 4}
        return JSONResponse(payload)

    async def gen():
        try:
            await asyncio.sleep(0.3 * SCALE)
            pieces = max(1, n // 16)
            for _ in range(pieces):
                await asyncio.sleep((secs - 0.3) / pieces * SCALE)
                yield json.dumps({"message": {"content": "토큰 "}, "done": False}).encode() + b"\n"
            yield json.dumps({"message": {"content": ""}, "done": True, "eval_count": n,
                              "prompt_eval_count": 500, "done_reason": "stop"}).encode() + b"\n"
        except asyncio.CancelledError:
            st["cancelled"] += 1
            raise
        finally:
            _done()
    return StreamingResponse(gen(), media_type="application/x-ndjson")


async def ps(_):
    return JSONResponse({"models": [{"name": MODEL, "size_vram": 1}]})


async def tags(_):
    return JSONResponse({"models": [{"name": MODEL}]})


async def stats(_):
    return JSONResponse(st)


async def reset(_):
    for k in ("max_running", "max_waiting", "served", "cancelled"):
        st[k] = 0
    return JSONResponse(st)


app = Starlette(routes=[
    Route("/api/chat", chat, methods=["POST"]), Route("/api/generate", chat, methods=["POST"]),
    Route("/api/ps", ps), Route("/api/tags", tags), Route("/stats", stats), Route("/reset", reset, methods=["POST"]),
])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
