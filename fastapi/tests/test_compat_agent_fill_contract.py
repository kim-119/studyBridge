"""
multi_chat_stream_compat 의 agent_answer 커버리지 계약 검증.

계약:
  정상 multi-agent : selected == executed == emitted, generic filler 0건
  의도적 partial   : executed < selected 가능, 단 suppressAgentFill == True → filler 0건
  실행 누락        : filler 로 조용히 성공 위장 금지 → degraded 카드 + ERROR 로그로 식별 가능

배경: summary-only/WRAP 경로에서 교수 1명만 실행됐는데 compat 가 나머지 선택 교수 슬롯에
"{agentName} 관점에서 핵심을 정리하면…" 동일 문장을 합성해 내보내던 라이브 버그.
"""
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import multi_chat_stream_compat as compat


AGENTS = [
    {"agentId": "a1", "name": "김교수", "personality": "전문적", "knowledgeLevel": "학사"},
    {"agentId": "a2", "name": "이교수", "personality": "냉소적", "knowledgeLevel": "학사"},
    {"agentId": "a3", "name": "박교수", "personality": "친근함", "knowledgeLevel": "학사"},
]


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(compat.router)
    return TestClient(app)


def _answer(agent_id: str, name: str, text: str):
    return {"event": "agent_answer", "data": {
        "type": "agent_answer", "agentId": agent_id, "agentName": name,
        "answer": text, "content": text, "status": "SUCCESS", "visible": True,
    }}


def _complete(answers, **extra):
    data = {"type": "all_complete", "answers": answers, "messages": answers,
            "status": "COMPLETED", "phase": "ALL_COMPLETE", "visible": True}
    data.update(extra)
    return {"event": "all_complete", "data": data}


def _install_stream(monkeypatch, events):
    """compat 가 호출 시점에 import 하는 build_stream_generator 를 갈아끼운다."""
    from app.services import multi_agent_service as mas
    monkeypatch.setattr(mas, "build_stream_generator", lambda req: iter(events))


def _post(client, mode="basic"):
    return client.post("/api/ai/multi-chat/stream", json={
        "message": "FastAPI나 Spring에서 mapping이 중요한 이유가 뭐야?",
        "mode": mode, "agents": AGENTS, "roomId": 1, "userId": 8,
    })


def _parse_sse(text):
    out = []
    for block in text.split("\n\n"):
        ev = dat = None
        for line in block.splitlines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                dat = json.loads(line[6:])
        if ev:
            out.append((ev, dat or {}))
    return out


def test_normal_multi_agent_selected_equals_executed_equals_emitted(client, monkeypatch):
    events = [
        _answer("a1", "김교수", "매핑은 계층 간 변환이다."),
        _answer("a2", "이교수", "ORM 매핑은 스키마와 객체를 잇는다."),
        _answer("a3", "박교수", "요청 매핑은 URL 을 핸들러에 연결한다."),
        _complete([], route="discussion_plan", suppressAgentFill=False),
    ]
    _install_stream(monkeypatch, events)

    parsed = _parse_sse(_post(client).text)
    answers = [d for e, d in parsed if e == "agent_answer"]

    assert len(answers) == 3
    assert {a["agentId"] for a in answers} == {"a1", "a2", "a3"}
    assert not any(a.get("synthesized") for a in answers), "정상 경로인데 필러가 합성됨"
    assert not any(a.get("degraded") for a in answers)


def test_summary_only_route_emits_zero_filler(client, monkeypatch):
    """교수 1명만 실행되는 정리 경로: 나머지 2명 슬롯에 필러가 0건이어야 한다."""
    events = [
        _answer("a1", "김교수", "핵심 개념 정리 / 오개념 / 복습 포인트"),
        _complete([], route="summary_only", suppressAgentFill=True),
    ]
    _install_stream(monkeypatch, events)

    parsed = _parse_sse(_post(client).text)
    answers = [d for e, d in parsed if e == "agent_answer"]

    assert len(answers) == 1, f"정리는 한 장이어야 함, got {len(answers)}"
    assert not any(a.get("synthesized") for a in answers)
    assert not any("관점에서 핵심을 정리하면" in (a.get("answer") or "") for a in answers)


def test_missing_agent_answer_is_surfaced_not_disguised(client, monkeypatch, caplog):
    """정상 multi-agent 인데 실행이 빠지면 정상 답변처럼 위장하지 않는다."""
    events = [
        _answer("a1", "김교수", "매핑은 계층 간 변환이다."),
        _answer("a2", "이교수", "ORM 매핑은 스키마와 객체를 잇는다."),
        _complete([], route="discussion_plan", suppressAgentFill=False),
    ]
    _install_stream(monkeypatch, events)

    with caplog.at_level(logging.INFO, logger="studybridge.multi_chat_stream_compat"):
        parsed = _parse_sse(_post(client).text)

    answers = [d for e, d in parsed if e == "agent_answer"]
    complete = [d for e, d in parsed if e == "all_complete"][0]
    filler = [a for a in answers if a.get("synthesized")]

    assert len(answers) == 3
    assert len(filler) == 1 and filler[0]["agentId"] == "a3"
    assert filler[0]["degraded"] is True
    assert filler[0]["status"] == "FAILED"
    assert filler[0]["code"] == "AGENT_ANSWER_MISSING"
    assert "관점에서 핵심을 정리하면" not in filler[0]["answer"]
    assert complete["degraded"] is True
    assert complete["missingAgentIds"] == ["a3"]
    assert any(r.levelno >= logging.ERROR and "[AGENT-FILL]" in r.getMessage() for r in caplog.records)


def test_route_coverage_log_is_emitted(client, monkeypatch, caplog):
    events = [
        _answer("a1", "김교수", "답변1"),
        _answer("a2", "이교수", "답변2"),
        _answer("a3", "박교수", "답변3"),
        _complete([], route="discussion_plan", suppressAgentFill=False, dialogueAct="NEW_STUDY_QUERY"),
    ]
    _install_stream(monkeypatch, events)

    with caplog.at_level(logging.INFO, logger="studybridge.multi_chat_stream_compat"):
        _post(client)

    line = next((r.getMessage() for r in caplog.records if "[MULTI-CHAT-ROUTE]" in r.getMessage()), None)
    assert line is not None, "라우팅 계측 로그가 없음"
    for field in ("route=", "selected_agent_ids=", "executed_agent_ids=",
                  "emitted_agent_ids=", "suppress_agent_fill=", "dialogue_act="):
        assert field in line, f"{field} 누락: {line}"
    assert "NEW_STUDY_QUERY" in line


def test_target_agent_route_emits_no_filler(client, monkeypatch):
    """@멘션 1명 지목: 나머지 교수 슬롯을 채우지 않는다(기존 계약 회귀 방어)."""
    events = [
        _answer("a2", "이교수", "지목된 교수만 답한다."),
        _complete([], route="target_agent"),
    ]
    _install_stream(monkeypatch, events)

    res = client.post("/api/ai/multi-chat/stream", json={
        "message": "이교수님 설명해주세요", "mode": "basic", "agents": AGENTS,
        "targetAgentId": "a2", "roomId": 1, "userId": 8,
    })
    answers = [d for e, d in _parse_sse(res.text) if e == "agent_answer"]
    assert len(answers) == 1 and answers[0]["agentId"] == "a2"
