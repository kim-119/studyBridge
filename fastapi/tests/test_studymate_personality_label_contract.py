"""
StudyMate 성격/지식수준 라벨 계약 테스트.

핵심 불변식: 요청 payload 의 personality / knowledgeLevel **key** 가 SSOT 이며,
클라이언트가 보낸 personalityLabel / knowledgeLevelLabel 이나 env 기본값("친절형"/"학사")이
아니라 **항상 key 에서 라벨을 다시 계산**해 agent_start / agent_answer / all_complete /
done 의 answers·messages 전 경로에 일관되게 실린다.

회귀 방지 대상(실장애): personality="critical" 인데 personalityLabel="친절형",
knowledgeLevel="doctor" 인데 knowledgeLevelLabel="학사" 로 나가던 fallback.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.schemas.multi_chat_schema import MultiChatRequest, AgentAnswer
from app.services import multi_agent_service as M

# (personality key, knowledge key, expected personalityLabel, expected knowledgeLevelLabel)
COMBOS = [
    ("friendly", "undergraduate", "친절형", "학사"),
    ("critical", "doctor", "냉철형", "박사"),
    ("logical", "expert", "논리형", "전문가"),
    ("creative", "graduate", "창의형", "석사"),
    ("concise", "beginner", "간결형", "입문"),
]


def _mock_default(monkeypatch, answer_text="이것은 설명입니다."):
    """default 스트림에서 LLM/검증/피드백을 격리한다(test_mode_contract_streams 동일 패턴)."""
    monkeypatch.setattr(M, "_get_rag_context", lambda *a, **k: "")

    def _basic(request, agent, idx, total, context):
        return AgentAnswer(
            agentName=agent.name,
            agentId=getattr(agent, "agentId", None) or f"a{idx}",
            answer=answer_text, content=answer_text,
            role=agent.role or "default",
            speechType="first_answer", displayOrder=idx, status="SUCCESS",
        )

    monkeypatch.setattr(M, "_basic_agent_stream_answer", _basic)
    monkeypatch.setattr(M, "_compute_stage2", lambda *a, **k: ([], {}, {}, "ollama", 0, []))
    monkeypatch.setattr(M, "_compute_validation", lambda *a, **k: ({}, []))
    monkeypatch.setattr(M, "_compute_stage3", lambda *a, **k: ([], "ollama", 0))


def _agents_for(personality, knowledge):
    """함정: 일부러 틀린 라벨(친절형/학사)을 주입해 'key 가 라벨을 덮어쓰는지' 검증한다."""
    return [{
        "name": "교수",
        "personality": personality,
        "personalityLabel": "친절형",      # stale/틀린 라벨 (신뢰하면 안 됨)
        "knowledgeLevel": knowledge,
        "knowledgeLevelLabel": "학사",     # stale/틀린 라벨 (신뢰하면 안 됨)
    }]


def _identity_rows(events):
    """personality/knowledge 관련 필드를 가진 모든 dict 를 평탄화해 반환."""
    rows = []

    def walk(ev_name, obj):
        if isinstance(obj, dict):
            if any(k in obj for k in ("personality", "personalityLabel",
                                      "knowledgeLevel", "knowledgeLevelLabel")):
                rows.append((ev_name, obj.get("personality"), obj.get("personalityLabel"),
                             obj.get("knowledgeLevel"), obj.get("knowledgeLevelLabel")))
            for v in obj.values():
                walk(ev_name, v)
        elif isinstance(obj, list):
            for x in obj:
                walk(ev_name, x)

    for e in events:
        walk(e["event"], e.get("data") or {})
    return rows


def _no_stale_fallback(rows, personality, knowledge):
    """key 가 친절/학사가 아닌데 라벨이 친절형/학사로 남아 있으면 fallback 잔존."""
    for (ev, p, pl, k, kl) in rows:
        if p == personality and personality != "friendly":
            assert pl != "친절형", f"{ev}: personalityLabel fallback(친절형) 잔존 (p={p})"
        if k == knowledge and knowledge != "undergraduate":
            assert kl != "학사", f"{ev}: knowledgeLevelLabel fallback(학사) 잔존 (k={k})"


# ── 1) 스트림 계약: agent_start / agent_answer / all_complete ────────────────────
@pytest.mark.parametrize("personality,knowledge,plabel,klabel", COMBOS)
def test_basic_stream_labels_from_key(monkeypatch, personality, knowledge, plabel, klabel):
    _mock_default(monkeypatch)
    req = MultiChatRequest(message="gRPC가 뭐야?", mode="basic", learningMode="basic",
                           agents=_agents_for(personality, knowledge))
    events = list(M.build_stream_generator(req))
    names = [e["event"] for e in events]

    assert "agent_start" in names
    assert "agent_answer" in names
    assert names.count("all_complete") == 1

    # agent_start
    astart = next(e for e in events if e["event"] == "agent_start")["data"]
    assert astart.get("personality") == personality
    assert astart.get("personalityLabel") == plabel
    assert astart.get("knowledgeLevel") == knowledge
    assert astart.get("knowledgeLevelLabel") == klabel

    # agent_answer
    aans = next(e for e in events if e["event"] == "agent_answer")["data"]
    assert aans.get("personalityLabel") == plabel
    assert aans.get("knowledgeLevelLabel") == klabel

    # all_complete.answers / all_complete.messages
    allc = next(e for e in events if e["event"] == "all_complete")["data"]
    assert allc.get("answers"), "all_complete.answers 비어있음"
    for ans in allc["answers"]:
        assert ans.get("personalityLabel") == plabel
        assert ans.get("knowledgeLevelLabel") == klabel
    assert allc.get("messages"), "all_complete.messages 비어있음"
    for msg in allc["messages"]:
        assert msg.get("personalityLabel") == plabel
        assert msg.get("knowledgeLevelLabel") == klabel

    _no_stale_fallback(_identity_rows(events), personality, knowledge)


# ── 2) 라우트 계약: done.answers / done.messages (TestClient SSE) ────────────────
def _parse_sse(text):
    events, cur = [], None
    for line in text.split("\n"):
        if line.startswith("event: "):
            cur = line[len("event: "):].strip()
        elif line.startswith("data: "):
            try:
                events.append({"event": cur, "data": json.loads(line[len("data: "):])})
            except Exception:
                pass
    return events


def _client():
    app = FastAPI()
    from app.api.multi_chat_routes import router
    app.include_router(router)
    return TestClient(app)


@pytest.mark.parametrize("personality,knowledge,plabel,klabel", COMBOS)
def test_route_stream_labels_from_key(monkeypatch, personality, knowledge, plabel, klabel):
    """라우트(실 SSE/HTTP) 경로에서도 all_complete.answers/messages 라벨이 key 기준.
    done 은 라우트가 의도적으로 terminator(visible:false)만 담으므로 종료 신호만 검증한다."""
    _mock_default(monkeypatch)
    resp = _client().post("/api/ai/multi-chat/stream", json={
        "message": "gRPC가 뭐야?", "mode": "basic", "learningMode": "basic",
        "agents": _agents_for(personality, knowledge),
    })
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    names = [e["event"] for e in events]
    assert names.count("all_complete") == 1
    assert "done" in names

    allc = next(e for e in events if e["event"] == "all_complete")["data"]
    assert allc.get("answers") and allc.get("messages")
    for coll in (allc["answers"], allc["messages"]):
        for item in coll:
            assert item.get("personalityLabel") == plabel
            assert item.get("knowledgeLevelLabel") == klabel

    done = [e for e in events if e["event"] == "done"][-1]["data"]
    assert done.get("status") == "done"  # 정상 종료 terminator

    _no_stale_fallback(_identity_rows(events), personality, knowledge)


# ── 3) 3-에이전트 혼합(실장애 재현): 각 교수가 자기 key 라벨을 유지 ──────────────
def test_mixed_agents_each_keep_own_label(monkeypatch):
    _mock_default(monkeypatch)
    agents = [
        {"name": "친절 교수", "personality": "friendly", "personalityLabel": "친절형",
         "knowledgeLevel": "undergraduate", "knowledgeLevelLabel": "학사"},
        {"name": "냉철 교수", "personality": "critical", "personalityLabel": "친절형",
         "knowledgeLevel": "doctor", "knowledgeLevelLabel": "학사"},
        {"name": "전문가 교수", "personality": "logical", "personalityLabel": "친절형",
         "knowledgeLevel": "expert", "knowledgeLevelLabel": "학사"},
    ]
    req = MultiChatRequest(message="gRPC가 뭐야? REST와 차이까지.", mode="basic",
                           learningMode="basic", agents=agents)
    allc = next(e for e in M.build_stream_generator(req) if e["event"] == "all_complete")["data"]

    by_name = {m["agentName"]: m for m in allc["messages"]}
    assert by_name["냉철 교수"]["personalityLabel"] == "냉철형"
    assert by_name["냉철 교수"]["knowledgeLevelLabel"] == "박사"
    assert by_name["전문가 교수"]["personalityLabel"] == "논리형"
    assert by_name["전문가 교수"]["knowledgeLevelLabel"] == "전문가"
    assert by_name["친절 교수"]["personalityLabel"] == "친절형"
    assert by_name["친절 교수"]["knowledgeLevelLabel"] == "학사"


# ── 4) 단위: helper / normalize / canonicalizer ────────────────────────────────
@pytest.mark.parametrize("personality,knowledge,plabel,klabel", COMBOS)
def test_label_helpers(personality, knowledge, plabel, klabel):
    assert M._studymate_personality_label(personality) == plabel
    assert M._studymate_knowledge_label(knowledge) == klabel


def test_normalize_overrides_stale_label():
    from app.schemas.multi_chat_schema import AgentProfile
    a = AgentProfile(name="x", personality="critical", personalityLabel="친절형",
                     knowledgeLevel="doctor", knowledgeLevelLabel="학사")
    M._normalize_studymate_agent_labels(a)
    assert a.personalityLabel == "냉철형"
    assert a.knowledgeLevelLabel == "박사"


def test_canonicalizer_fixes_nested_stale_labels():
    blob = {"answers": [{"personality": "logical", "personalityLabel": "친절형",
                         "knowledgeLevel": "expert", "knowledgeLevelLabel": "학사"}]}
    M._canonicalize_identity_labels(blob)
    assert blob["answers"][0]["personalityLabel"] == "논리형"
    assert blob["answers"][0]["knowledgeLevelLabel"] == "전문가"
