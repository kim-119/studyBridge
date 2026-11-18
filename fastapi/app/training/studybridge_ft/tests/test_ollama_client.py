import app.training.studybridge_ft.utils.ollama_client as oc


class _Resp:
    def __init__(self, j):
        self._j = j
        self.status_code = 200

    def json(self):
        return self._j

    def raise_for_status(self):
        pass


def test_chat_returns_content(monkeypatch):
    monkeypatch.setattr(oc, "_vram_used_mib", lambda: 1000)
    monkeypatch.setattr(oc.requests, "post",
                        lambda *a, **k: _Resp({"message": {"content": "안녕"}}))
    c = oc.OllamaClient("http://x", "qwen3:14b")
    assert c.chat("S", "U") == "안녕"


def test_chat_retries_on_blank(monkeypatch):
    monkeypatch.setattr(oc, "_vram_used_mib", lambda: 1000)
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        return _Resp({"message": {"content": "" if calls["n"] == 1 else "복구"}})

    monkeypatch.setattr(oc.requests, "post", fake_post)
    c = oc.OllamaClient("http://x", "qwen3:14b")
    assert c.chat("S", "U") == "복구"
    assert calls["n"] == 2


def test_payload_has_think_false(monkeypatch):
    monkeypatch.setattr(oc, "_vram_used_mib", lambda: 1000)
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured.update(json)
        return _Resp({"message": {"content": "ok"}})

    monkeypatch.setattr(oc.requests, "post", fake_post)
    oc.OllamaClient("http://x", "qwen3:14b").chat("S", "U")
    assert captured["think"] is False and captured["stream"] is False
