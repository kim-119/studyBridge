"""학습메이트 턴 실행 런타임 — SSE(stream) 와 JSON(non-stream) 이 같은 도메인 결과를 쓴다.

   validate_before_open ─► RequestRuntime(cancel/budget/requestId) ─► domain generator
        │                                                               (multi_agent_service.build_stream_generator)
        ▼                                                                         │
   422 JSON(스트림 열기 전)                          identity 정규화(CanonicalAgent) ◄┘
                                                      │
                               Sequencer(타입드 계약·순서·짝·dedup) ─► SSE serializer | JSON collector

취소 체인: 절단 감시 태스크(request.is_disconnected, 0.5s) → CancelToken → 파이프라인/엔진/LLM 스트림.
uvicorn 0.49 는 ASGI spec 2.4 라 Starlette 가 대기 중 절단을 스스로 감지하지 않는다(쓰기 실패 시에만).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from fastapi.responses import JSONResponse

from app.studymate import runtime_context as RC
from app.studymate import sse_contract as SC
from app.studymate.budget import TurnBudget
from app.studymate.profile_contract import CanonicalAgent, canonicalize_agents

logger = logging.getLogger("studybridge.studymate.stream")

_SENTINEL = object()
DEDICATED = ("debate", "socratic", "simulation")


def _next(gen):
    try:
        return next(gen)
    except StopIteration:
        return _SENTINEL


def _err(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": {"code": code, "message": message, **extra}})


def validate_before_open(payload: Any) -> Tuple[Optional[Any], Optional[JSONResponse]]:
    """스트림(200)을 열기 전에 알 수 있는 모든 오류를 422 JSON 으로 돌려준다."""
    if not isinstance(payload, dict):
        return None, _err(422, "INVALID_BODY", "요청 본문은 JSON 객체여야 합니다.")
    msg = payload.get("message")
    if msg is None or not str(msg).strip():
        return None, _err(422, "MESSAGE_REQUIRED", "message 는 비어 있을 수 없습니다.")
    from pydantic import ValidationError
    from app.schemas.multi_chat_schema import MultiChatRequest
    try:
        req = MultiChatRequest(**payload)
    except ValidationError as e:
        errs = [{"loc": ".".join(str(x) for x in er.get("loc", ())), "type": er.get("type")} for er in e.errors()[:10]]
        return None, _err(422, "INVALID_REQUEST", "요청 형식이 올바르지 않습니다.", errors=errs)
    from app.services import mode_router
    try:
        mode_router.resolve_mode(payload.get("mode"), payload.get("learningMode") or payload.get("learning_mode"))
    except mode_router.UnsupportedModeError as exc:
        return None, JSONResponse(status_code=422, content={"detail": mode_router.error_detail(exc)})
    target = str(payload.get("targetAgentId") or payload.get("target_agent_id") or "").strip()
    if target:
        from app.services.multi_agent_service import UnknownTargetAgentError, _filter_agents, _get_agents
        try:
            _filter_agents(_get_agents(req), req.targetAgentId)
        except UnknownTargetAgentError as e:
            return None, JSONResponse(status_code=422, content={"detail": {
                "code": "TARGET_AGENT_NOT_FOUND", "targetAgentId": e.target_id, "availableAgentIds": e.available,
                "message": "지정한 교수(targetAgentId)가 이 방의 에이전트 목록에 없습니다."}})
    return req, None


def resolved_mode(req: Any) -> str:
    from app.services import mode_router
    try:
        m = mode_router.resolve_request_mode(req)
    except Exception:
        return "basic"
    return "basic" if m not in DEDICATED else m


def new_runtime_for(req: Any, request_id: Optional[str]) -> RC.RequestRuntime:
    rt = RC.new_runtime(request_id=request_id or f"req_{uuid.uuid4().hex[:12]}")
    mode = resolved_mode(req)
    if mode in DEDICATED:
        rt.budget = TurnBudget.for_kind(mode)
    else:
        from app.services.multi_agent_service import _filter_agents, _get_agents
        try:
            n = len(_filter_agents(_get_agents(req), req.targetAgentId))
        except Exception:
            n = len(req.agents or []) or 1
        rt.budget = TurnBudget.for_kind("basic_single" if n <= 1 else "basic_multi")
    return rt


def canonical_room(req: Any) -> Dict[str, CanonicalAgent]:
    from app.services.multi_agent_service import _get_agents
    return {a.agentId: a for a in canonicalize_agents(_get_agents(req))}


_IDENTITY_KEYS = ("personality", "personalityKey", "personalityLabel", "knowledgeLevel", "knowledgeLevelKey",
                  "knowledgeLevelLabel", "personalityResolved", "knowledgeLevelResolved")


def apply_identity(data: Dict[str, Any], room: Dict[str, CanonicalAgent]) -> Dict[str, Any]:
    """transport 와 무관하게 같은 identity 필드를 보장(agentId 기준, 이름 기준 금지)."""
    def fix(d: Dict[str, Any]) -> None:
        aid = d.get("agentId")
        if aid in (None, ""):
            return
        ca = room.get(str(aid))
        if ca is None:
            return
        d.update(ca.identity_payload())
        d.setdefault("agentName", ca.name)
        if d.get("agentIndex") in (None, ""):
            d["agentIndex"] = ca.agentIndex
    fix(data)
    for key in ("answers", "messages", "agentErrors"):
        if isinstance(data.get(key), list):
            for it in data[key]:
                if isinstance(it, dict):
                    fix(it)
    return data


def coverage_from_sequencer(seq: SC.Sequencer, selected: List[str], data: Dict[str, Any], targeted: bool) -> Dict[str, Any]:
    if isinstance(data.get("agentCoverage"), dict):
        return data["agentCoverage"]
    emitted = sorted({str(a.get("agentId")) for a in seq.answers if a.get("agentId")})
    failed = sorted({str(a.get("agentId")) for a in seq.errors if a.get("agentId")})
    executed = sorted(set(seq.started_ids) - {""})
    route = data.get("route")
    intentional = bool(data.get("suppressAgentFill")) and route in ("memory_recall", "summary_only", "direct_reply")
    suppressed = [s for s in selected if s not in emitted and s not in failed] if intentional else []
    gap = [s for s in selected if s not in emitted and s not in failed and s not in suppressed]
    return {"selected": selected, "executed": executed, "emitted": emitted, "failed": failed,
            "suppressed": suppressed, "suppressedReason": route if intentional else None,
            "targeted": targeted, "unexpectedGap": gap}


def surface_missing_agents(seq: SC.Sequencer, data: Dict[str, Any], selected: List[str],
                           room: Dict[str, CanonicalAgent], req: Any) -> List[Tuple[str, Dict[str, Any]]]:
    """정상 multi-agent(의도적 partial 아님)에서 선택됐는데 발화가 전혀 없는 교수를 agent_error 로 드러낸다.
    (이전: 그럴듯한 필러 '답변'을 합성 → 실패가 정상처럼 보이고 Spring 이 AI 메시지로 영속)"""
    if data.get("suppressAgentFill") or getattr(req, "targetAgentId", None) not in (None, ""):
        return []
    answered = {str(a.get("agentId")) for a in seq.answers} | {str(e.get("agentId")) for e in seq.errors}
    started = set(seq.started_ids)
    out: List[Tuple[str, Dict[str, Any]]] = []
    missing = [aid for aid in selected if aid not in answered and aid not in started]
    for aid in missing:
        ca = room.get(aid)
        base = {"agentId": ca.agentIdRaw if ca else aid, "agentIndex": ca.agentIndex if ca else None,
                "agentName": ca.name if ca else None, **(ca.identity_payload() if ca else {})}
        out.extend(seq.feed("agent_start", {"type": "agent_start", "visible": True, **base}))
        out.extend(seq.feed("agent_error", {"type": "agent_error", "visible": True, "status": "FAILED", "degraded": True,
                                            "code": "AGENT_ANSWER_MISSING",
                                            "message": "이 교수의 답변을 받지 못했어요. 잠시 후 다시 시도해 주세요.", **base}))
    if missing:
        data["missingAgentIds"] = [room[a].agentIdRaw if a in room else a for a in missing]
        logging.getLogger("studybridge.multi_chat_stream_compat").error(
            "[AGENT-FILL] 실행 누락 %d명 missing=%s — agent_error 로 드러냄(필러 합성 금지)", len(missing), missing)
    return out


def finalize_all_complete(data: Dict[str, Any], seq: SC.Sequencer, req: Any, rt: RC.RequestRuntime,
                          selected: List[str], mode: str) -> Dict[str, Any]:
    from multi_chat_stream_compat import _messages_from_complete_payload, _stream_agent_maps
    payload = req.model_dump(by_alias=False)
    _, by_id, by_name = _stream_agent_maps(payload)
    data.setdefault("groupId", req.groupId)
    data.setdefault("roomId", req.roomId)
    data.setdefault("agentRoomId", req.agentRoomId)
    data["mode"] = data.get("mode") or mode
    ans = data.get("answers") if isinstance(data.get("answers"), list) else []
    # 실패 문구가 answers 에 섞이면 Spring 이 AI 메시지로 영속한다 → 성공만 남긴다.
    clean = [a for a in ans if isinstance(a, dict) and str(a.get("status") or "SUCCESS").upper() not in ("FAILED", "ERROR")]
    if len(clean) != len(ans):
        seq.contract_repairs.append(f"failed_answers_removed:{len(ans) - len(clean)}")
    data["answers"] = clean
    data["messages"] = _messages_from_complete_payload(data, payload, by_id, by_name)
    errs = data.get("agentErrors") if isinstance(data.get("agentErrors"), list) else []
    if not errs and seq.errors:
        errs = [{k: v for k, v in e.items() if k not in ("eventId",)} for e in seq.errors]
    data["agentErrors"] = errs
    cov = coverage_from_sequencer(seq, selected, data, bool(getattr(req, "targetAgentId", None)))
    data["agentCoverage"] = cov
    data["degraded"] = bool(data.get("degraded")) or bool(cov.get("failed")) or bool(cov.get("unexpectedGap"))
    data.setdefault("success", bool(clean) or data.get("status") == "BLOCKED" or bool(data.get("memoryAnswer")))
    data["sse"] = seq.stats()
    if not data.get("budget") and rt.budget:
        data["budget"] = {k: v for k, v in rt.budget.snapshot().items() if k in ("kind", "elapsedMs", "skippedStages")}
    if rt.degraded_notes:
        # 사용자 노출은 카테고리만(원인 상세는 서버 로그)
        notes = set(data.get("degradedNotes") or []) | set(rt.degraded_notes)
        data["degradedNotes"] = sorted({n.split(":", 1)[0] for n in notes})
    if cov.get("unexpectedGap"):
        logger.error("[AGENT-COVERAGE] request=%s mode=%s unexpected gap=%s", rt.request_id, mode, cov["unexpectedGap"])
    logging.getLogger("studybridge.multi_chat_stream_compat").info(
        "[MULTI-CHAT-ROUTE] request=%s turn=%s mode=%s route=%s selected_agent_ids=%s executed_agent_ids=%s "
        "emitted_agent_ids=%s failed_agent_ids=%s suppressed=%s suppress_agent_fill=%s reason=%s dialogue_act=%s "
        "degraded=%s sse=%s", rt.request_id, rt.turn_id, mode, data.get("route"),
        cov.get("selected"), cov.get("executed"), cov.get("emitted"), cov.get("failed"),
        cov.get("suppressed"), bool(data.get("suppressAgentFill")), cov.get("suppressedReason"),
        data.get("dialogueAct"), data["degraded"], seq.stats())
    return data


def timeout_closure(seq: SC.Sequencer, req: Any, rt: RC.RequestRuntime, selected: List[str], mode: str,
                    code: str, room: Dict[str, CanonicalAgent]) -> List[Tuple[str, Dict[str, Any]]]:
    """턴 예산/워치독 초과 또는 업스트림 누락: 성공한 답변은 보존하고 all_complete 로 닫는다."""
    out: List[Tuple[str, Dict[str, Any]]] = []
    for st in seq.open_starts():
        err = {"type": "agent_error", "agentId": st.get("agentId"), "agentIndex": st.get("agentIndex"),
               "agentName": st.get("agentName"), "phase": st.get("phase"), "actType": st.get("actType"),
               "displayOrder": st.get("displayOrder"), "status": "FAILED", "degraded": True, "code": code,
               "message": "이번 턴의 시간 예산을 넘어 이 답변 생성을 중단했어요."}
        out.extend(seq.feed("agent_error", apply_identity(err, room)))
    if not seq.all_complete_sent:
        answers = [{k: v for k, v in a.items() if k != "eventId"} for a in seq.answers]
        ac = {"type": "all_complete", "mode": mode, "learningMode": mode, "phase": "ALL_COMPLETE", "visible": True,
              "status": "PARTIAL" if answers else "FAILED", "code": code, "degraded": True,
              "answers": answers, "route": "turn_closure", "suppressAgentFill": True}
        ac = finalize_all_complete(ac, seq, req, rt, selected, mode)
        out.extend(seq.feed("all_complete", ac))
    return out


async def _watch_disconnect(request: Any, rt: RC.RequestRuntime, interval: float = 0.5) -> None:
    try:
        while not rt.cancel.cancelled:
            if await request.is_disconnected():
                rt.cancel.cancel("client_disconnected")
                logger.info("[SSE-CANCEL] request=%s client disconnected — 새 추론 시작 금지", rt.request_id)
                return
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        return
    except Exception as e:  # 감시 실패는 스트림을 막지 않는다(로그만)
        logger.warning("[SSE-CANCEL] watcher error: %s", type(e).__name__)


def _heartbeat_s() -> float:
    try:
        return max(2.0, float(os.getenv("AI_STREAM_HEARTBEAT_SECONDS", "10")))
    except (TypeError, ValueError):
        return 10.0


def _grace_s() -> float:
    try:
        return max(5.0, float(os.getenv("STUDYMATE_WATCHDOG_GRACE_S", "25")))
    except (TypeError, ValueError):
        return 25.0


async def stream_turn(request: Any, req: Any, rt: RC.RequestRuntime, *, generator_factory=None) -> AsyncGenerator[str, None]:
    from app.services import multi_chat_redis_memory as MEM
    from app.studymate import memory_summary as MS

    mode = resolved_mode(req)
    seq = SC.Sequencer(rt.request_id, rt.turn_id, str(getattr(req, "mode", None) or mode).lower())
    seq.mode = mode
    room = canonical_room(req)
    from app.services.multi_agent_service import _filter_agents, _get_agents
    selected = [str(a.agentId if a.agentId is not None else a.id) for a in _filter_agents(_get_agents(req), req.targetAgentId)]
    started = time.time()
    token = RC.set_current(rt)
    watcher = asyncio.create_task(_watch_disconnect(request, rt))
    mem_meta = None
    final_text = ""
    status = "done"
    try:
        try:
            req, mem_meta = await MEM.attach_memory_to_request(req)
        except Exception as e:
            rt.note("memory_attach_failed")
            logger.warning("[SSE] memory attach failed request=%s: %s", rt.request_id, type(e).__name__)
        if generator_factory is not None:
            gen = generator_factory(req)
        else:
            from app.services.multi_agent_service import build_stream_generator
            gen = build_stream_generator(req)
        hb = _heartbeat_s()
        hard_deadline = (rt.budget.deadline if rt.budget else started + 300) + _grace_s()
        while True:
            if rt.cancel.cancelled:
                status = "cancelled"
                break
            task = asyncio.ensure_future(asyncio.to_thread(_next, gen))
            item = None
            timed_out = False
            while True:
                done_set, _ = await asyncio.wait({task}, timeout=hb)
                if done_set:
                    item = task.result()
                    break
                if rt.cancel.cancelled:
                    break
                if time.time() > hard_deadline:
                    timed_out = True
                    rt.cancel.cancel("turn_timeout")
                    break
                open_starts = seq.open_starts()
                for name, d in seq.feed("heartbeat", {"elapsedMs": int((time.time() - started) * 1000),
                                                      "agentIndex": open_starts[-1].get("agentIndex") if open_starts else None}):
                    yield SC.serialize(name, d)
            if timed_out:
                logger.error("[SSE-TIMEOUT] request=%s watchdog deadline exceeded — closing turn", rt.request_id)
                for name, d in timeout_closure(seq, req, rt, selected, mode, "TURN_TIMEOUT", room):
                    yield SC.serialize(name, d)
                status = "timeout"
                break
            if rt.cancel.cancelled:
                # 절단 이후에는 업스트림이 무엇을 돌려줘도(종료 포함) 끊긴 연결에 이벤트/ done 을 보내지 않는다.
                status = "cancelled"
                break
            if item is _SENTINEL:
                break
            if not isinstance(item, dict):
                continue
            name = item.get("event") or "message"
            data = item.get("data") if isinstance(item.get("data"), dict) else {"content": item.get("data")}
            data = apply_identity(dict(data), room)
            if name == "all_complete":
                for n0, d0 in surface_missing_agents(seq, data, selected, room, req):
                    yield SC.serialize(n0, d0)
                data = finalize_all_complete(data, seq, req, rt, selected, mode)
                try:
                    final_text = MEM.extract_assistant_text_from_complete_event(data) or ""
                except Exception:
                    final_text = ""
            for n2, d2 in seq.feed(name, data):
                yield SC.serialize(n2, d2)
        if status in ("done", "timeout"):
            if not seq.all_complete_sent:
                seq.contract_repairs.append("all_complete_missing_upstream")
                for name, d in timeout_closure(seq, req, rt, selected, mode, "UPSTREAM_INCOMPLETE", room):
                    yield SC.serialize(name, d)
            n, d = seq.done("done" if status == "done" else "timeout", int((time.time() - started) * 1000),
                            {"sse": seq.stats()})
            yield SC.serialize(n, d)
            if status == "done" and mem_meta is not None and getattr(mem_meta, "enabled", False) and final_text \
                    and not rt.cancel.cancelled:
                await _persist(MEM, mem_meta, final_text, rt.request_id)
            if status == "done":
                try:
                    MS.schedule_update(req, final_text)
                except Exception as e:
                    logger.warning("[SSE] summary schedule failed: %s", type(e).__name__)
    except (asyncio.CancelledError, GeneratorExit):
        status = "cancelled"
        rt.cancel.cancel("client_disconnected")
        raise
    except Exception as exc:
        status = "error"
        logger.exception("[SSE] stream error request=%s: %s", rt.request_id, type(exc).__name__)
        rt.cancel.cancel("stream_error")
        if not seq.done_sent:
            if seq.answers:
                # 이미 답변을 흘렸다 → Spring failover(중복 재생성)를 피하도록 턴을 닫는다.
                for name, d in timeout_closure(seq, req, rt, selected, mode, "STREAM_INTERNAL_ERROR", room):
                    yield SC.serialize(name, d)
            else:
                err = {"type": "error", "phase": "ERROR", "visible": True, "status": "error",
                       "code": "STREAM_ERROR", "reason": type(exc).__name__,
                       "message": "AI 스트리밍 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."}
                yield SC.serialize("error", SC.envelope("error", err, request_id=rt.request_id,
                                                          turn_id=rt.turn_id, mode=mode))
            n, d = seq.done("error", int((time.time() - started) * 1000), {"sse": seq.stats()})
            yield SC.serialize(n, d)
    finally:
        watcher.cancel()
        if status != "done":
            rt.cancel.cancel(status)
        logger.info("[SSE-END] request=%s turn=%s status=%s elapsedMs=%d sse=%s", rt.request_id, rt.turn_id,
                    status, int((time.time() - started) * 1000), seq.stats())
        RC.reset(token)


async def _persist(MEM, meta, text, request_id):
    try:
        await MEM.persist_turn(meta, None, text)
    except Exception as e:
        logger.warning("[SSE] memory persist failed request=%s: %s", request_id, type(e).__name__)


def collect_turn(req: Any, rt: RC.RequestRuntime) -> Tuple[int, Dict[str, Any]]:
    """non-stream: 같은 domain generator + 같은 Sequencer/identity/finalize → JSON."""
    from app.services.multi_agent_service import _filter_agents, _get_agents, build_stream_generator
    mode = resolved_mode(req)
    seq = SC.Sequencer(rt.request_id, rt.turn_id, mode)
    room = canonical_room(req)
    selected = [str(a.agentId if a.agentId is not None else a.id) for a in _filter_agents(_get_agents(req), req.targetAgentId)]
    token = RC.set_current(rt)
    final: Dict[str, Any] = {}
    error_event: Optional[Dict[str, Any]] = None
    try:
        for item in build_stream_generator(req):
            if rt.budget is not None and time.time() > rt.budget.deadline + _grace_s():
                rt.cancel.cancel("turn_timeout")
                for name, d in timeout_closure(seq, req, rt, selected, mode, "TURN_TIMEOUT", room):
                    if name == "all_complete":
                        final = d
                break
            if not isinstance(item, dict):
                continue
            name = item.get("event") or "message"
            data = apply_identity(dict(item.get("data") or {}), room)
            if name == "all_complete":
                surface_missing_agents(seq, data, selected, room, req)
                data = finalize_all_complete(data, seq, req, rt, selected, mode)
            for n2, d2 in seq.feed(name, data):
                if n2 == "all_complete":
                    final = d2
                elif n2 == "error":
                    error_event = d2
        if not final:
            for name, d in timeout_closure(seq, req, rt, selected, mode,
                                           "UPSTREAM_INCOMPLETE" if error_event is None else (error_event.get("code") or "STREAM_ERROR"), room):
                if name == "all_complete":
                    final = d
    finally:
        RC.reset(token)
    body = {k: v for k, v in final.items() if k not in ("type", "eventType", "isFinal")}
    body["mode"] = body.get("mode") or mode
    if error_event is not None:
        body.setdefault("code", error_event.get("code"))
        body.setdefault("message", error_event.get("message"))
    ok = bool(body.get("answers")) or body.get("status") == "BLOCKED" or bool(body.get("memoryAnswer"))
    body["success"] = ok
    status_code = 200 if ok else 503
    return status_code, body
