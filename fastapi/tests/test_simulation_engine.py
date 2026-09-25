"""
분기형 상황극(미연시/비주얼 노벨) 상태 머신 엔진 테스트.

_sim_llm을 monkeypatch해 네트워크 없이 결정론적으로 검증한다.
phase 해석 / 첫 턴 SCENE_SETUP / 후속 CHOICE_RESULT / 선택 반영 / 5선택지 강제 /
반복 방지 / ENDING+learningFeedback / fallback 안정성 / 하위호환(simulationStages)을 커버한다.
"""
import json

import pytest

from app.schemas.multi_chat_schema import MultiChatRequest
from app.services import simulation_engine as se


def _req(**kw):
    base = {"message": kw.pop("message", "테스트"), "mode": "simulation", "learningMode": "simulation"}
    base.update(kw)
    return MultiChatRequest(**base)


def _scene_json(n=5):
    return json.dumps({
        "topic": "SSH란 무엇인가?",
        "learningObjective": "SSH의 개념과 보안성을 설명할 수 있다.",
        "userRole": "발표자",
        "worldState": "발표 리허설장",
        "sceneTitle": "리허설 시작",
        "sceneDescription": "교수가 질문한다.",
        "narratorText": "첫 질문이 날아온다.",
        "npc": {"name": "김교수", "role": "교수", "emotion": "curious"},
        "npcDialogue": "SSH가 뭔가요?",
        "npcInnerMonologue": "개념을 아는지 봐야지.",
        "consequence": "발표가 시작된다.",
        "choices": [
            {"choiceId": c, "label": f"선택 {c}", "action": f"행동 {c}",
             "expectedSkill": f"스킬 {c}", "riskLevel": "low"}
            for c in ["A", "B", "C", "D", "E"][:n]
        ],
    }, ensure_ascii=False)


def _result_json(tag="x", ending=False):
    payload = {
        "sceneTitle": f"장면 {tag}",
        "sceneDescription": f"설명 {tag}",
        "narratorText": f"내레이션 {tag}",
        "npc": {"name": "김교수", "role": "교수", "emotion": "interested"},
        "npcDialogue": f"추가 질문 {tag}",
        "npcInnerMonologue": f"속마음 {tag}",
        "consequence": f"결과 {tag}",
        "endingReached": ending,
        "choices": [] if ending else [
            {"choiceId": c, "label": f"{tag}-선택 {c}", "action": "a", "expectedSkill": "s", "riskLevel": "medium"}
            for c in ["A", "B", "C", "D", "E"]
        ],
    }
    if ending:
        payload["learningFeedback"] = {
            "strengths": ["개념 설명"], "weaknesses": ["원리 보완"],
            "nextStudy": ["공개키 인증"], "summary": "요약", "finalScore": 80,
        }
    return json.dumps(payload, ensure_ascii=False)


# ── phase 해석 ────────────────────────────────────────────────────────────────

def test_resolve_phase_first_turn():
    assert se.resolve_phase(_req(message="SSH가 뭐야?")) == se.SCENE_SETUP


def test_resolve_phase_choice_result_by_selected():
    r = _req(message="B", selectedChoice={"choiceId": "B", "label": "보안성"})
    assert se.resolve_phase(r) == se.CHOICE_RESULT


def test_resolve_phase_choice_result_by_state():
    r = _req(message="계속", simulationState={"scenarioId": "sim-1", "turnIndex": 1})
    assert se.resolve_phase(r) == se.CHOICE_RESULT


def test_resolve_phase_ending_flag():
    r = _req(message="끝", endingReached=True)
    assert se.resolve_phase(r) == se.ENDING


# ── 첫 턴 ─────────────────────────────────────────────────────────────────────

def test_scene_setup(monkeypatch):
    monkeypatch.setattr(se, "_sim_llm", lambda *a, **k: _scene_json())
    resp = se.run_simulation(_req(message="SSH는 보안 프로토콜이다."))
    assert resp.phase == se.SCENE_SETUP
    assert resp.scenarioId and resp.scenarioId.startswith("sim-")
    assert resp.turnIndex == 0
    assert resp.sceneTitle
    assert resp.userRole
    assert resp.npc and resp.npc.name == "김교수"
    assert len(resp.choices) == 5
    assert [c.choiceId for c in resp.choices] == ["A", "B", "C", "D", "E"]
    assert resp.endingReached is False
    assert resp.learningFeedback is None
    assert resp.content
    # 하위호환
    assert resp.simulationStages
    assert resp.mode == "simulation"


# ── 후속 턴: 선택 반영 ──────────────────────────────────────────────────────────

def test_choice_result_reflects_selection(monkeypatch):
    monkeypatch.setattr(se, "_sim_llm", lambda *a, **k: _result_json("t1"))
    r = _req(
        message="사용자가 선택지 B를 선택했습니다.",
        selectedChoice={"choiceId": "B", "label": "보안성과 암호화를 먼저 설명한다."},
        simulationState={"scenarioId": "sim-abc", "turnIndex": 1, "topic": "SSH란 무엇인가?",
                         "userRole": "발표자", "worldState": "교수 앞 발표"},
    )
    resp = se.run_simulation(r)
    assert resp.phase == se.CHOICE_RESULT
    assert resp.scenarioId == "sim-abc"
    assert resp.turnIndex == 2  # prev 1 + 1
    assert resp.selectedChoice["choiceId"] == "B"
    assert resp.npcDialogue
    assert resp.npcInnerMonologue
    assert resp.consequence
    assert len(resp.choices) == 5
    assert resp.endingReached is False


# ── 반복 방지: 턴마다 선택지가 달라진다 ─────────────────────────────────────────

def test_choices_change_across_turns(monkeypatch):
    monkeypatch.setattr(se, "_sim_llm", lambda *a, **k: _result_json("t2"))
    r2 = _req(message="C", selectedChoice={"choiceId": "C", "label": "예시 설명"},
              simulationState={"scenarioId": "s", "turnIndex": 1, "topic": "SSH"})
    resp2 = se.run_simulation(r2)
    labels2 = {c.label for c in resp2.choices}

    monkeypatch.setattr(se, "_sim_llm", lambda *a, **k: _result_json("t3"))
    r3 = _req(message="A", selectedChoice={"choiceId": "A", "label": "정의"},
              simulationState={"scenarioId": "s", "turnIndex": 2, "topic": "SSH"})
    resp3 = se.run_simulation(r3)
    labels3 = {c.label for c in resp3.choices}
    assert labels2 != labels3  # 다른 턴은 다른 선택지


# ── 종료: turnIndex가 MAX 이상이면 ENDING ───────────────────────────────────────

def test_ending_by_turn_threshold(monkeypatch):
    monkeypatch.setattr(se, "_sim_llm", lambda *a, **k: _result_json("late", ending=False))
    r = _req(message="E", selectedChoice={"choiceId": "E", "label": "마무리"},
             simulationState={"scenarioId": "s", "turnIndex": se._MAX_TURNS - 1, "topic": "SSH"})
    resp = se.run_simulation(r)
    assert resp.phase == se.ENDING
    assert resp.endingReached is True
    assert resp.choices == []
    assert resp.learningFeedback is not None
    assert resp.learningFeedback.summary


def test_ending_explicit_flag(monkeypatch):
    monkeypatch.setattr(se, "_sim_llm", lambda *a, **k: _result_json("end", ending=True))
    r = _req(message="끝내자", endingReached=True,
             simulationState={"scenarioId": "s", "turnIndex": 3, "topic": "SSH"})
    resp = se.run_simulation(r)
    assert resp.phase == se.ENDING
    assert resp.choices == []
    assert resp.learningFeedback.strengths


# ── fallback: LLM 빈 응답이어도 동작 ────────────────────────────────────────────

def test_scene_setup_fallback(monkeypatch):
    monkeypatch.setattr(se, "_sim_llm", lambda *a, **k: "")
    resp = se.run_simulation(_req(message="TCP 3-way handshake"))
    assert resp.phase == se.SCENE_SETUP
    assert len(resp.choices) == 5
    assert resp.npc is not None
    assert resp.content


def test_choice_result_fallback(monkeypatch):
    monkeypatch.setattr(se, "_sim_llm", lambda *a, **k: "쓰레기 응답 not json")
    r = _req(message="B", selectedChoice={"choiceId": "B", "label": "보안"},
             simulationState={"scenarioId": "s", "turnIndex": 1, "topic": "SSH"})
    resp = se.run_simulation(r)
    assert resp.phase == se.CHOICE_RESULT
    assert len(resp.choices) == 5


def test_ending_fallback(monkeypatch):
    monkeypatch.setattr(se, "_sim_llm", lambda *a, **k: "")
    r = _req(message="끝", endingReached=True,
             simulationState={"scenarioId": "s", "turnIndex": 4, "topic": "SSH"})
    resp = se.run_simulation(r)
    assert resp.phase == se.ENDING
    assert resp.learningFeedback is not None
    assert resp.choices == []


# ── 선택지 정규화 ─────────────────────────────────────────────────────────────

def test_normalize_choices_pads_to_five():
    out = se._normalize_choices([{"label": "하나"}, {"label": "둘"}], "주제")
    assert len(out) == 5
    assert [c.choiceId for c in out] == ["A", "B", "C", "D", "E"]


def test_normalize_choices_truncates_to_five():
    raw = [{"label": f"L{i}"} for i in range(8)]
    out = se._normalize_choices(raw, "주제")
    assert len(out) == 5


def test_normalize_choices_fills_missing_fields():
    out = se._normalize_choices([{"label": "정의만 있음"}], "주제")
    c = out[0]
    assert c.action  # action 보강
    assert c.expectedSkill
    assert c.riskLevel in {"low", "medium", "high"}
    assert c.text == c.label  # 하위호환 필드


# ── 스트림 ────────────────────────────────────────────────────────────────────

def test_stream_emits_scene_and_choices(monkeypatch):
    monkeypatch.setattr(se, "_sim_llm", lambda *a, **k: _scene_json())
    events = list(se.run_simulation_stream(_req(message="SSH")))
    names = [e["event"] for e in events]
    assert names[0] == "turn_start"
    assert "simulation_scene" in names
    assert names[-1] == "all_complete"
    scene = next(e for e in events if e["event"] == "simulation_scene")
    assert len(scene["data"]["choices"]) == 5
    final = events[-1]["data"]
    assert final["phase"] == se.SCENE_SETUP
    assert len(final["choices"]) == 5


def test_stream_ending_event(monkeypatch):
    monkeypatch.setattr(se, "_sim_llm", lambda *a, **k: _result_json("z", ending=True))
    r = _req(message="끝", endingReached=True,
             simulationState={"scenarioId": "s", "turnIndex": 5, "topic": "SSH"})
    events = list(se.run_simulation_stream(r))
    names = [e["event"] for e in events]
    assert "simulation_ending" in names
    end_ev = next(e for e in events if e["event"] == "simulation_ending")
    assert end_ev["data"]["choices"] == []
    assert end_ev["data"]["learningFeedback"]["summary"]
