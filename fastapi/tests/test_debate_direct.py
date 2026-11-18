"""
직접 질문(DIRECT_QUESTION) 토론 경로 엔진 테스트.

"gRPC가 뭐야"처럼 직접 질문이 들어오면 A~E 논제선택이 아니라 3인 토론
(주장자/반박자/중재자) 페이로드를 만들어야 한다. LLM은 monkeypatch로 격리한다.
"""
from app.services import debate_topic_engine as DTE


def test_fallback_direct_debate_has_three_roles():
    payload = DTE.fallback_direct_debate("gRPC가 뭐야")
    assert payload["phase"] == "DEBATE_DIRECT"
    assert payload["rawQuestion"] == "gRPC가 뭐야"
    # 3인 토론 핵심 파트가 모두 비어있지 않아야 한다.
    for key in ("claim", "rebuttal", "mediation"):
        part = payload[key]
        assert part.get("summary"), f"{key}.summary 비어있음"
    # 논제 후보(A~E)는 절대 만들지 않는다.
    assert not payload.get("debateTopicCandidates")
    # 직접 질문이므로 핵심 개념이 추출돼야 한다.
    assert payload["primaryConcept"]


def test_synthesize_direct_debate_stages_three_cards():
    payload = DTE.fallback_direct_debate("gRPC가 뭐야")
    stages = DTE.synthesize_direct_debate_stages(payload)
    assert len(stages) == 3
    titles = " ".join(s["stageTitle"] + s["role"] for s in stages)
    assert "주장" in titles and "반박" in titles and "중재" in titles
    # 각 stage 본문이 비어있지 않아야 한다(빈 content는 contract에서 drop됨).
    for s in stages:
        assert s["content"].strip()
        assert s["stageType"]  # 렌더러가 인식하는 stageType


def test_build_direct_debate_falls_back_when_llm_empty(monkeypatch):
    monkeypatch.setattr(DTE, "_llm_json", lambda *a, **k: None)

    class _Req:
        message = "gRPC가 뭐야"
        knowledgeLevel = None
        debateState = None

    payload = DTE.build_direct_debate(_Req())
    assert payload["phase"] == "DEBATE_DIRECT"
    assert payload["claim"]["summary"]
    assert payload["rebuttal"]["summary"]
    assert payload["mediation"]["summary"]
    assert not payload.get("debateTopicCandidates")
