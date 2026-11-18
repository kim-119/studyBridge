"""qwen3-vl:4b vision client — the "eye" in front of qwen3:14b.

Turns a rendered PDF page (PNG bytes) into RAG-ready text via Ollama's
``/api/generate`` with the ``images`` field. We never load transformers/torch
directly (requirement #54) and never pass image bytes to the text brain.

Hard rules honoured here:
    * deterministic decode (temperature 0, low top_p)
    * bounded timeout, at most ``max_retries`` retries (no infinite wait)
    * extraction-only prompt: transcribe what is visible, never invent content
"""
from __future__ import annotations

import base64
import logging
import os
import time

import requests

logger = logging.getLogger("studybridge.ollama_vision_client")


def _base_url() -> str:
    # 시스템 Ollama(0.24.0)는 qwen3-vl 을 받을 수 없다(registry 412) → 운영에서는 PDF_VL_BASE_URL 로
    # 비전 데몬(:11435, qwen3-vl:4b-instruct)을 지정한다. 미설정 시 기존 동작(OLLAMA_BASE_URL) 유지.
    return (os.getenv("PDF_VL_BASE_URL") or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")


def _model() -> str:
    return os.getenv("PDF_VL_MODEL", "qwen3-vl:4b")


def _timeout() -> int:
    try:
        return int(os.getenv("PDF_VL_TIMEOUT_SECONDS", "90"))
    except (TypeError, ValueError):
        return 90


# Extraction-only prompt (requirements #67-77). Transcribe, do not summarize,
# do not hallucinate. Preserve structure (titles, bullets, tables, code, math,
# diagram node/edge relations) and original language.
VL_PROMPT = (
    "이 이미지는 강의자료/PDF 페이지입니다. 목적은 이 페이지를 RAG용 텍스트로 변환하는 것입니다.\n"
    "규칙:\n"
    "- 이미지에 보이는 텍스트, 표, 수식, 다이어그램 구조만 추출하세요.\n"
    "- 보이지 않는 내용은 추측하지 마세요. (do not guess invisible content)\n"
    "- 요약하지 말고, 보이는 정보를 구조화해서 그대로 전사/설명하세요.\n"
    "- 제목, 본문 bullet, 표(행/열), 코드(들여쓰기 보존), 수식(LaTeX 또는 일반 텍스트), "
    "그래프 축/라벨, 화살표 관계를 최대한 보존하세요.\n"
    "- 다이어그램은 노드와 간선(화살표) 관계를 텍스트로 설명하세요. 예: A -> B.\n"
    "- 불확실한 부분은 [unclear]로 표시하세요.\n"
    "- 한국어와 영어가 섞이면 원문 언어를 보존하세요.\n"
    "- 결과는 Markdown 형식에 가깝게 작성하세요.\n"
)


def _default_max_retries() -> int:
    try:
        return max(0, int(os.getenv("PDF_VL_MAX_RETRIES", "2")))
    except (TypeError, ValueError):
        return 2


# 게이트웨이가 비전 슬롯을 거부하면(대기 초과/포화/회로 열림) 잠시 동안 다음 페이지도 즉시 실패시킨다.
# 정규화기는 페이지마다 예외를 잡고 다음 페이지로 가므로, 이게 없으면 페이지마다 대기 한도를 다시 기다린다.
_GW_BACKOFF_UNTIL = 0.0


def caption_page_image(png_bytes: bytes, page_number: int, *, max_retries: int | None = None) -> str:
    """Extract visible text/structure from a page image.

    Returns the model's text (possibly empty string). Raises after the retry
    budget is exhausted so the caller (normalizer) can record a ``failed`` page
    — it isolates the failure to one page and never 500s the whole request.

    qwen3-vl:4b on Ollama intermittently returns an **empty** ``response`` for a
    perfectly readable page (cold-load / decode race), so an empty body is
    treated as a retryable condition — not just HTTP exceptions. The final empty
    is returned as-is (the normalizer records it as ``failed`` and moves on).
    """
    import app.ai_gateway as _gw
    global _GW_BACKOFF_UNTIL
    if _gw.enabled() and time.monotonic() < _GW_BACKOFF_UNTIL:
        raise _gw.GatewayRejected("QUEUE_TIMEOUT", "vision backend busy (backoff)")
    image_b64 = base64.b64encode(png_bytes).decode("ascii")
    payload = {
        "model": _model(),
        "prompt": f"# Page {page_number} Visual Extraction\n\n{VL_PROMPT}",
        "images": [image_b64],
        "stream": False,
        "options": {
            "temperature": 0,
            "top_p": 0.1,
            "num_predict": int(os.getenv("PDF_VL_NUM_PREDICT", "1024")),
        },
        "think": False,
    }
    url = f"{_base_url()}/api/generate"

    if max_retries is None:
        max_retries = _default_max_retries()
    attempts = max(1, max_retries + 1)
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            t0 = time.time()
            with _gw.llm_slot(url=url, timeout=_timeout()) as _lease:
                try:
                    resp = requests.post(url, json=payload, timeout=_timeout())
                except requests.ConnectionError:
                    if _lease:
                        _lease.backend_fail()
                    raise
                if _lease:
                    _lease.backend_fail() if resp.status_code >= 500 else _lease.backend_ok()
            resp.raise_for_status()
            data = resp.json()
            text = (data.get("response") or "").strip()
            logger.info(
                "[PDF_VL] page=%s attempt=%s ms=%s chars=%s",
                page_number, attempt + 1, int((time.time() - t0) * 1000), len(text),
            )
            # Empty body on a successful call => retry if budget remains (model
            # flakiness), else return the empty string for the caller to handle.
            if not text and attempt + 1 < attempts:
                logger.warning(
                    "[PDF_VL] page=%s attempt=%s empty response, retrying",
                    page_number, attempt + 1,
                )
                continue
            return text
        except _gw.GatewayRejected:
            # 대기열 포화/타임아웃은 재시도하지 않고(재시도가 대기열을 더 키운다) 다음 페이지도 잠시 건너뛴다.
            _GW_BACKOFF_UNTIL = time.monotonic() + float(os.getenv("PDF_VL_GATEWAY_BACKOFF_S", "30"))
            raise
        except Exception as e:  # noqa: BLE001 — retry transient failures
            last_exc = e
            logger.warning(
                "[PDF_VL] page=%s attempt=%s failed: %s",
                page_number, attempt + 1, type(e).__name__,
            )
    # retries exhausted
    if last_exc is not None:
        raise last_exc
    return ""
