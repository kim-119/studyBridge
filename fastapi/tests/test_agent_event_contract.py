"""에이전트 SSE 이벤트 envelope/fingerprint 계약 테스트.

대상: app/services/agent_event_contract.py (신규)
- 모든 이벤트에 eventId/turnId/fingerprint/stage 부착(additive, 기존 키 보존)
- fingerprint = turnId + stage + agentId + canonicalize(content)
- canonicalize는 대소문자/공백 차이를 무시(중복 판정 일관성)
"""
import re

from app.services import agent_event_contract as C


def test_new_ids_are_unique_and_stringy():
    assert C.new_turn_id() != C.new_turn_id()
    assert C.new_event_id() != C.new_event_id()
    assert isinstance(C.new_turn_id(), str) and len(C.new_turn_id()) >= 8


def test_canonicalize_collapses_whitespace_and_case():
    a = C.canonicalize_content("  Hello   WORLD\n\n 입니다 ")
    b = C.canonicalize_content("hello world 입니다")
    assert a == b


def test_canonicalize_handles_none():
    assert C.canonicalize_content(None) == ""


def test_fingerprint_is_deterministic_and_whitespace_insensitive():
    f1 = C.compute_fingerprint("turn1", "FIRST_ANSWER", "a1", "Hello World")
    f2 = C.compute_fingerprint("turn1", "FIRST_ANSWER", "a1", "hello   world")
    assert f1 == f2
    assert re.fullmatch(r"[0-9a-f]{8,}", f1)


def test_fingerprint_differs_by_stage_agent_turn():
    base = ("turn1", "FIRST_ANSWER", "a1", "same content")
    assert C.compute_fingerprint(*base) != C.compute_fingerprint("turn2", "FIRST_ANSWER", "a1", "same content")
    assert C.compute_fingerprint(*base) != C.compute_fingerprint("turn1", "VALIDATION", "a1", "same content")
    assert C.compute_fingerprint(*base) != C.compute_fingerprint("turn1", "FIRST_ANSWER", "a2", "same content")


def test_resolve_stage_from_event_and_stagetype():
    assert C.resolve_stage("agent_answer", {"stageType": "FIRST_ANSWER"}) == "FIRST_ANSWER"
    assert C.resolve_stage("all_complete", {}) == "ALL_COMPLETE"
    assert C.resolve_stage("error", {}) == "ERROR"
    # socratic 단계는 stageType를 그대로 보존(중복 판정 세분화)
    assert C.resolve_stage("socratic_step", {"stageType": "DIAGNOSIS"}) == "DIAGNOSIS"


def test_enrich_event_is_additive_and_nonmutating():
    data = {"agentId": "a1", "agentName": "튜터", "content": "answer", "stageType": "FIRST_ANSWER"}
    out = C.enrich_event("agent_answer", data, turn_id="turnX", mode="default")
    # 기존 키 보존
    assert out["agentId"] == "a1"
    assert out["agentName"] == "튜터"
    assert out["content"] == "answer"
    # envelope 키 부착
    for k in ("eventId", "turnId", "mode", "stage", "fingerprint", "createdAt", "isFinal"):
        assert k in out, f"missing {k}"
    assert out["turnId"] == "turnX"
    assert out["mode"] == "default"
    assert out["stage"] == "FIRST_ANSWER"
    # 원본 dict는 변형하지 않는다
    assert "eventId" not in data


def test_enrich_event_same_content_same_fingerprint_diff_eventid():
    d1 = {"agentId": "a1", "content": "동일 내용"}
    d2 = {"agentId": "a1", "content": "동일   내용"}
    o1 = C.enrich_event("agent_answer", d1, turn_id="t", mode="default")
    o2 = C.enrich_event("agent_answer", d2, turn_id="t", mode="default")
    assert o1["fingerprint"] == o2["fingerprint"]
    assert o1["eventId"] != o2["eventId"]


def test_enrich_event_all_complete_is_final():
    out = C.enrich_event("all_complete", {}, turn_id="t", mode="default")
    assert out["isFinal"] is True
    assert out["stage"] == "ALL_COMPLETE"


def test_enrich_event_reads_answer_or_feedback_as_content():
    # content가 없으면 answer/feedback/question/hint에서 추출(fingerprint 안정화)
    out = C.enrich_event("agent_answer", {"agentId": "a1", "answer": "본문"}, turn_id="t", mode="default")
    f = C.compute_fingerprint("t", out["stage"], "a1", "본문")
    assert out["fingerprint"] == f
