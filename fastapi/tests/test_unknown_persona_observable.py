"""UNKNOWN 성격/지식수준은 조용히 friendly/bachelor 로 붕괴하지 않는다."""
import logging

from app.studymate.profile_contract import canonicalize_agent, resolve_knowledge, resolve_personality


def test_unknown_personality_is_flagged(caplog):
    with caplog.at_level(logging.WARNING, logger="studybridge.studymate.profile"):
        r = resolve_personality({"personality": "엄격형"})
    assert r.resolved is False and r.fallbackReason == "unknown_personality"
    assert r.key != "friendly" and r.overlay == "엄격형" and r.originalValue == "엄격형"
    assert any("unknown personality" in m for m in caplog.messages)


def test_unknown_knowledge_is_flagged():
    r = resolve_knowledge({"knowledgeLevel": "교수"})
    assert r.resolved is False and r.fallbackReason == "unknown_knowledge_level" and r.originalValue == "교수"


def test_identity_payload_exposes_resolution():
    ca = canonicalize_agent({"agentId": 9, "name": "최교수", "personality": "엄격형", "knowledgeLevel": "교수"}, 0)
    p = ca.identity_payload()
    assert p["personalityResolved"] is False and p["knowledgeLevelResolved"] is False
    assert p["personalityOriginalValue"] == "엄격형" and p["knowledgeLevelFallbackReason"] == "unknown_knowledge_level"


def test_spring_canonical_keys_resolve():
    mapping = {"default": "friendly", "professional": "logical", "friendly": "friendly", "honest": "critical",
               "unique": "creative", "efficient": "concise", "cynical": "sardonic"}
    for style, key in mapping.items():
        r = resolve_personality({"personalityStyle": style})
        assert r.key == key and r.resolved, style


def test_labels_match_frontend_vocabulary_and_critical_ne_sardonic():
    labels = {k: resolve_personality({"personality": k}).label for k in
              ("friendly", "critical", "creative", "concise", "sardonic", "logical")}
    assert labels == {"friendly": "친근함", "critical": "비판형", "creative": "독특함",
                      "concise": "효율적", "sardonic": "냉소적", "logical": "논리형"}
    assert labels["critical"] != labels["sardonic"]


def test_personality_style_field_is_not_dropped_by_schema():
    from app.schemas.multi_chat_schema import MultiChatRequest
    r = MultiChatRequest(message="x", userId=5, agents=[{"agentId": 1, "personalityStyle": "cynical",
                                                         "temperature": 0.55, "goal": "g", "persona": "p"}])
    a = r.agents[0]
    assert a.personalityStyle == "cynical" and a.temperature == 0.55 and a.goal == "g" and r.userId == 5
