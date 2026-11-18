"""Image-page + unified-schema contract tests for /api/ai/major-analysis/note.

Deterministic (no LLM, no S3): exercises the PDF→pages adapter, the per-page
normalization carrying OCR descriptions, and the unified ``totalPages`` /
``pages`` output schema (spec #4). The live path additionally loads the PDF
from S3 and runs real OCR; here we synthesize PDFs and hand-build summaries.
"""
import pytest

fitz = pytest.importorskip("fitz")

from app.api.major_analysis_routes import (
    MajorAnalysisRequest,
    _attach_page_schema,
    _new_schema_pages,
    _normalize_page_summaries,
    _pages_from_pdf,
    _source_type_of,
)


def _text_pdf(texts):
    doc = fitz.open()
    for body in texts:
        page = doc.new_page()
        page.insert_text((72, 72), body, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


# ── PDF → pages adapter (authoritative page count) ───────────────────────────

def test_pages_from_pdf_three_text_pages():
    req = MajorAnalysisRequest(materialId=1)
    pages = _pages_from_pdf(
        _text_pdf(["algorithm complexity recursion sorting",
                   "matrix eigenvalue derivative integral",
                   "probability sample variance regression"]),
        req,
    )
    assert [p["page"] for p in pages] == [1, 2, 3]
    assert all(p["source"] == "TEXT" for p in pages)
    assert "algorithm" in pages[0]["text"]


# ── normalization carries OCR description + image sourceType ─────────────────

def test_image_page_keeps_ocr_description_and_summary():
    # Simulate an image page after PDF extraction: source=OCR, rawText=OCR content.
    ocr = "Material UI Scaffold 강의자료 학습 목표 안드로이드 컴포넌트"
    pages = [{"page": 1, "text": ocr, "source": "OCR", "rawText": ocr, "imageDescription": ocr}]
    llm = [{"page": 1, "title": "Material UI 기초", "pageOverview": "Scaffold 구조 설명",
            "keyConcepts": ["Scaffold", "Material UI"], "summaryBullets": ["상단바/하단바 구성"],
            "studyFocus": "Scaffold 슬롯 이해"}]
    out = _normalize_page_summaries(llm, pages, ocr_enabled=True)
    assert len(out) == 1
    e = out[0]
    assert e["title"] == "Material UI 기초"
    assert e["imageDescription"] == ocr
    assert _source_type_of(e) == "image"


def test_empty_image_page_not_dropped():
    pages = [{"page": 1, "text": "", "source": "EMPTY", "rawText": "", "imageDescription": ""}]
    out = _normalize_page_summaries([], pages, ocr_enabled=True)
    assert len(out) == 1  # present, not dropped
    assert out[0]["page"] == 1


# ── unified schema (totalPages + pages[]) ────────────────────────────────────

def test_new_schema_field_mapping():
    summaries = [
        {"page": 1, "title": "T", "pageOverview": "ov", "summaryBullets": ["b1", "b2"],
         "keyConcepts": ["k1"], "studyFocus": "goal", "detectedTextSource": "TEXT",
         "sourceQuality": "TEXT", "extractedText": "raw text", "imageDescription": ""},
        {"page": 2, "title": "Img", "pageOverview": "slide", "summaryBullets": [],
         "keyConcepts": ["Scaffold"], "studyFocus": "", "detectedTextSource": "OCR",
         "sourceQuality": "TEXT", "extractedText": "", "imageDescription": "Scaffold UI"},
    ]
    pages = _new_schema_pages(summaries)
    assert [p["pageNumber"] for p in pages] == [1, 2]
    assert pages[0]["sourceType"] == "text"
    assert pages[0]["summary"] == "ov"
    assert pages[0]["learningGoal"] == "goal"
    assert pages[1]["sourceType"] == "image"
    assert pages[1]["imageDescription"] == "Scaffold UI"
    assert 0.0 <= pages[1]["confidence"] <= 1.0


def test_attach_schema_totalpages_matches_pagesummaries():
    result = {"pageSummaries": [{"page": i, "title": f"p{i}", "pageOverview": "x",
                                 "detectedTextSource": "TEXT", "sourceQuality": "TEXT"}
                                for i in range(1, 6)]}
    out = _attach_page_schema(result)
    assert out["totalPages"] == 5
    assert len(out["pages"]) == 5
    assert [p["pageNumber"] for p in out["pages"]] == [1, 2, 3, 4, 5]


def test_source_type_classification():
    assert _source_type_of({"detectedTextSource": "TEXT", "sourceQuality": "TEXT"}) == "text"
    assert _source_type_of({"detectedTextSource": "OCR", "sourceQuality": "TEXT"}) == "image"
    assert _source_type_of({"detectedTextSource": "MIXED", "sourceQuality": "TEXT"}) == "mixed"
    assert _source_type_of({"detectedTextSource": "INSUFFICIENT", "sourceQuality": "EMPTY"}) == "empty"
    assert _source_type_of({"detectedTextSource": "INSUFFICIENT", "sourceQuality": "OCR_DISABLED"}) == "image"
    assert _source_type_of({"detectedTextSource": "TEXT", "sourceQuality": "TEXT",
                            "imageDescription": "slide caption"}) == "mixed"
