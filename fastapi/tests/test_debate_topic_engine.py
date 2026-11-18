"""
토론 모드 논제선택 엔진 계약 테스트.

토론 모드는 개념 질문을 바로 설명/찬반하지 않고,
1) 첫 턴(selectedTopic 없음) → TOPIC_SELECTION: 개념추출 + 청킹 + 논제 후보 5개
2) 후속 턴(selectedTopic 있음) → DEBATE_ROUND: pro/con/rebuttal/keyIssues/learningTakeaway
구조로 동작해야 한다. 이 테스트는 네트워크(LLM) 비의존 결정론 경로만 검증한다.
"""
from app.services import debate_topic_engine as E


# ── phase 판별 ────────────────────────────────────────────────────────────────
def test_phase_topic_selection_when_no_topic():
    assert E.resolve_debate_phase({"message": "ssh가 뭐야?", "mode": "debate"}) == "TOPIC_SELECTION"


def test_phase_debate_round_with_selected_topic():
    payload = {"message": "A 선택", "mode": "debate",
               "selectedTopic": {"topicId": "A", "title": "SSH는 먼저 배워야 하는가?"}}
    assert E.resolve_debate_phase(payload) == "DEBATE_ROUND"


def test_phase_debate_round_with_debate_state_flag():
    payload = {"message": "A 선택", "mode": "debate",
               "debateState": {"topicSelected": True, "selectedTopic": {"topicId": "A", "title": "T"}}}
    assert E.resolve_debate_phase(payload) == "DEBATE_ROUND"


def test_phase_accepts_object_like_request():
    class Req:
        message = "ssh가 뭐야?"
        mode = "debate"
        selectedTopic = None
        debateState = None
    assert E.resolve_debate_phase(Req()) == "TOPIC_SELECTION"


# ── 개념 추출 ─────────────────────────────────────────────────────────────────
def test_extract_concept_ssh():
    assert "SSH" in E.extract_primary_concept("ssh가 뭐야?").upper()


def test_extract_concept_viewmodel():
    assert E.extract_primary_concept("ViewModel 설명해줘").lower().startswith("viewmodel")


def test_extract_concept_korean():
    assert E.extract_primary_concept("객체지향이 뭐야?") == "객체지향"


# ── TOPIC_SELECTION fallback ──────────────────────────────────────────────────
def test_fallback_topic_selection_shape():
    out = E.fallback_topic_selection("ssh가 뭐야?")
    assert out["phase"] == "TOPIC_SELECTION"
    assert out["mode"] == "debate"
    assert "SSH" in out["primaryConcept"].upper()
    assert out["topicSelected"] is False
    assert out.get("content")
    # 논제 후보는 정확히 5개, topicId A~E
    cands = out["debateTopicCandidates"]
    assert len(cands) == 5
    assert [c["topicId"] for c in cands] == ["A", "B", "C", "D", "E"]
    for c in cands:
        assert c["title"].strip()
        assert c["proPosition"].strip()
        assert c["conPosition"].strip()
        assert c["axis"].strip()
    # 청킹/축 범위
    assert 4 <= len(out["conceptChunks"]) <= 7
    assert 4 <= len(out["debateAxes"]) <= 6
    # 첫 턴엔 본 토론이 없어야 한다
    assert not out.get("pro")
    assert not out.get("con")


def test_fallback_topic_selection_generic_concept():
    out = E.fallback_topic_selection("모노레포가 뭐야?")
    assert len(out["debateTopicCandidates"]) == 5
    assert "모노레포" in out["primaryConcept"]


# ── DEBATE_ROUND fallback ─────────────────────────────────────────────────────
def test_fallback_debate_round_shape():
    topic = {"topicId": "A", "title": "SSH는 원격 접속의 표준 도구로 반드시 먼저 배워야 하는가?"}
    out = E.fallback_debate_round("ssh가 뭐야?", topic)
    assert out["phase"] == "DEBATE_ROUND"
    assert out["selectedTopic"]["title"] == topic["title"]
    for side in ("pro", "con"):
        assert out[side]["speaker"]
        assert out[side]["claim"].strip()
        assert 1 <= len(out[side]["evidence"]) <= 3
        assert out[side]["example"].strip()
    assert out["rebuttal"]["proRebuttal"].strip()
    assert out["rebuttal"]["conRebuttal"].strip()
    assert len(out["keyIssues"]) == 3
    assert out["learningTakeaway"].strip()
    assert out.get("content")


# ── LLM 출력 정규화(coerce): 후보 개수 강제 ──────────────────────────────────────
def test_coerce_topic_selection_pads_to_five():
    data = {"primaryConcept": "SSH",
            "debateTopicCandidates": [{"title": "t1"}, {"title": "t2"}, {"title": "t3"}]}
    out = E.coerce_topic_selection(data, "ssh가 뭐야?")
    assert len(out["debateTopicCandidates"]) == 5
    assert [c["topicId"] for c in out["debateTopicCandidates"]] == ["A", "B", "C", "D", "E"]


def test_coerce_topic_selection_truncates_to_five():
    data = {"primaryConcept": "SSH",
            "debateTopicCandidates": [{"title": f"t{i}"} for i in range(8)]}
    out = E.coerce_topic_selection(data, "ssh가 뭐야?")
    assert len(out["debateTopicCandidates"]) == 5


def test_coerce_debate_round_fills_key_issues():
    topic = {"topicId": "A", "title": "T"}
    data = {"pro": {"claim": "p"}, "con": {"claim": "c"}, "keyIssues": ["하나"]}
    out = E.coerce_debate_round(data, "ssh가 뭐야?", topic)
    assert len(out["keyIssues"]) == 3
    assert out["pro"]["claim"] == "p"


# ── JSON repair ───────────────────────────────────────────────────────────────
def test_strip_json_handles_fence_and_think():
    raw = "여기 결과입니다:\n```json\n<think>고민중</think>{\"a\": 1, \"b\": [2,3]}\n```\n끝"
    import json
    parsed = json.loads(E.strip_json_block(raw))
    assert parsed["a"] == 1 and parsed["b"] == [2, 3]


# ── debateStages 합성 (마인드맵 하위호환) ─────────────────────────────────────
def test_synthesize_debate_stages_backward_compat():
    topic = {"topicId": "A", "title": "SSH는 먼저 배워야 하는가?"}
    rnd = E.fallback_debate_round("ssh가 뭐야?", topic)
    stages = E.synthesize_debate_stages(rnd)
    types = {(s["stageType"], s["side"]) for s in stages}
    assert ("TOPIC", "TOPIC") in types
    assert ("OPENING_STATEMENT", "CON") in types
    assert ("OPENING_STATEMENT", "PRO") in types
    assert ("REBUTTAL", "CON") in types or ("REBUTTAL", "PRO") in types
    assert any(s["stageType"] == "JUDGEMENT" for s in stages)
