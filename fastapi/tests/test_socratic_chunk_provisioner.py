"""소크라테스 복습 on-demand 청크 준비(provisioner) 단위 테스트.

핵심 버그: 자료가 분석 완료(extracted_text 보유)되어도 RAG ingest가 자동 실행되지 않아
rag.document_chunk 가 0행이면 소크라테스 복습이 막힌다. provisioner 는 청크가 없을 때
원문을 우선순위(extracted_text → summary/analysis → S3 PDF)대로 확보해 1회 ingest 한다.

DB/S3/LLM 의존성은 모두 주입 fake 로 대체하므로 Ollama/네트워크/DB 없이 통과한다.
"""
from __future__ import annotations

import pytest

from app.services import socratic_chunk_provisioner as prov
from app.services import socratic_review_service as svc


# ── ensure_material_chunks: source-kind 우선순위 ────────────────────────────────
def test_extracted_text_only_ingests_and_succeeds(monkeypatch):
    """extracted_text 만 있어도 청크를 생성하고 canStart 가능 상태로 반환한다."""
    monkeypatch.setattr(prov, "_get_material_source", lambda mid: {
        "exists": True, "material_type": "PDF",
        "extracted_text": "광합성은 빛 에너지를 화학 에너지로 바꾼다. " * 30,
        "summary_text": "", "s3_key": None, "title": "생물", "file_name": "bio.pdf",
    })
    ingested = {}
    def fake_ingest(mid, title, text):
        ingested["text_len"] = len(text)
        return 5
    monkeypatch.setattr(prov, "_run_ingest", fake_ingest)

    out = prov.ensure_material_chunks(240, "생물")

    assert out["ok"] is True
    assert out["source_kind"] == "extracted_text"
    assert out["chunk_count"] == 5
    assert out["text_length"] > 0
    assert out["reason"] is None


def test_summary_fallback_when_no_extracted_text(monkeypatch):
    """extracted_text 가 없으면 분석/요약 조합으로 fallback context 를 만든다."""
    monkeypatch.setattr(prov, "_get_material_source", lambda mid: {
        "exists": True, "material_type": "PDF",
        "extracted_text": "",
        "summary_text": "핵심 개념: 세포 호흡과 ATP 생성. " * 20,
        "s3_key": "materials/u/x.pdf", "title": "세포", "file_name": "cell.pdf",
    })
    monkeypatch.setattr(prov, "_run_ingest", lambda mid, title, text: 3)
    # S3 로 내려가면 안 된다(요약이 먼저 잡혀야 함)
    monkeypatch.setattr(prov, "_extract_text_from_s3", lambda *a, **k: pytest.fail("S3 호출 금지"))

    out = prov.ensure_material_chunks(241, "세포")

    assert out["ok"] is True
    assert out["source_kind"] == "summary_fallback"
    assert out["chunk_count"] == 3


def test_s3_pdf_extract_when_no_text_or_summary(monkeypatch):
    """텍스트/요약이 전부 없으면 S3 PDF 원본에서 추출한다(pdf_extract)."""
    monkeypatch.setattr(prov, "_get_material_source", lambda mid: {
        "exists": True, "material_type": "PDF",
        "extracted_text": "", "summary_text": "",
        "s3_key": "materials/u/x.pdf", "title": "문서", "file_name": "x.pdf",
    })
    monkeypatch.setattr(prov, "_extract_text_from_s3",
                        lambda key, fname: "S3 에서 추출한 본문 텍스트입니다. " * 20)
    monkeypatch.setattr(prov, "_run_ingest", lambda mid, title, text: 4)

    out = prov.ensure_material_chunks(242, "문서")

    assert out["ok"] is True
    assert out["source_kind"] == "pdf_extract"
    assert out["chunk_count"] == 4


def test_empty_everything_returns_pdf_text_empty(monkeypatch):
    """원문/요약/S3 키 전부 없으면 명확히 PDF_TEXT_EMPTY 로 실패한다."""
    monkeypatch.setattr(prov, "_get_material_source", lambda mid: {
        "exists": True, "material_type": "PDF",
        "extracted_text": "", "summary_text": "", "s3_key": None,
        "title": "빈자료", "file_name": "",
    })
    out = prov.ensure_material_chunks(243, "빈자료")

    assert out["ok"] is False
    assert out["reason"] == "PDF_TEXT_EMPTY"
    assert out["chunk_count"] == 0


def test_image_pdf_returns_ocr_required(monkeypatch):
    """S3 키는 있으나 추출 결과가 비면(이미지 PDF) OCR_REQUIRED 로 반환한다."""
    monkeypatch.setattr(prov, "_get_material_source", lambda mid: {
        "exists": True, "material_type": "PDF",
        "extracted_text": "", "summary_text": "",
        "s3_key": "materials/u/scan.pdf", "title": "스캔본", "file_name": "scan.pdf",
    })
    monkeypatch.setattr(prov, "_extract_text_from_s3", lambda key, fname: "")

    out = prov.ensure_material_chunks(244, "스캔본")

    assert out["ok"] is False
    assert out["reason"] == "OCR_REQUIRED"


def test_s3_download_failure_returns_s3_not_found(monkeypatch):
    """S3 다운로드 자체가 실패하면 S3_NOT_FOUND 로 구분 반환한다."""
    monkeypatch.setattr(prov, "_get_material_source", lambda mid: {
        "exists": True, "material_type": "PDF",
        "extracted_text": "", "summary_text": "",
        "s3_key": "materials/u/missing.pdf", "title": "없음", "file_name": "missing.pdf",
    })
    def boom(key, fname):
        raise RuntimeError("S3에서 PDF를 로드할 수 없습니다: NoSuchKey")
    monkeypatch.setattr(prov, "_extract_text_from_s3", boom)

    out = prov.ensure_material_chunks(245, "없음")

    assert out["ok"] is False
    assert out["reason"] == "S3_NOT_FOUND"


def test_material_not_found(monkeypatch):
    monkeypatch.setattr(prov, "_get_material_source", lambda mid: None)
    out = prov.ensure_material_chunks(999999, None)
    assert out["ok"] is False
    assert out["reason"] == "MATERIAL_NOT_FOUND"


def test_ingest_returns_zero_is_not_success(monkeypatch):
    """ingest 결과 chunk_count 0 이면 success 로 새지 않는다(버그 방지)."""
    monkeypatch.setattr(prov, "_get_material_source", lambda mid: {
        "exists": True, "material_type": "PDF",
        "extracted_text": "본문 " * 30, "summary_text": "",
        "s3_key": None, "title": "t", "file_name": "",
    })
    monkeypatch.setattr(prov, "_run_ingest", lambda mid, title, text: 0)

    out = prov.ensure_material_chunks(246, "t")

    assert out["ok"] is False
    assert out["reason"] == "PDF_TEXT_EMPTY"
    assert out["chunk_count"] == 0


# ── start_session 통합: 기존 청크 / on-demand provision / 실패 사유 전파 ──────────
def _stub_llm(monkeypatch):
    # 질문/annotation 생성의 LLM 호출을 무력화 → 결정적 fallback 사용
    monkeypatch.setattr(svc, "_call_ollama", lambda *a, **k: None)


def test_start_session_uses_existing_chunks(monkeypatch):
    """이미 청크가 있으면 provision 없이 바로 세션을 시작한다(sourceKind=rag_chunks)."""
    _stub_llm(monkeypatch)
    chunks = [{"id": 1, "chunk_index": 0, "page_start": 1, "page_end": 1,
               "content": "광합성 명반응과 암반응의 차이를 설명한다. " * 5,
               "content_hash": "h1", "metadata": {}}]
    monkeypatch.setattr(svc, "load_document_chunks", lambda mid: chunks)
    monkeypatch.setattr(svc, "ensure_material_chunks",
                        lambda *a, **k: pytest.fail("기존 청크가 있으면 provision 금지"))

    out = svc.start_session(material_id=109, document_id=None, title="t",
                            max_turns_per_chunk=2, max_chunks=12, difficulty="auto")

    assert out["sessionId"].startswith("sr_")
    assert out["canStart"] is True
    assert out["sourceKind"] == "rag_chunks"
    assert out["chunkCount"] == 1


def test_start_session_provisions_when_no_chunks(monkeypatch):
    """청크가 없으면 ensure_material_chunks 로 생성 후 세션을 시작한다."""
    _stub_llm(monkeypatch)
    state = {"calls": 0}
    provisioned = [{"id": 10, "chunk_index": 0, "page_start": 1, "page_end": 1,
                    "content": "세포 호흡 단계: 해당과정·시트르산 회로·전자전달계. " * 4,
                    "content_hash": "h10", "metadata": {}}]
    def fake_load(mid):
        # 1차: 비어있음(아직 ingest 전), 2차: provision 후 채워짐
        state["calls"] += 1
        return [] if state["calls"] == 1 else provisioned
    monkeypatch.setattr(svc, "load_document_chunks", fake_load)
    monkeypatch.setattr(svc, "ensure_material_chunks", lambda mid, title=None: {
        "ok": True, "source_kind": "extracted_text", "chunk_count": 1,
        "text_length": 200, "reason": None, "message": "ok",
    })

    out = svc.start_session(material_id=240, document_id=None, title="t",
                            max_turns_per_chunk=2, max_chunks=12, difficulty="auto")

    assert out["sessionId"].startswith("sr_")
    assert out["canStart"] is True
    assert out["sourceKind"] == "extracted_text"
    assert state["calls"] == 2  # provision 후 재조회


def test_start_session_propagates_failure_reason(monkeypatch):
    """provision 실패 시 SessionError.status 에 구체 reason 이 실린다(FAILED 일반화 금지)."""
    _stub_llm(monkeypatch)
    monkeypatch.setattr(svc, "load_document_chunks", lambda mid: [])
    monkeypatch.setattr(svc, "ensure_material_chunks", lambda mid, title=None: {
        "ok": False, "source_kind": None, "chunk_count": 0, "text_length": 0,
        "reason": "PDF_TEXT_EMPTY", "message": "문서에서 추출 가능한 텍스트가 없습니다.",
    })

    with pytest.raises(svc.SessionError) as ei:
        svc.start_session(material_id=243, document_id=None, title="t",
                          max_turns_per_chunk=2, max_chunks=12, difficulty="auto")
    assert ei.value.status == "PDF_TEXT_EMPTY"


def test_start_session_provision_ok_but_still_no_chunks_is_internal_error(monkeypatch):
    """provision ok 라고 했는데 재조회가 비면 success 로 새지 않고 INTERNAL_ERROR."""
    _stub_llm(monkeypatch)
    monkeypatch.setattr(svc, "load_document_chunks", lambda mid: [])
    monkeypatch.setattr(svc, "ensure_material_chunks", lambda mid, title=None: {
        "ok": True, "source_kind": "extracted_text", "chunk_count": 2,
        "text_length": 100, "reason": None, "message": "ok",
    })
    with pytest.raises(svc.SessionError) as ei:
        svc.start_session(material_id=240, document_id=None, title="t",
                          max_turns_per_chunk=2, max_chunks=12, difficulty="auto")
    assert ei.value.status == "INTERNAL_ERROR"
