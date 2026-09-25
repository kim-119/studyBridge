"""Rolling summary: 요청 경로 밖(백그라운드), 임계 턴 수 이상에서만, 실패해도 답변 무영향."""
from types import SimpleNamespace

from app.studymate import memory_summary as MS


def _req(n):
    pa = [SimpleNamespace(role="USER" if i % 2 == 0 else "ASSISTANT", agentName="교수", answer=f"턴 {i} 내용") for i in range(n)]
    return SimpleNamespace(previousAnswers=pa, roomId=77, agentRoomId=None, sessionId=None, conversationId=None, groupId=None, userId=None)


def test_below_threshold_not_scheduled(monkeypatch):
    monkeypatch.setenv("STUDYMATE_ROLLING_SUMMARY", "on")
    assert MS.schedule_update(_req(2)) is False


def test_scheduled_in_background_and_failure_is_swallowed(monkeypatch):
    monkeypatch.setenv("STUDYMATE_ROLLING_SUMMARY", "on")
    ran = {}

    def boom(key, turns):
        ran["called"] = True
        raise RuntimeError("summary llm down")
    monkeypatch.setattr(MS, "_update", lambda key, turns: ran.setdefault("args", (key, len(turns))))
    assert MS.schedule_update(_req(8), "최종 답변") is True
    MS._EXEC.submit(lambda: None).result(timeout=5)
    assert ran["args"][0].startswith("studybridge:multi-chat:summary:room:77")


def test_update_failure_does_not_raise(monkeypatch):
    from app.studymate import llm_gateway as G, redis_sync
    monkeypatch.setattr(redis_sync, "client", lambda: None)
    monkeypatch.setattr(G, "ask_text", lambda *a, **k: (_ for _ in ()).throw(G.LLMUnavailable("down")))
    MS._update("studybridge:multi-chat:summary:room:1", ["a"] * 8)   # 예외 전파 없음
