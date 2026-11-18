from app.studymate import llm_gateway as G, model_router


def test_think_false_for_render_judge_engine():
    for task in ("render", "judge", "engine", "summary", "repair"):
        assert model_router.resolve(task, level="phd").think is False


def test_planner_think_policy(monkeypatch):
    monkeypatch.setenv("STUDYMATE_PLANNER_THINK", "off")
    assert model_router.resolve("planner", level="phd", complex_question=True).think is False
    monkeypatch.setenv("STUDYMATE_PLANNER_THINK", "auto")
    assert model_router.resolve("planner", level="phd", complex_question=True).think is True
    assert model_router.resolve("planner", level="bachelor", complex_question=True).think is False


def test_think_flag_always_in_payload():
    p = G._payload(G.LLMRequest(system="s", user="u", model="m", num_ctx=8192, num_predict=5, think=False))
    assert "think" in p and p["think"] is False
