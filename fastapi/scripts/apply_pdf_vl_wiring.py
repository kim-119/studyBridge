#!/usr/bin/env python3
"""Idempotent wiring applier for the PDF text-normalizer (qwen3-vl) layer.

WHY THIS EXISTS
---------------
ai07 runs ``studybridge-ai07-autodeploy.timer`` which does ``git reset --hard
origin/LLM-clean`` every ~2 minutes. That wipes any edit to a *tracked* file.
The normalizer itself (``app/services/pdf_text_normalizer.py`` +
``app/services/ollama_vision_client.py`` + tests) is *untracked*, so it survives.
The few lines of glue that connect it to the existing summary / keyword / quiz /
roadmap / RAG / AI-chat pipelines live in tracked files, so they keep getting
reset.

This script re-applies that glue. It is **idempotent** — run it as many times as
you like; each edit is skipped if its marker is already present. Run it after a
reset to re-materialise the wiring, then run the verifier.

USAGE
-----
    cd ~/capstoneLLM/fastapi
    .venv/bin/python scripts/apply_pdf_vl_wiring.py          # apply
    .venv/bin/python scripts/apply_pdf_vl_wiring.py --check  # report only

Each edit is an exact-string replacement against the current origin/LLM-clean
content. If an anchor is missing (upstream changed), that edit is reported as
FAILED rather than silently corrupting the file.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # .../fastapi
MARKER = "VL normalizer fallback"  # presence => already wired (most edits)


class Edit:
    def __init__(self, rel_path: str, anchor: str, replacement: str, marker: str = MARKER):
        self.path = ROOT / rel_path
        self.anchor = anchor
        self.replacement = replacement
        self.marker = marker

    def apply(self, check_only: bool) -> str:
        if not self.path.exists():
            return f"MISSING FILE  {self.path}"
        text = self.path.read_text(encoding="utf-8")
        if self.marker in text:
            return f"already wired {self.path.relative_to(ROOT)}"
        if self.anchor not in text:
            return f"FAILED anchor {self.path.relative_to(ROOT)} (upstream changed?)"
        if text.count(self.anchor) != 1:
            return f"FAILED ambiguous anchor x{text.count(self.anchor)} {self.path.relative_to(ROOT)}"
        if check_only:
            return f"would wire  {self.path.relative_to(ROOT)}"
        self.path.write_text(text.replace(self.anchor, self.replacement, 1), encoding="utf-8")
        return f"WIRED        {self.path.relative_to(ROOT)}"


EDITS: list[Edit] = []

# ── 1) s3_pdf_loader.load_text_from_s3_pdf — central S3→text VL fallback ───────
# Covers: roadmap, RAG ingest-by-s3, summary/keyword (via _prepare_context),
# and anything else routed through the shared S3 text loader.
EDITS.append(Edit(
    "app/services/s3_pdf_loader.py",
    anchor=(
        '    if len(best.strip()) < 50:\n'
        '        logger.warning("PDF 텍스트가 너무 짧습니다 (%d자): %s", len(best.strip()), file_name)\n'
        '    return best'
    ),
    replacement=(
        '    # VL normalizer fallback (the "eye" in front of qwen3:14b). Only reached for\n'
        '    # image-only / scanned PDFs where native + pypdf + OCR all came up short.\n'
        '    # normalize_pdf never fires VL for pages whose native text is sufficient, so\n'
        '    # text PDFs never reach here and stay fast. Returns a plain str (schema-safe).\n'
        '    if len(best.strip()) < 50:\n'
        '        try:\n'
        '            from app.services.pdf_text_normalizer import normalize_pdf\n'
        '            norm = normalize_pdf(pdf_bytes)\n'
        '            if len((norm.merged_text or "").strip()) > len(best.strip()):\n'
        '                logger.info(\n'
        '                    "S3 PDF VL normalizer fallback file=%s mode=%s vl_pages=%s ocr_pages=%s merged_len=%s",\n'
        '                    file_name, norm.document_mode, norm.vl_pages, norm.ocr_pages, len(norm.merged_text),\n'
        '                )\n'
        '                best = norm.merged_text\n'
        '        except Exception as e4:\n'
        '            logger.warning("S3 PDF VL normalizer fallback exception: %s", type(e4).__name__)\n'
        '\n'
        '    if len(best.strip()) < 50:\n'
        '        logger.warning("PDF 텍스트가 너무 짧습니다 (%d자): %s", len(best.strip()), file_name)\n'
        '    return best'
    ),
))

# ── 2) main._extract_pdf_text — 자료보관함 grounded quiz + 그룹스터디 quiz ──────
# generate_quiz_from_pdf (S3 bytes, has group_id) routes through this.
EDITS.append(Edit(
    "main.py",
    anchor=(
        '            logger.info("quiz PDF OCR attempted engine=%s chars=%s reason=%s", ocr.engine, len(ocr.text or ""), ocr.reason)\n'
        '        except Exception as e:\n'
        '            logger.warning("quiz PDF OCR exception: %s", type(e).__name__)\n'
        '    return _normalize_pdf_text(best), method'
    ),
    replacement=(
        '            logger.info("quiz PDF OCR attempted engine=%s chars=%s reason=%s", ocr.engine, len(ocr.text or ""), ocr.reason)\n'
        '        except Exception as e:\n'
        '            logger.warning("quiz PDF OCR exception: %s", type(e).__name__)\n'
        '\n'
        '    # VL normalizer fallback (image-only / scanned PDF). Only reached when\n'
        '    # native + pypdf + OCR all stayed under threshold; text PDFs never get here,\n'
        '    # so VL is never called for them. merged_text is plain text for qwen3:14b.\n'
        '    if len(best.strip()) < 100:\n'
        '        try:\n'
        '            from app.services.pdf_text_normalizer import normalize_pdf\n'
        '            norm = normalize_pdf(pdf_bytes)\n'
        '            if len((norm.merged_text or "").strip()) > len(best.strip()):\n'
        '                logger.info("quiz PDF VL normalizer fallback mode=%s vl_pages=%s merged_len=%s",\n'
        '                            norm.document_mode, norm.vl_pages, len(norm.merged_text))\n'
        '                best, method = norm.merged_text, f"vl_normalizer:{norm.document_mode}"\n'
        '        except Exception as e:\n'
        '            logger.warning("quiz PDF VL normalizer exception: %s", type(e).__name__)\n'
        '\n'
        '    return _normalize_pdf_text(best), method'
    ),
))

# ── 3a) material_analyze_routes._prepare_context — summary/keyword S3+VL ───────
EDITS.append(Edit(
    "app/api/material_analyze_routes.py",
    anchor=(
        'async def _prepare_context(material_id: Optional[int], text: Optional[str]) -> tuple[str, Dict[str, Any]]:\n'
        '    """추출 텍스트 검증 + chunk 기반 bounded context 생성. (context, text_status)"""\n'
        '    from app.services.material_ai_manager import validate_extracted_text, build_summary_context\n'
        '    from app.services.chunk_cache import get_or_build_chunks\n'
        '\n'
        '    ts = validate_extracted_text(text)\n'
        '    text_status = {'
    ),
    replacement=(
        'async def _prepare_context(material_id: Optional[int], text: Optional[str],\n'
        '                           s3_key: Optional[str] = None) -> tuple[str, Dict[str, Any]]:\n'
        '    """추출 텍스트 검증 + chunk 기반 bounded context 생성. (context, text_status)"""\n'
        '    from app.services.material_ai_manager import validate_extracted_text, build_summary_context\n'
        '    from app.services.chunk_cache import get_or_build_chunks\n'
        '\n'
        '    ts = validate_extracted_text(text)\n'
        '    # VL normalizer fallback: 이미지-only/스캔 PDF로 Spring이 추출 텍스트를 못 보낸 경우\n'
        '    # S3에서 직접 로드(load_text_from_s3_pdf 안에 native->OCR->qwen3-vl 정규화가 들어있음).\n'
        '    # qwen3:14b 에는 텍스트만 전달된다. 텍스트가 충분하면 이 분기는 타지 않는다.\n'
        '    if not ts.get("ok") and s3_key and s3_key.strip():\n'
        '        try:\n'
        '            from app.services.s3_pdf_loader import load_text_from_s3_pdf\n'
        '            loaded = await asyncio.to_thread(load_text_from_s3_pdf, s3_key, "")\n'
        '            if loaded and loaded.strip():\n'
        '                text = loaded\n'
        '                ts = validate_extracted_text(text)\n'
        '        except Exception as e:\n'
        '            logger.warning("analyze S3/VL normalizer fallback failed: %s", type(e).__name__)\n'
        '    text_status = {'
    ),
    marker="VL normalizer fallback: 이미지-only",
))

# ── 3b) material_analyze_routes — pass s3Key at the 3 call sites ───────────────
EDITS.append(Edit(
    "app/api/material_analyze_routes.py",
    anchor='    context, ts = await _prepare_context(material_id, text)\n    if not ts.get("ok"):\n        return {"error_code": "PDF_TEXT_EMPTY",',
    replacement='    context, ts = await _prepare_context(material_id, text, body.get("s3Key") or body.get("s3_key"))\n    if not ts.get("ok"):\n        return {"error_code": "PDF_TEXT_EMPTY",',
    marker='_prepare_context(material_id, text, body.get("s3Key") or body.get("s3_key"))\n    if not ts.get("ok"):\n        return {"error_code": "PDF_TEXT_EMPTY"',
))
EDITS.append(Edit(
    "app/api/material_analyze_routes.py",
    anchor='    context, ts = await _prepare_context(material_id, text)\n    job_id = uuid.uuid4().hex',
    replacement='    context, ts = await _prepare_context(material_id, text, body.get("s3Key") or body.get("s3_key"))\n    job_id = uuid.uuid4().hex',
    marker='_prepare_context(material_id, text, body.get("s3Key") or body.get("s3_key"))\n    job_id = uuid.uuid4().hex',
))
EDITS.append(Edit(
    "app/api/material_analyze_routes.py",
    anchor='        context, ts = await _prepare_context(material_id, text)\n        if not ts.get("ok"):\n            yield _sse("error"',
    replacement='        context, ts = await _prepare_context(material_id, text, body.get("s3Key") or body.get("s3_key"))\n        if not ts.get("ok"):\n            yield _sse("error"',
    marker='_prepare_context(material_id, text, body.get("s3Key") or body.get("s3_key"))\n        if not ts.get("ok"):\n            yield _sse("error"',
))

# ── 4) material_legacy_routes.ai_quiz — 자료보관함 text 퀴즈 S3+VL fallback ─────
# When Spring sends no usable text (image PDF) but a s3_file_url is present, load
# the PDF text (VL-capable) before failing with PDF_OCR_REQUIRED.
EDITS.append(Edit(
    "app/api/material_legacy_routes.py",
    anchor=(
        '    ts = validate_extracted_text(combined_for_check or None)\n'
        '\n'
        '    # 완전히 비어 있으면 OCR 안내(이미지 PDF), 짧으면 PDF_TEXT_INSUFFICIENT.\n'
        '    if ts["status"] == "empty":'
    ),
    replacement=(
        '    ts = validate_extracted_text(combined_for_check or None)\n'
        '\n'
        '    # VL normalizer fallback: 이미지-only PDF로 텍스트가 비었지만 s3_file_url 이 있으면\n'
        '    # S3에서 직접 로드(native->OCR->qwen3-vl)해 같은 텍스트 기반 퀴즈 파이프라인을 탄다.\n'
        '    if ts["status"] == "empty" and getattr(req, "s3_file_url", None):\n'
        '        try:\n'
        '            from app.services.s3_pdf_loader import load_text_from_s3_pdf\n'
        '            _norm = normalize_s3_key(req.s3_file_url) if "normalize_s3_key" in globals() else req.s3_file_url\n'
        '            loaded = await asyncio.to_thread(load_text_from_s3_pdf, _norm, req.document_title or "")\n'
        '            if loaded and loaded.strip():\n'
        '                primary_text = loaded.strip()\n'
        '                combined_for_check = primary_text\n'
        '                ts = validate_extracted_text(combined_for_check or None)\n'
        '        except Exception as _e:\n'
        '            logger.warning("material quiz S3/VL normalizer fallback failed: %s", type(_e).__name__)\n'
        '\n'
        '    # 완전히 비어 있으면 OCR 안내(이미지 PDF), 짧으면 PDF_TEXT_INSUFFICIENT.\n'
        '    if ts["status"] == "empty":'
    ),
    marker="VL normalizer fallback: 이미지-only PDF로 텍스트가 비었지만",
))

# ── 5) rag_schema.IngestRequest — optional s3Key + allow empty text ────────────
# Additive + backward compatible: existing callers that send text still work.
EDITS.append(Edit(
    "app/schemas/rag_schema.py",
    anchor=(
        '    material_id:    int = Field(..., description="자료 ID (Spring Boot material_id와 일치)")\n'
        '    document_title: str = Field(..., description="문서 제목")\n'
        '    text:           str = Field(..., description="PDF에서 추출한 전체 텍스트", min_length=1)'
    ),
    replacement=(
        '    material_id:    int = Field(..., description="자료 ID (Spring Boot material_id와 일치)")\n'
        '    document_title: str = Field(..., description="문서 제목")\n'
        '    # text 가 비어 있어도(이미지-only PDF) s3Key 가 있으면 서버가 VL 정규화로 텍스트를 만든다.\n'
        '    text:           str = Field("", description="PDF에서 추출한 전체 텍스트(없으면 s3Key로 서버 추출)")\n'
        '    s3Key:          str | None = Field(None, description="이미지 PDF용: text 미제공 시 S3에서 직접 로드+VL 정규화")'
    ),
    marker="s3Key:          str | None = Field(None, description=",
))

# ── 6) rag_routes — ingest VL fallback for AI 채팅(PDF 기반) over image PDFs ────
EDITS.append(Edit(
    "app/api/rag_routes.py",
    anchor=(
        'async def rag_ingest(\n'
        '    request: IngestRequest,\n'
        '    material_id: int = Path(..., gt=0),\n'
        ') -> IngestResponse:\n'
        '    if not request.text.strip():\n'
        '        raise HTTPException(status_code=400, detail="text는 비워둘 수 없습니다.")'
    ),
    replacement=(
        'async def rag_ingest(\n'
        '    request: IngestRequest,\n'
        '    material_id: int = Path(..., gt=0),\n'
        ') -> IngestResponse:\n'
        '    text = await _resolve_ingest_text(request)  # VL normalizer fallback for image PDFs\n'
        '    if not text.strip():\n'
        '        raise HTTPException(status_code=400, detail="text는 비워둘 수 없습니다.")'
    ),
    marker="text = await _resolve_ingest_text(request)",
))
EDITS.append(Edit(
    "app/api/rag_routes.py",
    anchor=(
        '            ingest_document,\n'
        '            material_id=material_id,\n'
        '            document_title=request.document_title,\n'
        '            text=request.text,\n'
        '        )'
    ),
    replacement=(
        '            ingest_document,\n'
        '            material_id=material_id,\n'
        '            document_title=request.document_title,\n'
        '            text=text,\n'
        '        )'
    ),
    marker="            text=text,\n        )\n    except ValueError as e:\n        raise HTTPException(status_code=400, detail=str(e))\n    except RuntimeError as e:\n        raise HTTPException(status_code=500, detail=str(e))\n\n    return IngestResponse(**result)",
))
EDITS.append(Edit(
    "app/api/rag_routes.py",
    anchor=(
        'async def spring_rag_ingest(request: IngestRequest) -> IngestResponse:\n'
        '    if not request.text.strip():\n'
        '        raise HTTPException(status_code=400, detail="text는 비워둘 수 없습니다.")\n'
        '\n'
        '    from app.services.rag_ingest_service import ingest_document\n'
        '    try:\n'
        '        result = await asyncio.to_thread(\n'
        '            ingest_document,\n'
        '            material_id=request.material_id,\n'
        '            document_title=request.document_title,\n'
        '            text=request.text,\n'
        '        )'
    ),
    replacement=(
        'async def spring_rag_ingest(request: IngestRequest) -> IngestResponse:\n'
        '    text = await _resolve_ingest_text(request)  # VL normalizer fallback for image PDFs\n'
        '    if not text.strip():\n'
        '        raise HTTPException(status_code=400, detail="text는 비워둘 수 없습니다.")\n'
        '\n'
        '    from app.services.rag_ingest_service import ingest_document\n'
        '    try:\n'
        '        result = await asyncio.to_thread(\n'
        '            ingest_document,\n'
        '            material_id=request.material_id,\n'
        '            document_title=request.document_title,\n'
        '            text=text,\n'
        '        )'
    ),
    marker="async def spring_rag_ingest(request: IngestRequest) -> IngestResponse:\n    text = await _resolve_ingest_text(request)",
))
# helper injected once, just below the imports of rag_routes
EDITS.append(Edit(
    "app/api/rag_routes.py",
    anchor='logger = logging.getLogger(__name__)\n',
    replacement=(
        'logger = logging.getLogger(__name__)\n'
        '\n'
        '\n'
        'async def _resolve_ingest_text(request) -> str:\n'
        '    """Return request.text, or — for image-only PDFs with an s3Key but no text —\n'
        '    load + VL-normalize the PDF from S3. qwen3:14b/embeddings only ever see text."""\n'
        '    text = (request.text or "").strip()\n'
        '    if text:\n'
        '        return text\n'
        '    s3_key = getattr(request, "s3Key", None) or getattr(request, "s3_key", None)\n'
        '    if not s3_key:\n'
        '        return text\n'
        '    try:\n'
        '        from app.services.s3_pdf_loader import load_text_from_s3_pdf\n'
        '        loaded = await asyncio.to_thread(\n'
        '            load_text_from_s3_pdf, s3_key, getattr(request, "document_title", "") or "")\n'
        '        if loaded and loaded.strip():\n'
        '            logger.info("RAG ingest VL normalizer fallback materialId=%s loaded_len=%s",\n'
        '                        getattr(request, "material_id", None), len(loaded))\n'
        '            return loaded.strip()\n'
        '    except Exception as e:  # noqa: BLE001\n'
        '        logger.warning("RAG ingest S3/VL normalizer fallback failed: %s", type(e).__name__)\n'
        '    return text\n'
    ),
    marker="async def _resolve_ingest_text(request) -> str:",
))


def main() -> int:
    check_only = "--check" in sys.argv
    print(f"[apply_pdf_vl_wiring] root={ROOT} mode={'CHECK' if check_only else 'APPLY'}\n")
    results = [e.apply(check_only) for e in EDITS]
    failed = [r for r in results if r.startswith("FAILED") or r.startswith("MISSING")]
    for r in results:
        print("  " + r)
    print(f"\n{len(results)} edits, {len(failed)} failed/missing")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
