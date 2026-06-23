"""
StudyMate 기본개념모드 — 확률적 다중답변 플래너의 라이브 스트림 배선 통합 테스트.

라이브 default/basic 경로는 build_stream_generator → _build_stream_generator_impl →
orchestrator_service.build_orchestrator_stream 이다. 플래너가 켜지면(default on)
이 경로가 N개 고정 답변 대신 [3,7]개의 답변(DIRECT_ANSWER+REACTION) + WRAP 1개 +
follow_up_suggestions 를 내보내야 한다. 네트워크(LLM)는 스텁한다.

계약(설계 doc 2026-06-23 섹션 B 5.3):
  - agent_answer 이벤트에 actType ∈ {DIRECT_ANSWER, REACTION, WRAP}
  - 답변(DIRECT_ANSWER+REACTION) 개수 ∈ [3,7]
  - WRAP 정확히 1개(마지막 답변류 이벤트), all_complete 정확히 1회
  - REACTION은 replyTo(대상 agentId) 보유, self 금지 / DIRECT·WRAP은 replyTo 없음
  - 첫 agent_answer는 DIRECT_ANSWER
  - 끝에 follow_up_suggestions 이벤트
  - PLANNER=off면 기존(1인1답) 동작, WRAP/follow_up 없음
"""
import pytest

from app.schemas.multi_chat_schema import AgentProfile, MultiChatRequest
from app.services import orchestrator_service as orch


@pytest.fixture(autouse=True)
def _stub_network(monkeypatch):
    import itertools
    monkeypatch.setattr(orch, "_fetch_wikipedia_context", lambda q: "")
    monkeypatch.setattr(orch, "_min_gap_seconds", lambda: 0.0)
    # 호출마다 '서로 다른' 본문을 반환한다. 상수 본문을 쓰면 WRAP/REACTION 이 DIRECT 와
    # 글자까지 동일해져 의미중복 억제(turn_semantic_dedup)에 걸리므로, 실제 LLM 처럼
    # 매 발화가 고유 내용이 되도록 한다(플래너 구조 계약 검증이 목적).
    _counter = itertools.count(1)

    def _fake_ask(**k):
        n = next(_counter)
        # 카운터를 모든 토큰 안에 박아 호출마다 문자 n-gram 이 거의 겹치지 않게 한다.
        return " ".join(f"{w}{n}" for w in ("항목", "핵심", "근거", "예시", "세부", "결론", "관점", "논점"))

    monkeypatch.setattr("app.services.ollama_client.ask_ollama", _fake_ask)


def _agents():
    return [
        AgentProfile(id=1, agentId="a1", name="전문봇", personality="전문적", knowledgeLevel="학사"),
        AgentProfile(id=2, agentId="a2", name="냉소봇", personality="냉소적", knowledgeLevel="학사"),
        AgentProfile(id=3, agentId="a3", name="친근봇", personality="친근함", knowledgeLevel="학사"),
    ]


def _run(monkeypatch, *, seed="7"):
    monkeypatch.setenv("STUDYMATE_DISCUSSION_PLANNER", "on")
    monkeypatch.setenv("STUDYMATE_DISCUSSION_SEED", seed)
    req = MultiChatRequest(message="SQL JOIN이 뭐야?", agents=_agents())
    return list(orch.build_orchestrator_stream(req, _agents()))


def _answers(events):
    return [e["data"] for e in events
            if e["event"] == "agent_answer"
            and e["data"].get("actType") in ("DIRECT_ANSWER", "REACTION")]


def test_answer_count_within_bounds(monkeypatch):
    events = _run(monkeypatch)
    assert 3 <= len(_answers(events)) <= 7


def test_every_agent_answer_has_act_type(monkeypatch):
    events = _run(monkeypatch)
    aa = [e["data"] for e in events if e["event"] == "agent_answer"]
    assert aa, "agent_answer 이벤트가 없음"
    for d in aa:
        assert d.get("actType") in ("DIRECT_ANSWER", "REACTION", "WRAP"), d


def test_first_answer_is_direct(monkeypatch):
    events = _run(monkeypatch)
    first = next(e["data"] for e in events if e["event"] == "agent_answer")
    assert first["actType"] == "DIRECT_ANSWER"


def test_no_auto_wrap_on_default_turn(monkeypatch):
    # WRAP 온디맨드: 기본 토론 턴에는 자동 WRAP가 붙지 않는다(정리는 사용자 요청 시에만).
    events = _run(monkeypatch)
    wraps = [e["data"] for e in events
             if e["event"] == "agent_answer" and e["data"].get("actType") == "WRAP"]
    assert len(wraps) == 0


def test_reactions_have_valid_reply_to(monkeypatch):
    events = _run(monkeypatch)
    for e in events:
        if e["event"] != "agent_answer":
            continue
        d = e["data"]
        if d.get("actType") == "REACTION":
            assert d.get("replyTo"), f"REACTION에 replyTo 없음: {d}"
            assert d["replyTo"] != d.get("agentId"), "self-reaction 금지"
        elif d.get("actType") in ("DIRECT_ANSWER", "WRAP"):
            assert not d.get("replyTo")


def test_display_delay_is_sequential(monkeypatch):
    # 순차 강제: displayOrder/displayDelayMs가 발화 순번대로 단조 증가해야 한다(도착순 뒤섞임 방지).
    events = _run(monkeypatch)
    aa = [e["data"] for e in events if e["event"] == "agent_answer"]
    orders = [d.get("displayOrder") for d in aa]
    delays = [d.get("displayDelayMs") for d in aa]
    assert orders == sorted(orders) and orders == list(range(1, len(orders) + 1))
    assert all(isinstance(x, int) for x in delays)
    assert delays == sorted(delays)              # 단조 증가
    assert delays[0] == 0                          # 첫 발화 0ms


def test_all_complete_exactly_once(monkeypatch):
    events = _run(monkeypatch)
    kinds = [e["event"] for e in events]
    assert kinds[0] == "turn_start"
    assert kinds.count("all_complete") == 1
    assert kinds[-1] == "all_complete"


def test_follow_up_suggestions_emitted(monkeypatch):
    events = _run(monkeypatch)
    fu = [e for e in events if e["event"] == "follow_up_suggestions"]
    assert len(fu) == 1
    assert fu[0]["data"].get("suggestions")


def test_planner_off_is_legacy(monkeypatch):
    monkeypatch.setenv("STUDYMATE_DISCUSSION_PLANNER", "off")
    monkeypatch.setenv("STUDYMATE_FEEDBACK_ROUND", "off")
    req = MultiChatRequest(message="SQL JOIN이 뭐야?", agents=_agents())
    events = list(orch.build_orchestrator_stream(req, _agents()))
    # 레거시: 에이전트 수만큼 답변, WRAP/follow_up 없음
    aa = [e for e in events if e["event"] == "agent_answer"]
    assert len(aa) == 3
    assert all(e["data"].get("actType") != "WRAP" for e in aa)
    assert not any(e["event"] == "follow_up_suggestions" for e in events)
