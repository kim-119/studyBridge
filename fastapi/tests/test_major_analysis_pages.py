"""Deterministic contract tests for page-level detailed core contents.

These tests exercise ONLY the deterministic layer of
``/api/ai/major-analysis/note`` (page splitting + page-count backfill +
per-page field normalization). They never call an LLM, so they are fast and
stable.

Root cause they guard against: EC2 Spring sends the whole PDF as a single
``{page:1, text:"...[Page N]..."}`` blob (extract_compat emits ``[Page N]``
markers only for text-bearing pages, never form-feed) while Spring's
buildPageTexts split only on form-feed — so multi-page PDFs collapsed into a
single ``p.1`` and the React DetailedPager showed ``1 / 1`` instead of
``1 / 9`` / ``1 / 23``.

Covers (maps to the spec's required tests 1-9):
  1. single blob with mixed ``[Page 1]`` / ``[Page2]`` / ``[Page 5]`` markers
  2. ``[OCR Page N]`` marker recognition (with/without space)
  3. form-feed splitting (no markers)
  4. marker-less / already-paged input is idempotent (no page renumbering)
  5. pageCount=9 with only 1 page of text -> pageSummaries length == 9
  6. pageCount=23 with sparse text -> 23 entries; max-marker inference backfill
  7. sourceQuality INSUFFICIENT / OCR_DISABLED / EMPTY honesty
  8. extractedText cap + ``extractedTextTruncated`` flag/warning
  9. detailedCoreContents preserved + length tracks pageSummaries
plus: additive new-name aliases (pageNumber/oneLineSummary/keywords/
bulletPoints/takeaway) coexist with legacy fields, and no over-count.
"""
from app.api.major_analysis_routes import (
    MajorAnalysisRequest,
    _PageItem,
    _backfill_pages,
    _collect_pages,
    _detailed_from_pages,
    _explode_pages,
    _normalize_page_summaries,
    _page_source_quality,
    _page_warnings,
    _MAX_EXTRACTED_TEXT,
)

LONG = "Alpha beta gamma delta epsilon zeta "  # >= _MIN_PAGE_MEANINGFUL meaningful chars


def P(page, text):
    return _PageItem(page=page, text=text)


# ── 1. mixed [Page 1] / [Page2] / [Page 5] single blob → real page numbers ──
def test_explode_mixed_markers_preserves_real_page_numbers():
    blob = "\n\n[Page 1]\nAlpha content here\n\n[Page2]\nBeta content here\n\n[Page 5]\nEpsilon content here\n"
    out = _explode_pages([P(1, blob)])
    assert [it.page for it in out] == [1, 2, 5]
    texts = {it.page: it.text for it in out}
    assert "Alpha content here" in texts[1]
    assert "[Page" not in texts[1]  # marker stripped from segment
    assert "Beta content here" in texts[2]
    assert "Epsilon content here" in texts[5]


# ── 2. [OCR Page N] recognized (with and without space before number) ──
def test_explode_recognizes_ocr_page_marker():
    blob = "[Page 2]\nfoo body text here\n[OCR Page 3]\nbar body text here"
    out = _explode_pages([P(1, blob)])
    assert [it.page for it in out] == [2, 3]
    assert "bar body text here" in {it.page: it.text for it in out}[3]


def test_marker_regex_handles_nospace_variants():
    blob = "[Page2]\nblock two body\n[OCR Page4]\nblock four body"
    out = _explode_pages([P(1, blob)])
    assert [it.page for it in out] == [2, 4]


# ── 3. form-feed split (no markers) → sequential from entry.page ──
def test_explode_formfeed_sequential_numbering():
    out = _explode_pages([P(1, "first page body\fsecond page body\fthird page body")])
    assert [it.page for it in out] == [1, 2, 3]
    # entry.page None → start at 1
    out2 = _explode_pages([P(None, "aaa body\fbbb body")])
    assert [it.page for it in out2] == [1, 2]


# ── 4. marker-less / already-paged input is idempotent (no shuffle) ──
def test_explode_idempotent_for_normal_multipage_array():
    items = [P(1, "page one body"), P(2, "page two body"), P(7, "page seven body")]
    out = _explode_pages(items)
    assert [it.page for it in out] == [1, 2, 7]
    assert [it.text for it in out] == ["page one body", "page two body", "page seven body"]


def test_explode_single_marker_entry_is_not_split():
    # rule: only entries with >=2 markers are exploded
    out = _explode_pages([P(4, "[Page 4]\nonly one marker present here")])
    assert len(out) == 1
    assert out[0].page == 4


# ── 5. pageCount=9, only 1 page has text → pageSummaries length == 9 ──
def test_declared_pagecount_backfills_to_full_length():
    req = MajorAnalysisRequest(pageTexts=[P(1, LONG * 5)], pageCount=9)
    pages = _collect_pages(req)
    assert [p["page"] for p in pages] == list(range(1, 10))  # 1..9, no gaps

    summaries = _normalize_page_summaries([], pages)
    assert len(summaries) == 9
    assert [s["page"] for s in summaries] == list(range(1, 10))
    assert [s["pageNumber"] for s in summaries] == list(range(1, 10))  # alias too
    # page 1 has text; 2..9 are honest empty/ocr-disabled fallbacks
    assert summaries[0]["sourceQuality"] == "TEXT"
    for s in summaries[1:]:
        assert s["sourceQuality"] in {"OCR_DISABLED", "EMPTY"}
        assert s["keywords"] == [] and s["bulletPoints"] == []


# ── 6. pageCount=23 + sparse markers → 23 entries; inference when no count ──
def test_declared_pagecount_23_with_sparse_markers():
    blob = f"[Page 1]\n{LONG*5}\n[Page 12]\n{LONG*5}\n[Page 23]\n{LONG*5}"
    req = MajorAnalysisRequest(pageTexts=[P(1, blob)], totalPages=23)
    pages = _collect_pages(req)
    assert [p["page"] for p in pages] == list(range(1, 24))
    summaries = _normalize_page_summaries([], pages)
    assert len(summaries) == 23
    assert {s["page"] for s in (summaries[0], summaries[11], summaries[22])} == {1, 12, 23}


def test_max_marker_inference_backfills_without_declared_count():
    # No pageCount provided: infer N from the highest [Page N] marker, fill gaps.
    blob = f"[Page 1]\n{LONG*5}\n[Page 9]\n{LONG*5}"
    req = MajorAnalysisRequest(pageTexts=[P(1, blob)])
    pages = _collect_pages(req)
    assert [p["page"] for p in pages] == list(range(1, 10))  # 1..9
    summaries = _normalize_page_summaries([], pages)
    assert len(summaries) == 9


def test_declared_count_never_drops_real_pages_no_over_no_under():
    # declared 3 but a real [Page 5] exists → keep 5, fill 2,3,4 → 1..5 (floor, not ceiling)
    blob = f"[Page 1]\n{LONG*5}\n[Page 5]\n{LONG*5}"
    req = MajorAnalysisRequest(pageTexts=[P(1, blob)], pageCount=3)
    pages = _collect_pages(req)
    assert [p["page"] for p in pages] == [1, 2, 3, 4, 5]


def test_backfill_pages_helper_fills_gaps_only():
    real = [{"page": 1, "text": "x", "source": "TEXT", "rawText": "x"},
            {"page": 3, "text": "y", "source": "TEXT", "rawText": "y"}]
    out = _backfill_pages(real, 4)
    assert [p["page"] for p in out] == [1, 2, 3, 4]
    assert out[1]["source"] == "EMPTY" and out[3]["source"] == "EMPTY"
    assert out[0]["source"] == "TEXT" and out[2]["source"] == "TEXT"


# ── 7. sourceQuality / warnings honesty ──
def test_insufficient_page_is_honest():
    req = MajorAnalysisRequest(pageTexts=[P(1, "ab")])  # < _MIN_PAGE_MEANINGFUL
    pages = _collect_pages(req)
    summaries = _normalize_page_summaries([], pages)
    s = summaries[0]
    assert s["sourceQuality"] == "INSUFFICIENT"
    assert "TEXT_EXTRACTION_INSUFFICIENT" in s["warnings"]
    assert s["detectedTextSource"] == "INSUFFICIENT"


def test_image_only_backfilled_page_reports_ocr_disabled_when_ocr_off(monkeypatch):
    monkeypatch.setenv("OCR_ENABLED", "false")
    req = MajorAnalysisRequest(pageTexts=[P(1, LONG * 5)], pageCount=2)
    pages = _collect_pages(req)
    summaries = _normalize_page_summaries([], pages)
    p2 = summaries[1]
    assert p2["sourceQuality"] == "OCR_DISABLED"
    assert "OCR_DISABLED" in p2["warnings"] and "PAGE_TEXT_EMPTY" in p2["warnings"]
    assert "이미지" in p2["title"]            # honest, page-specific title (not hardcoded)
    assert p2["oneLineSummary"]               # non-empty honest message
    assert p2["extractedText"] == "" and p2["textPreview"] == ""


def test_source_quality_enum_mapping():
    assert _page_source_quality(0, ocr_enabled=False) == "OCR_DISABLED"
    assert _page_source_quality(0, ocr_enabled=True) == "EMPTY"
    assert _page_source_quality(5, ocr_enabled=False) == "INSUFFICIENT"
    assert _page_source_quality(500, ocr_enabled=False) == "TEXT"


def test_page_warnings_vocabulary():
    assert _page_warnings(0, ocr_enabled=False, truncated=False) == ["PAGE_TEXT_EMPTY", "OCR_DISABLED"]
    assert _page_warnings(0, ocr_enabled=True, truncated=False) == ["PAGE_TEXT_EMPTY"]
    assert _page_warnings(5, ocr_enabled=False, truncated=False) == ["TEXT_EXTRACTION_INSUFFICIENT"]
    assert _page_warnings(500, ocr_enabled=False, truncated=True) == ["EXTRACTED_TEXT_TRUNCATED"]
    assert _page_warnings(500, ocr_enabled=False, truncated=False) == []


# ── 8. extractedText cap + truncated flag/warning; textPreview is short ──
def test_extracted_text_truncation_flag_and_warning():
    long_text = "Xy " * _MAX_EXTRACTED_TEXT  # well over the cap
    req = MajorAnalysisRequest(pageTexts=[P(1, long_text)])
    pages = _collect_pages(req)
    summaries = _normalize_page_summaries(
        [{"page": 1, "title": "T", "pageOverview": "o", "summaryBullets": ["b"]}], pages
    )
    s = summaries[0]
    assert s["extractedTextTruncated"] is True
    assert len(s["extractedText"]) <= _MAX_EXTRACTED_TEXT
    assert "EXTRACTED_TEXT_TRUNCATED" in s["warnings"]
    assert len(s["textPreview"]) <= 220  # ~200 + ellipsis


def test_short_text_not_truncated():
    req = MajorAnalysisRequest(pageTexts=[P(1, LONG * 3)])
    pages = _collect_pages(req)
    summaries = _normalize_page_summaries(
        [{"page": 1, "title": "T", "pageOverview": "o", "summaryBullets": ["b"]}], pages
    )
    assert summaries[0]["extractedTextTruncated"] is False
    assert "EXTRACTED_TEXT_TRUNCATED" not in summaries[0]["warnings"]


# ── 9. additive contract: new aliases + legacy fields coexist; detailed tracks ──
def test_new_aliases_and_legacy_fields_coexist():
    blob = f"[Page 1]\n{LONG*5}\n[Page2]\n{LONG*5}"
    req = MajorAnalysisRequest(pageTexts=[P(1, blob)])
    pages = _collect_pages(req)
    summaries = _normalize_page_summaries(
        [{"page": 1, "title": "T1", "pageOverview": "o1", "keyConcepts": ["k"],
          "summaryBullets": ["b1"], "studyFocus": "f1"}],
        pages,
    )
    s = summaries[0]
    # legacy fields preserved (backward compatible)
    for legacy in ("page", "title", "detectedTextSource", "pageOverview",
                   "keyConcepts", "summaryBullets", "studyFocus"):
        assert legacy in s, f"missing legacy field {legacy}"
    # new additive fields present
    for new in ("pageNumber", "oneLineSummary", "keywords", "bulletPoints",
                "takeaway", "extractedText", "textPreview",
                "extractedTextTruncated", "sourceQuality", "warnings"):
        assert new in s, f"missing new field {new}"
    # aliases carry the same content as their legacy counterparts
    assert s["pageNumber"] == s["page"]
    assert s["oneLineSummary"] == s["pageOverview"]
    assert s["keywords"] == s["keyConcepts"]
    assert s["bulletPoints"] == s["summaryBullets"]
    assert s["takeaway"] == s["studyFocus"]


def test_detailed_core_contents_tracks_page_summaries_length():
    req = MajorAnalysisRequest(pageTexts=[P(1, LONG * 5)], pageCount=9)
    pages = _collect_pages(req)
    summaries = _normalize_page_summaries([], pages)
    detailed = _detailed_from_pages(summaries)
    assert len(detailed) == len(summaries) == 9
    for d in detailed:
        assert "title" in d and "content" in d
