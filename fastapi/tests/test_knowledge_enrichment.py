"""
knowledge_enrichment 단위 테스트.

build_knowledge_context(query): 한국어 위키 + (키 있을 때)Tavily 웹검색을 단일 [참고자료]
블록으로 합친다. graceful: Tavily 없음/실패→위키만, 위키도 없음→빈문자열. 캐시. timeout.
하드코딩 주제어 금지(content-free): 특정 도메인 단어를 로직에 박지 않는다.
"""
import pytest

from app.services import knowledge_enrichment as ke


@pytest.fixture(autouse=True)
def _clear_cache_and_key(monkeypatch):
    ke.clear_cache()
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)


def test_wiki_only_when_no_tavily_key(monkeypatch):
    monkeypatch.setattr(ke, "_fetch_wiki", lambda q, timeout: "위키요약 본문")
    monkeypatch.setattr(ke, "_fetch_tavily", lambda q, timeout: pytest.fail("Tavily는 키 없을 때 호출되면 안 됨"))
    out = ke.build_knowledge_context("아무질문")
    assert "위키요약 본문" in out
    assert "[참고자료]" in out


def test_combines_wiki_and_tavily_when_key_present(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    monkeypatch.setattr(ke, "_fetch_wiki", lambda q, timeout: "위키부분")
    monkeypatch.setattr(ke, "_fetch_tavily", lambda q, timeout: "웹부분")
    out = ke.build_knowledge_context("질문")
    assert "위키부분" in out and "웹부분" in out


def test_tavily_failure_falls_back_to_wiki(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    monkeypatch.setattr(ke, "_fetch_wiki", lambda q, timeout: "위키부분")
    def _boom(q, timeout):
        raise RuntimeError("network")
    monkeypatch.setattr(ke, "_fetch_tavily", _boom)
    out = ke.build_knowledge_context("질문")
    assert "위키부분" in out  # Tavily 실패해도 위키는 살아있다


def test_empty_when_no_sources(monkeypatch):
    monkeypatch.setattr(ke, "_fetch_wiki", lambda q, timeout: "")
    out = ke.build_knowledge_context("질문")
    assert out == ""


def test_wiki_failure_is_graceful(monkeypatch):
    def _boom(q, timeout):
        raise RuntimeError("wiki down")
    monkeypatch.setattr(ke, "_fetch_wiki", _boom)
    out = ke.build_knowledge_context("질문")
    assert out == ""  # 예외가 위로 새지 않는다


def test_blank_query_returns_empty():
    assert ke.build_knowledge_context("") == ""
    assert ke.build_knowledge_context("   ") == ""


def test_result_is_cached(monkeypatch):
    calls = {"n": 0}
    def _wiki(q, timeout):
        calls["n"] += 1
        return "캐시본문"
    monkeypatch.setattr(ke, "_fetch_wiki", _wiki)
    a = ke.build_knowledge_context("같은질문")
    b = ke.build_knowledge_context("같은질문")
    assert a == b
    assert calls["n"] == 1  # 두 번째는 캐시


def test_no_hardcoded_domain_terms():
    # 모듈 소스에 특정 도메인 주제어(반복 유발)를 박지 않았는지 가벼운 가드.
    # 단어 경계로 검사(파이썬 str.join 같은 우연한 부분일치 제외).
    import inspect
    import re
    src = inspect.getsource(ke).lower()
    for term in ("grpc", "sql", "kubernetes", "polymorphism"):
        assert not re.search(rf"\b{re.escape(term)}\b", src), f"하드코딩 주제어 '{term}' 발견"
