"""
POST /api/ai/multi-chat API 테스트.
Ollama/GPT 없이도 mode, answers 구조를 검증한다.
"""
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

_SINGLE_AGENT_REQUEST = {
    "message": "RAG 아키텍처에 대해 설명해줘",
    "mode": "multi_agent_discussion",
    "rounds": 1,
    "showFinalSynthesis": False,
    "targetAgentId": None,
    "previousAnswers": [],
    "agents": [
        {
            "id": 1,
            "agentId": 1,
            "name": "SummaryAgent",
            "role": "요약봇",
            "personality": "간결_요약형",
            "personalityStrength": "moderate",
            "knowledgeLevel": "학사",
        }
    ],
}

_MULTI_AGENT_REQUEST = {
    "message": "딥러닝과 머신러닝의 차이를 설명해줘",
    "mode": "multi_agent_discussion",
    "rounds": 1,
    "showFinalSynthesis": False,
    "agents": [
        {"id": 1, "agentId": 1, "name": "설명봇", "personality": "친절_설명형", "knowledgeLevel": "학사"},
        {"id": 2, "agentId": 2, "name": "분석봇", "personality": "비판적_분析형", "knowledgeLevel": "석사"},
    ],
}


def test_multi_chat_response_structure():
    """응답에 mode, answers가 반드시 포함된다."""
    resp = client.post("/api/ai/multi-chat", json=_SINGLE_AGENT_REQUEST)
    assert resp.status_code == 200
    body = resp.json()
    assert "mode" in body
    assert "answers" in body
    assert isinstance(body["answers"], list)


def test_multi_chat_answer_structure():
    """각 answer에 agentName, answer가 포함된다."""
    resp = client.post("/api/ai/multi-chat", json=_SINGLE_AGENT_REQUEST)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["answers"]) > 0
    for a in body["answers"]:
        assert "agentName" in a
        assert "answer" in a


def test_multi_chat_mode_preserved():
    """응답의 mode가 요청과 일치한다."""
    resp = client.post("/api/ai/multi-chat", json=_SINGLE_AGENT_REQUEST)
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == _SINGLE_AGENT_REQUEST["mode"]


def test_multi_chat_target_agent_id():
    """targetAgentId 지정 시 해당 에이전트만 답변한다."""
    request = {**_MULTI_AGENT_REQUEST, "targetAgentId": 1}
    resp = client.post("/api/ai/multi-chat", json=request)
    assert resp.status_code == 200
    body = resp.json()
    agent_names = [a["agentName"] for a in body["answers"]]
    # 지정된 에이전트(agentId=1 → name=설명봇)만 있어야 함
    assert "설명봇" in agent_names
    # 다른 에이전트(분析봇)는 없어야 함
    assert "분析봇" not in agent_names


def test_multi_chat_empty_agents_uses_default():
    """agents 배열이 비어있으면 기본 에이전트가 답변한다."""
    resp = client.post(
        "/api/ai/multi-chat",
        json={"message": "파이썬이란?", "agents": [], "showFinalSynthesis": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["answers"]) > 0


def test_multi_chat_previous_answers_context():
    """previousAnswers가 있을 때 오류 없이 응답한다."""
    request = {
        **_SINGLE_AGENT_REQUEST,
        "previousAnswers": [
            {"agentName": "SummaryAgent", "answer": "RAG는 정보 검색을 통합한 기술입니다.", "role": "ASSISTANT", "agentId": 1}
        ],
    }
    resp = client.post("/api/ai/multi-chat", json=request)
    assert resp.status_code == 200
    body = resp.json()
    assert "answers" in body


def test_multi_chat_empty_message_error():
    """빈 message는 400 에러를 반환한다."""
    resp = client.post(
        "/api/ai/multi-chat",
        json={"message": "   ", "agents": []},
    )
    assert resp.status_code == 400


def test_multi_chat_response_field_names():
    """응답 필드명이 Spring 명세(camelCase)와 일치한다."""
    resp = client.post("/api/ai/multi-chat", json=_SINGLE_AGENT_REQUEST)
    assert resp.status_code == 200
    body = resp.json()
    assert "mode" in body
    assert "answers" in body
    for a in body["answers"]:
        assert "agentName" in a
        assert "answer" in a
        assert "agent_name" not in a
