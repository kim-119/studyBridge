"""실제 라이브 생성기 프레임(가짜 LLM 캡처)으로 stream_gate 를 검증한다.

fixture: scripts/capture_stream_frames.py 가 hotfix_main:app 의 실제 라우트(학습메이트 multi-chat SSE 3모드, agents/group-study/
material/tasks fetch-stream NDJSON, 자료 퀴즈/로드맵 NDJSON)를 가짜 Ollama 앞에서 호출해 받은 원시 바이트.
가짜 LLM 출력에는 CANARY 와 비밀키 형태 문자열이 들어 있다.

주의: 이 테스트는 '게이트로 감쌌을 때' 새지 않는다는 증명이다. 현재 라이브 라우트는 게이트로 감싸져 있지 않다(미연결).
"""
import asyncio
import gzip
import json
import random
from pathlib import Path

import pytest

from app.contracts.response_quality_v1 import SCHEMA_VERSION, QualityInput, QualityOutput
from app.quality_gate import evaluator as E
from app.quality_gate import stream_gate as G

CAP = Path(__file__).parent / "fixtures" / "stream_captures"
CASES = sorted(CAP.glob("*.json.gz"))
ALLOWED_WHEN_DENIED = G.PROGRESS_EVENTS | G.TERMINAL_EVENTS | G.ERROR_EVENTS | {"quality_rejected"}


def _load(p):
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _is_sse(rec):
    return "event-stream" in rec["contentType"]


def _q(ok, rid="req-live-000001"):
    return QualityOutput(schemaVersion="response-quality.v1", requestId=rid, taskType="STUDYMATE_BASIC", success=ok, verified=ok,
                         qualityStatus="APPROVED" if ok else "REJECTED", score=90.0 if ok else 10.0, hardFail=not ok,
                         evaluatorVersion="test")


async def _approve(key, text, msg, rid):
    return _q(True, rid)


async def _deny(key, text, msg, rid):
    return _q(False)


def _policy(rec):
    if "roadmap" in rec["name"]:
        return G.policy_for("roadmap")
    return G.policy_for("studymate" if rec["name"].startswith("studymate") else None)


def _wire(rec, ev, seed=0):
    raw = rec["raw"].encode()
    rnd = random.Random(seed)

    async def chunks():
        i = 0
        while i < len(raw):
            n = rnd.randint(1, 4096)
            yield raw[i:i + n]          # 바이트 경계(한글 멀티바이트 중간 포함)로 임의 분할
            i += n

    wrap = G.wrap_sse_stream if _is_sse(rec) else G.wrap_ndjson_stream

    async def go():
        return [s async for s in wrap(chunks(), ev, policy=_policy(rec))]
    return asyncio.run(go())


def _parse_out(rec, frames):
    async def it():
        for f in frames:
            yield f
    parse = G.parse_sse if _is_sse(rec) else G.parse_ndjson

    async def go():
        return [e async for e in parse(it())]
    return asyncio.run(go())


def _content_strings(rec):
    """입력 이벤트의 '본문일 수 있는' 문자열 전부(식별자/표시명 패턴은 제외)."""
    async def it():
        yield rec["raw"]
    parse = G.parse_sse if _is_sse(rec) else G.parse_ndjson

    async def go():
        return [e async for e in parse(it())]
    out = set()

    def walk(v):
        if isinstance(v, str):
            s = v.strip()
            if len(s) >= 4 and not G._SAFE_ID.match(s) and not G._SAFE_NAME.match(s):
                out.add(s)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    for e in asyncio.run(go()):
        walk(e["data"])
    return out


def test_captures_exist_and_are_from_live_routes():
    names = {p.name.split(".")[0] for p in CASES}
    assert {"studymate_multichat_default", "studymate_multichat_debate", "studymate_multichat_socratic",
            "agents_chat_fetch_stream", "group_study_fetch_stream", "quiz_generate_stream",
            "roadmap_generate_stream"} <= names
    for p in CASES:
        rec = _load(p)
        assert rec["status"] == 200, rec["name"]


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.name.split(".")[0])
def test_deny_all_forwards_no_generated_text(path):
    rec = _load(path)
    frames = _wire(rec, _deny)
    joined = "".join(frames)
    assert rec["canary"] not in joined and "sk-proj" not in joined
    leaked = [s for s in _content_strings(rec) if s in joined]
    assert leaked == []
    kinds = {e["event"] for e in _parse_out(rec, frames)}
    assert kinds <= ALLOWED_WHEN_DENIED, kinds - ALLOWED_WHEN_DENIED


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.name.split(".")[0])
def test_approve_all_keeps_transport_contract_and_terminates(path):
    rec = _load(path)
    frames = _wire(rec, _approve, seed=1)
    evs = _parse_out(rec, frames)
    assert evs and evs[-1]["event"] in (G.TERMINAL_EVENTS | {"error"})
    assert not [e for e in evs if e["event"] == "quality_rejected"
                or (e["event"] == "agent_error" and e["data"].get("code") == "QUALITY_REJECTED")]   # 전부 승인이면 본문을 잃지 않는다
    if rec["canary"] in rec["raw"]:
        assert rec["canary"] in "".join(frames)
    for e in evs:
        s = json.dumps(e["data"], ensure_ascii=False)
        if rec["canary"] in s:
            # CANARY(생성 본문)는 승인된 본문 이벤트, 또는 종료 이벤트의 '승인 항목'에만 있을 수 있다
            assert e["event"] in (G.MESSAGE_EVENTS | G.DELTA_EVENTS | G.TERMINAL_EVENTS), e["event"]
            if e["event"] in G.TERMINAL_EVENTS and any(isinstance(e["data"].get(f), list) for f in ("answers", "messages")):
                for f in ("answers", "messages"):
                    for it in e["data"].get(f) or []:
                        assert rec["canary"] not in json.dumps(it, ensure_ascii=False) or "quality" in it
            else:
                assert "quality" in e["data"]
    if _is_sse(rec):
        assert all(f.startswith(("event:", "id:", ":")) for f in frames)   # 원 SSE 처럼 event: 라인 유지
    else:
        assert all(isinstance(json.loads(f), dict) and ("type" in json.loads(f) or "event" in json.loads(f))
                   for f in frames)


def test_real_evaluator_blocks_secret_in_live_studymate_answer():
    """현재 라이브 학습메이트 스트림은 생성된 비밀키 형태 문자열을 그대로 내보낸다. 게이트로 감싸면 SECRET_LEAK 로 막힌다."""
    rec = _load(CAP / "studymate_multichat_default.json.gz")
    assert "sk-proj-" in rec["raw"]          # 미게이트 원본에는 실제로 실려 있다
    E.clear_cache()

    async def ev(key, text, msg, rid):
        return await E.evaluate(QualityInput.model_validate({
            "schemaVersion": SCHEMA_VERSION, "requestId": rid, "taskType": "STUDYMATE_BASIC",
            "outputKind": "agent_message", "originalRequest": rec["request"]["message"], "proposedOutput": text,
            "groundingEvidence": [], "constraints": {}}))
    frames = _wire(rec, ev)
    joined = "".join(frames)
    assert "sk-proj" not in joined and rec["canary"] not in joined
    rej = [e for e in _parse_out(rec, frames) if e["event"] == "agent_error" and e["data"].get("code") == "QUALITY_REJECTED"]
    assert rej and any("SECRET_LEAK" in e["data"]["qualityCodes"] for e in rej)
    fin = [e for e in _parse_out(rec, frames) if e["event"] == "all_complete"][-1]["data"]
    assert all("sk-proj" not in json.dumps(a) for a in fin.get("answers", []))      # 영속화 목록에도 안 실린다


def test_studymate_capture_keeps_spring_relay_fields():
    """Spring 은 eventId 로 중복 제거, agentIndex/agentId 로 커버리지, all_complete.answers[] 로 영속화한다."""
    rec = _load(CAP / "studymate_multichat_default.json.gz")
    evs = _parse_out(rec, _wire(rec, _approve))
    ans = [e for e in evs if e["event"] == "agent_answer"]
    assert ans and all(e["data"].get("eventId") and e["data"].get("agentIndex") and e["data"].get("answer") for e in ans)
    fin = [e for e in evs if e["event"] == "all_complete"][-1]["data"]
    assert "answers" in fin and fin.get("eventId")
    errs = [e for e in evs if e["event"] == "agent_error"]
    assert errs and all(e["data"].get("code") == "AGENT_DUPLICATE" for e in errs)   # 원 에이전트 실패 코드 유지
