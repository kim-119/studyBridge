"""지식수준별 근거(grounding) 정책 테스트.

설계: 생성은 항상 Ollama, 근거 소스만 레벨별 차등.
  입문(INTRO)    : 없음
  학사(BACHELOR) : 위키
  석사(MASTER)   : 위키 + Tavily
  박사(DOCTOR)   : 위키 + GPT
  전문가(EXPERT) : GPT + Tavily
같은 메시지 내에서 각 소스는 1회만 호출(cache)된다.
"""
from app.services import orchestrator_service as orch


def test_level_grounding_source_mapping():
    m = orch._LEVEL_GROUNDING_SOURCES
    assert m["INTRO"] == ()
    assert m["BACHELOR"] == ("wiki",)
    assert m["MASTER"] == ("wiki", "tavily")
    assert m["DOCTOR"] == ("wiki", "gpt")
    assert m["EXPERT"] == ("gpt", "tavily")


def test_build_level_grounding_uses_expected_sources(monkeypatch):
    calls = []

    def fake_fetch(src, query):
        calls.append(src)
        return f"[{src}]내용"

    monkeypatch.setattr(orch, "_fetch_grounding_source", fake_fetch)

    # 입문: 근거 없음 → 호출 0, 빈 문자열
    calls.clear()
    out = orch._build_level_grounding("q", "INTRO", {})
    assert out == "" and calls == []

    # 박사: 위키 + GPT
    calls.clear()
    out = orch._build_level_grounding("q", "DOCTOR", {})
    assert calls == ["wiki", "gpt"]
    assert "[wiki]내용" in out and "[gpt]내용" in out

    # 전문가: GPT + Tavily
    calls.clear()
    out = orch._build_level_grounding("q", "EXPERT", {})
    assert calls == ["gpt", "tavily"]


def test_build_level_grounding_caches_per_source(monkeypatch):
    calls = []

    def fake_fetch(src, query):
        calls.append(src)
        return f"[{src}]"

    monkeypatch.setattr(orch, "_fetch_grounding_source", fake_fetch)

    cache: dict = {}
    # 석사(위키+Tavily) 두 번 호출해도 캐시로 소스당 1회만
    orch._build_level_grounding("q", "MASTER", cache)
    orch._build_level_grounding("q", "MASTER", cache)
    assert calls == ["wiki", "tavily"]  # 중복 호출 없음


def test_gpt_brief_returns_empty_when_disabled(monkeypatch):
    # OPENAI 키 없으면 GPT 브리핑은 빈 문자열(다른 근거/Ollama로 진행)
    import app.services.openai_client as oc
    monkeypatch.setattr(oc, "is_enabled", lambda: False)
    assert orch._build_gpt_brief("아무 주제") == ""
