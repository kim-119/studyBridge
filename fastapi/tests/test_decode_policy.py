from app.studymate import model_router, persona_policy as PP
from app.studymate.profile_contract import PERSONALITY_KEYS


def test_decode_is_auxiliary_and_ordered():
    t = {p: PP.decode_policy(p).temperature for p in PERSONALITY_KEYS}
    assert t["creative"] > t["friendly"] > t["logical"] and t["concise"] <= t["critical"]


def test_render_uses_persona_decode_structured_tasks_low_temp():
    assert model_router.resolve("render", level="master", persona="creative").temperature == PP.decode_policy("creative").temperature
    assert model_router.resolve("judge").temperature <= 0.2 and model_router.resolve("planner").temperature <= 0.2


def test_env_override(monkeypatch):
    monkeypatch.setenv("STUDYMATE_DECODE_CREATIVE_TEMP", "0.7")
    assert PP.decode_policy("creative").temperature == 0.7


def test_same_num_ctx_for_all_tasks():
    ctxs = {model_router.resolve(t, level="phd", persona="logical").num_ctx for t in ("render", "planner", "judge", "summary", "engine")}
    assert len(ctxs) == 1
