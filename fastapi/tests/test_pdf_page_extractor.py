"""Per-page PDF extraction tests (text + image/OCR pages).

Guards the authoritative per-page pipeline used by /api/ai/major-analysis/note
when the PDF itself is available (loaded from S3). The extractor must:

  * report the *true* page count from PyMuPDF (not "pages that had text"),
  * return one entry per page, page numbers 1..N contiguous,
  * never drop an image-only page as "empty" when an image is present,
  * route image-only pages through OCR (here injected for determinism),
  * classify sourceType as text | image | mixed | empty,
  * leave no temporary render files behind.

Spec test mapping (A/B/C/D):
  A. 1-page text PDF
  B. 3-page text PDF
  C. 3 pages, one is an image/screenshot page
  D. image-only PDF whose text layer is empty (OCR supplies the content)
"""
import glob
import os
import tempfile

import pytest

fitz = pytest.importorskip("fitz")

from app.services.pdf_page_extractor import extract_pdf_pages


# ── synthetic PDF builders ───────────────────────────────────────────────────

def _text_pdf(texts):
    """A PDF with a real text layer, one page per item in ``texts``."""
    doc = fitz.open()
    for body in texts:
        page = doc.new_page()
        page.insert_text((72, 72), body, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _image_only_page(doc, caption):
    """Append a page whose only content is a rasterized image (no text layer)."""
    tmp = fitz.open()
    tp = tmp.new_page()
    tp.insert_text((72, 72), caption, fontsize=14)
    pix = tp.get_pixmap(dpi=120)
    tmp.close()
    page = doc.new_page()
    page.insert_image(page.rect, pixmap=pix)
    return page


def _image_only_pdf(captions):
    doc = fitz.open()
    for cap in captions:
        _image_only_page(doc, cap)
    data = doc.tobytes()
    doc.close()
    return data


def _mixed_pdf(text_pages, image_captions):
    doc = fitz.open()
    for body in text_pages:
        page = doc.new_page()
        page.insert_text((72, 72), body, fontsize=11)
    for cap in image_captions:
        _image_only_page(doc, cap)
    return doc.tobytes()


def _fake_ocr(_image):
    # Deterministic stand-in for tesseract on image pages.
    return "Material UI Scaffold 강의자료 학습 목표 안드로이드 슬라이드"


# ── A. single text page ──────────────────────────────────────────────────────

def test_a_single_text_page():
    res = extract_pdf_pages(_text_pdf(["Newton's second law F = m a momentum kinetic"]),
                            ocr_enabled=True, ocr_fn=_fake_ocr)
    assert res.total_pages == 1
    assert len(res.pages) == 1
    p = res.pages[0]
    assert p["page"] == 1
    assert p["sourceType"] == "text"
    assert "Newton" in p["text"]


# ── B. three text pages ──────────────────────────────────────────────────────

def test_b_three_text_pages():
    res = extract_pdf_pages(
        _text_pdf(["page one about integrals and matrices",
                   "page two derivative eigenvalues theorem",
                   "page three probability distribution sampling"]),
        ocr_enabled=True, ocr_fn=_fake_ocr)
    assert res.total_pages == 3
    assert [p["page"] for p in res.pages] == [1, 2, 3]
    assert all(p["sourceType"] == "text" for p in res.pages)
    assert "integrals" in res.pages[0]["text"]
    assert "probability" in res.pages[2]["text"]


# ── C. three pages, middle one is an image/screenshot ────────────────────────

def test_c_text_pages_with_one_image_page():
    res = extract_pdf_pages(
        _mixed_pdf(["intro text algorithm complexity loop",
                    "conclusion text sorting recursion"],
                   ["Android lecture slide screenshot"]),
        ocr_enabled=True, ocr_fn=_fake_ocr)
    assert res.total_pages == 3
    assert [p["page"] for p in res.pages] == [1, 2, 3]
    image_page = res.pages[2]
    assert image_page["sourceType"] == "image"
    # image content must be reflected via OCR, not discarded as empty
    assert "Scaffold" in image_page["ocrText"]


# ── D. image-only PDF (empty text layer) → OCR supplies content ──────────────

def test_d_image_only_pdf_uses_ocr():
    res = extract_pdf_pages(_image_only_pdf(["slide 1", "slide 2"]),
                            ocr_enabled=True, ocr_fn=_fake_ocr)
    assert res.total_pages == 2
    assert len(res.pages) == 2
    for p in res.pages:
        assert p["sourceType"] in ("image", "mixed")
        assert p["ocrText"].strip()  # OCR description present
        assert p["text"].strip() == "" or len(p["text"].strip()) < 12


def test_d_image_only_without_ocr_is_image_not_empty():
    # OCR disabled → still must not be dropped/empty when an image is present.
    res = extract_pdf_pages(_image_only_pdf(["slide A"]),
                            ocr_enabled=False, ocr_fn=_fake_ocr)
    assert res.total_pages == 1
    assert res.pages[0]["sourceType"] == "image"


# ── page-count authority + max_pages cap + cleanup ───────────────────────────

def test_total_pages_is_authoritative_even_with_cap():
    res = extract_pdf_pages(_text_pdf([f"page {i} content body text" for i in range(7)]),
                            max_pages=3, ocr_enabled=True, ocr_fn=_fake_ocr)
    assert res.total_pages == 7          # true count preserved
    assert len(res.pages) == 3           # only first 3 materialized (route backfills rest)
    assert [p["page"] for p in res.pages] == [1, 2, 3]


def test_no_temp_render_files_left_behind():
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "*.png")))
    extract_pdf_pages(_image_only_pdf(["x", "y", "z"]), ocr_enabled=True, ocr_fn=_fake_ocr)
    after = set(glob.glob(os.path.join(tempfile.gettempdir(), "*.png")))
    assert after == before


def test_corrupt_pdf_raises():
    with pytest.raises(Exception):
        extract_pdf_pages(b"not a pdf at all", ocr_enabled=True, ocr_fn=_fake_ocr)
