"""PDF 페이지 강제 보장 + OCR/빈 페이지 정직성 계약 테스트 (deterministic).

가드하는 증상:
  1. PDF 가 2~3장이어도 세부 핵심이 1/1 페이지만 나옴 → totalPages/pageAnalyses 가 실제 페이지 수.
  2. 1페이지 OCR 실패가 전체를 1페이지로 축소 → 모든 페이지 보존, 이미지 페이지는 OCR/이미지 status.
  4. 빈 페이지는 EMPTY_PAGE 로 표기하되 전체 페이지 수는 유지.

PyMuPDF 가 없으면 PDF 합성 테스트는 skip 한다.
"""
import pytest

fitz = pytest.importorskip("fitz")

from app.api.major_analysis_routes import (
    MajorAnalysisRequest,
    _attach_page_schema,
    _detailed_from_pages,
    _new_schema_pages,
    _normalize_page_summaries,
    _pages_from_pdf,
)


def _text_pdf(texts):
    doc = fitz.open()
    for body in texts:
        page = doc.new_page()
        page.insert_text((72, 72), body, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


_NOT_ENOUGH = ("OCR 정보 부족", "텍스트 추출 결과가 부족", "정보가 더 필요")


# ── 1. 3-page text PDF → totalPages==3, pageAnalyses==3, detailedCoreContents>=3 ──
def test_three_page_text_pdf_full_coverage():
    pdf = _text_pdf([
        "algorithm complexity recursion sorting tree traversal",
        "matrix eigenvalue derivative integral linear algebra",
        "probability sample variance regression statistics",
    ])
    req = MajorAnalysisRequest(materialId=1)
    pages = _pages_from_pdf(pdf, req)
    assert [p["page"] for p in pages] == [1, 2, 3]
    assert all(p["source"] == "TEXT" for p in pages)

    # LLM 요약이 비어도(빈 parsed) 페이지 entry 는 텍스트 기반으로 모두 유지된다.
    summaries = _normalize_page_summaries([], pages, ocr_enabled=False)
    assert len(summaries) == 3

    result = _attach_page_schema({"pageSummaries": summaries})
    assert result["totalPages"] == 3
    assert len(result["pageAnalyses"]) == 3
    assert len(result["pages"]) == 3
    assert [p["pageNumber"] for p in result["pageAnalyses"]] == [1, 2, 3]

    detailed = _detailed_from_pages(summaries)
    assert len(detailed) >= 3


# ── 2. 이미지 전용(OCR) 페이지 매핑: status OCR, sourceType image, '정보 부족' 카드 아님 ──
def test_image_only_page_maps_to_ocr_status():
    ocr = "강의자료 Material UI Scaffold 안드로이드 컴포넌트 상단바 하단바"
    pages = [{"page": 1, "text": ocr, "source": "OCR", "rawText": ocr, "imageDescription": ocr}]
    summaries = _normalize_page_summaries(
        [{"page": 1, "title": "Material UI", "pageOverview": "Scaffold 구조",
          "keyConcepts": ["Scaffold"], "summaryBullets": ["상단바/하단바"], "studyFocus": "슬롯 이해"}],
        pages, ocr_enabled=True,
    )
    analyses = _new_schema_pages(summaries)
    assert len(analyses) == 1
    a = analyses[0]
    assert a["extractionStatus"] == "OCR"
    assert a["sourceType"] == "image"
    assert a["imageDescription"] == ocr
    # 최종 사용자 카드가 '정보 부족' 류가 아니어야 한다(실제 OCR 내용이 있으므로).
    assert not any(bad in (a["summary"] + a["coreTitle"]) for bad in _NOT_ENOUGH)


def test_ocr_disabled_image_page_is_ocr_failed_not_text():
    # 이미지 기반인데 텍스트 레이어가 비고 OCR 비활성 → OCR_FAILED(거짓 TEXT 보고 금지)
    pages = [{"page": 1, "text": "", "source": "INSUFFICIENT", "rawText": "", "imageDescription": ""}]
    summaries = _normalize_page_summaries([], pages, ocr_enabled=False)
    a = _new_schema_pages(summaries)[0]
    assert a["extractionStatus"] in ("OCR_FAILED", "EMPTY_PAGE")
    assert a["needsReview"] is True


# ── 4. 빈 페이지는 EMPTY_PAGE 로 표기, 전체 페이지 수 유지 ─────────────────────
def test_empty_trailing_page_kept_as_empty_page():
    # 1p 텍스트 + 선언 3p → 2,3 은 빈 페이지로 backfill 되어도 totalPages 는 3 유지.
    pdf = _text_pdf(["algorithm complexity recursion sorting tree"])
    req = MajorAnalysisRequest(materialId=2, pageCount=3)
    # _pages_from_pdf 는 PDF page_count(=1)만 보지만, 빈 페이지 정직 처리 자체를 검증한다.
    pages = [
        {"page": 1, "text": "algorithm complexity recursion sorting tree", "source": "TEXT",
         "rawText": "algorithm complexity recursion sorting tree", "imageDescription": ""},
        {"page": 2, "text": "", "source": "EMPTY", "rawText": "", "imageDescription": ""},
        {"page": 3, "text": "", "source": "EMPTY", "rawText": "", "imageDescription": ""},
    ]
    summaries = _normalize_page_summaries([], pages, ocr_enabled=True)
    result = _attach_page_schema({"pageSummaries": summaries})
    assert result["totalPages"] == 3
    statuses = [p["extractionStatus"] for p in result["pageAnalyses"]]
    assert statuses[1] == "EMPTY_PAGE" and statuses[2] == "EMPTY_PAGE"
    assert result["pageAnalyses"][1]["needsReview"] is True
