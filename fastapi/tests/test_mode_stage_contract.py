"""
mode_stage_contract: 사용자 표시 라벨 정규화 + SSE contract 래퍼 테스트.

계약:
  - 내부 라벨('1차 초안','FIRST_ANSWER','validation' 등)은 허용 라벨로 정규화된다.
  - content/stage_label/agent_role에 금지 내부 용어가 남지 않는다.
  - 같은 turn_id+stage+agent_id 조합은 1회만 emit.
  - all_complete는 turn당 정확히 1회.
  - content가 빈 content 이벤트는 emit하지 않는다.
  - 모든 이벤트에 공통 필드(event_type/turn_id/mode/stage/stage_label/sequence/
    is_final/ui_group_color)가 부착된다.
"""
import pytest

from app.services import mode_stage_contract as MC


# ── 라벨 정규화 ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("1차 초안", "답변"),
    ("초안", "답변"),
    ("draft", "답변"),
    ("DRAFT", "답변"),
    ("FIRST_ANSWER", "답변"),
    ("validation", "근거 검증"),
    ("VALIDATION", "근거 검증"),
    ("peer_feedback", "상호 피드백"),
    ("PEER_FEEDBACK", "상호 피드백"),
])
def test_normalize_user_label(raw, expected):
    assert MC.normalize_user_label(raw) == expected


def test_normalize_user_label_passthrough():
    assert MC.normalize_user_label("주장자") == "주장자"
    assert MC.normalize_user_label("") == ""


def test_stage_label_and_color():
    assert MC.stage_label_for("debate_claim") == "주장"
    assert MC.stage_label_for("answer") == "답변"
    assert MC.ui_group_color_for("debate_claim")
    assert MC.ui_group_color_for("answer") != MC.ui_group_color_for("debate_rebuttal")


# ── strip_internal_labels: 자유 텍스트에서 금지어 제거 ─────────────────────────
def test_strip_internal_labels_removes_forbidden():
    for forbidden, text in [
        ("초안", "이것은 1차 초안 입니다."),
        ("FIRST_ANSWER", "stage=FIRST_ANSWER 입니다"),
        ("validation_score", "validation_score: 0.7"),
        ("성격 검증", "성격 검증 0.69 보완 필요"),
        ("DRAFT", "DRAFT 내용"),
    ]:
        out = MC.strip_internal_labels(text)
        assert forbidden not in out


# ── apply_mode_contract: 공통 필드 부착 ───────────────────────────────────────
def _evt(event, **data):
    return {"event": event, "data": data}


def test_contract_attaches_common_fields():
    raw = [
        _evt("turn_start"),
        _evt("agent_answer", agentId="a1", agentName="에이전트1", content="안녕 gRPC"),
        _evt("all_complete", content=""),
    ]
    out = list(MC.apply_mode_contract(iter(raw), mode="default", turn_id="T1"))
    ans = next(e for e in out if e["event"] == "agent_answer")["data"]
    for key in ("event_type", "turn_id", "mode", "stage", "stage_label",
                "agent_id", "agent_name", "content", "sequence", "is_final", "ui_group_color"):
        assert key in ans, f"missing {key}"
    assert ans["turn_id"] == "T1"
    assert ans["stage"] == "answer"
    assert ans["stage_label"] == "답변"
    assert ans["mode"] == "default"


def test_contract_single_all_complete():
    raw = [_evt("all_complete", content="x"), _evt("all_complete", content="y")]
    out = list(MC.apply_mode_contract(iter(raw), mode="default", turn_id="T"))
    assert sum(1 for e in out if e["event"] == "all_complete") == 1


def test_contract_dedupes_turn_stage_agent():
    raw = [
        _evt("agent_answer", agentId="a1", content="첫 답변"),
        _evt("agent_answer", agentId="a1", content="다른 내용이지만 같은 stage+agent"),
        _evt("agent_answer", agentId="a2", content="에이전트2 답변"),
    ]
    out = list(MC.apply_mode_contract(iter(raw), mode="default", turn_id="T"))
    answers = [e for e in out if e["event"] == "agent_answer"]
    assert len(answers) == 2  # a1 1회 + a2 1회


def test_contract_drops_empty_content():
    raw = [
        _evt("agent_answer", agentId="a1", content=""),
        _evt("agent_answer", agentId="a2", content="실내용"),
    ]
    out = list(MC.apply_mode_contract(iter(raw), mode="default", turn_id="T"))
    answers = [e for e in out if e["event"] == "agent_answer"]
    assert len(answers) == 1
    assert answers[0]["data"]["agent_id"] == "a2"


def test_contract_sequence_increments_and_same_turn():
    raw = [
        _evt("agent_answer", agentId="a1", content="A"),
        _evt("agent_answer", agentId="a2", content="B"),
        _evt("all_complete", content="done"),
    ]
    out = list(MC.apply_mode_contract(iter(raw), mode="default", turn_id="T"))
    seqs = [e["data"]["sequence"] for e in out]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert all(e["data"]["turn_id"] == "T" for e in out)


def test_contract_normalizes_leaky_stage_label():
    # stageType=FIRST_ANSWER 가 들어와도 stage_label/stage는 깨끗해야 한다
    raw = [_evt("agent_answer", agentId="a1", content="x", stageType="FIRST_ANSWER")]
    out = list(MC.apply_mode_contract(iter(raw), mode="default", turn_id="T"))
    d = out[0]["data"]
    assert "FIRST_ANSWER" not in d["stage_label"]
    assert "초안" not in d["stage_label"]
    assert d["stage"] == "answer"


def test_contract_cleans_content_internal_labels():
    raw = [_evt("agent_answer", agentId="a1", content="이건 1차 초안 이고 validation_score 0.7")]
    out = list(MC.apply_mode_contract(iter(raw), mode="default", turn_id="T"))
    c = out[0]["data"]["content"]
    assert "초안" not in c
    assert "validation_score" not in c
