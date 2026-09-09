"""특정 교수 타겟 질문 라우팅(STRICT TARGETING) 회귀 테스트.

불변조건: 사용자가 지정한 targetAgentId = 실제 답변 AgentProfile = SSE agentId/agentName/agentIndex(방 슬롯).
  - _filter_agents: str/int 혼용 id 해석, 모르는 id 는 UnknownTargetAgentError(agents[0]/전체 폴백 금지),
    None/blank 는 전체(협업 모드) 유지.
  - _get_agents: 요청 agents 배열 위치를 agentSlot(1-based) 로 고정 → 필터 후에도 보존.
  - 스트림: 2번 교수 지정 시 모든 agent_start/agent_answer 가 agentId=2번, agentIndex=2(필터 배열 위치 1 아님).
  - 라우트: 모르는 targetAgentId → 422 TARGET_AGENT_NOT_FOUND (정식 라우트 + 운영 compat 라우트).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.schemas.multi_chat_schema import AgentProfile, MultiChatRequest
from app.services import multi_agent_service as M
from app.services import orchestrator_service as O


def _agents():
    return [
        {"id": 101, "agentId": 101, "name": "개념 정리 교수", "personality": "전문적", "knowledgeLevel": "학사 수준"},
        {"id": 102, "agentId": 102, "name": "쉬운 풀이 튜터", "personality": "친절형", "knowledgeLevel": "입문"},
        {"id": 103, "agentId": 103, "name": "논점 검증 코치", "personality": "비판적", "knowledgeLevel": "석사 수준"},
    ]


def _req(target=None, message="스택과 큐의 차이를 설명해줘", agents=None):
    body = {"message": message, "mode": "default", "learningMode": "basic", "roomId": 1, "userId": 1,
            "agents": agents if agents is not None else _agents(), "previousAnswers": []}
    if target is not None:
        body["targetAgentId"] = target
    return MultiChatRequest(**body)


# ── resolver 단위 ────────────────────────────────────────────────────────────
def test_get_agents_assigns_room_slots():
    agents = M._get_agents(_req())
    assert [a.agentSlot for a in agents] == [1, 2, 3]
    assert [a.agentId for a in agents] == [101, 102, 103]


def test_filter_resolves_string_target_against_int_id_and_keeps_slot():
    agents = M._get_agents(_req())
    got = M._filter_agents(agents, "102")
    assert [a.agentId for a in got] == [102]
    assert got[0].name == "쉬운 풀이 튜터"
    assert got[0].agentSlot == 2  # 필터 후에도 방 슬롯 보존


def test_filter_resolves_int_target_against_string_id():
    agents = M._get_agents(_req(agents=[{"agentId": "a-1", "name": "A"}, {"agentId": "a-2", "name": "B"}]))
    got = M._filter_agents(agents, "a-2")
    assert [a.name for a in got] == ["B"] and got[0].agentSlot == 2


def test_filter_unknown_target_rejects_instead_of_fallback():
    agents = M._get_agents(_req())
    with pytest.raises(M.UnknownTargetAgentError) as ei:
        M._filter_agents(agents, "999")
    assert ei.value.target_id == "999"
    assert ei.value.available == ["101", "102", "103"]


def test_filter_null_or_blank_preserves_group_mode():
    agents = M._get_agents(_req())
    assert [a.agentId for a in M._filter_agents(agents, None)] == [101, 102, 103]
    assert [a.agentId for a in M._filter_agents(agents, "  ")] == [101, 102, 103]


# ── 스트림 identity ────────────────────────────────────────────────────────────
@pytest.fixture
def fast_llm(monkeypatch):
    """LLM 호출 없이 오케스트레이터를 돌린다. 답변 본문에 실제로 프롬프트에 쓰인 AgentProfile 을 각인해
    '어떤 persona 로 생성됐는지' 를 검증할 수 있게 한다."""
    monkeypatch.setenv("STUDYMATE_MIN_ANSWER_GAP_SECONDS", "0")
    monkeypatch.setenv("MULTI_CHAT_REDIS_MEMORY_ENABLED", "false")

    def fake_single(agent, request, mode, cache, context, agents, peer=None, social=False, position=0, total=1):
        return f"[persona:{agent.agentId}:{agent.name}] 답변"

    def fake_round2(agent, request, mode, others):
        return f"[persona:{agent.agentId}:{agent.name}] 반응"

    def fake_wrap(request, all_answers, mode, agent):
        return f"[persona:{agent.agentId}:{agent.name}] 정리"

    monkeypatch.setattr(O, "_generate_single_agent_answer", fake_single)
    monkeypatch.setattr(O, "_generate_round2_feedback", fake_round2)
    monkeypatch.setattr(O, "_generate_discussion_wrap", fake_wrap)
    return None


def _collect(req):
    return [(ev["event"], ev["data"]) for ev in M.build_stream_generator(req)]


@pytest.mark.parametrize("target,expect_id,expect_name,expect_slot", [
    ("101", 101, "개념 정리 교수", 1),
    ("102", 102, "쉬운 풀이 튜터", 2),
    ("103", 103, "논점 검증 코치", 3),
    (102, 102, "쉬운 풀이 튜터", 2),
])
def test_stream_target_identity_preserved_end_to_end(fast_llm, target, expect_id, expect_name, expect_slot):
    events = _collect(_req(target=target))
    names = [e for e, _ in events]
    assert names[0] == "turn_start" and names[-1] == "all_complete"
    ts = events[0][1]
    assert ts["targetAgentId"] == str(target)
    assert ts["responderAgentIds"] == [str(expect_id)]

    agent_events = [(e, d) for e, d in events if e in ("agent_start", "agent_answer")]
    assert agent_events, "agent 이벤트가 없다"
    for e, d in agent_events:
        assert d["agentId"] == expect_id, (e, d)
        assert d["agentName"] == expect_name, (e, d)
        assert d["agentIndex"] == expect_slot, (e, d)  # 필터된 배열 위치(1)가 아니라 방 슬롯
        if e == "agent_answer":
            assert f"[persona:{expect_id}:{expect_name}]" in d["answer"]  # 실제 LLM 호출 persona = 대상

    done = [d for e, d in events if e == "all_complete"][0]
    assert {a["agentId"] for a in done["answers"]} == {expect_id}
    assert {a["agentName"] for a in done["answers"]} == {expect_name}


def test_stream_without_target_keeps_group_mode(fast_llm):
    events = _collect(_req())
    ts = events[0][1]
    assert ts["targetAgentId"] is None
    assert ts["responderAgentIds"] == ["101", "102", "103"]
    direct = [d for e, d in events if e == "agent_answer" and d.get("actType") == "DIRECT_ANSWER"]
    assert {d["agentId"] for d in direct} == {101, 102, 103}
    # 각 교수의 agentIndex 는 방 슬롯과 일치(1-based)
    slot_by_id = {101: 1, 102: 2, 103: 3}
    for d in direct:
        assert d["agentIndex"] == slot_by_id[d["agentId"]]
        assert f"[persona:{d['agentId']}:{d['agentName']}]" in d["answer"]


def test_stream_target_independent_of_array_order(fast_llm):
    """배열 순서를 바꿔도 같은 id 가 답한다(index 의존 없음). 슬롯은 새 순서를 따른다."""
    reordered = [_agents()[2], _agents()[0], _agents()[1]]  # 103, 101, 102
    events = _collect(_req(target="102", agents=reordered))
    answers = [d for e, d in events if e == "agent_answer"]
    assert answers and all(d["agentId"] == 102 and d["agentName"] == "쉬운 풀이 튜터" for d in answers)
    assert all(d["agentIndex"] == 3 for d in answers)


def test_stream_unknown_target_raises_before_stream(fast_llm):
    with pytest.raises(M.UnknownTargetAgentError):
        M.build_stream_generator(_req(target="999"))


# ── 라우트 4xx ────────────────────────────────────────────────────────────────
def test_official_stream_route_rejects_unknown_target_422():
    from app.api.multi_chat_routes import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        body = {"message": "q", "mode": "default", "learningMode": "basic",
                "agents": _agents(), "targetAgentId": "999"}
        resp = client.post("/api/ai/multi-chat/stream", json=body)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "TARGET_AGENT_NOT_FOUND"
    assert detail["targetAgentId"] == "999"
    assert detail["availableAgentIds"] == ["101", "102", "103"]


def test_official_sync_route_rejects_unknown_target_422():
    from app.api.multi_chat_routes import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        body = {"message": "q", "mode": "default", "learningMode": "basic",
                "agents": _agents(), "targetAgentId": "999"}
        resp = client.post("/api/ai/multi-chat", json=body)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "TARGET_AGENT_NOT_FOUND"


def test_compat_live_route_rejects_unknown_target_422():
    import multi_chat_stream_compat as compat
    app = FastAPI()
    app.include_router(compat.router)
    with TestClient(app) as client:
        body = {"message": "q", "mode": "default", "learningMode": "basic",
                "agents": _agents(), "targetAgentId": "999"}
        resp = client.post("/api/ai/multi-chat/stream", json=body)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "TARGET_AGENT_NOT_FOUND"


def test_compat_live_route_passes_known_target_and_keeps_slot(monkeypatch):
    """운영 compat 라우트: 알려진 대상은 200 스트림, 내부 generator 의 agentIndex(방 슬롯)를 바꾸지 않는다."""
    import json
    import multi_chat_stream_compat as compat

    def fake_gen(request):
        agents = M._filter_agents(M._get_agents(request), request.targetAgentId)
        a = agents[0]
        yield {"event": "turn_start", "data": {"type": "turn_start"}}
        yield {"event": "agent_answer", "data": {"type": "agent_answer", "agentIndex": a.agentSlot,
                                                  "agentId": a.agentId, "agentName": a.name, "answer": "ok"}}
        yield {"event": "all_complete", "data": {"type": "all_complete", "answers": [
            {"agentId": a.agentId, "agentName": a.name, "answer": "ok", "agentIndex": a.agentSlot}]}}

    monkeypatch.setattr("app.services.multi_agent_service.build_stream_generator", fake_gen)
    app = FastAPI()
    app.include_router(compat.router)
    with TestClient(app) as client:
        body = {"message": "q", "mode": "default", "learningMode": "basic",
                "agents": _agents(), "targetAgentId": "102"}
        resp = client.post("/api/ai/multi-chat/stream", json=body)
    assert resp.status_code == 200
    answers = []
    for block in resp.text.split("\n\n"):
        if block.startswith("event: agent_answer"):
            answers.append(json.loads(block.split("data:", 1)[1].strip()))
    assert len(answers) == 1  # 누락 교수 filler 합성 없음(대상 1명만)
    assert answers[0]["agentId"] == 102 and answers[0]["agentName"] == "쉬운 풀이 튜터"
    assert answers[0]["agentIndex"] == 2


# ── 비스트림 라이브 엔드포인트(fastapi/main.py) ────────────────────────────────
# 운영 앱은 hotfix_main(=main:app + compat 스트림 라우터)이다. SSE 가 실패하면 프론트/Spring 은
# 같은 요청을 비스트림 POST /api/ai/multi-chat 로 재시도하므로, 이 경로도 STRICT TARGETING 이어야 한다.
def _live_agents():
    import main as LIVE
    return [LIVE.AgentProfile(**a) for a in _agents()]


def test_live_nonstream_resolver_matches_string_target_against_int_id():
    """Spring 은 targetAgentId 를 문자열로, agents[].id 는 숫자로 보낸다(101 == "101" → False)."""
    import main as LIVE
    got = LIVE.select_agents_for_response(_live_agents(), "102")
    assert [a.name for a in got] == ["쉬운 풀이 튜터"]
    assert [str(a.agentId) for a in got] == ["102"]


def test_live_nonstream_resolver_matches_int_target():
    import main as LIVE
    got = LIVE.select_agents_for_response(_live_agents(), 103)
    assert [a.name for a in got] == ["논점 검증 코치"]


def test_live_nonstream_resolver_rejects_unknown_target():
    """모르는 id 는 '전체 에이전트 사용' 으로 조용히 폴백하지 않는다(=1번 교수가 대신 답하는 원인)."""
    import main as LIVE
    with pytest.raises(M.UnknownTargetAgentError) as ei:
        LIVE.select_agents_for_response(_live_agents(), "999")
    assert ei.value.target_id == "999"
    assert ei.value.available == ["101", "102", "103"]


def test_live_nonstream_resolver_keeps_group_mode_when_no_target():
    import main as LIVE
    for empty in (None, "", "   "):
        got = LIVE.select_agents_for_response(_live_agents(), empty)
        assert [a.name for a in got] == ["개념 정리 교수", "쉬운 풀이 튜터", "논점 검증 코치"]


@pytest.fixture
def live_client(monkeypatch):
    """LLM 없이 비스트림 엔드포인트를 태운다. 답변은 '실제로 넘겨받은 AgentProfile' 을 각인한다."""
    import main as LIVE

    def fake_parallel(agents, message, context, timeout_seconds, learning_mode="basic",
                      strict_persona=True, generation_payload=None):
        answers = [
            LIVE.AgentAnswer(agentName=a.name, agentId=a.agentId,
                             answer=f"[persona:{a.agentId}:{a.name}] 답변")
            for a in agents
        ]
        return answers, LIVE.ProcessSteps()

    monkeypatch.setattr(LIVE, "_run_agents_parallel", fake_parallel)
    return TestClient(LIVE.app)


def _live_body(target=None):
    body = {"message": "스택과 큐의 차이를 설명해줘", "mode": "multi_agent_discussion",
            "learningMode": "basic", "roomId": 1, "rounds": 1, "agents": _agents()}
    if target is not None:
        body["targetAgentId"] = target
    return body


def test_live_nonstream_route_answers_only_target(live_client):
    """2번 교수 지정 → 2번만 답변. (버그 시엔 3명 전원이 답해 1번 답변이 맨 위에 붙었다)"""
    resp = live_client.post("/api/ai/multi-chat", json=_live_body("102"))
    assert resp.status_code == 200
    data = resp.json()
    assert [a["agentId"] for a in data["answers"]] == [102]
    assert [a["agentName"] for a in data["answers"]] == ["쉬운 풀이 튜터"]
    assert "[persona:102:쉬운 풀이 튜터]" in data["answers"][0]["answer"]
    assert [m["agentId"] for m in data["messages"]] == [102]


def test_live_nonstream_route_without_target_keeps_group_mode(live_client):
    resp = live_client.post("/api/ai/multi-chat", json=_live_body())
    assert resp.status_code == 200
    assert [a["agentId"] for a in resp.json()["answers"]] == [101, 102, 103]


def test_live_nonstream_route_unknown_target_422(live_client):
    resp = live_client.post("/api/ai/multi-chat", json=_live_body("999"))
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "TARGET_AGENT_NOT_FOUND"
    assert detail["targetAgentId"] == "999"
    assert detail["availableAgentIds"] == ["101", "102", "103"]
