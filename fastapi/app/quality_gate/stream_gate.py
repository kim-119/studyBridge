"""SSE/NDJSON 선노출 방지 게이트.

검증 전 생성 본문을 흘리지 않는다. 진행상태 이벤트(allowlist)만 즉시 통과시키고, 본문 이벤트(토큰/에이전트 발화/
최종 메시지)는 메시지 단위로 버퍼링한 뒤 evaluate_message 결과가 APPROVED 일 때만 방출한다.
모르는 이벤트 타입은 본문으로 간주해 버퍼링한다(fail-closed). 중간 에이전트 발화도 개별 검증한다.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Tuple

from app.contracts.response_quality_v1 import QualityOutput, is_displayable

PROGRESS_EVENTS = frozenset({"stage_start", "stage_complete", "progress", "heartbeat", "ping", "turn_start",
                             "agent_start", "thinking", "status", "queue", "meta"})
DELTA_EVENTS = frozenset({"token", "delta", "chunk", "agent_delta", "content_delta"})
MESSAGE_EVENTS = frozenset({"agent_answer", "message", "answer", "final", "agent_message", "final_summary",
                            "debate_section", "socratic_question"})
TERMINAL_EVENTS = frozenset({"all_complete", "done", "complete", "end"})


def _key(ev: Dict[str, Any]) -> str:
    d = ev.get("data") if isinstance(ev.get("data"), dict) else ev
    return f"{d.get('turnId') or d.get('turn_id') or 't'}:{d.get('agentId') or d.get('agent_id') or 'main'}"


def _content(ev: Dict[str, Any]) -> str:
    d = ev.get("data") if isinstance(ev.get("data"), dict) else ev
    for k in ("content", "text", "answer", "message", "delta", "token"):
        if isinstance(d.get(k), str):
            return d[k]
    return ""


def _strip_content(ev: Dict[str, Any]) -> Dict[str, Any]:
    """종료 이벤트에 실린 본문 묶음(messages/answers 등)을 제거해 미승인 본문이 새지 않게 한다."""
    out = {k: v for k, v in ev.items() if k not in ("data",)}
    d = ev.get("data")
    if isinstance(d, dict):
        out["data"] = {k: v for k, v in d.items() if k not in ("messages", "answers", "content", "text", "answer")}
    return out


async def gate_event_stream(
    source: AsyncIterator[Dict[str, Any]],
    evaluate_message: Callable[[str, str, Dict[str, Any]], Awaitable[QualityOutput]],
    *,
    on_approved: Optional[Callable[[str, str, QualityOutput], Awaitable[None]]] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """이벤트 dict({'event': type, 'data': {...}}) 스트림을 품질 게이트로 감싼다."""
    buffers: Dict[str, List[str]] = {}
    pending_msgs: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []

    async def _flush(key: str) -> AsyncIterator[Dict[str, Any]]:
        text = "".join(buffers.pop(key, []))
        msg = pending_msgs.pop(key, None)
        if msg is not None and _content(msg):
            text = _content(msg)
        if key in order:
            order.remove(key)
        if not text.strip():
            return
        q = await evaluate_message(key, text, msg or {})
        if is_displayable(q):
            if on_approved is not None:
                try:
                    await on_approved(key, text, q)
                except Exception:  # noqa: BLE001 — 수집 실패가 응답을 막지 않는다
                    pass
            yield {"event": (msg or {}).get("event", "agent_answer"),
                   "data": {**((msg or {}).get("data") or {}), "content": text,
                            "quality": {"qualityStatus": q.qualityStatus.value, "score": q.score,
                                        "evaluatorVersion": q.evaluatorVersion}}}
        else:
            yield {"event": "quality_rejected",
                   "data": {"messageKey": key, "qualityStatus": q.qualityStatus.value, "score": q.score,
                            "hardFail": q.hardFail, "codes": sorted({v.code for v in q.violations})[:10]}}

    async for ev in source:
        et = str(ev.get("event") or ev.get("type") or "").lower()
        if et in PROGRESS_EVENTS:
            yield ev
            continue
        key = _key(ev)
        if et in DELTA_EVENTS:
            buffers.setdefault(key, []).append(_content(ev))
            if key not in order:
                order.append(key)
            continue
        if et in MESSAGE_EVENTS:
            pending_msgs[key] = ev
            if key not in order:
                order.append(key)
            async for out in _flush(key):
                yield out
            continue
        if et in TERMINAL_EVENTS:
            for k in list(order):
                async for out in _flush(k):
                    yield out
            yield _strip_content(ev)
            continue
        # 알 수 없는 타입: 본문일 수 있으므로 내용만 버퍼링하고 원 이벤트는 내보내지 않는다.
        c = _content(ev)
        if c:
            buffers.setdefault(key, []).append(c)
            if key not in order:
                order.append(key)
    for k in list(order):
        async for out in _flush(k):
            yield out


def to_sse(ev: Dict[str, Any]) -> str:
    return f"event: {ev.get('event', 'message')}\ndata: {json.dumps(ev.get('data', {}), ensure_ascii=False)}\n\n"
