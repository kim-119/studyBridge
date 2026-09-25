"""클라이언트 절단 → CancelToken → 새 추론(다음 교수/반응/repair) 시작 금지, 끊긴 연결에 done 억지 전송 금지."""
import asyncio
import time

from app.schemas.multi_chat_schema import MultiChatRequest
from app.studymate import stream_runtime as SR
from tests.studymate_fakes import AGENTS3, FakeOllama, install


class _Req:
    def __init__(self, disconnect_after_s):
        self.t0 = time.time(); self.after = disconnect_after_s

    async def is_disconnected(self):
        return time.time() - self.t0 > self.after


def test_disconnect_stops_new_inference(monkeypatch):
    monkeypatch.setenv("STUDYMATE_MIN_ANSWER_GAP_SECONDS", "0")
    monkeypatch.setenv("STUDYMATE_DISCUSSION_PLANNER", "off")

    def slow_render(req):
        time.sleep(1.0)
        return "첫 문장은 다르게 시작합니다. " + req.system[-40:] + " 설명과 예시, 결론을 포함합니다. " * 3
    fake = install(monkeypatch, FakeOllama(render=slow_render))
    req = MultiChatRequest(message="캐시 설명해줘", agents=AGENTS3, mode="basic")
    rt = SR.new_runtime_for(req, "req_disc")

    async def run():
        out = []
        async for chunk in SR.stream_turn(_Req(1.3), req, rt):
            out.append(chunk)
        return out
    out = asyncio.run(run())
    renders_at_cancel = fake.count("render")
    time.sleep(1.5)
    assert rt.cancel.cancelled and rt.cancel.reason == "client_disconnected"
    assert fake.count("render") == renders_at_cancel <= 2
    assert not any("event: done" in c for c in out)
