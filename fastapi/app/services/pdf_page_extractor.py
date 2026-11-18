"""Authoritative per-page PDF extraction for the major-analysis study note.

Used when the PDF bytes themselves are available (loaded from S3). Unlike the
Spring-side ``\\f`` split — which collapses multi-page PDFs into a single page
and cannot see image-only pages — this module asks PyMuPDF for the *true* page
count and processes every page individually:

    1) extract the text layer (PyMuPDF ``get_text``)
    2) if the text is insufficient, render the page to an in-memory image and
       run OCR (tesseract via ``ocr_fn`` — injectable for tests / fallback)
    3) classify each page as text | image | mixed | empty

Design guarantees (match the page-card requirements):
  * ``total_pages`` is the real PDF page count (never "pages that had text").
  * Image-only pages are never silently dropped as "empty" — if the page has a
    raster image we keep it as ``image`` even when OCR is disabled/unavailable.
  * Rendering happens fully in memory (pixmap → PIL), so no temp files leak.
  * A single page's OCR failure never aborts the whole document.

This module is additive: it does not modify the existing text-only contract
(``pdf_text_extractor`` / ``ocr_service`` / the request ``pageTexts`` path),
which remains the fallback when no PDF source is provided.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

# Defaults (env-overridable). OCR is bounded for latency on large PDFs.
_DEFAULT_MAX_PAGES = int(os.getenv("MAJOR_ANALYSIS_MAX_PAGES", "20"))
_DEFAULT_OCR_MAX_PAGES = int(os.getenv("MAJOR_ANALYSIS_OCR_MAX_PAGES", "12"))
_DEFAULT_MIN_TEXT_CHARS = int(os.getenv("MAJOR_ANALYSIS_MIN_PAGE_CHARS", "12"))
_DEFAULT_DPI = int(os.getenv("MAJOR_ANALYSIS_OCR_DPI", os.getenv("OCR_DPI", "150")))
_DEFAULT_OCR_LANG = os.getenv("OCR_LANG", "kor+eng")
_DEFAULT_OCR_TIMEOUT = int(os.getenv("OCR_TIMEOUT_SECONDS", "30"))
_RAW_BOUND = 20000  # per-page raw text retention cap (memory guard)


@dataclass
class PageExtract:
    page: int
    text: str = ""
    ocr_text: str = ""
    source_type: str = "empty"  # text | image | mixed | empty
    has_image: bool = False


@dataclass
class PdfPagesResult:
    total_pages: int
    pages: List[dict] = field(default_factory=list)
    ocr_attempted: int = 0


def _stripped_len(s: Optional[str]) -> int:
    return len(re.sub(r"\s+", "", s or ""))


def _default_ocr_fn(lang: str, timeout: int) -> Callable[[object], str]:
    """Build a tesseract OCR callable. Returns a function image->text, or one
    that returns "" if OCR deps are missing (never raises)."""
    def _ocr(image) -> str:
        try:
            import pytesseract
            return (pytesseract.image_to_string(image, lang=lang, timeout=timeout) or "").strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("major-analysis OCR failed: %s", type(e).__name__)
            return ""
    return _ocr


def _classify(has_text: bool, has_ocr: bool, has_image: bool) -> str:
    if has_text and has_ocr:
        return "mixed"
    if has_text:
        return "text"
    if has_ocr:
        return "image"
    if has_image:
        return "image"  # image present but unreadable — still an image page, not empty
    return "empty"


def extract_pdf_pages(
    pdf_bytes: bytes,
    *,
    max_pages: int = _DEFAULT_MAX_PAGES,
    ocr_max_pages: int = _DEFAULT_OCR_MAX_PAGES,
    ocr_enabled: bool = True,
    min_text_chars: int = _DEFAULT_MIN_TEXT_CHARS,
    dpi: int = _DEFAULT_DPI,
    ocr_lang: str = _DEFAULT_OCR_LANG,
    ocr_timeout: int = _DEFAULT_OCR_TIMEOUT,
    ocr_fn: Optional[Callable[[object], str]] = None,
) -> PdfPagesResult:
    """Extract per-page text/OCR/classification from PDF bytes.

    Raises on an unreadable/corrupt PDF so the caller can fall back to the
    request ``pageTexts`` path. Per-page OCR errors are swallowed (page kept).
    """
    import fitz  # PyMuPDF — raises if bytes are not a valid PDF

    if ocr_fn is None:
        ocr_fn = _default_ocr_fn(ocr_lang, ocr_timeout)

    zoom = max(dpi, 72) / 72.0
    pages: List[dict] = []
    ocr_attempted = 0

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        total_pages = doc.page_count
        limit = min(total_pages, max(1, max_pages))
        for idx in range(limit):
            page = doc[idx]
            text = (page.get_text() or "").strip()
            has_text = _stripped_len(text) >= min_text_chars
            try:
                has_image = bool(page.get_images(full=True))
            except Exception:  # noqa: BLE001
                has_image = False

            ocr_text = ""
            # OCR only when the text layer is insufficient (latency guard) and
            # the page actually carries visual content worth reading.
            want_ocr = (not has_text) and (has_image or _stripped_len(text) == 0)
            if want_ocr and ocr_enabled and ocr_attempted < ocr_max_pages:
                ocr_attempted += 1
                pix = None
                try:
                    from PIL import Image
                    matrix = fitz.Matrix(zoom, zoom)
                    pix = page.get_pixmap(matrix=matrix, alpha=False)
                    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    ocr_text = (ocr_fn(image) or "").strip()
                except Exception as e:  # noqa: BLE001
                    logger.warning("major-analysis page %d OCR render failed: %s", idx + 1, type(e).__name__)
                    ocr_text = ""
                finally:
                    if pix is not None:
                        try:
                            pix = None  # release C-side pixmap promptly
                        except Exception:  # noqa: BLE001
                            pass

            has_ocr = _stripped_len(ocr_text) >= min_text_chars
            source_type = _classify(has_text, has_ocr, has_image)
            pages.append({
                "page": idx + 1,
                "text": text[:_RAW_BOUND],
                "ocrText": ocr_text[:_RAW_BOUND],
                "sourceType": source_type,
                "hasImage": has_image,
            })
        return PdfPagesResult(total_pages=total_pages, pages=pages, ocr_attempted=ocr_attempted)
    finally:
        doc.close()
