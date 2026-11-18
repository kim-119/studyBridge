"""
LLM Intent Router 테스트 (POST /api/ai/intent/route).

LLM 호출 없이 검증 가능한 부분:
  - deterministic fallback 정책 (빈 입력/인사/퀴즈/요약/위협/surface별 기본)
  - enum 정규화 + 위험도↔routeAction 정합성 보정 (_finalize)
  - LLM 응답 mock 시 정상 라우팅
"""
import app.api.intent_router_routes as ir
from app.api.intent_router_routes import (
    IntentContext,
    IntentRouteRequest,
    _fallback_decision,
    _finalize,
    _norm,
    _norm_surface,
    INTENTS,
    RISK_LEVELS,
    ROUTE_ACTIONS,
)


def _final(decision, ctx=None, fallback=True):
    ctx = ctx or IntentContext()
    decision.setdefault("normalizedText", decision.get("normalizedText", ""))
    return _finalize(decision, ctx, fallback_used=fallback)


# ── enum 정규화 ───────────────────────────────────────────────────────────────
def test_norm_handles_case_and_separators():
    assert _norm("learning_question", INTENTS) == "LEARNING_QUESTION"
    assert _norm("quiz-pipeline", ROUTE_ACTIONS) == "QUIZ_PIPELINE"
    assert _norm("allow", RISK_LEVELS) == "ALLOW"
    assert _norm("garbage", INTENTS) is None
    assert _norm(None, RISK_LEVELS) is None


def test_norm_surface_defaults_to_learning_mate():
    assert _norm_surface("archive_chat") == "archive_chat"
    assert _norm_surface("GROUP-STUDY_CHAT") == "group_study_chat"
    assert _norm_surface("nonsense") == "learning_mate"
    assert _norm_surface(None) == "learning_mate"


# ── fallback 정책 ─────────────────────────────────────────────────────────────
def test_fallback_empty_text_clarifies():
    d = _fallback_decision("", "learning_mate", IntentContext())
    assert d["routeAction"] == "CLARIFY"
    assert d["intent"] == "UNKNOWN"
    assert d["directReply"]


def test_fallback_greeting_direct_reply():
    d = _fallback_decision("안녕", "learning_mate", IntentContext())
    assert d["intent"] == "GREETING"
    assert d["routeAction"] == "DIRECT_REPLY"
    assert d["directReply"]


def test_fallback_quiz_request():
    d = _fallback_decision("이 PDF로 객관식 10개 만들어줘", "archive_chat", IntentContext())
    assert d["intent"] == "QUIZ_GENERATION"
    assert d["routeAction"] == "QUIZ_PIPELINE"


def test_fallback_summary_request():
    d = _fallback_decision("이 자료 요약해줘", "archive_chat", IntentContext())
    assert d["routeAction"] == "SUMMARY_PIPELINE"


def test_fallback_threat_blocks():
    d = _fallback_decision("너 죽여버린다", "learning_mate", IntentContext())
    assert d["intent"] == "UNSAFE_THREAT"
    assert d["riskLevel"] == "BLOCK"
    assert d["routeAction"] == "BLOCK"


def test_fallback_surface_defaults():
    assert _fallback_decision("OOP가 뭐야?", "learning_mate", IntentContext())["routeAction"] == "LEARNING_MATE_AGENT"
    assert _fallback_decision("OOP가 뭐야?", "group_study_chat", IntentContext())["routeAction"] == "GROUP_STUDY_AGENT"
    # archive_chat: 자료 컨텍스트 유무로 분기
    assert _fallback_decision("OOP가 뭐야?", "archive_chat", IntentContext())["routeAction"] == "ARCHIVE_AI_AGENT"
    ctx = IntentContext(hasMaterialContext=True)
    assert _fallback_decision("OOP가 뭐야?", "archive_chat", ctx)["routeAction"] == "MATERIAL_QA_AGENT"


# ── _finalize 정합성 보정 ─────────────────────────────────────────────────────
def test_finalize_block_overrides_route_and_clears_direct_reply():
    out = _final({"intent": "UNSAFE_THREAT", "riskLevel": "BLOCK", "routeAction": "LEARNING_MATE_AGENT",
                  "confidence": 0.9, "directReply": "leak", "reason": "x", "normalizedText": "t"})
    assert out.routeAction == "BLOCK"
    assert out.directReply is None
    assert out.warningMessage  # 자동 채워짐


def test_finalize_unsafe_allow_is_upgraded_to_warn():
    out = _final({"intent": "UNSAFE_PROFANITY", "riskLevel": "ALLOW", "routeAction": "LEARNING_MATE_AGENT",
                  "confidence": 0.5, "reason": "x", "normalizedText": "t"})
    assert out.riskLevel == "WARN"
    assert out.routeAction == "WARN"


def test_finalize_derives_needs_flags():
    quiz = _final({"intent": "QUIZ_GENERATION", "riskLevel": "ALLOW", "routeAction": "QUIZ_PIPELINE",
                   "confidence": 0.8, "reason": "x", "normalizedText": "t"})
    assert quiz.needsQuizPipeline is True
    mat = _final({"intent": "MATERIAL_QA", "riskLevel": "ALLOW", "routeAction": "MATERIAL_QA_AGENT",
                  "confidence": 0.8, "reason": "x", "normalizedText": "t"})
    assert mat.needsMaterialContext is True


def test_finalize_direct_reply_kept_for_greeting():
    out = _final({"intent": "GREETING", "riskLevel": "ALLOW", "routeAction": "DIRECT_REPLY",
                  "confidence": 0.9, "directReply": "안녕하세요!", "reason": "x", "normalizedText": "안녕"})
    assert out.directReply == "안녕하세요!"
    assert out.warningMessage is None


# ── 엔드포인트 (LLM mock / disabled) ──────────────────────────────────────────
def _client():
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(ir.router)
    return TestClient(app)


def test_endpoint_fallback_when_disabled(monkeypatch):
    monkeypatch.setattr(ir, "INTENT_ROUTER_ENABLED", False)
    c = _client()
    r = c.post("/api/ai/intent/route",
               json={"text": "OOP가 뭐야?", "surface": "learning_mate"})
    assert r.status_code == 200
    body = r.json()
    assert body["fallbackUsed"] is True
    assert body["routeAction"] == "LEARNING_MATE_AGENT"
    assert body["normalizedText"] == "OOP가 뭐야?"


def test_endpoint_uses_llm_when_parsed(monkeypatch):
    monkeypatch.setattr(ir, "INTENT_ROUTER_ENABLED", True)

    def fake(req, ctx):
        return {
            "intent": "LEARNING_QUESTION", "riskLevel": "ALLOW",
            "routeAction": "LEARNING_MATE_AGENT", "confidence": 0.93,
            "directReply": None, "reason": "conceptual question",
            "needsMaterialContext": False, "needsQuizPipeline": False,
            "warningMessage": None,
        }

    monkeypatch.setattr(ir, "_classify_with_llm", fake)
    c = _client()
    r = c.post("/api/ai/intent/route",
               json={"text": "OOP가 뭐야?", "surface": "learning_mate"})
    assert r.status_code == 200
    body = r.json()
    assert body["fallbackUsed"] is False
    assert body["intent"] == "LEARNING_QUESTION"
    assert body["confidence"] == 0.93


def test_endpoint_falls_back_when_llm_returns_none(monkeypatch):
    monkeypatch.setattr(ir, "INTENT_ROUTER_ENABLED", True)
    monkeypatch.setattr(ir, "_classify_with_llm", lambda req, ctx: None)
    c = _client()
    r = c.post("/api/ai/intent/route",
               json={"text": "이 PDF로 객관식 10개 만들어줘", "surface": "archive_chat"})
    assert r.status_code == 200
    body = r.json()
    assert body["fallbackUsed"] is True
    assert body["routeAction"] == "QUIZ_PIPELINE"
    assert body["needsQuizPipeline"] is True
