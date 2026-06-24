"""Unit tests for the PDF text normalization layer.

These tests build *real* PDFs with PyMuPDF (text-layer, image-only, mixed) so we
exercise the real per-page routing logic. The VL ("eye") and OCR callables are
injected fakes so the suite passes with **no Ollama / no tesseract** present
(requirement: "Ollama가 없어도 단위 테스트는 통과해야 한다").
"""
from __future__ import annotations

import io

import pytest

fitz = pytest.importorskip("fitz")  # PyMuPDF
PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from app.services.pdf_text_normalizer import (  # noqa: E402
    normalize_pdf,
    SOURCE_NATIVE,
    SOURCE_VL,
    SOURCE_OCR,
    SOURCE_MIXED,
    SOURCE_FAILED,
)


# ── PDF builders ────────────────────────────────────────────────────────────
_LONG = (
    "Distributed systems lecture: a node communicates with another node over a "
    "network channel using a request response protocol with retries and backoff."
)


def _png_bytes(color=(200, 120, 40), size=(220, 160)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def make_text_pdf(pages: list[str]) -> bytes:
    doc = fitz.open()
    for body in pages:
        page = doc.new_page()
        page.insert_text((72, 72), body, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def make_image_pdf(n_pages: int = 1) -> bytes:
    """Pages carrying only a raster image — get_text() returns ''."""
    doc = fitz.open()
    img = _png_bytes()
    for _ in range(n_pages):
        page = doc.new_page(width=240, height=200)
        page.insert_image(fitz.Rect(0, 0, 240, 200), stream=img)
    data = doc.tobytes()
    doc.close()
    return data


def make_mixed_pdf() -> bytes:
    """Page 1 = text layer, Page 2 = image only."""
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), _LONG, fontsize=11)
    p2 = doc.new_page(width=240, height=200)
    p2.insert_image(fitz.Rect(0, 0, 240, 200), stream=_png_bytes())
    data = doc.tobytes()
    doc.close()
    return data


class CountingVL:
    """Injected fake VL callable (png bytes -> markdown text)."""

    def __init__(self, text="# Page Visual Extraction\nnode A -> node B"):
        self.calls = 0
        self.seen = []
        self._text = text

    def __call__(self, png_bytes: bytes, page_number: int) -> str:
        self.calls += 1
        self.seen.append(page_number)
        return self._text


def _disabled_ocr(*_a, **_k):  # never produces text
    return ""


# ── 1. text-dominant PDF: native only, ZERO VL calls ────────────────────────
def test_text_pdf_uses_native_and_never_calls_vl():
    vl = CountingVL()
    result = normalize_pdf(
        make_text_pdf([_LONG, _LONG]),
        vl_fn=vl,
        ocr_fn=_disabled_ocr,
        cache_dir=None,
    )
    assert vl.calls == 0
    assert result.document_mode == "text_dominant"
    assert result.ok is True
    assert len(result.pages) == 2
    for meta in result.pages:
        assert meta.source_method == SOURCE_NATIVE
        assert meta.vl_used is False
        assert meta.ocr_used is False
        assert meta.error is None
        assert meta.native_text_len >= 80


# ── 2. image-only PDF: VL fires, never empty, no PDF_TEXT_EMPTY ──────────────
def test_image_only_pdf_routes_to_vl_and_is_not_empty():
    vl = CountingVL()
    result = normalize_pdf(
        make_image_pdf(2),
        vl_fn=vl,
        ocr_fn=_disabled_ocr,
        cache_dir=None,
    )
    assert vl.calls == 2
    assert result.document_mode == "image_dominant"
    assert result.ok is True
    assert result.merged_text.strip() != ""
    for meta in result.pages:
        assert meta.source_method == SOURCE_VL
        assert meta.vl_used is True
        assert "node A" in meta.text


# ── 3. mixed PDF: text page native, image page VL ───────────────────────────
def test_mixed_pdf_splits_routing_per_page():
    vl = CountingVL()
    result = normalize_pdf(
        make_mixed_pdf(),
        vl_fn=vl,
        ocr_fn=_disabled_ocr,
        cache_dir=None,
    )
    assert result.document_mode == "mixed"
    assert result.pages[0].source_method == SOURCE_NATIVE
    assert result.pages[0].vl_used is False
    assert result.pages[1].source_method == SOURCE_VL
    assert result.pages[1].vl_used is True
    assert vl.calls == 1
    assert vl.seen == [2]


# ── 4. every page leaves a [Page N] marker in merged_text ───────────────────
def test_merged_text_has_page_markers_for_every_page():
    result = normalize_pdf(
        make_image_pdf(3),
        vl_fn=CountingVL(),
        ocr_fn=_disabled_ocr,
        cache_dir=None,
    )
    for n in (1, 2, 3):
        assert f"[Page {n}]" in result.merged_text


# ── 5. metadata schema ──────────────────────────────────────────────────────
def test_page_metadata_schema_fields_present():
    result = normalize_pdf(
        make_mixed_pdf(),
        vl_fn=CountingVL(),
        ocr_fn=_disabled_ocr,
        cache_dir=None,
    )
    for meta in result.pages:
        d = meta.to_dict()
        for key in ("page_number", "source_method", "native_text_len", "vl_used", "ocr_used", "error"):
            assert key in d, key
        assert d["source_method"] in {
            SOURCE_NATIVE, SOURCE_VL, SOURCE_OCR, SOURCE_MIXED, SOURCE_FAILED,
        }
        assert isinstance(d["page_number"], int)
        assert isinstance(d["native_text_len"], int)
        assert isinstance(d["vl_used"], bool)
        assert isinstance(d["ocr_used"], bool)


# ── 6. VL failure on one page must not abort the document ────────────────────
def test_vl_failure_marks_page_failed_but_continues():
    class FlakyVL:
        def __init__(self):
            self.calls = 0

        def __call__(self, png, page_number):
            self.calls += 1
            if page_number == 1:
                raise RuntimeError("VL timeout")
            return "ok caption with node graph A -> B"

    vl = FlakyVL()
    result = normalize_pdf(
        make_image_pdf(2),
        vl_fn=vl,
        ocr_fn=_disabled_ocr,
        cache_dir=None,
    )
    assert vl.calls == 2  # second page still attempted
    assert result.pages[0].source_method == SOURCE_FAILED
    assert result.pages[0].error
    assert result.pages[1].source_method == SOURCE_VL
    # document still usable (page 2 produced text)
    assert result.ok is True
    assert "[Page 1]" in result.merged_text  # marker survives even on failure


# ── 7. PDF_VL_MAX_PAGES limit → truncated, VL not called past cap ────────────
def test_vl_max_pages_limit_truncates():
    vl = CountingVL()
    result = normalize_pdf(
        make_image_pdf(5),
        vl_fn=vl,
        ocr_fn=_disabled_ocr,
        vl_max_pages=2,
        cache_dir=None,
    )
    assert vl.calls == 2
    assert result.truncated is True
    assert result.total_pages == 5


# ── 8. OCR sufficiency short-circuits VL ────────────────────────────────────
def test_ocr_sufficient_skips_vl():
    vl = CountingVL()

    def good_ocr(image, page_number):
        return (
            "OCR extracted line one of scanned slide. OCR extracted line two with "
            "more than eighty characters of recognized korean and english text."
        )

    result = normalize_pdf(
        make_image_pdf(1),
        vl_fn=vl,
        ocr_fn=good_ocr,
        ocr_enabled=True,
        cache_dir=None,
    )
    assert vl.calls == 0
    assert result.pages[0].source_method == SOURCE_OCR
    assert result.pages[0].ocr_used is True


# ── 9. cache hit: second run does not re-invoke VL ──────────────────────────
def test_vl_cache_hit_avoids_second_call(tmp_path):
    pdf = make_image_pdf(1)
    cache = str(tmp_path / "vlcache")

    vl1 = CountingVL()
    r1 = normalize_pdf(pdf, vl_fn=vl1, ocr_fn=_disabled_ocr, cache_dir=cache)
    assert vl1.calls == 1
    assert r1.pages[0].source_method == SOURCE_VL

    vl2 = CountingVL()
    r2 = normalize_pdf(pdf, vl_fn=vl2, ocr_fn=_disabled_ocr, cache_dir=cache)
    assert vl2.calls == 0  # served from cache
    assert r2.pages[0].source_method == SOURCE_VL
    assert "node A" in r2.pages[0].text


# ── 10. corrupt cache must not break the request ────────────────────────────
def test_corrupt_cache_is_ignored(tmp_path):
    import hashlib
    import os

    pdf = make_image_pdf(1)
    cache = tmp_path / "vlcache"
    cache.mkdir()
    # poison the cache directory with garbage
    (cache / "garbage.json").write_text("{ not json")
    os.makedirs(str(cache), exist_ok=True)

    vl = CountingVL()
    result = normalize_pdf(pdf, vl_fn=vl, ocr_fn=_disabled_ocr, cache_dir=str(cache))
    assert result.ok is True
    assert result.pages[0].source_method == SOURCE_VL
    assert hashlib  # silence lint


# ── 11. total failure only when nothing extractable ─────────────────────────
def test_total_failure_when_everything_empty():
    result = normalize_pdf(
        make_image_pdf(1),
        vl_fn=lambda png, page_number: "",  # VL yields nothing
        ocr_fn=_disabled_ocr,
        cache_dir=None,
    )
    assert result.ok is False
    assert result.pages[0].source_method == SOURCE_FAILED


# ── 12. qwen3:14b only ever sees text (merged_text is a str) ─────────────────
def test_merged_text_is_plain_text_only():
    result = normalize_pdf(
        make_mixed_pdf(),
        vl_fn=CountingVL(),
        ocr_fn=_disabled_ocr,
        cache_dir=None,
    )
    assert isinstance(result.merged_text, str)
    # no base64 image data leaks into the brain-bound text
    assert "base64" not in result.merged_text.lower()
    assert "data:image" not in result.merged_text.lower()
