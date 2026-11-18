"""
RAG 정확도 개선 단위 테스트 (LLM/DB/reranker 모델 불필요 — 순수 로직).

pytest: cd ~/capstoneLLM/fastapi && .venv/bin/python -m pytest tests/test_rag_pipeline.py -q
plain : cd ~/capstoneLLM/fastapi && .venv/bin/python -m tests.test_rag_pipeline
"""
from app.services.text_chunker import split_text_with_metadata
from app.services.rag_ingest_service import _build_chunk_records, _chunk_id
from app.services import rag_pipeline_service as pipe
from app.services import rag_rerank_service as rr


# ── 청킹: 400자 윈도우 + overlap + metadata ───────────────────────────────────
def test_split_with_metadata_windows():
    text = "가" * 1000
    chunks = split_text_with_metadata(text, 400, 100)
    assert len(chunks) >= 3
    assert chunks[0]["charStart"] == 0 and chunks[0]["charEnd"] == 400
    # step = 400 - 100 = 300
    assert chunks[1]["charStart"] == 300
    assert all(c["text"] for c in chunks)
    assert all(c["chunkIndex"] == i for i, c in enumerate(chunks))


def test_long_document_uses_400_chunking():
    long_text = "문장. " * 700  # 2,000자 이상
    records, policy = _build_chunk_records(10, long_text)
    assert policy["longDocument"] is True
    assert policy["chunkSizeChars"] == 400
    assert policy["chunkOverlapChars"] == 100
    # 문서 전체가 하나의 chunk로만 저장되지 않는다 (시나리오 A 성공 기준)
    assert len(records) > 1
    assert records[0]["metadata"]["chunkId"] == "doc10_chunk_0000"
    assert "charStart" in records[0]["metadata"]


def test_short_document_keeps_legacy_path():
    short_text = "짧은 자료입니다. Activity 설명."
    records, policy = _build_chunk_records(7, short_text)
    assert policy["longDocument"] is False
    assert len(records) >= 1
    assert records[0]["metadata"]["chunkId"] == "doc7_chunk_0000"


def test_chunk_id_format():
    assert _chunk_id(10, 7) == "doc10_chunk_0007"


# ── chunkId 추출 (metadata 우선, 없으면 material_id+index 조합) ─────────────────
def test_chunk_id_of_from_metadata():
    row = {"metadata": {"chunkId": "doc10_chunk_0042"}, "material_id": 10, "chunk_index": 42}
    assert pipe._chunk_id_of(row, 10) == "doc10_chunk_0042"


def test_chunk_id_of_derived():
    row = {"metadata": {}, "material_id": 5, "chunk_index": 3}
    assert pipe._chunk_id_of(row, 5) == "doc5_chunk_0003"


def test_resolve_material_id():
    assert pipe._resolve_material_id(10, None) == 10
    assert pipe._resolve_material_id(None, "doc_7") == 7
    assert pipe._resolve_material_id(None, "12") == 12
    assert pipe._resolve_material_id(None, None) is None


# ── context 구성: top-N 만 들어가고 지시문 포함 ────────────────────────────────
def test_build_context_includes_only_selected():
    selected = [
        {"chunkId": "doc10_chunk_0007", "text": "Retrofit2는 REST API 라이브러리", "pageStart": 3},
        {"chunkId": "doc10_chunk_0012", "text": "Room 은 로컬 DB", "pageStart": 5},
    ]
    ctx = pipe._build_context("Retrofit2가 뭐야?", selected)
    assert "doc10_chunk_0007" in ctx and "doc10_chunk_0012" in ctx
    assert "근거 안에서만" in ctx
    assert "만들지 않는다" in ctx


# ── reranker fallback: 모델 없이 vectorScore 정렬 ─────────────────────────────
def test_rerank_fallback_when_model_unavailable():
    # 모델 로드 상태를 강제로 failed 로 만들어 fallback 경로 검증(다운로드/네트워크 미발생)
    rr._STATE = "failed"
    candidates = [
        {"chunkId": "a", "text": "x", "vectorScore": 0.2},
        {"chunkId": "b", "text": "y", "vectorScore": 0.9},
        {"chunkId": "c", "text": "z", "vectorScore": 0.5},
    ]
    selected, info = rr.rerank("q", candidates, top_n=2)
    assert info["rerankerUsed"] is False
    assert info["fallbackUsed"] is True
    assert info["reason"] is not None
    assert [c["chunkId"] for c in selected] == ["b", "c"]  # vectorScore 내림차순


def test_clamp_top_n():
    assert rr.clamp_top_n(None) == rr.RAG_RERANK_TOP_N
    assert rr.clamp_top_n(999) == rr.RAG_RERANK_TOP_N_MAX
    assert rr.clamp_top_n(0) == 1
    assert rr.clamp_top_n(2) == 2


def test_rerank_empty_candidates():
    selected, info = rr.rerank("q", [], top_n=3)
    assert selected == []
    assert info["fallbackUsed"] is False


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
