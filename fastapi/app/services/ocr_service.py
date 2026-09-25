"""
OCR helpers for image-based PDFs.

Policy:
- Text extraction callers should try normal PDF text first.
- If text is too short, call OCR only when OCR_ENABLED=true.
- OCR requires both Python packages (pytesseract, Pillow, PyMuPDF) and the
  system tesseract binary with the requested language packs.
"""
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OcrResult:
    text: str
    engine: str
    page_count: int
    attempted: bool
    available: bool
    reason: str = ""


def _enabled() -> bool:
    return os.getenv("OCR_ENABLED", "false").strip().lower() in {"true", "1", "yes", "on"}


def _settings() -> tuple[int, int, str, int, int]:
    min_chars = int(os.getenv("OCR_MIN_TEXT_CHARS", os.getenv("PDF_MIN_TEXT_CHARS", "80")))
    max_pages = int(os.getenv("OCR_MAX_PAGES", "5"))
    dpi = int(os.getenv("OCR_DPI", "180"))
    lang = os.getenv("OCR_LANG", "kor+eng")
    timeout = int(os.getenv("OCR_TIMEOUT_SECONDS", "45"))
    return min_chars, max_pages, lang, dpi, timeout


def ocr_status() -> dict:
    enabled = _enabled()
    tesseract_path = shutil.which("tesseract")
    try:
        import pytesseract  # noqa: F401
        py_ok = True
    except Exception:
        py_ok = False
    try:
        import PIL  # noqa: F401
        pil_ok = True
    except Exception:
        pil_ok = False
    try:
        import fitz  # noqa: F401
        fitz_ok = True
    except Exception:
        fitz_ok = False
    _, max_pages, lang, dpi, timeout = _settings()
    return {
        "enabled": enabled,
        "available": bool(enabled and tesseract_path and py_ok and pil_ok and fitz_ok),
        "tesseractPath": bool(tesseract_path),
        "pytesseract": py_ok,
        "pillow": pil_ok,
        "pymupdf": fitz_ok,
        "lang": lang,
        "maxPages": max_pages,
        "dpi": dpi,
        "timeoutSeconds": timeout,
    }


def should_attempt_ocr(text: Optional[str], min_chars: Optional[int] = None) -> bool:
    threshold = min_chars if min_chars is not None else _settings()[0]
    return len((text or "").strip()) < threshold


def extract_pdf_ocr_from_path(path: str, min_chars: Optional[int] = None) -> OcrResult:
    if not _enabled():
        return OcrResult("", "ocr-disabled", 0, attempted=False, available=False, reason="OCR_ENABLED=false")

    status = ocr_status()
    if not status["available"]:
        missing = [k for k in ("tesseractPath", "pytesseract", "pillow", "pymupdf") if not status.get(k)]
        reason = "missing " + ",".join(missing)
        logger.warning("OCR fallback unavailable: %s", reason)
        return OcrResult("", "ocr-unavailable", 0, attempted=True, available=False, reason=reason)

    import fitz
    import pytesseract
    from PIL import Image

    threshold = min_chars if min_chars is not None else _settings()[0]
    _, max_pages, lang, dpi, timeout = _settings()
    zoom = max(dpi, 72) / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    parts: list[str] = []
    page_count = 0

    try:
        with fitz.open(path) as doc:
            page_count = len(doc)
            pages_to_scan = min(page_count, max_pages)
            for page_index in range(pages_to_scan):
                page = doc[page_index]
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                page_text = pytesseract.image_to_string(image, lang=lang, timeout=timeout).strip()
                if page_text:
                    parts.append(f"\n\n[OCR Page {page_index + 1}]\n{page_text}")
    except RuntimeError as e:
        logger.warning("OCR fallback failed: %s", e)
        return OcrResult("", "tesseract-ocr", page_count, attempted=True, available=True, reason=str(e))
    except Exception as e:
        logger.warning("OCR fallback failed: %s", type(e).__name__)
        return OcrResult("", "tesseract-ocr", page_count, attempted=True, available=True, reason=type(e).__name__)

    text = "\n".join(parts).strip()
    if len(text) < threshold:
        logger.warning("OCR fallback produced short text chars=%s threshold=%s pages=%s", len(text), threshold, page_count)
        return OcrResult(text, "tesseract-ocr", page_count, attempted=True, available=True, reason="too_short")

    logger.info("OCR fallback succeeded chars=%s pages=%s lang=%s", len(text), page_count, lang)
    return OcrResult(text, "tesseract-ocr", page_count, attempted=True, available=True)


def extract_pdf_ocr_from_bytes(pdf_bytes: bytes, min_chars: Optional[int] = None) -> OcrResult:
    import tempfile
    path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            path = tmp.name
            tmp.write(pdf_bytes)
        return extract_pdf_ocr_from_path(path, min_chars=min_chars)
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
