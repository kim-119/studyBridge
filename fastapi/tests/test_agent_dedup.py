"""turn 단위 중복 이벤트 방어 + all_complete 게이트 테스트.

대상: app/services/agent_dedup.py (신규)
규칙:
  - 같은 fingerprint가 같은 turn에서 재발행되면 drop.
  - all_complete(또는 done) 이후 같은 turn의 answer류 이벤트는 drop.
  - 제어/하트비트/에러 이벤트는 항상 통과(게이트/중복판정 제외).
"""
from app.services import agent_event_contract as C
from app.services.agent_dedup import TurnDeduper


def _ev(event_name, **data):
    return event_name, C.enrich_event(event_name, data, turn_id="t1", mode="default")


def test_control_events_always_emit():
    d = TurnDeduper("t1")
    for _ in range(3):
        name, data = _ev("heartbeat")
        assert d.should_emit(name, data) is True
    name, data = _ev("turn_start", message="시작")
    assert d.should_emit(name, data) is True


def test_duplicate_fingerprint_dropped():
    d = TurnDeduper("t1")
    n1, d1 = _ev("agent_answer", agentId="a1", content="중복 내용", stageType="FIRST_ANSWER")
    n2, d2 = _ev("agent_answer", agentId="a1", content="중복   내용", stageType="FIRST_ANSWER")
    assert d.should_emit(n1, d1) is True
    assert d.should_emit(n2, d2) is False  # 공백만 다른 동일 내용 → drop


def test_distinct_content_not_dropped():
    d = TurnDeduper("t1")
    n1, d1 = _ev("agent_answer", agentId="a1", content="첫 답변", stageType="FIRST_ANSWER")
    n2, d2 = _ev("agent_answer", agentId="a1", content="다른 답변", stageType="FIRST_ANSWER")
    assert d.should_emit(n1, d1) is True
    assert d.should_emit(n2, d2) is True


def test_same_content_different_agent_not_dropped():
    d = TurnDeduper("t1")
    n1, d1 = _ev("agent_answer", agentId="a1", content="같은 본문", stageType="FIRST_ANSWER")
    n2, d2 = _ev("agent_answer", agentId="a2", content="같은 본문", stageType="FIRST_ANSWER")
    assert d.should_emit(n1, d1) is True
    assert d.should_emit(n2, d2) is True


def test_answer_after_all_complete_dropped():
    d = TurnDeduper("t1")
    n0, d0 = _ev("agent_answer", agentId="a1", content="정상 답변", stageType="FIRST_ANSWER")
    assert d.should_emit(n0, d0) is True
    nc, dc = _ev("all_complete")
    assert d.should_emit(nc, dc) is True  # 종료 이벤트는 통과
    n1, d1 = _ev("agent_answer", agentId="a2", content="늦게 온 답변", stageType="FIRST_ANSWER")
    assert d.should_emit(n1, d1) is False  # all_complete 이후 answer는 drop


def test_done_after_all_complete_emits_but_late_answer_dropped():
    d = TurnDeduper("t1")
    nc, dc = _ev("all_complete")
    assert d.should_emit(nc, dc) is True
    nd, dd = _ev("done")
    assert d.should_emit(nd, dd) is True  # 레거시 done은 통과
    nlate, dlate = _ev("socratic_step", agentId="a1", content="늦은 단계", stageType="HINT")
    assert d.should_emit(nlate, dlate) is False


def test_error_always_emits():
    d = TurnDeduper("t1")
    nc, dc = _ev("all_complete")
    d.should_emit(nc, dc)
    ne, de = _ev("error", code="X", reason="y")
    assert d.should_emit(ne, de) is True
