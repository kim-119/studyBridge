"""보강(enrichment) 품질 + HTML entity 디코드 계약 테스트 (deterministic, no LLM/network).

가드하는 증상:
  3. 보강 정보가 자료와 무관한 사전식 설명으로 나옴('페이지'→'래리 페이지', '임상 실습', '생물 분류').
  4. HTML entity 가 그대로 노출됨(&quot;쭉&quot;).

원칙: 보강 term 은 (1) UI/일반 단어 제외, (2) 자료 본문/요약에 실제 등장, (3) 외부 검색 결과가
자료 맥락과 무관하면 버림, (4) html.unescape, (5) 문장 단위 정리, (6) pageNumbers/evidenceText 추적.
"""
from app.api.major_analysis_routes import (
    _build_enrichment,
    _complete_sentences,
    _enrichment_terms,
    _is_enrich_blocked,
)
from app.services.material_summary_builder import sanitize_markdown_text
from app.utils.sanitize import sanitize_markdown_text as util_sanitize

# 안드로이드 Material UI 자료 맥락(보강이 이 맥락과 맞아야 통과).
MATERIAL = (
    "안드로이드 Material UI Scaffold 컴포넌트 상단바 하단바 네비게이션 구조를 설명하는 강의자료. "
    "Scaffold 슬롯에 TopAppBar 와 BottomBar 를 배치한다."
)


# ── 4. HTML entity 디코드 ─────────────────────────────────────────────────────
def test_sanitize_unescapes_html_entities():
    assert sanitize_markdown_text("&quot;쭉&quot;") == '"쭉"'
    assert util_sanitize("&quot;쭉&quot;") == '"쭉"'
    assert sanitize_markdown_text("a &amp; b &#39;c&#39;") == "a & b 'c'"


# ── 3a. UI/일반 단어는 보강 후보에서 제외 ─────────────────────────────────────
def test_ui_words_blocked():
    for w in ("페이지", "연습", "내용", "자료", "그림", "표", "page", "pdf", "이미지"):
        assert _is_enrich_blocked(w) is True
    assert _is_enrich_blocked("Scaffold") is False


def test_ui_words_excluded_from_enrichment_terms():
    ctx = MATERIAL + " 페이지 페이지 연습 내용 자료"
    terms = _enrichment_terms(
        ctx,
        candidates=["페이지", "Scaffold", "연습"],
        page_summaries=[],
        keywords=["Material", "페이지", "내용"],
    )
    low = [t.lower() for t in terms]
    assert "페이지" not in low and "연습" not in low and "내용" not in low
    assert "scaffold" in low  # 자료에 실제 등장한 진짜 개념은 남는다


def test_term_must_appear_in_material():
    # 자료에 없는 단어는 grounding 실패로 제외(근거 없는 보강 금지)
    terms = _enrichment_terms(MATERIAL, candidates=["대장균", "Scaffold"], page_summaries=[], keywords=[])
    assert "대장균" not in terms
    assert "Scaffold" in terms


# ── 3b. '페이지' → '래리 페이지' 오확장 금지 ──────────────────────────────────
def test_page_term_never_expands_to_larry_page():
    def fake_fetch(term, ctx):
        return {"title": "래리 페이지", "summary": "구글 공동 창업자이자 컴퓨터 과학자"}

    # term 자체가 차단되어 fetch 까지 가지 않는다(설령 호출돼도 결과 0).
    enr = _build_enrichment(["페이지"], MATERIAL, [], fetch_fn=fake_fetch)
    assert enr == []


# ── 3c. 자료와 무관한 외부 결과는 버림('임상 실습', '생물 분류') ──────────────
def test_unrelated_wiki_result_filtered_out():
    def fake_fetch(term, ctx):
        return {"title": "임상 실습", "summary": "간호학과 학생이 병원에서 수행하는 임상 실습 교육 과정"}

    enr = _build_enrichment(["Scaffold"], MATERIAL, [], fetch_fn=fake_fetch)
    assert enr == []  # 안드로이드/Material 맥락과 토큰 겹침 없음 → 탈락


def test_biology_classification_not_attached_to_ui_material():
    def fake_fetch(term, ctx):
        return {"title": "생물 분류", "summary": "생물을 계 문 강 목 과 속 종으로 나누는 분류 체계"}

    enr = _build_enrichment(["Scaffold"], MATERIAL, [], fetch_fn=fake_fetch)
    assert enr == []


# ── 3d. 자료 맥락과 맞는 보강은 유지 + html 해제 + 근거(pageNumbers/evidence) ──
def test_relevant_enrichment_kept_with_evidence_and_unescaped_html():
    def fake_fetch(term, ctx):
        return {
            "title": "Scaffold",
            "summary": ("Material UI 의 Scaffold 는 상단바 하단바 &quot;구조&quot; 를 제공하는 "
                        "안드로이드 컴포넌트다. 화면 레이아웃의 뼈대 역할을 한다."),
        }

    page_summaries = [
        {"page": 1, "pageOverview": "Scaffold 구조 설명", "keyConcepts": ["Scaffold"],
         "extractedText": "Scaffold 상단바 하단바 컴포넌트"},
        {"page": 2, "pageOverview": "다른 주제", "keyConcepts": [], "extractedText": "무관"},
    ]
    enr = _build_enrichment(["Scaffold"], MATERIAL + " Scaffold 상단바 하단바", page_summaries,
                            fetch_fn=fake_fetch)
    assert len(enr) == 1
    e = enr[0]
    assert e["term"] == "Scaffold"
    assert "&quot;" not in e["explanation"]  # html entity 해제됨
    assert '"구조"' in e["explanation"]
    assert e["sourceType"] == "wikipedia"
    assert 1 in e["pageNumbers"] and 2 not in e["pageNumbers"]  # 근거 페이지만
    assert e["evidenceText"] and isinstance(e["evidenceText"], list)


# ── 3e. 설명이 문장 중간에서 잘리지 않음 ──────────────────────────────────────
def test_complete_sentences_no_midcut():
    s = _complete_sentences("첫 문장이다. 두 번째 문장이 길게 이어지다가 중간에서 끊긴다.", max_chars=10)
    assert s.endswith("다.")
    assert "중간에서" not in s  # 두 번째 문장은 잘려 들어가지 않음
