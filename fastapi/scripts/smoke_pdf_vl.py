#!/usr/bin/env python3
"""Real qwen3-vl:4b smoke test for the PDF text normalizer.

Unlike the unit tests (which inject fake VL/OCR), this script hits the live
Ollama server. It prints per-page routing, VL call count, and the first 1000
chars of the merged text for each provided PDF.

Usage:
    python scripts/smoke_pdf_vl.py <pdf1> [<pdf2> ...]

If no paths are given it synthesizes a text PDF and an image-only PDF in memory
so you can verify "text => 0 VL calls" and "image-only => VL fires" end to end.

Requires: Ollama running with qwen3-vl:4b pulled.
"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.pdf_text_normalizer import normalize_pdf  # noqa: E402


def _synth_pdfs():
    import fitz
    from PIL import Image

    long_text = (
        "Operating systems lecture: a process is an instance of a running program "
        "with its own address space, scheduled by the kernel using context switches."
    )
    td = fitz.open()
    td.new_page().insert_text((72, 72), long_text, fontsize=11)
    text_pdf = td.tobytes()
    td.close()

    buf = io.BytesIO()
    Image.new("RGB", (240, 200), (40, 90, 160)).save(buf, format="PNG")
    idoc = fitz.open()
    pg = idoc.new_page(width=240, height=200)
    pg.insert_image(fitz.Rect(0, 0, 240, 200), stream=buf.getvalue())
    image_pdf = idoc.tobytes()
    idoc.close()
    return [("synthetic-text.pdf", text_pdf), ("synthetic-image-only.pdf", image_pdf)]


def _check_ollama():
    import requests
    base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("PDF_VL_MODEL", "qwen3-vl:4b")
    try:
        tags = requests.get(f"{base}/api/tags", timeout=5).json()
        names = [m.get("name", "") for m in tags.get("models", [])]
        ok = any(model.split(":")[0] in n for n in names)
        print(f"[ollama] {base} reachable; models={names}; {model} present={ok}")
        return ok
    except Exception as e:  # noqa: BLE001
        print(f"[ollama] NOT reachable: {type(e).__name__}: {e}")
        return False


def run_one(name: str, pdf_bytes: bytes):
    print("\n" + "=" * 78)
    print(f"PDF: {name}  ({len(pdf_bytes)} bytes)")
    print("=" * 78)
    result = normalize_pdf(pdf_bytes, cache_dir=None)
    print(f"document_mode = {result.document_mode}")
    print(f"total_pages   = {result.total_pages}")
    print(f"avg_native    = {result.avg_native_chars:.1f}")
    print(f"vl_pages      = {result.vl_pages}  ocr_pages = {result.ocr_pages}")
    print(f"truncated     = {result.truncated}  ok = {result.ok}")
    print(f"failed_pages  = {result.failed_pages}")
    print("-- per-page routing --")
    for p in result.pages:
        print(
            f"  page {p.page_number}: {p.source_method:12s} "
            f"native_len={p.native_text_len:5d} vl={p.vl_used} ocr={p.ocr_used} "
            f"err={p.error}"
        )
    print("-- merged_text[:1000] --")
    print(result.merged_text[:1000])


def main():
    _check_ollama()
    if len(sys.argv) > 1:
        items = []
        for path in sys.argv[1:]:
            with open(path, "rb") as f:
                items.append((os.path.basename(path), f.read()))
    else:
        print("[smoke] no PDF args -> using synthetic text + image-only PDFs")
        items = _synth_pdfs()
    for name, data in items:
        run_one(name, data)


if __name__ == "__main__":
    main()
