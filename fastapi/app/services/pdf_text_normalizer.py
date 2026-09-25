"""PDF text normalization layer (the pre-processor in front of qwen3:14b).

Goal: whatever the PDF is — a clean text PDF, an image-heavy slide export, or a
fully scanned image-only PDF — produce **one normalized text string** plus
per-page metadata that the existing summary / keyword / RAG / quiz / feedback /
roadmap pipelines can consume unchanged.

Division of labour (hard rule):
    * qwen3-vl:4b  = the "eye"   — turns page pixels into text (vision client).
    * qwen3:14b    = the "brain" — only ever receives ``merged_text`` (plain str).

Per-page routing:
    1. native text layer (PyMuPDF ``page.get_text``) — if >= TEXT_MIN, use it,
       and **never** call OCR/VL for that page (text PDFs stay fast).
    2. otherwise the page is an image candidate:
         a. optional OCR (tesseract) — if it yields >= TEXT_MIN, use it.
         b. otherwise render the page to PNG and ask qwen3-vl (the eye).
       VL failures are isolated per page (``failed`` + error metadata) and never
       abort the document.

Design notes:
    * ``vl_fn`` / ``ocr_fn`` are injectable so unit tests run with no Ollama and
      no tesseract installed.
    * VL results are cached on disk keyed by (pdf hash, page index, dpi, model)
      so the same page is never re-captioned. A broken cache never fails a call.
    * Additive module — it does not modify ``extract_compat`` / ``ocr_service`` /
      ``pdf_page_extractor``; callers opt in by calling ``normalize_pdf``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

logger = logging.getLogger("studybridge.pdf_text_normalizer")

# ── source_method vocabulary (unified, requirement #24) ─────────────────────
SOURCE_NATIVE = "native_text"
SOURCE_VL = "vl_caption"
SOURCE_OCR = "ocr_text"
SOURCE_MIXED = "mixed"
SOURCE_FAILED = "failed"

# ── document-level mode (requirement #32) ───────────────────────────────────
MODE_TEXT = "text_dominant"
MODE_MIXED = "mixed"
MODE_IMAGE = "image_dominant"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


# Env defaults (requirements #171-180)
DEF_TEXT_MIN = lambda: _env_int("PDF_TEXT_MIN", 80)                       # noqa: E731
DEF_IMG_AVG = lambda: _env_int("PDF_IMAGE_DOMINANT_AVG_CHARS", 50)        # noqa: E731
DEF_VL_ENABLED = lambda: _env_bool("PDF_VL_ENABLED", True)                # noqa: E731
DEF_VL_DPI = lambda: _env_int("PDF_VL_DPI", 240)                          # noqa: E731
DEF_VL_MAX_PAGES = lambda: _env_int("PDF_VL_MAX_PAGES", 40)               # noqa: E731
DEF_OCR_ENABLED = lambda: _env_bool("PDF_OCR_ENABLED", True)              # noqa: E731
DEF_VL_MODEL = lambda: os.getenv("PDF_VL_MODEL", "qwen3-vl:4b")           # noqa: E731
DEF_MAX_LONG_EDGE = lambda: _env_int("PDF_VL_MAX_LONG_EDGE", 2000)        # noqa: E731

_RAW_BOUND = 20000  # per-page text retention cap (memory guard)


@dataclass
class PageMeta:
    page_number: int
    source_method: str = SOURCE_FAILED
    native_text_len: int = 0
    vl_used: bool = False
    ocr_used: bool = False
    error: Optional[str] = None
    text: str = ""

    def to_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "source_method": self.source_method,
            "native_text_len": self.native_text_len,
            "vl_used": self.vl_used,
            "ocr_used": self.ocr_used,
            "error": self.error,
        }


@dataclass
class NormalizedPdf:
    merged_text: str
    pages: List[PageMeta] = field(default_factory=list)
    document_mode: str = MODE_TEXT
    total_pages: int = 0
    avg_native_chars: float = 0.0
    vl_pages: int = 0
    ocr_pages: int = 0
    failed_pages: List[int] = field(default_factory=list)
    truncated: bool = False
    ok: bool = False

    def to_dict(self) -> dict:
        return {
            "merged_text": self.merged_text,
            "document_mode": self.document_mode,
            "total_pages": self.total_pages,
            "avg_native_chars": round(self.avg_native_chars, 1),
            "vl_pages": self.vl_pages,
            "ocr_pages": self.ocr_pages,
            "failed_pages": self.failed_pages,
            "truncated": self.truncated,
            "ok": self.ok,
            "pages": [p.to_dict() for p in self.pages],
        }


# ── disk cache for VL captions ──────────────────────────────────────────────
def _cache_key(pdf_hash: str, page_idx: int, dpi: int, model: str) -> str:
    raw = f"{pdf_hash}:{page_idx}:{dpi}:{model}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(cache_dir: Optional[str], key: str) -> Optional[str]:
    if not cache_dir:
        return None
    path = os.path.join(cache_dir, key + ".json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        text = data.get("text")
        if isinstance(text, str):
            logger.info("[PDF_VL_CACHE] hit key=%s", key[:12])
            return text
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001 — broken cache never fails the request
        logger.warning("[PDF_VL_CACHE] read failed key=%s err=%s", key[:12], type(e).__name__)
    return None


def _cache_put(cache_dir: Optional[str], key: str, text: str) -> None:
    if not cache_dir:
        return
    try:
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.join(cache_dir, key + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"text": text}, f, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        logger.warning("[PDF_VL_CACHE] write failed key=%s err=%s", key[:12], type(e).__name__)


def _render_png(page, dpi: int, max_long_edge: int) -> bytes:
    """Render a PyMuPDF page to PNG bytes, defensively downscaling huge pages."""
    import fitz

    zoom = max(dpi, 72) / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    long_edge = max(pix.width, pix.height)
    if long_edge > max_long_edge:
        shrink = max_long_edge / float(long_edge)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom * shrink, zoom * shrink), alpha=False)
    png = pix.tobytes("png")
    del pix  # release C-side pixmap promptly (memory guard, requirement #50)
    return png


def _render_pil(page, dpi: int, max_long_edge: int):
    """Render a page to a PIL.Image for the OCR path."""
    import fitz
    from PIL import Image

    zoom = max(dpi, 72) / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    if max(pix.width, pix.height) > max_long_edge:
        shrink = max_long_edge / float(max(pix.width, pix.height))
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom * shrink, zoom * shrink), alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    del pix
    return img


def normalize_pdf(
    pdf_bytes: Optional[bytes] = None,
    *,
    pdf_path: Optional[str] = None,
    text_min: Optional[int] = None,
    image_dominant_avg: Optional[int] = None,
    dpi: Optional[int] = None,
    vl_enabled: Optional[bool] = None,
    vl_max_pages: Optional[int] = None,
    ocr_enabled: Optional[bool] = None,
    max_long_edge: Optional[int] = None,
    model: Optional[str] = None,
    vl_fn: Optional[Callable[[bytes, int], str]] = None,
    ocr_fn: Optional[Callable[[object, int], str]] = None,
    cache_dir: Optional[str] = "DEFAULT",
) -> NormalizedPdf:
    """Normalize a PDF into a single text string + per-page metadata.

    Args:
        pdf_bytes / pdf_path: PDF source (one is required).
        vl_fn:  (png_bytes, page_number) -> markdown text. None => Ollama qwen3-vl.
        ocr_fn: (PIL.Image, page_number) -> text. None => tesseract.
        cache_dir: VL caption cache dir. "DEFAULT" => ``.cache/pdf_vl/``;
                   None disables caching.
    """
    import fitz

    text_min = text_min if text_min is not None else DEF_TEXT_MIN()
    image_dominant_avg = image_dominant_avg if image_dominant_avg is not None else DEF_IMG_AVG()
    dpi = dpi if dpi is not None else DEF_VL_DPI()
    vl_enabled = vl_enabled if vl_enabled is not None else DEF_VL_ENABLED()
    vl_max_pages = vl_max_pages if vl_max_pages is not None else DEF_VL_MAX_PAGES()
    ocr_enabled = ocr_enabled if ocr_enabled is not None else DEF_OCR_ENABLED()
    max_long_edge = max_long_edge if max_long_edge is not None else DEF_MAX_LONG_EDGE()
    model = model or DEF_VL_MODEL()

    if cache_dir == "DEFAULT":
        cache_dir = os.path.join(os.getcwd(), ".cache", "pdf_vl")

    if pdf_bytes is None:
        if not pdf_path:
            raise ValueError("normalize_pdf requires pdf_bytes or pdf_path")
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

    # default VL/OCR wiring (lazy import so tests need neither)
    if vl_fn is None and vl_enabled:
        try:
            from app.services.ollama_vision_client import caption_page_image
            vl_fn = caption_page_image
        except Exception as e:  # noqa: BLE001
            logger.warning("[PDF_NORM] VL client unavailable: %s", type(e).__name__)
            vl_fn = None
    if ocr_fn is None and ocr_enabled:
        ocr_fn = _default_ocr_fn()

    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    t0 = time.time()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages: List[PageMeta] = []
    vl_calls = 0
    truncated = False
    try:
        total_pages = doc.page_count
        logger.info("[PDF_NORM] start pages=%s hash=%s dpi=%s model=%s", total_pages, pdf_hash[:12], dpi, model)

        for idx in range(total_pages):
            page = doc[idx]
            native = (page.get_text() or "").strip()
            native_len = len(native)
            meta = PageMeta(page_number=idx + 1, native_text_len=native_len)

            # 1) native text sufficient -> done, no OCR / no VL
            if native_len >= text_min:
                meta.source_method = SOURCE_NATIVE
                meta.text = native[:_RAW_BOUND]
                pages.append(meta)
                logger.info("[PDF_NORM] page=%s route=native native_len=%s", idx + 1, native_len)
                continue

            # 2a) OCR fallback
            ocr_text = ""
            if ocr_enabled and ocr_fn is not None:
                try:
                    img = _render_pil(page, dpi, max_long_edge)
                    o0 = time.time()
                    ocr_text = (ocr_fn(img, idx + 1) or "").strip()
                    logger.info("[PDF_NORM] page=%s ocr_ms=%s ocr_len=%s", idx + 1, int((time.time() - o0) * 1000), len(ocr_text))
                    del img
                except Exception as e:  # noqa: BLE001 — OCR never aborts the doc
                    logger.warning("[PDF_NORM] page=%s OCR failed: %s", idx + 1, type(e).__name__)
                    ocr_text = ""
            if len(ocr_text) >= text_min:
                meta.ocr_used = True
                meta.source_method = SOURCE_MIXED if native_len > 0 else SOURCE_OCR
                meta.text = (native + "\n" + ocr_text).strip()[:_RAW_BOUND] if native_len else ocr_text[:_RAW_BOUND]
                pages.append(meta)
                continue

            # 2b) VL fallback (the "eye")
            if vl_enabled and vl_fn is not None:
                if vl_calls >= vl_max_pages:
                    truncated = True
                    meta.source_method = SOURCE_FAILED
                    meta.error = "vl_max_pages_exceeded"
                    meta.text = native[:_RAW_BOUND]
                    pages.append(meta)
                    logger.info("[PDF_NORM] page=%s route=skipped(vl_cap)", idx + 1)
                    continue

                key = _cache_key(pdf_hash, idx, dpi, model)
                cached = _cache_get(cache_dir, key)
                if cached is not None:
                    vl_text = cached
                else:
                    logger.info("[PDF_VL_CACHE] miss key=%s", key[:12])
                    vl_calls += 1
                    try:
                        png = _render_png(page, dpi, max_long_edge)
                        v0 = time.time()
                        vl_text = (vl_fn(png, idx + 1) or "").strip()
                        logger.info("[PDF_NORM] page=%s vl_ms=%s vl_len=%s", idx + 1, int((time.time() - v0) * 1000), len(vl_text))
                        del png
                        if vl_text:
                            _cache_put(cache_dir, key, vl_text)
                    except Exception as e:  # noqa: BLE001 — per-page isolation
                        logger.warning("[PDF_NORM] page=%s VL failed: %s", idx + 1, type(e).__name__)
                        meta.source_method = SOURCE_FAILED
                        meta.error = f"vl_error:{type(e).__name__}"
                        meta.text = native[:_RAW_BOUND]
                        pages.append(meta)
                        continue

                if vl_text:
                    meta.vl_used = True
                    meta.source_method = SOURCE_MIXED if native_len > 0 else SOURCE_VL
                    meta.text = (native + "\n" + vl_text).strip()[:_RAW_BOUND] if native_len else vl_text[:_RAW_BOUND]
                    pages.append(meta)
                    continue

            # 3) nothing worked
            if native_len > 0:
                meta.source_method = SOURCE_NATIVE
                meta.text = native[:_RAW_BOUND]
            else:
                meta.source_method = SOURCE_FAILED
                if meta.error is None:
                    meta.error = "no_text_extracted"
            pages.append(meta)

        # ── document-level aggregation ──
        avg_native = (sum(p.native_text_len for p in pages) / len(pages)) if pages else 0.0
        low_pages = sum(1 for p in pages if p.native_text_len < text_min)
        if avg_native < image_dominant_avg:
            mode = MODE_IMAGE
        elif low_pages == 0:
            mode = MODE_TEXT
        else:
            mode = MODE_MIXED

        merged = "\n\n".join(f"[Page {p.page_number}]\n{p.text}".rstrip() for p in pages).strip()
        failed = [p.page_number for p in pages if p.source_method == SOURCE_FAILED and not p.text]
        ok = any(p.text.strip() for p in pages)

        result = NormalizedPdf(
            merged_text=merged,
            pages=pages,
            document_mode=mode,
            total_pages=total_pages,
            avg_native_chars=avg_native,
            vl_pages=sum(1 for p in pages if p.vl_used),
            ocr_pages=sum(1 for p in pages if p.ocr_used),
            failed_pages=failed,
            truncated=truncated,
            ok=ok,
        )
        logger.info(
            "[PDF_NORM] done mode=%s pages=%s avg_native=%.1f vl=%s ocr=%s failed=%s merged_len=%s ms=%s ok=%s",
            mode, total_pages, avg_native, result.vl_pages, result.ocr_pages,
            failed, len(merged), int((time.time() - t0) * 1000), ok,
        )
        return result
    finally:
        doc.close()


def _default_ocr_fn() -> Optional[Callable[[object, int], str]]:
    """Build a tesseract OCR callable (PIL.Image, page_number) -> text.

    Returns None if OCR deps are missing so the normalizer skips OCR cleanly.
    Reuses the project OCR language/timeout env conventions.
    """
    try:
        import pytesseract  # noqa: F401
    except Exception:  # noqa: BLE001
        return None
    lang = os.getenv("PDF_OCR_LANG", os.getenv("OCR_LANG", "kor+eng"))
    timeout = _env_int("OCR_TIMEOUT_SECONDS", 45)

    def _ocr(image, page_number: int) -> str:  # noqa: ARG001
        try:
            import pytesseract
            return (pytesseract.image_to_string(image, lang=lang, timeout=timeout) or "").strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("[PDF_NORM] tesseract OCR failed page=%s: %s", page_number, type(e).__name__)
            return ""

    return _ocr
