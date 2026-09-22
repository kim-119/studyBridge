"""Redis 1회 실패로 영구 비활성화하지 않는다: 지수 백오프 후 재연결."""
import time

from app.studymate import redis_sync as R


class _Good:
    def ping(self):
        return True


def test_backoff_then_reconnect(monkeypatch):
    monkeypatch.setenv("STUDYMATE_REDIS", "on")
    monkeypatch.setattr(R, "_CLIENT", None); monkeypatch.setattr(R, "_FAILS", 0); monkeypatch.setattr(R, "_NEXT_TRY", 0.0)
    calls = {"n": 0}

    class FakeRedisMod:
        class Redis:
            @staticmethod
            def from_url(url, **kw):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise ConnectionError("down")
                return _Good()
    import sys
    monkeypatch.setitem(sys.modules, "redis", FakeRedisMod)
    assert R.client() is None and R._FAILS == 1
    assert R.client() is None and calls["n"] == 1          # 백오프 중엔 재시도하지 않는다
    monkeypatch.setattr(R, "_NEXT_TRY", time.time() - 1)    # 백오프 만료
    assert isinstance(R.client(), _Good) and R._FAILS == 0   # 자동 복구
    monkeypatch.setattr(R, "_CLIENT", None)


def test_disabled_gate(monkeypatch):
    monkeypatch.setenv("STUDYMATE_REDIS", "off")
    assert R.client() is None
