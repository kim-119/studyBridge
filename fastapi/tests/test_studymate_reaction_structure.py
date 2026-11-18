"""반박(REACTION) 프롬프트 구조화 검증 — 어느지점/왜/올바른설명/근거 골격이 주입되는지."""
import pytest

from app.schemas.multi_chat_schema import AgentProfile, MultiChatRequest
from app.services import orchestrator_service as orch


def _capture_prompts(monkeypatch):
    captured = {}

    def _spy(**kw):
        captured["system"] = kw.get("system_prompt", "")
        captured["user"] = kw.get("user_prompt", "")
        return "보충 본문"

    monkeypatch.setattr("app.services.ollama_client.ask_ollama", _spy)
    return captured


def test_reaction_prompt_has_four_part_structure(monkeypatch):
    cap = _capture_prompts(monkeypatch)
    agent = AgentProfile(id=1, agentId="a1", name="냉소봇", personality="냉소적", knowledgeLevel="학사")
    req = MultiChatRequest(message="SQL JOIN이 뭐야?", agents=[agent])
    orch._generate_round2_feedback(agent, req, "basic", [{"agentName": "x", "answer": "JOIN은 합치는 것"}])
    s = cap["system"]
    # 4부 구조 + 사용자 중심 + 인신공격 금지가 프롬프트에 들어있다.
    assert "어느 지점" in s
    assert "왜" in s
    assert ("올바" in s or "보완" in s)
    assert ("근거" in s or "예시" in s)
    assert "사용자" in s
    assert "인신공격" in s
