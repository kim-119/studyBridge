"""Phase B6 — 외부 전송(egress) 정책 회귀 테스트 (hermetic).

검증 축
  (a) 정책 OFF(기본)면 어떤 경로도 비루프백 소켓/DNS·OpenAI SDK 클라이언트 생성·Tavily SDK 를 쓰지 않는다.
  (b) 차단 시에도 각 라우트/함수의 응답 계약 필드가 채워지고 비어 있지 않다(로컬 Ollama 스텁으로 대체).
  (c) 마스터 ON + (destination:feature) 허용이면 외부 클라이언트(스텁)가 실제로 사용된다.
  (d) AI_EGRESS_ALLOW 파서는 잘못된 항목을 거부하고, 마스터 OFF 는 허용 목록을 무력화한다.

네트워크 가드: socket.connect / connect_ex / getaddrinfo 를 감싸 비루프백 목적지를 기록·거부한다.
루프백이라도 운영 서비스 포트(8000 FastAPI, 11434/11435 Ollama, 6379 Redis)는 기록·거부한다(테스트가 운영을 건드리지 않음).
"""
from __future__ import annotations

import asyncio
import json
import socket
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# 무거운/부수효과 import 는 가드 설치 전에 끝낸다(qwen_service 는 import 시 로컬 vLLM용 OpenAI SDK 객체를 만든다).
import main  # noqa: F401
from app.core import egress_policy as EP
from app.services import openai_client as OC
from app.services import ollama_client as OL
from app.services import llm_engine_router as LER
from app.services import material_ai_manager as MAM
from app.services import knowledge_enrichment as KE
from app.services import wikipedia_service as WS
from app.services import tavily_service as TS
from app.services import openalex_service as OAS
from app.services import openalex_live as OAL
from app.services import orchestrator_service as ORCH
from app.services import roadmap_service as RS
from app.services import gpt_verifier as GV
from app.services import ai_pipeline as AP
from app.services import study_action_router as SAR
from app.services import chunk_cache as CC
from app.services import pdf_text_normalizer as PTN
from app.api import study_journal_routes as SJ
from app.api import major_analysis_routes as MA
from app.api import material_legacy_routes as MLR
from app.api import keyword_routes as KR
from app.api import material_classify_routes as MCR
from app.studymate import grounding as SG
from app.vision import answer as VA
from app.vision.config import get_settings as vision_settings

_PROD_LOCAL_PORTS = {8000, 11434, 11435, 6379}
_LOCAL_NAMES = {"localhost", "testserver", "testclient", "ip6-localhost"}


def _is_loopback(host) -> bool:
    h = str(host or "").strip("[]").lower()
    return h in _LOCAL_NAMES or h.startswith("127.") or h == "::1"


class _Guard:
    def __init__(self) -> None:
        self.calls: list = []


@pytest.fixture
def guard(monkeypatch):
    """정책 OFF + 더미 키 + 네트워크/SDK 가드. 테스트는 guard.calls == [] 를 단언한다."""
    g = _Guard()
    for k in ("AI_EXTERNAL_EGRESS_ENABLED", "AI_EGRESS_ALLOW", "STUDY_JOURNAL_LOCAL_JUDGE_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    EP.reset_counters_for_tests()
    # 키가 있어도 정책만으로 막히는지 보기 위해 더미 키를 심는다(실제 키는 쓰지 않는다).
    for mod in (OC, MAM, RS, GV, main):
        monkeypatch.setattr(mod, "OPENAI_API_KEY", "sk-test-dummy-not-a-key", raising=False)
    import app.core.config as CFG
    monkeypatch.setattr(CFG, "OPENAI_API_KEY", "sk-test-dummy-not-a-key", raising=False)
    monkeypatch.setattr(TS, "TAVILY_API_KEY", "tvly-test-dummy", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-dummy")
    monkeypatch.setenv("OPENALEX_ENABLED", "true")
    monkeypatch.setattr(OC, "_sync_client", None)
    monkeypatch.setattr(OC, "_async_client", None)
    monkeypatch.setattr(CC, "CACHE_BACKEND", "memory")
    KE.clear_cache()

    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_gai = socket.getaddrinfo

    def _check(address):
        if not isinstance(address, tuple):
            return True
        host, port = address[0], address[1] if len(address) > 1 else None
        if not _is_loopback(host):
            g.calls.append(("connect", str(host), port))
            return False
        if port in _PROD_LOCAL_PORTS:
            g.calls.append(("prod_local", str(host), port))
            return False
        return True

    def connect(self, address):
        if not _check(address):
            raise ConnectionRefusedError("egress blocked by test guard")
        return real_connect(self, address)

    def connect_ex(self, address):
        if not _check(address):
            return 111
        return real_connect_ex(self, address)

    def getaddrinfo(host, *a, **k):
        if host is not None and not _is_loopback(host):
            g.calls.append(("dns", str(host)))
            raise socket.gaierror("egress blocked by test guard")
        return real_gai(host, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)

    import openai

    class _NoOpenAI:
        def __init__(self, *a, **k):
            g.calls.append(("openai_sdk_client",))
            raise AssertionError("OpenAI SDK client constructed")

    monkeypatch.setattr(openai, "OpenAI", _NoOpenAI)
    monkeypatch.setattr(openai, "AsyncOpenAI", _NoOpenAI)

    fake_tavily = types.ModuleType("tavily")

    class _NoTavily:
        def __init__(self, *a, **k):
            g.calls.append(("tavily_sdk_client",))
            raise AssertionError("Tavily client constructed")

    fake_tavily.TavilyClient = _NoTavily
    monkeypatch.setitem(sys.modules, "tavily", fake_tavily)
    return g


def _allow(monkeypatch, spec: str) -> None:
    monkeypatch.setenv("AI_EXTERNAL_EGRESS_ENABLED", "true")
    monkeypatch.setenv("AI_EGRESS_ALLOW", spec)


class _FakeOpenAI:
    """허용 경로 확인용 OpenAI SDK 스텁(네트워크 없음). 생성/호출을 기록한다."""
    instances: list = []

    def __init__(self, *a, content: str = "외부 응답 본문", **k):
        self.calls: list = []
        self._content = content
        _FakeOpenAI.instances.append(self)
        outer = self

        class _Comp:
            def create(self_inner, **kw):
                outer.calls.append(kw)
                msg = types.SimpleNamespace(content=outer._content)
                return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=None,
                                             model=kw.get("model"))

        self.chat = types.SimpleNamespace(completions=_Comp())


def _install_fake_openai(monkeypatch, content: str = "외부 응답 본문"):
    import openai
    _FakeOpenAI.instances = []

    def factory(*a, **k):
        return _FakeOpenAI(content=content)

    monkeypatch.setattr(openai, "OpenAI", factory)
    monkeypatch.setattr(OC, "_sync_client", None)
    return _FakeOpenAI.instances


def _stub_local(monkeypatch, responder):
    """로컬 Ollama 스텁: ask_ollama / is_ollama_available / call_primary_llm 을 responder(system, user, **kw) 로."""
    seen: list = []

    def ask(system_prompt, user_prompt, **kw):
        seen.append({"system": system_prompt, "user": user_prompt, **kw})
        return responder(system_prompt, user_prompt, **kw)

    def primary(system_prompt, user_prompt, max_tokens=None, temperature=None, knowledge_level=None,
                allow_external=True, feature="llm_router_fallback"):
        seen.append({"system": system_prompt, "user": user_prompt, "allow_external": allow_external,
                     "primary": True})
        return responder(system_prompt, user_prompt)

    monkeypatch.setattr(OL, "ask_ollama", ask)
    monkeypatch.setattr(OL, "is_ollama_available", lambda: True)
    monkeypatch.setattr(LER, "call_primary_llm", primary)
    return seen


# ════════════════════════════════════════════════════════════════════════════
# (d) 정책 파서 / 판정
# ════════════════════════════════════════════════════════════════════════════
def test_allowlist_parser_rejects_malformed_entries():
    allow, rejected = EP.parse_allowlist(
        "openai:vision_answer, wikipedia:keyword_define ,bogus,openai:,:feat,*:*,openai:Bad-Name,"
        "ftp:thing,tavily:a:b,openalex:*,  ,openai:x y")
    assert allow == frozenset({("openai", "vision_answer"), ("wikipedia", "keyword_define"), ("openalex", "*")})
    assert rejected == [3, 4, 5, 6, 7, 8, 9, 12]


def test_master_off_overrides_allowlist(monkeypatch):
    monkeypatch.delenv("AI_EXTERNAL_EGRESS_ENABLED", raising=False)
    monkeypatch.setenv("AI_EGRESS_ALLOW", "openai:*,wikipedia:*,tavily:*,openalex:*")
    EP.reset_counters_for_tests()
    for d in ("openai", "wikipedia", "tavily", "openalex"):
        assert EP.egress_allowed(d, "anything") is False
        with pytest.raises(EP.EgressBlocked):
            EP.require_egress(d, "anything")
    monkeypatch.setenv("AI_EXTERNAL_EGRESS_ENABLED", "false")
    assert EP.egress_allowed("openai", "vision_answer") is False


def test_master_on_requires_exact_feature_or_wildcard(monkeypatch):
    _allow(monkeypatch, "openai:vision_answer,wikipedia:*")
    assert EP.egress_allowed("openai", "vision_answer") is True
    assert EP.egress_allowed("openai", "study_journal_judge") is False
    assert EP.egress_allowed("openai", None) is False           # unspecified → wildcard 만 허용
    assert EP.egress_allowed("wikipedia", None) is True          # wildcard
    assert EP.egress_allowed("tavily", "web_search") is False
    assert EP.egress_allowed("s3", "anything") is False          # 알 수 없는 destination
    snap = EP.snapshot()
    assert snap["masterEnabled"] is True and "openai:vision_answer" in snap["allow"]
    assert snap["decisions"]["openai:vision_answer:ALLOW"] >= 1


def test_policy_logs_no_content(monkeypatch, caplog):
    import logging
    EP.reset_counters_for_tests()
    with caplog.at_level(logging.DEBUG, logger="studybridge.egress"):
        EP.egress_allowed("openai", "material_feedback")
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "destination=openai feature=material_feedback decision=BLOCK" in text


# ════════════════════════════════════════════════════════════════════════════
# OpenAI 5 지점 (openai_client / main / material_ai_manager / roadmap_service / gpt_verifier)
# ════════════════════════════════════════════════════════════════════════════
def test_openai_client_blocked_without_network(guard):
    assert OC.key_configured() is True
    assert OC.is_enabled("material_feedback") is False
    with pytest.raises(EP.EgressBlocked):
        OC.get_sync_client("material_feedback")
    with pytest.raises(EP.EgressBlocked):
        OC.get_async_client("vision_answer")
    out = OC.chat_sync("s", "u", feature="material_feedback")
    assert out.startswith("[GPT 차단]")
    assert asyncio.run(OC.chat_async("s", "u", feature="x")).startswith("[GPT")
    with pytest.raises(RuntimeError):
        OC.embed_sync("t")
    assert guard.calls == []


def test_openai_client_used_when_allowlisted(guard, monkeypatch):
    _allow(monkeypatch, "openai:material_feedback")
    inst = _install_fake_openai(monkeypatch, "허용된 외부 응답")
    assert OC.chat_sync("s", "u", feature="material_feedback") == "허용된 외부 응답"
    assert len(inst) == 1 and inst[0].calls[0]["messages"][1]["content"] == "u"
    # 다른 feature 는 여전히 차단
    assert OC.chat_sync("s", "u", feature="material_quiz").startswith("[GPT 차단]")
    assert guard.calls == []


def test_main_openai_paths_blocked(guard, monkeypatch):
    assert main.openai_client is None
    assert main._openai_client_for("chat_fallback") is None
    assert main._call_openai("s", "u", feature="quiz_generate") is None
    monkeypatch.setattr(main, "_call_ollama", lambda *a, **k: '[{"question":"로컬 문항"}]')
    assert main._call_quiz_llm("s", "u", 3) == '[{"question":"로컬 문항"}]'
    assert guard.calls == []


def test_main_openai_used_when_allowlisted(guard, monkeypatch):
    _allow(monkeypatch, "openai:quiz_generate")
    inst = _install_fake_openai(monkeypatch, "외부 퀴즈")
    called = []
    monkeypatch.setattr(main, "_call_ollama", lambda *a, **k: called.append(1) or "로컬")
    assert main._call_quiz_llm("s", "u", 3) == "외부 퀴즈"
    assert inst and not called and guard.calls == []


def test_material_ai_manager_gpt_blocked_and_local_used(guard, monkeypatch):
    seen = _stub_local(monkeypatch, lambda s, u, **k: "로컬 결과 본문")
    assert MAM._call_gpt("s", "u", feature="material_quiz").startswith("[GPT")
    text, prov = MAM._gpt_or_local("s", "u", 500, feature="material_quiz")
    assert (text, prov) == ("로컬 결과 본문", "ollama_qwen")
    assert seen and all(c.get("allow_external") is False for c in seen if c.get("primary"))
    q = MAM.generate_quiz("문서", "본문 " * 50)
    assert q["quiz"] == "로컬 결과 본문"
    r = MAM.generate_roadmap("문서", "본문 " * 50)
    assert r["roadmap"] == "로컬 결과 본문"
    a = MAM.answer_from_pdf("질문", [{"chunk_index": 0, "content": "자료"}])
    assert a["gpt_raw"] == "로컬 결과 본문"
    assert guard.calls == []


def test_roadmap_service_and_gpt_verifier_blocked(guard):
    assert RS.generate_roadmap_with_gpt("문서", "본문", 4, "보통", "목표", "학사") is None
    v = asyncio.run(GV.verify_answer_async("q", "a", "학사", "친절_설명형"))
    assert v["is_valid"] is True and any("외부 전송 정책" in i for i in v["issues"])
    assert asyncio.run(GV.generate_corrected_answer_async("q", "원본", "제안", "학사", "x")) == "원본"
    assert guard.calls == []


def test_vision_answer_blocked_then_allowed(guard, monkeypatch):
    monkeypatch.setenv("VISION_ANSWER_PROVIDER", "openai")
    s = vision_settings()
    with pytest.raises(Exception) as ei:
        asyncio.run(VA.generate_answer({"readableText": "화면"}, "질문", s, timeout=5))
    assert getattr(ei.value, "code", None) == "VISION_ANSWER_DISABLED"
    assert guard.calls == []

    _allow(monkeypatch, "openai:vision_answer")
    fake_calls = []

    class _AsyncFake:
        def with_options(self, **kw):
            return self

        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                async def create(**kw):
                    fake_calls.append(kw)
                    msg = types.SimpleNamespace(content="외부 답변")
                    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)],
                                                 model="gpt-x", usage=None)

    monkeypatch.setattr(OC, "_async_client", _AsyncFake())
    ans, meta = asyncio.run(VA.generate_answer({"readableText": "[전화번호]"}, "질문", s, timeout=5))
    assert ans == "외부 답변" and fake_calls
    sent = json.dumps(fake_calls[0]["messages"], ensure_ascii=False)
    # PII 마스킹은 라우터(mask_obj/mask_text)에서 이 함수 전에 적용된다 — 라우트 단위 검증은
    # tests/test_vision_api.py::test_openai_request_has_no_image_and_masks_pii(정책 허용 env 추가) 가 담당.
    assert "image_url" not in sent and "<screen_extraction>" in sent
    assert guard.calls == []


# ════════════════════════════════════════════════════════════════════════════
# Tavily 2 / Wikipedia 4 / OpenAlex 2
# ════════════════════════════════════════════════════════════════════════════
def test_search_leaves_blocked(guard):
    assert TS.search_web("질문") == []
    assert WS.search_wikipedia("질문") == []
    assert KE._fetch_wiki("질문", 1.0) == ""
    assert KE._fetch_tavily("질문", 1.0) == ""
    assert KE._tavily_enabled() is False
    assert KE.build_knowledge_context("질문") == ""
    assert ORCH._fetch_wikipedia_context("질문") == ""
    assert asyncio.run(KR._wikipedia_define("키워드")) is None
    r = OAS.search("질문", "박사")
    assert r.skipped and r.skip_reason == "egress_policy_blocked"
    o = OAL.enrich("최신 연구 동향 논문 분석", profile_name="live")
    assert o.outcome == "skipped" and o.status["status"] == "disabled"
    with pytest.raises(EP.EgressBlocked):
        OAL._client.search("x", OAL.live_profile())
    assert guard.calls == []


def test_search_leaves_used_when_allowlisted(guard, monkeypatch):
    _allow(monkeypatch, "wikipedia:wikipedia_search,wikipedia:knowledge_enrichment,tavily:web_search,"
                        "openalex:openalex_search,wikipedia:keyword_define")
    used = []

    class _Resp:
        status_code = 200

        def __init__(self, data):
            self._d = data

        def raise_for_status(self):
            return None

        def json(self):
            return self._d

    monkeypatch.setattr(WS.requests, "get",
                        lambda *a, **k: used.append("wiki_requests") or _Resp(
                            {"query": {"search": [{"pageid": 1, "title": "T", "snippet": "S"}]}}))
    assert WS.search_wikipedia("q")[0]["title"] == "T"

    class _UrlResp:
        def __init__(self, data):
            self._b = json.dumps(data).encode()

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    pages = iter([{"query": {"search": [{"title": "T"}]}},
                  {"query": {"pages": {"1": {"title": "T", "extract": "위키 본문"}}}}])
    monkeypatch.setattr(KE.urllib.request, "urlopen",
                        lambda *a, **k: used.append("wiki_urlopen") or _UrlResp(next(pages)))
    assert "위키 본문" in KE._fetch_wiki("q", 1.0)

    class _Tav:
        def __init__(self, *a, **k):
            used.append("tavily_sdk")

        def search(self, **k):
            return {"results": [{"title": "t", "url": "u", "content": "c", "score": 0.5}]}

    sys.modules["tavily"].TavilyClient = _Tav
    assert TS.search_web("q")[0]["content"] == "c"

    import httpx

    class _HC:
        def __init__(self, *a, **k):
            used.append("openalex_httpx")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return _Resp({"results": [{"display_name": "W", "publication_year": 2024}]})

    monkeypatch.setattr(httpx, "Client", _HC)
    r = OAS.search("질문", "박사")
    assert not r.skipped and r.works and r.works[0].title == "W"

    class _AC:
        def __init__(self, *a, **k):
            used.append("keyword_wiki_httpx")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _Resp({"title": "K", "extract": "정의 본문", "content_urls": {"desktop": {"page": "p"}}})

    monkeypatch.setattr(KR.httpx, "AsyncClient", _AC)
    assert asyncio.run(KR._wikipedia_define("K"))["extract"] == "정의 본문"
    assert used == ["wiki_requests", "wiki_urlopen", "wiki_urlopen", "tavily_sdk", "openalex_httpx",
                    "keyword_wiki_httpx"]
    assert guard.calls == []


def test_multichat_grounding_blocked_returns_local_empty(guard):
    cache: dict = {}
    for lvl in ("BACHELOR", "MASTER", "DOCTOR", "EXPERT"):
        assert ORCH._build_level_grounding("TCP 혼잡제어", lvl, cache) == ""
    assert ORCH._build_knowledge_context("TCP 혼잡제어") == ""
    assert ORCH._build_gpt_brief("TCP") == ""
    for src in ("wiki", "tavily", "gpt"):
        assert SG._fetch(src, "TCP") == ""
    assert guard.calls == []


# ════════════════════════════════════════════════════════════════════════════
# 라우트 (b): 차단 시 로컬로 계약 유지
# ════════════════════════════════════════════════════════════════════════════
def _app(*routers) -> TestClient:
    app = FastAPI()
    for r in routers:
        app.include_router(r)
    return TestClient(app)


_SJ_CTX = {"title": "객체지향 프로그래밍", "keywords": ["클래스", "객체", "상속"],
           "chunks": ["클래스는 객체를 만들기 위한 설계도이며 상속으로 재사용한다."],
           "max_similarity": 0.81, "has_context": True}


def _verdict(**over):
    v = {"category": "PDF_CONCEPT_SUMMARY", "relationType": "DIRECT", "relationPath": "OOP → 클래스",
         "studyRelated": True, "pdfGrounded": True, "conceptExpanded": False,
         "reason": "자료의 핵심 개념을 정리했습니다.", "decision": "ACCEPT", "confidence": 0.9,
         "suggestion": None}
    v.update(over)
    return json.dumps(v, ensure_ascii=False)


def test_study_journal_local_judge_accept_when_openai_blocked(guard, monkeypatch):
    monkeypatch.setattr(SJ, "_gather_pdf_context", lambda mid, memo: dict(_SJ_CTX))
    seen = _stub_local(monkeypatch, lambda s, u, **k: _verdict())
    c = _app(SJ.router)
    r = c.post("/api/ai/study-journal/validate",
               json={"materialId": 7, "title": "객체지향 프로그래밍", "memoText": "클래스와 객체의 차이를 정리했다."})
    d = r.json()
    assert r.status_code == 200 and d["decision"] == "ACCEPT" and d["relationType"] == "DIRECT"
    assert set(d) == set(SJ.StudyJournalValidateResponse.model_fields)       # 계약 불변(필드 추가 없음)
    call = seen[0]
    assert call["think"] is False and call["temperature"] == 0.0
    assert isinstance(call["format"], dict) and call["format"]["properties"]["decision"]["enum"]
    assert guard.calls == []


@pytest.mark.parametrize("local,expected", [
    (_verdict(decision="BLOCK", category="OFF_TOPIC"), "REQUEST_REVISION"),      # BLOCK 은 욕설/광고만
    (_verdict(decision="ACCEPT", relationType="SAME_TERM_DIFFERENT_CONTEXT"), "REQUEST_REVISION"),
    (_verdict(decision="ACCEPT", relationPath=None), "REQUEST_REVISION"),
    (_verdict(decision="BLOCK", category="ADVERTISEMENT"), "BLOCK"),
    ("not json at all", "REQUEST_REVISION"),
    ("현재 Ollama 서버(http://x)에 연결할 수 없습니다.", "REQUEST_REVISION"),
])
def test_study_journal_local_judge_post_guards(guard, monkeypatch, local, expected):
    monkeypatch.setattr(SJ, "_gather_pdf_context", lambda mid, memo: dict(_SJ_CTX))
    _stub_local(monkeypatch, lambda s, u, **k: local)
    d = _app(SJ.router).post("/api/ai/study-journal/validate",
                             json={"materialId": 7, "title": "OOP", "memoText": "상속 개념을 정리했다."}).json()
    assert d["decision"] == expected and d["reason"]
    assert guard.calls == []


def test_study_journal_local_judge_disabled_is_conservative(guard, monkeypatch):
    monkeypatch.setenv("STUDY_JOURNAL_LOCAL_JUDGE_ENABLED", "false")
    monkeypatch.setattr(SJ, "_gather_pdf_context", lambda mid, memo: dict(_SJ_CTX))
    seen = _stub_local(monkeypatch, lambda s, u, **k: _verdict())
    d = _app(SJ.router).post("/api/ai/study-journal/validate",
                             json={"materialId": 7, "title": "OOP", "memoText": "클래스와 객체를 정리했다."}).json()
    assert d["decision"] == "REQUEST_REVISION" and not seen and guard.calls == []


def test_study_journal_uses_openai_when_allowlisted(guard, monkeypatch):
    _allow(monkeypatch, "openai:study_journal_judge")
    inst = _install_fake_openai(monkeypatch, _verdict(relationType="COMPARISON", relationPath="절차 ↔ 객체"))
    monkeypatch.setattr(SJ, "_gather_pdf_context", lambda mid, memo: dict(_SJ_CTX))
    seen = _stub_local(monkeypatch, lambda s, u, **k: _verdict(decision="REQUEST_REVISION"))
    assert SJ.local_judge_enabled() is False
    d = _app(SJ.router).post("/api/ai/study-journal/validate",
                             json={"materialId": 7, "title": "OOP", "memoText": "절차지향과 객체지향을 비교했다."}).json()
    assert d["decision"] == "ACCEPT" and d["relationType"] == "COMPARISON"
    assert inst and inst[0].calls and not seen and guard.calls == []


_MA_PAGES = [
    {"page": 1, "text": "Stack is a LIFO data structure. push adds an item and pop removes the top item. " * 3},
    {"page": 2, "text": "Queue is a FIFO structure used for BFS traversal and scheduling of tasks. " * 3},
    {"page": 3, "text": "Binary search tree keeps left child smaller than parent and right child larger. " * 3},
]


def _ma_note_json(pages=(1, 2)):
    return json.dumps({
        "coreObject": "Stack", "coreObjectLabel": "스택", "documentOverview": "자료구조 스택과 큐를 설명한다.",
        "keywords": ["스택", "큐"], "coreContents": ["스택은 LIFO 이다.", "큐는 FIFO 이다."],
        "studyPoints": ["push/pop 동작"], "aiStudyQuestions": ["스택과 큐의 차이는?"],
        "pageSummaries": [{"page": p, "title": f"p{p}", "pageOverview": f"페이지 {p} 개요",
                           "keyConcepts": ["개념"], "conceptExplanations": [{"term": "개념", "explanation": "설명"}],
                           "examples": ["예시"], "summaryBullets": ["요점"], "studyFocus": "초점"} for p in pages],
    }, ensure_ascii=False)


_MA_KEYS = {"materialId", "mode", "domain", "domainLabel", "coreObject", "coreObjectLabel", "disclaimer",
            "documentOverview", "keywords", "coreContents", "detailedCoreContents", "pageSummaries",
            "studyPoints", "aiStudyQuestions", "wikiSummaries", "limitations"}


def test_major_analysis_local_note_when_openai_blocked(guard, monkeypatch):
    def responder(s, u, **k):
        if "[페이지 3 내용" in u:
            return json.dumps({"page": 3, "title": "BST", "pageOverview": "이진 탐색 트리",
                               "summaryBullets": ["왼쪽 작음"], "keyConcepts": ["BST"]}, ensure_ascii=False)
        return _ma_note_json()
    seen = _stub_local(monkeypatch, responder)
    d = _app(MA.router).post("/api/ai/major-analysis/note",
                             json={"materialId": 1, "materialTitle": "자료구조", "pageTexts": _MA_PAGES}).json()
    assert _MA_KEYS <= set(d)
    assert d["documentOverview"] == "자료구조 스택과 큐를 설명한다."
    assert [p["page"] for p in d["pageSummaries"]] == [1, 2, 3]
    assert all(p["detectedTextSource"] == "TEXT" and p["pageOverview"] for p in d["pageSummaries"])
    assert all(c["think"] is False and c["format"] == "json" for c in seen)
    assert guard.calls == []


def test_major_analysis_prompt_is_bounded(guard, monkeypatch):
    big = [{"page": i, "text": ("Graph traversal uses adjacency lists and visited sets. " * 40)} for i in range(1, 41)]
    seen = _stub_local(monkeypatch, lambda s, u, **k: _ma_note_json(pages=(1,)))
    d = _app(MA.router).post("/api/ai/major-analysis/note",
                             json={"materialId": 2, "materialTitle": "그래프", "pageTexts": big}).json()
    batch = seen[0]["user"]
    sent = "Graph traversal uses adjacency lists and visited sets. "
    # 입력 40쪽×2200자 중 프롬프트에 실린 본문(문장 단위 셈이라 페이지당 부분 문장 1개 오차 허용)
    page_chars = batch.count("Graph traversal") * len(sent)
    assert page_chars <= MA._LOCAL_MAX_INPUT_CHARS + len(sent) * MA._LOCAL_MAX_PAGES and len(batch) < 9000
    assert batch.count("[페이지 ") <= MA._LOCAL_MAX_PAGES
    assert seen[0]["max_tokens"] <= MA._LOCAL_MAX_TOKENS
    assert len(d["pageSummaries"]) == 40 and all(p["pageOverview"] for p in d["pageSummaries"])
    assert "충분하지 않습니다" not in d["documentOverview"]
    assert guard.calls == []


def test_major_analysis_llm_failure_returns_extractive_not_generic(guard, monkeypatch):
    _stub_local(monkeypatch, lambda s, u, **k: "현재 Ollama 서버(http://127.0.0.1:9)에 연결할 수 없습니다.")
    d = _app(MA.router).post("/api/ai/major-analysis/note",
                             json={"materialId": 3, "materialTitle": "자료구조", "pageTexts": _MA_PAGES}).json()
    assert _MA_KEYS <= set(d)
    assert "충분하지 않습니다" not in d["documentOverview"] and "Stack" in d["documentOverview"]
    assert d["keywords"] and d["coreContents"] and len(d["pageSummaries"]) == 3
    assert all(p["detectedTextSource"] == "TEXT" and p["title"] != "내용 식별 제한" for p in d["pageSummaries"])
    assert guard.calls == []


def test_major_analysis_s3_local_ocr_instead_of_gpt(guard, monkeypatch):
    import fitz
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Heap is a complete binary tree used for priority queues and heap sort.", fontsize=11)
    doc.new_page()  # 2페이지: 텍스트 없음(이미지 페이지 대용) → 로컬 OCR 경로
    pdf = doc.tobytes()
    doc.close()
    import app.services.s3_pdf_loader as S3
    monkeypatch.setattr(S3, "load_pdf_bytes_from_s3", lambda key: pdf)
    ocr_calls = []
    monkeypatch.setattr(PTN, "_default_ocr_fn",
                        lambda: (lambda img, n: ocr_calls.append(n) or "Heapify restores the heap property "
                                                                       "by sifting nodes down the tree."))
    monkeypatch.setattr(PTN, "DEF_TEXT_MIN", lambda: 40)
    _stub_local(monkeypatch, lambda s, u, **k: _ma_note_json(pages=(1, 2)))
    d = _app(MA.router).post("/api/ai/major-analysis/note",
                             json={"materialId": 4, "materialTitle": "힙", "s3Key": "materials/x.pdf"}).json()
    assert ocr_calls == [2]
    srcs = {p["page"]: p["detectedTextSource"] for p in d["pageSummaries"]}
    assert srcs == {1: "TEXT", 2: "OCR"}
    assert guard.calls == []


def test_summary_with_s3_url_falls_back_to_local_text(guard, monkeypatch):
    import app.services.s3_pdf_loader as S3
    img_calls = []
    monkeypatch.setattr(S3, "load_pdf_images_from_s3", lambda url: img_calls.append(url) or ["data:image/png;base64,AA"])
    md = ("## 문서 개요\n이 문서는 운영체제의 프로세스 스케줄링을 설명한다.\n"
          "## 핵심 키워드\n프로세스, 스케줄링, 문맥교환\n"
          "## 세부 핵심 내용\n### 스케줄링\n- FCFS 와 RR 을 비교한다.\n"
          "## 학습 포인트\n- 문맥교환 비용\n## AI 학습 질문\n- RR 의 단점은?")
    _stub_local(monkeypatch, lambda s, u, **k: md)
    text = "운영체제 프로세스 스케줄링 FCFS RR 문맥교환 " * 30
    d = _app(MLR.router).post("/api/ai/summary", json={"text": text, "document_title": "OS", "material_id": 11,
                                                       "s3_file_url": "https://bucket.s3/x.pdf"}).json()
    assert d["success"] is True and d["summary"].strip() and d["overview"]
    assert img_calls == []          # 비전 경로 미허용 → 이미지 추출/전송 자체를 하지 않음
    assert guard.calls == []


def test_feedback_uses_local_llm_not_gpt_placeholder(guard, monkeypatch):
    _stub_local(monkeypatch, lambda s, u, **k: "핵심 개념을 잘 정리했습니다. 예시를 더 추가해 보세요.")
    d = _app(MLR.router).post("/api/ai/feedback", json={"content": "프로세스와 스레드의 차이 정리 " * 30}).json()
    assert d["success"] is True and d["feedback"].startswith("핵심 개념") and "[GPT" not in d["feedback"]
    assert d["metadata"]["provider"] == "ollama_qwen"
    assert guard.calls == []


def test_feedback_when_everything_fails_is_failure_contract(guard, monkeypatch):
    _stub_local(monkeypatch, lambda s, u, **k: "[Ollama 미응답]")
    d = _app(MLR.router).post("/api/ai/feedback", json={"content": "프로세스와 스레드 " * 40}).json()
    assert d["success"] is False and d["errorCode"] == "AI_UNAVAILABLE"
    assert guard.calls == []


def test_feedback_uses_gpt_when_allowlisted(guard, monkeypatch):
    _allow(monkeypatch, "openai:material_feedback")
    inst = _install_fake_openai(monkeypatch, "외부 피드백")
    seen = _stub_local(monkeypatch, lambda s, u, **k: "로컬")
    d = _app(MLR.router).post("/api/ai/feedback", json={"content": "프로세스와 스레드 " * 40}).json()
    assert d["feedback"] == "외부 피드백" and d["metadata"]["provider"] == "openai_gpt"
    assert inst and not seen and guard.calls == []


def test_keyword_define_local_only_when_blocked(guard, monkeypatch):
    j = json.dumps({"name": "TCP", "shortDefinition": "연결 지향 프로토콜", "detailedDefinition": "상세",
                    "importance": "중요", "examples": ["웹"], "relatedConcepts": ["UDP"]}, ensure_ascii=False)
    _stub_local(monkeypatch, lambda s, u, **k: j)
    c = _app(KR.router)
    for source in ("auto", "wikipedia", "gpt"):
        d = c.post("/api/ai/keyword/define", json={"keyword": "TCP", "source": source}).json()
        assert d["success"] is True and d["shortDefinition"] == "연결 지향 프로토콜"
        assert d["sourceUsed"] == "GPT" and d["wikiUrl"] is None
    assert guard.calls == []


def test_roadmap_review_planner_classify_paths_local(guard, monkeypatch):
    seen = _stub_local(monkeypatch, lambda s, u, **k: '{"type": "STUDY_PDF", "confidence": 0.8, "reason": "강의 자료"}')
    # roadmap/generate 품질 보정 단계(GPT 우선) → 로컬
    out = SAR.refiner_llm("s", "u")
    assert out.startswith("{") and json.loads(out)["type"] == "STUDY_PDF"
    # review/planner 2단계 파이프라인 → OpenAI 보강 생략, 로컬 초안 채택
    got = AP.generate_structured(draft_system="d", draft_user="u", refine_system="r",
                                 refine_user_builder=lambda d: "ru", validator=lambda d: "type" in d,
                                 feature="review_feedback")
    assert got["type"] == "STUDY_PDF"
    assert AP.repair_to_valid(repair_system="r", repair_user="u", validator=lambda d: "type" in d,
                              feature="review_note")["type"] == "STUDY_PDF"
    # material/classify 검증자(GPT 우선) → 로컬
    req = MCR.ClassifyRequest(file_name="a.pdf", extracted_text="강의 자료 본문")
    refined = MCR._openai_refine(req, {"type": "STUDY_PDF", "confidence": 0.6, "reason": "r"})
    assert refined and refined["type"] == "STUDY_PDF"
    # planner assist: 로컬 성공이면 그대로
    from app.api import planner_ai_routes as PL
    assert PL._llm("s", "u", 100).startswith("{")
    assert seen and guard.calls == []


def test_debate_socratic_never_surface_gpt_placeholder(guard, monkeypatch):
    from app.services import debate_mode_service as DM, socratic_mode_service as SM
    import app.services.qwen_service as QS
    monkeypatch.setattr(QS, "ask_qwen", lambda *a, **k: "")
    assert not DM._call_llm("s", "u").startswith("[GPT")
    assert not SM._call_llm("s", "u").startswith("[GPT")
    assert guard.calls == []


def test_guard_itself_detects_real_egress(guard):
    """가드가 실제로 동작하는지(위 테스트들의 'calls == []' 가 공허하지 않음) 확인."""
    import requests
    import urllib.request
    with pytest.raises(Exception):
        requests.get("https://api.openai.com/v1/models", timeout=2)
    with pytest.raises(Exception):
        urllib.request.urlopen("https://ko.wikipedia.org/w/api.php", timeout=2)
    with pytest.raises(Exception):
        socket.create_connection(("127.0.0.1", 11434), timeout=1)
    kinds = {c[0] for c in guard.calls}
    hosts = {c[1] for c in guard.calls}
    assert kinds == {"dns", "prod_local"} and {"api.openai.com", "ko.wikipedia.org"} <= hosts
