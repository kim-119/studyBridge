"""SSE/NDJSON 선노출 방지 게이트 — 스트리밍 응답의 '단일 공유 경계'.

검증 전 생성 본문을 흘리지 않는다.
- 진행상태 이벤트(allowlist)는 식별자만 남긴 새 이벤트로 즉시 통과(텍스트 필드는 버림).
- 본문 이벤트(토큰/에이전트 발화/최종 메시지/구조화 결과)는 메시지 단위로 버퍼링한 뒤 evaluate_message 결과가
  APPROVED 일 때만 방출한다. 중간 에이전트 발화도 개별 검증한다.
- 모르는 이벤트 타입은 절대 그대로 내보내지 않고, 다른 메시지 버퍼에 섞지도 않는다(quality_rejected 만 알림).
- error 이벤트의 문구(내부 예외/호스트 등)는 버리고 안정된 errorCode 만 전달한다. 해당 메시지의 미완성 버퍼는 폐기.
- 평가기 예외/타임아웃 → quality_rejected(VALIDATION_ERROR). 상류 스트림 예외 → error(STREAM_SOURCE_ERROR) 후 종료,
  잘린 버퍼는 평가하지 않고 폐기.
- 메시지/전체 버퍼 상한 초과 → 해당 메시지 거부(STREAM_MESSAGE_TOO_LARGE / STREAM_BUFFER_LIMIT), 메모리 상한 유지.
- 같은 메시지(key+본문 해시)가 다시 오면 다시 내보내지 않는다(재전송/중복 이벤트).
- 소비자가 끊으면(aclose/취소) 상류 생성기를 닫는다(LLM 슬롯 반환).

이 모듈은 라이브 라우트에 '연결되어 있지 않다'. 연결은 경로별 계약(EC2)이 확정된 뒤 wrap_sse_stream /
wrap_ndjson_stream 으로 StreamingResponse 의 본문 생성기를 감싸는 방식으로만 한다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Union

from app.contracts.response_quality_v1 import QualityOutput, is_displayable

PROGRESS_EVENTS = frozenset({
    "stage_start", "stage_complete", "progress", "heartbeat", "ping", "turn_start", "agent_start", "thinking",
    "status", "queue", "meta",
    # 자료보관함 fetch-stream(stream_events.py) 진행 이벤트 — message 는 고정 UI 문구지만 그래도 버린다
    "start", "context_ready", "generation_started", "validating", "repair_started", "fallback_started",
    "batch_generated", "phase_progress", "__comment__",
})
DELTA_EVENTS = frozenset({"token", "delta", "chunk", "agent_delta", "content_delta"})
MESSAGE_EVENTS = frozenset({"agent_answer", "message", "answer", "final", "agent_message", "final_summary",
                            "debate_section", "socratic_question", "partial_validated",
                            "follow_up_suggestions",
                            # 학습메이트 SSE(studymate-sse-2) 본문 이벤트 — 실제 생성기 기준(2026-11-04 경로 매트릭스)
                            "direct_reply", "socratic_step", "debate_round", "simulation_stage"})
TERMINAL_EVENTS = frozenset({"all_complete", "done", "complete", "end"})
ERROR_EVENTS = frozenset({"error", "stream_error", "agent_error", "fatal"})

_SAFE_ID = re.compile(r"^[A-Za-z0-9_\-:.+]{1,64}$")         # 공백 불가 → 문장이 식별자 필드로 새지 못한다
_SAFE_NAME = re.compile(r"^[\w .()\-]{1,20}$")             # 표시용 에이전트 이름(한글 허용, 20자)
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")

# 출력 이벤트는 원본을 복사하지 않고 allowlist 로 '새로' 만든다(원본의 다른 필드에 실린 미승인 본문 차단).
_ID_KEYS = ("turnId", "turn_id", "agentId", "agent_id", "stage", "stageName", "stageKey", "status", "index",
            "total", "round", "mode", "messageId", "timestamp", "seq", "requestId", "jobId", "elapsedMs", "phase",
            "visible", "dedupeKey", "type", "event", "success", "feature", "roomId", "materialId",
            # 진행 개수(정수)만 — answerIndex 같은 '내용을 담는 숫자'는 넣지 않는다
            "batch", "validatedCount", "targetCount", "totalCount", "validatedWeeks", "targetWeeks", "totalDays",
            "totalWeeks", "daysPerWeek",
            # studymate-sse-2 envelope 식별자 — Spring 은 eventId 로 중복 제거, React 는 agentIndex 로 카드 갱신
            "eventId", "eventType", "contractVersion", "fingerprint", "createdAt", "agentIndex", "displayOrder",
            "isFinal", "degraded", "actType", "replyTo", "learningMode", "sessionId", "socraticRole", "stageType",
            "personality", "personalityKey", "knowledgeLevel", "knowledgeLevelKey", "personalityResolved",
            "knowledgeLevelResolved", "code", "expectedAgentCount", "rebuttalRounds", "debateStrength",
            "failedAgentId", "failedStage")
_NAME_KEYS = ("agentName", "personalityLabel", "knowledgeLevelLabel", "roleLabel", "stageTitle", "failedAgentName")
# 본문 메시지에서 '평가하고, 승인되면 그대로 싣는' 텍스트 필드(Spring 은 answer||content, 소크라테스는 question 사용)
_EMIT_TEXT_FIELDS = ("content", "answer", "question", "hint", "feedback")


@dataclass(frozen=True)
class StreamGatePolicy:
    progress_events: frozenset = PROGRESS_EVENTS
    delta_events: frozenset = DELTA_EVENTS
    message_events: frozenset = MESSAGE_EVENTS
    terminal_events: frozenset = TERMINAL_EVENTS
    error_events: frozenset = ERROR_EVENTS
    text_fields: tuple = ("content", "text", "answer", "message", "delta", "token")
    # 텍스트가 없는 메시지 이벤트는 구조화 결과(퀴즈 문항/로드맵 등)를 JSON 으로 평가한다
    struct_fields: tuple = ("questions", "items", "quiz", "roadmap", "result", "nodes", "weeks", "suggestions")
    # 종료 이벤트의 '모아 보내기' 목록(all_complete.answers[]/messages[]) — 승인된 항목만 다시 만들어 싣는다
    aggregate_fields: tuple = ("answers", "messages")
    # 거절 알림 방식: quality_rejected(기본) | agent_error(학습메이트: 기존 Spring/React 가 이미 처리하는 이벤트)
    reject_as: str = "quality_rejected"
    reject_message: str = "이 답변은 품질 기준을 통과하지 못해 표시하지 않았어요."
    max_message_chars: int = 32_000
    max_total_chars: int = 200_000
    max_open_messages: int = 32
    evaluate_timeout_s: float = 30.0
    # (Phase B4) all_complete 모아 보내기 항목 중 재사용할 수 없는 것만 병렬 평가(상한). 평가 API 의 동시성 상한
    # (AI_QUALITY_EVAL_MAX_CONCURRENCY=2)과 같게 둬 GPU judge 동시 점유를 늘리지 않는다.
    max_parallel_evaluations: int = 2
    # 평가 중에도 상류 생성기를 계속 읽어 다음 에이전트 생성이 멈추지 않게 하는 선읽기 버퍼(이벤트 수). 0 = 끔.
    prefetch_events: int = 128


DEFAULT_POLICY = StreamGatePolicy()
# 경로(기능)별 정책 — 같은 경계를 쓰되 본문 크기만 다르다. 84일 로드맵 JSON 은 실측 약 15만 자(2026-11-04 캡처).
ROUTE_POLICIES: Dict[str, StreamGatePolicy] = {
    "roadmap": StreamGatePolicy(max_message_chars=400_000, max_total_chars=900_000),
    "studymate": StreamGatePolicy(reject_as="agent_error"),
}


def policy_for(feature: Optional[str]) -> StreamGatePolicy:
    return ROUTE_POLICIES.get((feature or "").strip().lower(), DEFAULT_POLICY)


def _data(ev: Dict[str, Any]) -> Dict[str, Any]:
    d = ev.get("data")
    return d if isinstance(d, dict) else ev


def _safe_part(v: Any, default: str) -> str:
    if v is None or v == "":
        return default
    s = str(v)
    return s if _SAFE_ID.match(s) else "h" + hashlib.sha256(s.encode()).hexdigest()[:12]


def _key(ev: Dict[str, Any]) -> str:
    """메시지 단위 = (turn, agent, phase). phase 로 초안/최종 같은 단계별 본문을 섞지 않는다."""
    d = _data(ev)
    k = f"{_safe_part(d.get('turnId') or d.get('turn_id'), 't')}:{_safe_part(d.get('agentId') or d.get('agent_id'), 'main')}"
    ph = d.get("phase")
    return f"{k}:{_safe_part(ph, '')}" if ph not in (None, "") else k


def _text(ev: Dict[str, Any], policy: StreamGatePolicy) -> str:
    d = _data(ev)
    for k in policy.text_fields:
        if isinstance(d.get(k), str):
            return d[k]
    return ""


def _message_texts(d: Dict[str, Any], policy: StreamGatePolicy) -> Dict[str, str]:
    """본문 메시지의 노출 텍스트 필드들. 없으면 일반 text_fields 의 첫 값."""
    out = {k: d[k] for k in _EMIT_TEXT_FIELDS if isinstance(d.get(k), str) and d[k].strip()}
    if not out:
        for k in policy.text_fields:
            if isinstance(d.get(k), str) and d[k].strip():
                out[k] = d[k]
                break
    return out


def _joined(texts: Dict[str, str]) -> str:
    seen: List[str] = []
    for v in texts.values():
        if v not in seen:
            seen.append(v)
    return "\n".join(seen)


def _struct(ev: Dict[str, Any], policy: StreamGatePolicy) -> Optional[tuple]:
    d = _data(ev)
    for k in policy.struct_fields:
        v = d.get(k)
        if isinstance(v, (dict, list)) and v:
            return k, v
    return None


def _ids_only(ev: Dict[str, Any]) -> Dict[str, Any]:
    d = _data(ev)
    out: Dict[str, Any] = {}
    for k in _ID_KEYS:
        v = d.get(k)
        if isinstance(v, bool) or isinstance(v, (int, float)):
            out[k] = v
        elif isinstance(v, str) and _SAFE_ID.match(v):
            out[k] = v
    for k in _NAME_KEYS:
        v = d.get(k)
        if isinstance(v, str) and _SAFE_NAME.match(v):
            out[k] = v
    return out


def _out(ev: Dict[str, Any], et: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = {**_ids_only(ev), **(extra or {})}
    if "eventType" in data and data["eventType"] != et:
        data["eventType"] = et
    o: Dict[str, Any] = {"event": et, "data": data}
    style = ev.get("_style")
    if style:
        o["_style"] = style
    sid = ev.get("id")
    if isinstance(sid, str) and _SAFE_ID.match(sid):
        o["id"] = sid
    return o


def _rejected(key: str, status: str, codes: List[str], score: Optional[float] = None,
              hard_fail: Optional[bool] = None) -> Dict[str, Any]:
    return {"event": "quality_rejected",
            "data": {"messageKey": key, "qualityStatus": status, "score": score, "hardFail": hard_fail,
                     "codes": sorted(set(codes))[:10]}}


@dataclass
class _Msg:
    parts: List[str] = field(default_factory=list)
    chars: int = 0
    final: Optional[Dict[str, Any]] = None
    overflow: bool = False
    last_delta: Optional[Dict[str, Any]] = None     # delta 로만 온 본문은 같은 delta 계약으로 '승인 후 전문 1회' 방출
    delta_field: str = "content"


_RID_SCOPE_RE = re.compile(r"[A-Za-z0-9._:\-]{1,100}")


def _rid_scope(request_id: Optional[str]) -> str:
    # 평가 requestId = <scope>.<n> (response-quality.v1 의 [A-Za-z0-9._:-]{8,128}). 호출자 id 가 형식에 맞지 않으면 새로 만든다.
    if request_id and _RID_SCOPE_RE.fullmatch(request_id):
        return request_id
    return "sg-" + secrets.token_hex(8)


class _Prefetch:
    """상류 async 이터레이터를 별도 작업에서 제한된 큐로 미리 읽는다(순서 보존, 상류 예외는 소비 시점에 재발생).
    평가를 기다리는 동안에도 상류(LLM 생성)가 진행된다 — 본문은 여전히 승인 후에만 방출된다."""

    _END = object()

    def __init__(self, source, maxsize: int) -> None:
        self._q: asyncio.Queue = asyncio.Queue(maxsize=max(1, maxsize))
        self._task = asyncio.ensure_future(self._run(source))

    async def _run(self, source) -> None:
        try:
            async for ev in source:
                await self._q.put(("ev", ev))
            await self._q.put(("end", None))
        except asyncio.CancelledError:
            raise
        except BaseException as e:  # noqa: BLE001 — 소비자에게 그대로 전달
            await self._q.put(("err", e))

    def __aiter__(self):
        return self

    async def __anext__(self):
        kind, val = await self._q.get()
        if kind == "ev":
            return val
        if kind == "err":
            raise val
        raise StopAsyncIteration

    async def stop(self) -> None:
        if not self._task.done():
            self._task.cancel()
        try:
            await self._task
        except BaseException:  # noqa: BLE001
            pass


async def gate_event_stream(
    source: AsyncIterator[Dict[str, Any]],
    evaluate_message: Callable[[str, str, Dict[str, Any], str], Awaitable[QualityOutput]],
    *,
    on_approved: Optional[Callable[[str, str, QualityOutput], Awaitable[None]]] = None,
    policy: StreamGatePolicy = DEFAULT_POLICY,
    request_id: Optional[str] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """이벤트 dict({'event': type, 'data': {...}}) 스트림을 품질 게이트로 감싼다.
    게이트가 만든 이벤트(quality_rejected/error/승인 본문)는 원 스트림의 직렬화 스타일(data.type / data.event)을 따른다.

    evaluate_message(key, text, src, eval_request_id) 는 반드시 eval_request_id 를 QualityInput.requestId 로 써야 한다.
    게이트는 돌아온 판정의 requestId 가 자신이 준 값과 다르면 승인으로 보지 않는다(EC2 isDisplayable 과 같은 바인딩).
    같은 본문의 판정은 이 스트림(요청) 안에서만 재사용한다 — 스트림 간 공유 없음."""
    style: Dict[str, Optional[str]] = {"v": None}

    async def tap():
        async for ev in source:
            if style["v"] is None and ev.get("_style"):
                style["v"] = ev["_style"]
            yield ev
    core = _gate_core(tap(), evaluate_message, on_approved, policy, getattr(source, "aclose", None),
                      _rid_scope(request_id))
    try:
        async for o in core:
            if style["v"] and "_style" not in o:
                o["_style"] = style["v"]
            yield o
    finally:
        await core.aclose()


async def _gate_core(source, evaluate_message, on_approved, policy: StreamGatePolicy, close_upstream,
                     rid_scope: str) -> AsyncIterator[Dict[str, Any]]:
    msgs: Dict[str, _Msg] = {}
    order: List[str] = []
    emitted: set = set()
    verdicts: Dict[str, tuple] = {}          # 본문 해시 → (QualityOutput, 평가 requestId) — 요청(스트림) 범위 재사용
    approved_fields: Dict[str, List[tuple]] = {}   # 에이전트 식별 → [(승인된 노출 필드 값들, (q, rid))]
    seq = {"n": 0}
    stats = {"evaluations": 0, "reused": 0, "aggregateReused": 0}
    total = {"chars": 0}

    def _drop(key: str) -> Optional[_Msg]:
        m = msgs.pop(key, None)
        if key in order:
            order.remove(key)
        if m is not None:
            total["chars"] -= m.chars
        return m

    def _open(key: str) -> Optional[_Msg]:
        m = msgs.get(key)
        if m is None:
            if len(msgs) >= policy.max_open_messages:
                return None
            m = msgs[key] = _Msg()
            order.append(key)
        return m

    def _append(m: _Msg, s: str) -> bool:
        if m.overflow:
            return False
        if m.chars + len(s) > policy.max_message_chars or total["chars"] + len(s) > policy.max_total_chars:
            total["chars"] -= m.chars
            m.parts.clear()
            m.chars = 0
            m.overflow = True
            return False
        m.parts.append(s)
        m.chars += len(s)
        total["chars"] += len(s)
        return True

    def _reject(key: str, src: Dict[str, Any], status: str, codes: List[str], score: Optional[float] = None,
                hard_fail: Optional[bool] = None) -> Dict[str, Any]:
        sd = _data(src) if src else {}
        if policy.reject_as == "agent_error" and (sd.get("agentId") or sd.get("agentIndex") is not None):
            # 학습메이트: 기존 계약의 '에이전트 실패'로 알린다(Spring 커버리지/React 카드가 이미 처리, 비치명).
            return _out(src, "agent_error", {"code": "QUALITY_REJECTED", "status": "FAILED", "degraded": True,
                                             "message": policy.reject_message, "qualityStatus": status,
                                             "qualityCodes": sorted(set(codes))[:10]})
        r = _rejected(key, status, codes, score, hard_fail)
        for k in ("turnId", "agentId", "agentIndex", "eventId"):
            v = _ids_only(src).get(k) if src else None
            if v is not None:
                r["data"][k] = v
        return r

    async def _verdict(key: str, text: str, src: Dict[str, Any]):
        """(QualityOutput|None, 거절 이벤트|None). 같은 본문은 한 번만 평가."""
        h = hashlib.sha256(text.encode()).hexdigest()
        hit = verdicts.get(h)
        if hit is not None:
            stats["reused"] += 1
            return hit, None
        seq["n"] += 1
        rid = f"{rid_scope}.{seq['n']}"
        stats["evaluations"] += 1
        try:
            q = await asyncio.wait_for(evaluate_message(key, text, src, rid), timeout=policy.evaluate_timeout_s)
        except asyncio.TimeoutError:
            return None, _reject(key, src, "VALIDATION_ERROR", ["EVALUATOR_TIMEOUT"])
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            return None, _reject(key, src, "VALIDATION_ERROR", ["EVALUATOR_ERROR"])
        verdicts[h] = (q, rid)
        return verdicts[h], None

    def _agent_ident(d: Dict[str, Any]) -> str:
        a = d.get("agentId") or d.get("agent_id")
        if a in (None, ""):
            a = d.get("agentIndex")
        return _safe_part(a, "main")

    def _remember_approved(d: Dict[str, Any], texts: Dict[str, str], qr: tuple) -> None:
        if texts:
            approved_fields.setdefault(_agent_ident(d), []).append((dict(texts), qr))

    def _reusable(item: Dict[str, Any], texts: Dict[str, str]) -> Optional[tuple]:
        """같은 스트림에서 같은 에이전트가 이미 승인받은 필드 값과 '완전히 같은' 필드만 싣는 항목이면 그 판정을 쓴다
        (all_complete.messages[] 가 스트림 메시지를 다시 싣는 경우 — 실캡처 소크라테스 3건 중복 평가 제거)."""
        for prev, qr in approved_fields.get(_agent_ident(item), ()):
            if texts and all(prev.get(k) == v for k, v in texts.items()):
                return qr
        return None

    async def _aggregate(ev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """all_complete.answers[]/messages[] 를 '승인된 항목만'으로 다시 만든다(없으면 None).
        예전: 종료 이벤트에서 목록을 통째로 지워 Spring 의 답변 영속화(answers[] 기반)가 끊겼다.
        재사용 불가 항목은 상한(max_parallel_evaluations) 안에서 병렬 평가하고, 결과는 원래 순서로 싣는다."""
        d = _data(ev)
        present = [f for f in policy.aggregate_fields if isinstance(d.get(f), list)]
        if not present:
            return None
        sem = asyncio.Semaphore(max(1, policy.max_parallel_evaluations))

        async def judge_item(f: str, item: Dict[str, Any]):
            texts = _message_texts(item, policy)
            text = _joined(texts)
            if not text.strip() or len(text) > policy.max_message_chars:
                return None
            qr = _reusable(item, texts)
            if qr is not None:
                stats["aggregateReused"] += 1
            else:
                async with sem:
                    qr, _rej = await _verdict(f"{_key({'data': item})}#{f}", text, {"data": item})
            if qr is None or not is_displayable(*qr):
                return None
            q = qr[0]
            return {**_ids_only(item), **texts, "quality": {"qualityStatus": q.qualityStatus.value, "score": q.score,
                                                           "evaluatorVersion": q.evaluatorVersion}}
        rebuilt: Dict[str, Any] = {}
        for f in present:
            items = [it for it in d[f][:64] if isinstance(it, dict)]
            results = await asyncio.gather(*(judge_item(f, it) for it in items))
            rebuilt[f] = [r for r in results if r is not None]
        return rebuilt

    async def _flush(key: str, emit_as: Optional[str] = None) -> AsyncIterator[Dict[str, Any]]:
        m = _drop(key)
        if m is None:
            return
        if m.overflow:
            yield _reject(key, m.final or m.last_delta or {}, "REJECTED", ["STREAM_MESSAGE_TOO_LARGE"], hard_fail=True)
            return
        final = m.final or {}
        src = final or m.last_delta or {}
        # 구조화 결과가 있으면 그것이 본문이다(fetch-stream 의 message 는 고정 UI 문구라 본문으로 쓰지 않는다)
        struct = _struct(final, policy) if final else None
        texts = {} if (struct is not None or not final) else _message_texts(_data(final), policy)
        text = _joined(texts)
        if not text and struct is None:
            text = "".join(m.parts)
        if struct is not None:
            text = json.dumps(struct[1], ensure_ascii=False, sort_keys=True)
        if not text.strip():
            return
        if len(text) > policy.max_message_chars:
            yield _reject(key, src, "REJECTED", ["STREAM_MESSAGE_TOO_LARGE"], hard_fail=True)
            return
        h = hashlib.sha256(text.encode()).hexdigest()
        if (key, h) in emitted:
            return                                         # 같은 메시지 재전송은 한 번만 평가/노출
        emitted.add((key, h))
        # 같은 본문(예: partial → complete 최종본)은 재평가하지 않는다. 평가 실패/타임아웃 = 미검증 = 노출 금지.
        qr, rej = await _verdict(key, text, final or src)
        if rej is not None:
            yield rej
            return
        q = qr[0]
        if not is_displayable(*qr):
            yield _reject(key, src, q.qualityStatus.value, [v.code for v in q.violations], q.score, q.hardFail)
            return
        if struct is None:
            _remember_approved(_data(final) if final else _data(m.last_delta or {}),
                               texts if texts else {m.delta_field if not final else "content": text}, qr)
        if on_approved is not None:
            try:
                await on_approved(key, text, q)
            except Exception:  # noqa: BLE001 — 수집 실패가 응답을 막지 않는다
                pass
        quality = {"qualityStatus": q.qualityStatus.value, "score": q.score, "evaluatorVersion": q.evaluatorVersion}
        if not final and m.last_delta is not None:
            # delta 계약(fetch-stream/token SSE)은 그대로: 같은 타입/필드로 '승인된 전문'을 한 번에 보낸다.
            dl = m.last_delta
            yield _out(dl, str(dl.get("event")).lower(), {m.delta_field: text, "quality": quality})
            return
        et = str(final.get("event") or "agent_answer").lower() if final else "agent_answer"
        body = {struct[0]: struct[1]} if struct is not None else (dict(texts) if texts else {"content": text})
        name = emit_as or (et if et in policy.message_events else "agent_answer")
        yield _out(final or {}, name, {**body, "quality": quality})

    pump = _Prefetch(source, policy.prefetch_events) if policy.prefetch_events > 0 else None
    try:
        try:
            async for ev in (pump if pump is not None else source):
                et = str(ev.get("event") or ev.get("type") or "").lower()
                if et in policy.progress_events:
                    yield _out(ev, et)
                    continue
                key = _key(ev)
                if et in policy.error_events:
                    _drop(key)                              # 실패한 메시지의 미완성 본문은 평가하지 않는다
                    dd = _data(ev)
                    code_key = next((k for k in ("errorCode", "code", "error_code") if k in dd), "errorCode")
                    raw_code = dd.get(code_key)
                    code = raw_code if isinstance(raw_code, str) and _SAFE_CODE.match(raw_code) else "UPSTREAM_ERROR"
                    # 이벤트 이름(agent_error/error/stream_error)과 코드 필드 이름은 원 계약 그대로, 문구는 버린다.
                    yield _out(ev, et, {code_key: code})
                    continue
                if et in policy.delta_events:
                    m = _open(key)
                    if m is None:
                        yield _rejected(key, "REJECTED", ["STREAM_BUFFER_LIMIT"], hard_fail=True)
                        continue
                    d = _data(ev)
                    fld = next((k for k in policy.text_fields if isinstance(d.get(k), str)), "content")
                    m.last_delta, m.delta_field = {**ev, "event": et}, fld
                    _append(m, _text(ev, policy))
                    continue
                if et in policy.message_events:
                    m = _open(key)
                    if m is None:
                        yield _reject(key, ev, "REJECTED", ["STREAM_BUFFER_LIMIT"], hard_fail=True)
                        continue
                    m.final = {**ev, "event": et}
                    async for out in _flush(key):
                        yield out
                    continue
                if et in policy.terminal_events:
                    for k in list(order):
                        async for out in _flush(k):
                            yield out
                    agg = await _aggregate(ev)
                    if agg is not None:
                        yield _out(ev, et, agg)
                        continue
                    # 최종 이벤트가 구조화 결과(퀴즈 questions/로드맵 roadmap)를 싣는 계약이면 그것도 검증 후에만 싣는다.
                    if _struct(ev, policy) is not None:
                        tkey = key + "#final"
                        m = _open(tkey)
                        if m is not None:
                            m.final = {**ev, "event": et}
                            shown = False
                            async for out in _flush(tkey, emit_as=et):
                                shown = shown or out["event"] == et
                                yield out
                            if shown:
                                continue
                    yield _out(ev, et)
                    continue
                # 알 수 없는 타입: 본문일 수 있으므로 내보내지 않고, 다른 메시지에 섞지도 않는다.
                if _text(ev, policy) or _struct(ev, policy):
                    yield _rejected(key, "REJECTED", ["UNKNOWN_EVENT_TYPE"])
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — 상류 실패: 잘린 본문은 버리고 안정된 오류만 알린다
            for k in list(order):
                _drop(k)
            yield {"event": "error", "data": {"errorCode": "STREAM_SOURCE_ERROR", "code": "STREAM_SOURCE_ERROR"}}
            return
        for k in list(order):
            async for out in _flush(k):
                yield out
    finally:
        if pump is not None:
            await pump.stop()                    # 선읽기 작업을 먼저 끝내야 상류 aclose 가 '실행 중' 오류 없이 닫힌다
        for closer in (getattr(source, "aclose", None), close_upstream):
            if closer is not None:
                try:
                    await closer()
                except Exception:  # noqa: BLE001
                    pass


# ── 전송 포맷 어댑터: 라이브 생성기가 내는 SSE/NDJSON '문자열'을 이벤트 dict 로, 그리고 다시 문자열로 ──────────
def _parse_sse_frame(frame: str) -> Optional[Dict[str, Any]]:
    name, sid, data_lines, comment = None, None, [], False
    for line in frame.split("\n"):
        if not line:
            continue
        if line.startswith(":"):
            comment = True
            continue
        f, _, v = line.partition(":")
        v = v[1:] if v.startswith(" ") else v
        if f == "event":
            name = v.strip()
        elif f == "data":
            data_lines.append(v)
        elif f == "id":
            sid = v.strip()
    if not data_lines and name is None:
        return {"event": "__comment__", "data": {}} if comment else None
    raw = "\n".join(data_lines)
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {"text": raw}
    if not isinstance(data, dict):
        data = {"text": raw}
    if name:
        style, et = "sse_event", name
    elif isinstance(data.get("event"), str):
        style, et = "data_event", data["event"]
    else:
        style, et = "data_type", str(data.get("type") or "message")
    ev: Dict[str, Any] = {"event": et, "data": data, "_style": style}
    if sid:
        ev["id"] = sid
    return ev


async def parse_sse(chunks: AsyncIterator[Union[str, bytes]], *, max_frame_chars: int = 256_000
                    ) -> AsyncIterator[Dict[str, Any]]:
    buf = ""
    async for ch in chunks:
        buf += ch.decode("utf-8", "replace") if isinstance(ch, (bytes, bytearray)) else str(ch)
        buf = buf.replace("\r\n", "\n")
        while "\n\n" in buf:
            frame, buf = buf.split("\n\n", 1)
            ev = _parse_sse_frame(frame)
            if ev is not None:
                yield ev
        if len(buf) > max_frame_chars:          # 구분자 없는 거대 프레임 → 버리고 실패로 본다
            raise ValueError("SSE_FRAME_TOO_LARGE")
    if buf.strip():
        ev = _parse_sse_frame(buf)
        if ev is not None:
            yield ev


async def parse_ndjson(chunks: AsyncIterator[Union[str, bytes]], *, max_line_chars: int = 256_000
                       ) -> AsyncIterator[Dict[str, Any]]:
    buf = ""
    async for ch in chunks:
        buf += ch.decode("utf-8", "replace") if isinstance(ch, (bytes, bytearray)) else str(ch)
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            if line.strip():
                yield _ndjson_event(line)
        if len(buf) > max_line_chars:
            raise ValueError("NDJSON_LINE_TOO_LARGE")
    if buf.strip():
        yield _ndjson_event(buf)


def _ndjson_event(line: str) -> Dict[str, Any]:
    try:
        data = json.loads(line)
    except ValueError:
        return {"event": "message", "data": {"text": line}, "_style": "data_event"}
    if not isinstance(data, dict):
        return {"event": "message", "data": {"text": line}, "_style": "data_event"}
    if isinstance(data.get("event"), str):
        return {"event": data["event"], "data": data, "_style": "data_event"}
    return {"event": str(data.get("type") or "message"), "data": data, "_style": "data_type"}


def _wire_data(ev: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(ev.get("data") or {})
    style = ev.get("_style")
    if style == "data_type":
        data["type"] = ev.get("event")
    elif style == "data_event":
        data["event"] = ev.get("event")
    return data


def to_sse(ev: Dict[str, Any]) -> str:
    if ev.get("event") == "__comment__":
        return ": keepalive\n\n"
    head = f"id: {ev['id']}\n" if ev.get("id") else ""
    data = json.dumps(_wire_data(ev), ensure_ascii=False)
    if ev.get("_style") in ("data_type", "data_event"):
        return f"{head}data: {data}\n\n"
    return f"{head}event: {ev.get('event', 'message')}\ndata: {data}\n\n"


def to_ndjson(ev: Dict[str, Any]) -> str:
    if ev.get("event") == "__comment__":
        return ""
    data = _wire_data(ev)
    if ev.get("_style") not in ("data_type", "data_event"):
        data["event"] = ev.get("event")
    return json.dumps(data, ensure_ascii=False) + "\n"


async def wrap_sse_stream(chunks: AsyncIterator[Union[str, bytes]], evaluate_message, *, on_approved=None,
                          policy: StreamGatePolicy = DEFAULT_POLICY, request_id: Optional[str] = None) -> AsyncIterator[str]:
    """StreamingResponse(media_type='text/event-stream') 의 본문 생성기를 그대로 감싼다."""
    async for ev in gate_event_stream(parse_sse(chunks), evaluate_message, on_approved=on_approved, policy=policy,
                                      request_id=request_id):
        s = to_sse(ev)
        if s:
            yield s


async def wrap_ndjson_stream(chunks: AsyncIterator[Union[str, bytes]], evaluate_message, *, on_approved=None,
                             policy: StreamGatePolicy = DEFAULT_POLICY, request_id: Optional[str] = None) -> AsyncIterator[str]:
    async for ev in gate_event_stream(parse_ndjson(chunks), evaluate_message, on_approved=on_approved, policy=policy,
                                      request_id=request_id):
        s = to_ndjson(ev)
        if s:
            yield s
