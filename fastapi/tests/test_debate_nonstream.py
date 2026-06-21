"""
비스트림 /api/ai/multi-chat 토론 게이트 헬퍼(main.build_debate_mode_payload) 계약 테스트.
LLM은 monkeypatch로 격리한다.
"""
import main
from app.services import debate_topic_engine as DTE


def test_nonstream_request_preserves_selected_topic():
    req = main.MultiChatRequest(
        message="A 선택", mode="debate", learningMode="debate",
        selectedTopic={"topicId": "A", "title": "T"}, topicSelected=True,
        debateState={"rawQuestion": "ssh가 뭐야?"},
    )
    assert req.selectedTopic["title"] == "T"
    assert req.topicSelected is True
    assert req.debateState["rawQuestion"] == "ssh가 뭐야?"


def test_nonstream_topic_selection(monkeypatch):
    monkeypatch.setattr(DTE, "build_topic_selection",
                        lambda req: DTE.fallback_topic_selection("ssh가 뭐야?"))
    req = main.MultiChatRequest(message="ssh가 뭐야?", mode="debate", learningMode="debate")
    out = main.build_debate_mode_payload(req, [])
    assert out["mode"] == "debate"
    assert out["phase"] == "TOPIC_SELECTION"
    assert out["success"] is True
    assert out["topicSelected"] is False
    assert len(out["debateTopicCandidates"]) == 5
    assert out["answers"]
    assert out.get("content")
    # 첫 턴엔 본 토론 없음
    assert not out.get("pro")


def test_nonstream_debate_round(monkeypatch):
    topic = {"topicId": "A", "title": "SSH는 먼저 배워야 하는가?"}
    monkeypatch.setattr(DTE, "build_debate_round",
                        lambda req: DTE.fallback_debate_round("ssh가 뭐야?", topic))
    req = main.MultiChatRequest(
        message="A 선택", mode="debate", learningMode="debate",
        selectedTopic=topic, topicSelected=True,
        debateState={"rawQuestion": "ssh가 뭐야?", "debateSessionId": "debate-z"},
    )
    out = main.build_debate_mode_payload(req, [])
    assert out["phase"] == "DEBATE_ROUND"
    assert out["selectedTopic"]["title"] == topic["title"]
    assert out["pro"]["claim"]
    assert out["con"]["claim"]
    assert len(out["keyIssues"]) == 3
    assert out["debateStages"]
    assert out["debateSessionId"] == "debate-z"
