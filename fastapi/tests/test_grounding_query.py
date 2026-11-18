"""검색 질의는 현재 질문만: Redis 기억/이전 대화를 Wiki/Tavily/OpenAI 질의로 보내지 않는다."""
from app.studymate import grounding as GR


def test_search_query_is_current_message_only(monkeypatch):
    monkeypatch.setenv("STUDYMATE_GROUNDING", "on")
    seen = []
    b = GR.gather("TCP 혼잡제어를 설명해줘", ["phd"], fetcher=lambda src, q: (seen.append((src, q)) or f"{src} 근거"))
    assert {q for _, q in seen} == {"TCP 혼잡제어를 설명해줘"}
    assert set(b.by_source) == {"wiki", "gpt"}


def test_pipeline_uses_stripped_message(monkeypatch):
    from app.schemas.multi_chat_schema import MultiChatRequest
    from app.services import orchestrator_service as O
    from app.studymate import basic_pipeline as BP
    got = {}

    def fake(request, agents, current_message, social, rt=None, mode="basic"):
        got["q"] = current_message
        yield {"event": "all_complete", "data": {}}
    monkeypatch.setattr(BP, "run_basic_turn", fake)
    msg = "[이전 대화 기억]\n- user: 예전 질문 비밀 내용\n[현재 질문] Redis 설명해줘"
    req = MultiChatRequest(message=msg, mode="basic", agents=[{"agentId": 1, "name": "a"}])
    list(O.build_orchestrator_stream(req, req.agents))
    assert got["q"] == "Redis 설명해줘"


def test_slow_source_does_not_block_turn(monkeypatch):
    import time
    monkeypatch.setenv("STUDYMATE_GROUNDING", "on")
    t0 = time.time()
    b = GR.gather("느린 질의", ["master"], max_wait_s=0.5, fetcher=lambda src, q: (time.sleep(3) or "x") if src == "tavily" else "wiki ok")
    assert time.time() - t0 < 1.5 and "tavily:timeout" in b.failures and b.by_source.get("wiki") == "wiki ok"
