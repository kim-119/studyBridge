"""
소크라테스 복습 세션 단위 테스트 (오프라인: DB/LLM 미접속 순수 로직만).

라이브 검증(실제 DB + Ollama)은 TestClient 수동 플로우로 별도 수행한다.
여기서는 라우트 등록, document_id 스코핑 매핑, 출제 plan 순회, 평가 정규화,
qwen3 <think> 제거, mastery→복습일 매핑 등 결정적 로직만 검증한다.
"""
import pytest

from app.services import socratic_review_service as svc


def test_routes_registered():
    from app.api.socratic_review_routes import router
    paths = {getattr(r, "path", None) for r in router.routes}
    assert "/api/ai/socratic-review/sessions" in paths
    assert "/api/ai/socratic-review/sessions/{session_id}/answers" in paths
    assert "/api/ai/socratic-review/sessions/{session_id}/finish" in paths
    assert "/api/ai/socratic-review/sessions/{session_id}" in paths


def test_resolve_material_id_from_material():
    assert svc.resolve_material_id(50, None) == 50


def test_resolve_material_id_from_document_id_variants():
    assert svc.resolve_material_id(None, "doc_50") == 50
    assert svc.resolve_material_id(None, "doc-50") == 50
    assert svc.resolve_material_id(None, "50") == 50


def test_resolve_material_id_material_takes_priority():
    # materialId 우선 — folderId 등 다른 식별자는 라우터 단계에서 무시됨
    assert svc.resolve_material_id(77, "doc_50") == 77


def test_resolve_material_id_missing_raises():
    with pytest.raises(svc.SessionError):
        svc.resolve_material_id(None, None)


def test_resolve_material_id_unmappable_document_raises():
    # 매핑 불가 documentId 는 전체 코퍼스로 넘어가지 않고 명확히 실패해야 한다
    with pytest.raises(svc.SessionError):
        svc.resolve_material_id(None, "folder_abc")


def test_document_id_of():
    assert svc.document_id_of(50) == "doc_50"


def test_build_plan_skips_short_and_duplicate_and_caps():
    chunks = [
        {"id": 1, "content": "x" * 5, "content_hash": "h1"},      # 너무 짧음 → skip
        {"id": 2, "content": "A" * 100, "content_hash": "h2"},
        {"id": 3, "content": "A" * 100, "content_hash": "h2"},    # 중복 hash → skip
        {"id": 4, "content": "B" * 100, "content_hash": "h4"},
        {"id": 5, "content": "C" * 100, "content_hash": "h5"},
    ]
    plan = svc.build_plan(chunks, max_chunks=2)
    assert [c["id"] for c in plan] == [2, 4]  # 짧은1·중복3 제외, cap 2


def test_strip_think_removes_reasoning():
    assert svc._strip_think("<think>secret</think>실제답변") == "실제답변"
    assert svc._strip_think("앞<think>중간</think>뒤") == "앞뒤"
    # 닫는 태그만 있는 경우도 방어
    assert svc._strip_think("reasoning</think>JSON결과").strip() == "JSON결과"


def test_review_days_mapping():
    assert svc._review_days_for(0.9) == 7
    assert svc._review_days_for(0.72) == 4
    assert svc._review_days_for(0.55) == 2
    assert svc._review_days_for(0.2) == 1


def test_normalize_eval_corrects_next_action_from_correctness():
    out = svc._normalize_eval({"correctness": 0.9})
    assert out["next_action"] == "next"
    out = svc._normalize_eval({"correctness": 0.5})
    assert out["next_action"] == "follow_up"
    out = svc._normalize_eval({"correctness": 0.2})
    assert out["next_action"] == "easier"


def test_normalize_eval_clamps_and_defaults():
    out = svc._normalize_eval({"correctness": "bad", "on_topic": False})
    assert out["correctness"] == 0.5
    assert out["on_topic"] is False
    assert isinstance(out["covered"], list)


def test_fallback_eval_shape():
    fb = svc._fallback_eval()
    assert set(fb) == {"on_topic", "correctness", "covered", "missing", "next_action", "direction"}
    assert fb["next_action"] == "follow_up"


def test_chunk_mastery_weights_latest_and_penalizes_off_topic():
    # 최신 답변에 가중: [낮음, 높음] → 0.5보다 큼
    m = svc._chunk_mastery([{"correctness": 0.2}, {"correctness": 0.9}])
    assert m > 0.5
    # off_topic 페널티
    on = svc._chunk_mastery([{"correctness": 0.8, "on_topic": True}])
    off = svc._chunk_mastery([{"correctness": 0.8, "on_topic": False}])
    assert off < on
