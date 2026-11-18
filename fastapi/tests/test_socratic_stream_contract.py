"""소크라테스 모드 실패 복구 테스트.

근본원인(수정 대상):
  - _run_socratic_stage 가 ollama 호출 시 think=False 를 전달하지 않아(qwen3 thinking ON)
    빈 응답/지연 → "(제목) 단계를 생성하지 못했습니다…" 가 답변처럼 노출됐다.

요구:
  1. 소크라테스 단계의 ollama 호출은 think=False 로 나간다(지연/빈응답 방지).
  2. LLM이 빈 응답/실패여도 사용자에겐 결정적 소크라테스 '질문'이 반환된다.
     ("단계를 생성하지 못했습니다" 같은 실패 문구를 노출하지 않는다.)
  3. run_socratic_mode_stream 은 예외 없이 socratic_step + all_complete SSE 이벤트를 낸다.
"""
import pytest

from app.services import multi_agent_service as M
from app.schemas.multi_chat_schema import MultiChatRequest

_FAIL_PHRASE = "단계를 생성하지 못했습니다"


@pytest.fixture
def force_ollama(monkeypatch):
    """소크라테스 단계 provider 를 ollama 로 고정(테스트 결정성)."""
    monkeypatch.setattr(
        M.A, "resolve_agent_generation_params",
        lambda *a, **k: {"provider": "ollama", "max_tokens": 320, "temperature": 0.5},
    )


def test_socratic_stage_calls_ollama_with_think_false(monkeypatch, force_ollama):
    captured = {}

    def fake_ask(*args, **kwargs):
        captured.update(kwargs)
        return "객체와 클래스의 차이를 네 말로 설명해볼래?"

    monkeypatch.setattr("app.services.ollama_client.ask_ollama", fake_ask)
    monkeypatch.setattr("app.services.ollama_client.is_ollama_available", lambda: True)

    req = MultiChatRequest(message="객체지향이 뭐야?", mode="socratic", learningMode="socratic")
    cfg = M.normalize_socratic_config(req)
    agent = M._create_virtual_socratic_agent("질문자", 1)

    text = M._run_socratic_stage(req, agent, "diagnosis", cfg, "")
    assert captured.get("think") is False
    assert _FAIL_PHRASE not in text


def test_socratic_stage_returns_deterministic_question_on_blank_llm(monkeypatch, force_ollama):
    # LLM이 빈 응답을 주는 상황 재현
    monkeypatch.setattr("app.services.ollama_client.ask_ollama", lambda *a, **k: "")
    monkeypatch.setattr("app.services.ollama_client.is_ollama_available", lambda: True)

    req = MultiChatRequest(message="역방향 SSH가 뭐야?", mode="socratic", learningMode="socratic")
    cfg = M.normalize_socratic_config(req)
    agent = M._create_virtual_socratic_agent("질문자", 1)

    text = M._run_socratic_stage(req, agent, "diagnosis", cfg, "")
    assert text.strip()                       # 비어 있지 않다
    assert _FAIL_PHRASE not in text           # 실패 문구 금지
    assert "?" in text or "까요" in text or "요" in text  # 질문 형태


def test_socratic_stream_yields_steps_and_all_complete_on_llm_failure(monkeypatch, force_ollama):
    # 모든 단계에서 LLM 실패(빈 응답) → 그래도 정상 SSE 계약
    monkeypatch.setattr("app.services.ollama_client.ask_ollama", lambda *a, **k: "")
    monkeypatch.setattr("app.services.ollama_client.is_ollama_available", lambda: True)

    req = MultiChatRequest(message="역방향 SSH를 소크라테스식으로 설명해줘.",
                           mode="socratic", learningMode="socratic")

    events = list(M.run_socratic_mode_stream(req, [], ""))
    names = [e["event"] for e in events]

    assert "socratic_step" in names
    assert names[-1] == "all_complete"

    step_contents = [e["data"].get("content", "") for e in events if e["event"] == "socratic_step"]
    assert step_contents, "socratic_step 이벤트가 없음"
    for c in step_contents:
        assert c.strip()
        assert _FAIL_PHRASE not in c          # 어떤 단계도 실패 문구를 노출하지 않음
