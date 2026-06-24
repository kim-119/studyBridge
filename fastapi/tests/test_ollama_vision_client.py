"""Unit tests for the qwen3-vl Ollama vision client.

No real Ollama: ``requests.post`` is monkeypatched. Verifies payload shape
(base64 image, deterministic options, model from env), response parsing, retry
behaviour, and that exhausted retries raise rather than hang forever.
"""
from __future__ import annotations

import base64

import pytest

from app.services import ollama_vision_client as vc


PNG = b"\x89PNG\r\n\x1a\n-fake-png-bytes-for-test"


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_payload_is_deterministic_and_carries_base64_image(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResp({"response": "node A -> node B"})

    monkeypatch.setattr(vc.requests, "post", fake_post)
    monkeypatch.setenv("PDF_VL_MODEL", "qwen3-vl:4b")

    out = vc.caption_page_image(PNG, 3)

    assert out == "node A -> node B"
    body = captured["json"]
    assert body["model"] == "qwen3-vl:4b"
    assert body["stream"] is False
    assert body["options"]["temperature"] == 0
    # image is base64 of the raw png, not the raw bytes
    assert body["images"] == [base64.b64encode(PNG).decode("ascii")]
    assert "/api/generate" in captured["url"]
    # prompt must instruct extraction, not summarization / hallucination
    assert "추측" in body["prompt"] or "guess" in body["prompt"].lower()


def test_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky_post(url, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise vc.requests.ConnectionError("boom")
        return FakeResp({"response": "recovered text"})

    monkeypatch.setattr(vc.requests, "post", flaky_post)
    out = vc.caption_page_image(PNG, 1, max_retries=2)
    assert out == "recovered text"
    assert calls["n"] == 2


def test_exhausted_retries_raise_not_hang(monkeypatch):
    def always_fail(url, json=None, timeout=None):
        raise vc.requests.Timeout("slow")

    monkeypatch.setattr(vc.requests, "post", always_fail)
    with pytest.raises(Exception):
        vc.caption_page_image(PNG, 1, max_retries=1)


def test_empty_model_output_returns_empty_string(monkeypatch):
    monkeypatch.setattr(vc.requests, "post", lambda *a, **k: FakeResp({"response": "   "}))
    assert vc.caption_page_image(PNG, 1, max_retries=1) == ""


def test_empty_response_is_retried_then_succeeds(monkeypatch):
    # qwen3-vl:4b flakiness: an empty body on a *successful* HTTP call must be
    # retried (not just exceptions), since the model returns content on retry.
    calls = {"n": 0}

    def post(url, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResp({"response": "   "})  # empty -> should trigger retry
        return FakeResp({"response": "# Page\nnode A -> node B"})

    monkeypatch.setattr(vc.requests, "post", post)
    out = vc.caption_page_image(PNG, 1, max_retries=2)
    assert out == "# Page\nnode A -> node B"
    assert calls["n"] == 2  # retried once after the empty response


def test_max_retries_defaults_from_env(monkeypatch):
    monkeypatch.setenv("PDF_VL_MAX_RETRIES", "3")
    calls = {"n": 0}

    def always_empty(url, json=None, timeout=None):
        calls["n"] += 1
        return FakeResp({"response": ""})

    monkeypatch.setattr(vc.requests, "post", always_empty)
    assert vc.caption_page_image(PNG, 1) == ""
    assert calls["n"] == 4  # 1 + 3 retries
