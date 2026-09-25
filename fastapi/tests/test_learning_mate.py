"""
학습메이트 정책/프롬프트/엔드포인트 테스트 (LLM mock).
"""
import app.learning_mate.service as svc
from app.learning_mate import policies as P
from app.learning_mate.prompt_builder import build_learning_mate_prompt, resolve_effective_question
from app.learning_mate.schemas import LearningMateChatRequest, LearningMatePersona


def _req(**kw):
    return LearningMateChatRequest(**kw)


# ── 정책 보정(방식 B) ─────────────────────────────────────────────────────────
def test_resolve_known_and_alias_and_unknown():
    assert P.resolve_mode("socratic") == "socratic"
    assert P.resolve_mode("소크라테스") == "socratic"      # 한글 라벨 alias
    assert P.resolve_mode("bad_mode") == "explain"          # 알 수 없음 → 기본값
    assert P.resolve_tone("cold") == "cold"
    assert P.resolve_level("knowledge") == "beginner"       # 알 수 없음 → 기본
    assert P.resolve_level("학사") == "undergraduate"        # Spring 한글
    assert P.resolve_quick_action("easier") == "easier"
    assert P.resolve_quick_action(None) is None
    assert P.resolve_quick_action("nope") is None


def test_knowledge_level_alias_maps_to_learner_level():
    # Spring이 knowledgeLevel로 보내도 흡수
    r = _req(question="q", persona={"knowledgeLevel": "advanced"})
    assert r.persona.learnerLevel == "advanced"


def test_labels_and_summary():
    ml, tl, ll, summary = P.labels("socratic", "friendly", "beginner")
    assert summary == "소크라테스 · 친근한 말투 · 입문자 맞춤"


# ── previousQuestion / effective question ─────────────────────────────────────
def test_effective_question_uses_previous_on_quickaction():
    r = _req(question="더 쉽게 설명해줘", previousQuestion="OOP가 뭐야?", quickAction="easier")
    assert resolve_effective_question(r) == "OOP가 뭐야?"


def test_effective_question_uses_question_without_rewrite():
    r = _req(question="OOP가 뭐야?", previousQuestion="이전질문")
    # rewrite/quickAction 없으면 현재 question 사용
    assert resolve_effective_question(r) == "OOP가 뭐야?"


def test_effective_question_uses_previous_on_rewrite_instruction():
    r = _req(question="다시 설명", previousQuestion="OOP가 뭐야?", rewriteInstruction="소크라테스식으로")
    assert resolve_effective_question(r) == "OOP가 뭐야?"


# ── prompt builder: mode별 instruction 반영, 분기문 없음 ──────────────────────
def test_prompt_contains_mode_tone_level_instructions():
    r = _req(question="OOP가 뭐야?", mode="debate", persona={"tone": "cold", "learnerLevel": "advanced"})
    sys_p, user_p, eff, resolved = build_learning_mate_prompt(r)
    assert resolved == {"mode": "debate", "tone": "cold", "level": "advanced"}
    assert P.MODE_POLICIES["debate"]["instruction"] in sys_p
    assert P.TONE_POLICIES["cold"]["instruction"] in sys_p
    assert P.LEARNER_LEVEL_POLICIES["advanced"]["instruction"] in sys_p
    assert "OOP가 뭐야?" in user_p


def test_prompt_includes_quickaction_and_custom():
    r = _req(question="더 쉽게", previousQuestion="OOP가 뭐야?", quickAction="code_example",
             persona={"customInstruction": "자바로 설명"})
    sys_p, user_p, eff, resolved = build_learning_mate_prompt(r)
    assert P.QUICK_ACTION_POLICIES["code_example"]["instruction"] in sys_p
    assert "자바로 설명" in sys_p
    assert eff == "OOP가 뭐야?"


# ── 엔드포인트 (LLM mock) ─────────────────────────────────────────────────────
def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.learning_mate.router import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_endpoint_success_metadata(monkeypatch):
    monkeypatch.setattr(svc, "ask_ollama", lambda **kw: "OOP는 객체지향 프로그래밍입니다. 예: ...")
    c = _client()
    r = c.post("/api/ai/learning-mate/chat",
               json={"question": "OOP가 뭐야?", "mode": "socratic",
                     "persona": {"tone": "friendly", "learnerLevel": "beginner"}})
    assert r.status_code == 200
    b = r.json()
    assert b["mode"] == "socratic"
    assert b["modeLabel"] == "소크라테스"
    assert b["summaryLabel"] == "소크라테스 · 친근한 말투 · 입문자 맞춤"
    assert b["availableModes"] == ["explain", "socratic", "debate", "roleplay"]
    assert "easier" in b["availableQuickActions"]
    assert b["question"] == "OOP가 뭐야?"


def test_endpoint_quickaction_returns_previous_question(monkeypatch):
    monkeypatch.setattr(svc, "ask_ollama", lambda **kw: "더 쉬운 설명입니다.")
    c = _client()
    r = c.post("/api/ai/learning-mate/chat",
               json={"question": "더 쉽게 설명해줘", "previousQuestion": "OOP가 뭐야?",
                     "mode": "explain", "quickAction": "easier"})
    assert r.status_code == 200
    assert r.json()["question"] == "OOP가 뭐야?"  # 실제 설명 대상


def test_endpoint_invalid_mode_coerced_to_explain(monkeypatch):
    monkeypatch.setattr(svc, "ask_ollama", lambda **kw: "설명입니다.")
    c = _client()
    r = c.post("/api/ai/learning-mate/chat", json={"question": "OOP가 뭐야?", "mode": "bad_mode"})
    assert r.status_code == 200
    assert r.json()["mode"] == "explain"  # 방식 B 보정


def test_endpoint_empty_question_422():
    c = _client()
    r = c.post("/api/ai/learning-mate/chat", json={"question": "", "previousQuestion": None})
    assert r.status_code == 422


def test_endpoint_llm_failure_returns_502(monkeypatch):
    # ask_ollama가 실패 안내 문자열을 반환 → 가짜 성공 금지, 502
    monkeypatch.setattr(svc, "ask_ollama", lambda **kw: "현재 Ollama 서버(http://...)에 연결할 수 없습니다.")
    c = _client()
    r = c.post("/api/ai/learning-mate/chat", json={"question": "OOP가 뭐야?"})
    assert r.status_code == 502


def test_endpoint_empty_llm_returns_502(monkeypatch):
    monkeypatch.setattr(svc, "ask_ollama", lambda **kw: "   ")
    c = _client()
    r = c.post("/api/ai/learning-mate/chat", json={"question": "OOP가 뭐야?"})
    assert r.status_code == 502
