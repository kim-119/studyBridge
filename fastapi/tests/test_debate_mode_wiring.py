"""
토론 모드 배선(schema + stream gate) 통합 테스트.
LLM 호출은 monkeypatch로 격리하고, 배선(필드 보존/이벤트/응답 구조)만 검증한다.
"""
import pytest

from app.schemas.multi_chat_schema import MultiChatRequest, MultiChatResponse
from app.services import debate_topic_engine as DTE
from app.services import multi_agent_service as M


# ── schema: 신규 필드가 extra="ignore"에 의해 유실되지 않아야 한다 ─────────────────
def test_request_preserves_selected_topic_fields():
    req = MultiChatRequest(
        message="A 선택", mode="debate", learningMode="debate",
        selectedTopic={"topicId": "A", "title": "SSH는 먼저 배워야 하는가?"},
        topicSelected=True,
        debateState={"debateSessionId": "debate-x", "turnIndex": 1, "rawQuestion": "ssh가 뭐야?"},
    )
    assert req.selectedTopic["title"] == "SSH는 먼저 배워야 하는가?"
    assert req.topicSelected is True
    assert req.debateState["rawQuestion"] == "ssh가 뭐야?"


def test_response_serializes_new_debate_fields():
    resp = MultiChatResponse(
        mode="debate", answers=[], phase="TOPIC_SELECTION",
        primaryConcept="SSH", conceptChunks=["원격 접속"], debateAxes=["보안성"],
        debateTopicCandidates=[{"topicId": "A", "title": "T", "axis": "x",
                                "proPosition": "p", "conPosition": "c"}],
        topicSelected=False, content="토론할 논제를 선택해 주세요.",
    )
    d = resp.model_dump()
    assert d["phase"] == "TOPIC_SELECTION"
    assert d["debateTopicCandidates"][0]["topicId"] == "A"
    assert d["content"]


# ── stream gate: 첫 턴은 논제 후보 이벤트, 본 토론 없음 ──────────────────────────
def test_stream_first_turn_emits_topic_candidates(monkeypatch):
    monkeypatch.setattr(DTE, "build_topic_selection",
                        lambda req: DTE.fallback_topic_selection("ssh가 뭐야?"))
    req = MultiChatRequest(message="ssh가 뭐야?", mode="debate", learningMode="debate")
    events = list(M.run_debate_mode_stream(req, [], ""))
    names = [e["event"] for e in events]
    assert "debate_topic_candidates" in names
    assert names[-1] == "all_complete"

    cand_ev = next(e for e in events if e["event"] == "debate_topic_candidates")
    assert cand_ev["data"]["phase"] == "TOPIC_SELECTION"
    assert len(cand_ev["data"]["debateTopicCandidates"]) == 5

    final = next(e for e in events if e["event"] == "all_complete")["data"]
    assert final["phase"] == "TOPIC_SELECTION"
    assert final["topicSelected"] is False
    assert len(final["debateTopicCandidates"]) == 5
    # 첫 턴엔 본 토론(찬반)이 없어야 한다
    assert not final.get("pro")
    assert not final.get("con")
    # 하위호환: answers/content 비어있지 않음
    assert final["answers"]
    assert final.get("content")


# ── stream gate: 논제 선택 후엔 찬반 토론 이벤트 ────────────────────────────────
def test_stream_second_turn_emits_debate_round(monkeypatch):
    topic = {"topicId": "A", "title": "SSH는 원격 접속의 표준 도구로 반드시 먼저 배워야 하는가?"}
    monkeypatch.setattr(DTE, "build_debate_round",
                        lambda req: DTE.fallback_debate_round("ssh가 뭐야?", topic))
    req = MultiChatRequest(
        message="A 선택", mode="debate", learningMode="debate",
        selectedTopic=topic,
        debateState={"topicSelected": True, "rawQuestion": "ssh가 뭐야?", "debateSessionId": "debate-1"},
    )
    events = list(M.run_debate_mode_stream(req, [], ""))
    names = [e["event"] for e in events]
    assert "debate_round" in names
    assert names[-1] == "all_complete"

    final = next(e for e in events if e["event"] == "all_complete")["data"]
    assert final["phase"] == "DEBATE_ROUND"
    assert final["selectedTopic"]["title"] == topic["title"]
    assert final["pro"]["claim"]
    assert final["con"]["claim"]
    assert final["rebuttal"]["proRebuttal"]
    assert len(final["keyIssues"]) == 3
    assert final["learningTakeaway"]
    # 마인드맵 하위호환: debateStages 보존
    assert final["debateStages"]
    stage_types = {s["stageType"] for s in final["debateStages"]}
    assert "OPENING_STATEMENT" in stage_types and "JUDGEMENT" in stage_types


# ── phase 판별이 MultiChatRequest로도 동작 ────────────────────────────────────
def test_resolve_phase_with_pydantic_request():
    first = MultiChatRequest(message="ssh가 뭐야?", mode="debate", learningMode="debate")
    assert DTE.resolve_debate_phase(first) == "TOPIC_SELECTION"
    second = MultiChatRequest(message="A", mode="debate",
                              selectedTopic={"topicId": "A", "title": "T"})
    assert DTE.resolve_debate_phase(second) == "DEBATE_ROUND"
