"""
모드 계약 행동 테스트(필수 7종) — task 명세.

LLM은 monkeypatch로 격리하고, 라우팅/이벤트 계약만 검증한다.
"""
import pytest

from app.schemas.multi_chat_schema import MultiChatRequest
from app.services import multi_agent_service as M
from app.services import debate_topic_engine as DTE
from app.services import mode_stage_contract as MC

FORBIDDEN = ["1차 초안", "초안", "FIRST_ANSWER", "DRAFT", "validation_score", "성격 검증"]

DEBATE_AGENTS = [
    {"name": "주장자", "personality": "논리", "level": "학사"},
    {"name": "반박자", "personality": "비판", "level": "학사"},
    {"name": "중재자", "personality": "친절", "level": "학사"},
]


def _collect(gen):
    return list(gen)


def _stages(events):
    return [e["data"].get("stage") for e in events]


def _scan_forbidden(events):
    """content/stage_label/agent_role 필드를 재귀 스캔해 금지어 검출."""
    hits = []

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("content", "stage_label", "agent_role", "agentRole", "stageLabel") and isinstance(v, str):
                    for bad in FORBIDDEN:
                        if bad in v:
                            hits.append((k, bad, v[:60]))
                walk(v)
        elif isinstance(obj, list):
            for x in obj:
                walk(x)

    for e in events:
        walk(e.get("data") or {})
    return hits


# ── 1. debate_direct_question_no_options ──────────────────────────────────────
def test_debate_direct_question_no_options(monkeypatch):
    monkeypatch.setattr(DTE, "build_debate_round",
                        lambda req: DTE.fallback_debate_round("gRPC가 뭐야",
                                                              {"topicId": None, "title": "gRPC가 뭐야"}))
    req = MultiChatRequest(message="gRPC가 뭐야", mode="debate", learningMode="debate", agents=DEBATE_AGENTS)
    events = _collect(M.run_debate_mode_stream(req, M._get_agents(req), ""))

    names = [e["event"] for e in events]
    # A~E 선택지 금지
    assert "debate_topic_candidates" not in names
    for e in events:
        assert not e["data"].get("debateTopicCandidates")

    stages = _stages(events)
    assert "debate_claim" in stages
    assert "debate_rebuttal" in stages
    assert "debate_mediation" in stages

    # 3명 에이전트(서로 다른 agent_id)
    agent_ids = {e["data"].get("agent_id") for e in events
                 if e["data"].get("stage") in ("debate_claim", "debate_rebuttal", "debate_mediation")}
    assert len(agent_ids) == 3

    # gRPC 설명이 content에 존재
    blob = " ".join(e["data"].get("content", "") for e in events)
    assert "gRPC" in blob

    # all_complete 정확히 1회
    assert names.count("all_complete") == 1


# ── 2. debate_request_options ─────────────────────────────────────────────────
def test_debate_request_options(monkeypatch):
    monkeypatch.setattr(DTE, "build_topic_selection",
                        lambda req: DTE.fallback_topic_selection("gRPC"))
    req = MultiChatRequest(message="토론 주제 추천해줘", mode="debate", learningMode="debate", agents=DEBATE_AGENTS)
    events = _collect(M.run_debate_mode_stream(req, M._get_agents(req), ""))

    names = [e["event"] for e in events]
    assert "debate_topic_candidates" in names
    cand = next(e for e in events if e["event"] == "debate_topic_candidates")["data"]
    assert len(cand["debateTopicCandidates"]) == 5

    # pending_choice_context 포함(후보 echo용)
    pcc = None
    for e in events:
        pcc = e["data"].get("pendingChoiceContext") or pcc
    assert pcc is not None
    assert len(pcc["options"]) == 5
    assert pcc["options"][0]["optionId"] == "A"


# ── 3. debate_option_selection_without_context ────────────────────────────────
def test_debate_option_selection_without_context(monkeypatch):
    # 호출되면 안 되는 함수들 — 호출 시 테스트 실패
    def _boom(req):
        raise AssertionError("선택지/토론을 새로 생성하면 안 된다")
    monkeypatch.setattr(DTE, "build_topic_selection", _boom)
    monkeypatch.setattr(DTE, "build_debate_round", _boom)

    req = MultiChatRequest(message="A", mode="debate", learningMode="debate", agents=DEBATE_AGENTS)
    events = _collect(M.run_debate_mode_stream(req, M._get_agents(req), ""))

    # 새 후보 생성 금지
    for e in events:
        assert not e["data"].get("debateTopicCandidates")
    # 안내 메시지 존재
    blob = " ".join(e["data"].get("content", "") for e in events)
    assert "이전" in blob or "없습니다" in blob
    assert [e["event"] for e in events].count("all_complete") == 1


# ── 6. exactly_one_all_complete_per_turn (debate direct) ──────────────────────
def test_exactly_one_all_complete_debate(monkeypatch):
    monkeypatch.setattr(DTE, "build_debate_round",
                        lambda req: DTE.fallback_debate_round("gRPC가 뭐야", {"title": "gRPC가 뭐야"}))
    req = MultiChatRequest(message="gRPC가 뭐야", mode="debate", learningMode="debate", agents=DEBATE_AGENTS)
    events = _collect(M.run_debate_mode_stream(req, M._get_agents(req), ""))
    turn_ids = {e["data"].get("turn_id") for e in events}
    assert len(turn_ids) == 1  # 모든 이벤트 동일 turn
    assert [e["event"] for e in events].count("all_complete") == 1


# ── 7. no_duplicate_agent_stage (debate direct) ───────────────────────────────
def test_no_duplicate_agent_stage_debate(monkeypatch):
    monkeypatch.setattr(DTE, "build_debate_round",
                        lambda req: DTE.fallback_debate_round("gRPC가 뭐야", {"title": "gRPC가 뭐야"}))
    req = MultiChatRequest(message="gRPC가 뭐야", mode="debate", learningMode="debate", agents=DEBATE_AGENTS)
    events = _collect(M.run_debate_mode_stream(req, M._get_agents(req), ""))
    keys = []
    for e in events:
        d = e["data"]
        if d.get("stage") in ("debate_claim", "debate_rebuttal", "debate_mediation"):
            keys.append((d.get("turn_id"), d.get("stage"), d.get("agent_id")))
    assert len(keys) == len(set(keys))


# ── 5(부분). no_internal_labels (debate) ──────────────────────────────────────
def test_no_internal_labels_debate(monkeypatch):
    monkeypatch.setattr(DTE, "build_debate_round",
                        lambda req: DTE.fallback_debate_round("gRPC가 뭐야", {"title": "gRPC가 뭐야"}))
    req = MultiChatRequest(message="gRPC가 뭐야", mode="debate", learningMode="debate", agents=DEBATE_AGENTS)
    events = _collect(M.run_debate_mode_stream(req, M._get_agents(req), ""))
    assert _scan_forbidden(events) == []


# ── default 모드 모킹(LLM 비호출) ─────────────────────────────────────────────
from app.schemas.multi_chat_schema import AgentAnswer


def _mock_default(monkeypatch, answer_text="이것은 깨끗한 답변입니다."):
    monkeypatch.setattr(M, "_get_rag_context", lambda *a, **k: "")

    def _basic(request, agent, idx, total, context):
        return AgentAnswer(agentName=agent.name, agentId=getattr(agent, "agentId", None) or f"a{idx}",
                           answer=answer_text, content=answer_text, role=agent.role or "default",
                           speechType="first_answer", displayOrder=idx, status="SUCCESS")
    monkeypatch.setattr(M, "_basic_agent_stream_answer", _basic)
    monkeypatch.setattr(M, "_compute_stage2", lambda *a, **k: ([], {}, {}, "ollama", 0, []))
    monkeypatch.setattr(M, "_compute_validation", lambda *a, **k: ({}, []))
    monkeypatch.setattr(M, "_compute_stage3", lambda *a, **k: ([], "ollama", 0))


# ── 4. multi_question_no_forced_choice ────────────────────────────────────────
def test_multi_question_no_forced_choice(monkeypatch):
    _mock_default(monkeypatch)
    req = MultiChatRequest(message="SSH가 뭐고 gRPC가 뭐고 둘 차이가 뭐야?",
                           agents=DEBATE_AGENTS)  # mode 미지정 → default
    events = _collect(M.build_stream_generator(req))

    ts = next(e for e in events if e["event"] == "turn_start")["data"]
    assert ts.get("multiQuestion") is True
    assert len(ts.get("atomicQuestions") or []) >= 2

    # "하나만 선택" 같은 강제 문구가 없어야 한다
    blob = " ".join(str(e["data"].get("content", "")) for e in events)
    for forbidden in ["하나만 선택", "하나를 선택", "하나만 고르", "select one", "한 개만"]:
        assert forbidden not in blob

    # 3명 에이전트가 각각 답한다
    ans_agents = {e["data"].get("agent_id") for e in events
                  if e["event"] == "agent_answer"}
    assert len(ans_agents) == 3


# ── 5. no_internal_labels (default) ───────────────────────────────────────────
def test_no_internal_labels_default(monkeypatch):
    _mock_default(monkeypatch, answer_text="객체지향은 1차 초안 같은 내부어가 없는 설명입니다.")
    req = MultiChatRequest(message="객체지향이 뭐야?", agents=DEBATE_AGENTS)
    events = _collect(M.build_stream_generator(req))
    assert _scan_forbidden(events) == []
    # 누출 단어를 일부러 넣어도 정제된다
    contents = [e["data"].get("content", "") for e in events if e["event"] == "agent_answer"]
    assert all("초안" not in c for c in contents)


# ── 5. no_internal_labels (socratic) ──────────────────────────────────────────
def test_no_internal_labels_socratic(monkeypatch):
    monkeypatch.setattr(M, "_get_rag_context", lambda *a, **k: "")
    monkeypatch.setattr(M, "_call_llm_no_think",
                        lambda *a, **k: "이 개념을 당신의 말로 설명해볼까요?")
    req = MultiChatRequest(message="객체지향이 뭐야?", mode="socratic", learningMode="socratic",
                           agents=DEBATE_AGENTS)
    events = _collect(M.build_stream_generator(req))
    assert _scan_forbidden(events) == []
    assert [e["event"] for e in events].count("all_complete") == 1


# ── 6. exactly_one_all_complete_per_turn (default) ────────────────────────────
def test_exactly_one_all_complete_default(monkeypatch):
    _mock_default(monkeypatch)
    req = MultiChatRequest(message="객체지향이 뭐야?", agents=DEBATE_AGENTS)
    events = _collect(M.build_stream_generator(req))
    assert [e["event"] for e in events].count("all_complete") == 1
    assert len({e["data"].get("turn_id") for e in events}) == 1


# ── 7. no_duplicate_agent_stage (default) ─────────────────────────────────────
def test_no_duplicate_agent_stage_default(monkeypatch):
    _mock_default(monkeypatch)
    req = MultiChatRequest(message="객체지향이 뭐야?", agents=DEBATE_AGENTS)
    events = _collect(M.build_stream_generator(req))
    keys = [(e["data"].get("turn_id"), e["data"].get("stage"), e["data"].get("agent_id"))
            for e in events if e["event"] == "agent_answer"]
    assert len(keys) == len(set(keys))
    # answer stage 3명 모두 등장
    assert sum(1 for e in events if e["event"] == "agent_answer") == 3
