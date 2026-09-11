import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger("studybridge.multi_chat_stream_compat")

router = APIRouter(prefix="/api/ai", tags=["ai-stream-compat"])

_STREAM_SENTINEL = object()


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data or {}, ensure_ascii=False)}\n\n"


PERSONALITY_LABEL_MAP = {
    "친절": "friendly", "친절형": "friendly", "친근함": "friendly",
    "비판": "critical", "비판형": "critical", "솔직함": "critical",
    "논리": "logical", "논리형": "logical", "전문적": "logical",
    "창의": "creative", "창의형": "creative", "독특함": "creative",
    "간결": "concise", "간결형": "concise", "효율적": "concise",
    "츤데레": "coach", "코치": "coach", "냉소적": "coach",
}

KNOWLEDGE_LABEL_MAP = {
    "입문": "beginner", "초급": "beginner", "학사": "undergraduate", "학부": "undergraduate",
    "석사": "master", "박사": "phd", "전문가": "expert",
}


def _resolve_label(value: Any, mapping: Dict[str, str], default: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    lower = raw.lower()
    for label, key in mapping.items():
        if raw == label or lower == label.lower() or label.replace(" ", "") in raw.replace(" ", ""):
            return key
    return lower.replace(" ", "_")


def _normalize_stream_agent(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    raw = raw or {}
    personality_raw = raw.get("personality") or raw.get("persona") or raw.get("type") or raw.get("personalityLabel") or raw.get("personality_label")
    knowledge_raw = raw.get("knowledgeLevel") or raw.get("knowledge_level") or raw.get("level") or raw.get("knowledgeLevelLabel") or raw.get("knowledge_level_label")
    personality = _resolve_label(personality_raw, PERSONALITY_LABEL_MAP, os.getenv("AI_DEFAULT_PERSONALITY", "friendly"))
    knowledge = _resolve_label(knowledge_raw, KNOWLEDGE_LABEL_MAP, os.getenv("AI_DEFAULT_KNOWLEDGE_LEVEL", "undergraduate"))
    return {
        "agentId": raw.get("agentId") or raw.get("agent_id") or raw.get("id") or f"agent-{index + 1}",
        "agentName": raw.get("name") or raw.get("agentName") or raw.get("agent_name") or raw.get("displayName") or f"에이전트 {index + 1}",
        "personality": personality,
        "personalityLabel": raw.get("personalityLabel") or raw.get("personality_label") or os.getenv("AI_DEFAULT_PERSONALITY_LABEL", "친절형"),
        "knowledgeLevel": knowledge,
        "knowledgeLevelLabel": raw.get("knowledgeLevelLabel") or raw.get("knowledge_level_label") or os.getenv("AI_DEFAULT_KNOWLEDGE_LEVEL_LABEL", "학사"),
        "role": raw.get("role") or raw.get("agentRole") or raw.get("agent_role") or os.getenv("AI_DEFAULT_AGENT_ROLE", "학습 지원"),
    }


def _stream_agent_maps(payload: Dict[str, Any]):
    agents = [_normalize_stream_agent(a, idx) for idx, a in enumerate(payload.get("agents") or [])]
    by_id = {str(a.get("agentId")): a for a in agents if a.get("agentId") is not None}
    by_name = {str(a.get("agentName")): a for a in agents if a.get("agentName")}
    return agents, by_id, by_name


def _find_stream_agent(data: Dict[str, Any], by_id: Dict[str, Dict[str, Any]], by_name: Dict[str, Dict[str, Any]], index: int) -> Dict[str, Any]:
    agent = by_id.get(str(data.get("agentId"))) if data.get("agentId") is not None else None
    if not agent:
        agent = by_name.get(str(data.get("agentName") or data.get("name") or ""))
    if agent:
        return agent
    return _normalize_stream_agent(data, index - 1)


def _message_from_stream_answer(data: Dict[str, Any], agent: Dict[str, Any], mode: str, sequence: int, group_id: Any, room_id: Any) -> Dict[str, Any]:
    content = data.get("content") or data.get("answer") or data.get("feedback") or ""
    return {
        "senderType": "AGENT",
        "agentId": data.get("agentId") or agent.get("agentId"),
        "agentName": data.get("agentName") or agent.get("agentName"),
        "personality": data.get("personality") or agent.get("personality"),
        "personalityLabel": data.get("personalityLabel") or agent.get("personalityLabel"),
        "knowledgeLevel": data.get("knowledgeLevel") or agent.get("knowledgeLevel"),
        "knowledgeLevelLabel": data.get("knowledgeLevelLabel") or agent.get("knowledgeLevelLabel"),
        "role": data.get("role") or agent.get("role"),
        "mode": mode,
        "round": data.get("round") or 1,
        "sequence": data.get("sequence") or data.get("displayOrder") or sequence,
        "content": content,
        "createdAt": data.get("createdAt") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "groupId": group_id,
        "roomId": room_id,
    }


def _enrich_stream_event(data: Dict[str, Any], by_id: Dict[str, Dict[str, Any]], by_name: Dict[str, Dict[str, Any]], mode: str) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return data
    agent = _find_stream_agent(data, by_id, by_name, int(data.get("agentIndex") or data.get("sequence") or 1))
    data.setdefault("agentId", agent.get("agentId"))
    data.setdefault("agentName", agent.get("agentName"))
    data.setdefault("personality", agent.get("personality"))
    data.setdefault("personalityLabel", agent.get("personalityLabel"))
    data.setdefault("knowledgeLevel", agent.get("knowledgeLevel"))
    data.setdefault("knowledgeLevelLabel", agent.get("knowledgeLevelLabel"))
    data.setdefault("role", agent.get("role"))
    data.setdefault("mode", mode)
    return data


def _messages_from_complete_payload(data: Dict[str, Any], payload: Dict[str, Any], by_id: Dict[str, Dict[str, Any]], by_name: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    mode = str(payload.get("mode") or payload.get("learningMode") or data.get("mode") or "default").lower()
    group_id = payload.get("groupId") if payload.get("groupId") is not None else payload.get("group_id")
    room_id = payload.get("roomId") if payload.get("roomId") is not None else payload.get("room_id")
    messages = []
    answers = data.get("answers") or []
    for idx, answer in enumerate(answers, start=1):
        if not isinstance(answer, dict):
            continue
        agent = _find_stream_agent(answer, by_id, by_name, idx)
        messages.append(_message_from_stream_answer(answer, agent, mode, idx, group_id, room_id))
    return messages


# ── selectedAgents 보존 guard ────────────────────────────────────────────────
# 모드 무관 공통: selectedAgentCount=N이면 agent_answer가 N개 미만일 때 누락 에이전트의
# agent_answer SSE를 백엔드에서 실제로 보강 emit한다(프론트 fake 아님). simulation에서
# NPC 1명이 selected 교수 N명을 대체하던 버그(agent_answer=0) 방어. content는 mode/agent
# role 기반 fallback으로 채워 빈 content/누락이 없도록 한다.
# ── 필러는 '정상 AI 답변'이 아니라 '실행 누락 표시'다 ────────────────────────
# 과거엔 모드별로 그럴듯한 문장("{agentName} 관점에서 핵심을 정리하면…")을 합성했는데,
# 그 결과 (a) 실제 LLM 실행 실패가 정상 답변처럼 위장되고, (b) 의도적 partial route
# (정리 요청 WRAP / 기억 회상 / direct reply)에서 교수 2~3명이 똑같은 문장을 내뱉었다.
# 의도적 partial 은 handler 가 suppressAgentFill=True 로 알리고, 그 외의 누락은
# 여기서 degraded 카드로 '드러내야' 한다(조용한 성공 위장 금지).
_MISSING_ANSWER_TEXT = (
    "{agentName}의 답변을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요."
)


def _fallback_content(mode: str, agent_name: str) -> str:
    return _MISSING_ANSWER_TEXT.format(agentName=agent_name or "이 에이전트")


def _synth_agent_answer(agent: Dict[str, Any], index: int, mode: str) -> Dict[str, Any]:
    content = _fallback_content(mode, agent.get("agentName"))
    return {
        "type": "agent_answer",
        "agentId": agent.get("agentId"),            # _normalize_stream_agent가 항상 채움(null 금지)
        "agentIndex": index + 1,
        "agentName": agent.get("agentName"),
        "personality": agent.get("personality"),
        "personalityLabel": agent.get("personalityLabel"),
        "knowledgeLevel": agent.get("knowledgeLevel"),
        "knowledgeLevelLabel": agent.get("knowledgeLevelLabel"),
        "role": agent.get("role"),
        "mode": mode,
        "round": 1,
        "sequence": index + 1,
        "content": content,
        "answer": content,
        "synthesized": True,
        # 성공 위장 금지: 이 카드는 실패 표시다.
        "degraded": True,
        "status": "FAILED",
        "code": "AGENT_ANSWER_MISSING",
    }


def _reject_unknown_target(payload: Dict[str, Any]):
    """targetAgentId 가 있는데 agents 에서 해석되지 않으면 422 JSONResponse, 아니면 None.
    대상 없음/blank 는 기존 전체 협업 모드이므로 통과. 그 외 검증 오류는 기존 스트림 경로에 맡긴다."""
    target_id = str(payload.get("targetAgentId") or payload.get("target_agent_id") or "").strip()
    if not target_id:
        return None
    try:
        from app.schemas.multi_chat_schema import MultiChatRequest
        from app.services.multi_agent_service import UnknownTargetAgentError, _filter_agents, _get_agents
        req = MultiChatRequest(**payload)
        resolved = _filter_agents(_get_agents(req), req.targetAgentId)
        logger.info("[AGENT-RESOLVE] compat targetAgentId=%s → %s", target_id,
                    [(a.agentId, a.name, getattr(a, "agentSlot", None)) for a in resolved])
        return None
    except UnknownTargetAgentError as e:
        logger.warning("[AGENT-RESOLVE] compat targetAgentId=%s 거절: %s", target_id, e)
        return JSONResponse(status_code=422, content={"detail": {
            "code": "TARGET_AGENT_NOT_FOUND",
            "targetAgentId": e.target_id,
            "availableAgentIds": e.available,
            "message": "지정한 교수(targetAgentId)가 이 방의 에이전트 목록에 없습니다.",
        }})
    except Exception as exc:  # 스키마 오류 등은 기존 스트림 경로에서 처리
        logger.warning("[AGENT-RESOLVE] compat 사전 검증 건너뜀: %s", type(exc).__name__)
        return None


def _reject_unknown_mode(payload: Dict[str, Any]):
    """알 수 없는 mode/learningMode 는 basic 으로 조용히 폴백하지 않고 422 로 거절한다.
    (mode 자체가 없는 legacy 요청은 basic 으로 통과.)"""
    from app.services import mode_router
    try:
        resolved = mode_router.resolve_mode(payload.get("mode"), payload.get("learningMode") or payload.get("learning_mode"))
        logger.info("[MODE-ROUTER] compat mode=%r learningMode=%r → %s",
                    payload.get("mode"), payload.get("learningMode"), resolved)
        return None
    except mode_router.UnsupportedModeError as exc:
        logger.warning("[MODE-ROUTER] compat 거절: %s", exc)
        return JSONResponse(status_code=422, content={"detail": mode_router.error_detail(exc)})
    except Exception as exc:  # pragma: no cover - 라우터 장애가 스트림을 막지 않게
        logger.warning("[MODE-ROUTER] compat 검증 건너뜀: %s", type(exc).__name__)
        return None


@router.post("/multi-chat/stream")
async def multi_chat_stream_compat(request: Request):
    """
    운영 hotfix_main 전용 호환 SSE 라우터.

    기존 구현은 /api/ai/multi-chat 동기 JSON을 끝까지 기다린 뒤
    agent_complete/all_complete를 한꺼번에 보내서 UI가 '우르르' 표시됐다.

    이 구현은 정식 multi_agent_service.build_stream_generator를 직접 사용해서
    turn_start → agent_start → heartbeat → agent_answer/error → all_complete 순서로 즉시 전송한다.
    """
    payload = await request.json()

    # ── STRICT TARGETING ──────────────────────────────────────────────────────
    # targetAgentId 가 요청 agents 에 없으면 스트림(200)을 열지 않고 422 로 명시 거절한다.
    # (첫 번째/전체 에이전트로 조용히 폴백하면 다른 교수가 대신 답하는 identity 오류가 된다.)
    rejected = _reject_unknown_target(payload)
    if rejected is not None:
        return rejected

    # ── STRICT MODE ───────────────────────────────────────────────────────────
    # mode=debate 오타 하나가 basic 답변으로 조용히 나가던 silent fallback 을 막는다.
    rejected_mode = _reject_unknown_mode(payload)
    if rejected_mode is not None:
        return rejected_mode

    async def event_generator():
        route_request_id = f"compat_{uuid.uuid4().hex[:12]}"
        heartbeat_s = max(5.0, float(os.getenv("AI_STREAM_HEARTBEAT_SECONDS", "10")))
        started = time.time()
        last_agent_index = None
        last_agent_name = None
        sent_done = False
        errored = False
        mem_meta = None            # Redis 대화기억 메타(scope/key). attach 시 채워진다.
        final_assistant_text = ""  # all_complete에서 추출한 최종 답변(persist 입력).

        # ai07 내부 이벤트 버스 + envelope/dedup. 외부 SSE 계약(이벤트명/페이로드)은 불변, 키만 추가.
        from app.services import agent_event_contract as C
        from app.services.agent_event_bus import stream_with_contract, normalize_error_event, get_bus
        from app.services import multi_chat_redis_memory as _mem

        turn_id = C.new_turn_id()
        mode = str(payload.get("mode") or payload.get("learningMode") or "default").lower()
        bus = get_bus()

        def _emit(event: str, data: Dict[str, Any]) -> str:
            """compat 자체 생성 이벤트(heartbeat/done/error)에 동일 turnId envelope를 부착한다."""
            enriched = C.enrich_event(event, data or {}, turn_id=turn_id, mode=mode)
            if event in ("error", "agent_error"):
                enriched = normalize_error_event(enriched)
            return _sse(event, enriched)

        try:
            from app.schemas.multi_chat_schema import MultiChatRequest
            from app.services.multi_agent_service import build_stream_generator

            selected_agents, agent_by_id, agent_by_name = _stream_agent_maps(payload)
            # @멘션으로 특정 1명을 지목(targetAgentId)했으면, 누락 에이전트 필러 합성을 하지 않는다
            # (그 1명만 답하는 게 의도이므로 나머지를 채우면 안 됨).
            target_id = str(payload.get("targetAgentId") or payload.get("target_agent_id") or "").strip()
            # selectedAgents 보존 + agent_answer 커버리지 추적(누락 보강 / all_complete 1회 보장).
            # executed_*: 파이프라인이 '실제로 실행'해 내보낸 agent_answer.
            # emitted_*: 최종적으로 SSE 로 나간 것(= executed + 합성 필러).
            emitted_ids: set = set()
            emitted_names: set = set()
            executed_ids: set = set()
            executed_names: set = set()
            dialogue_act = None
            all_complete_sent = False
            chat_request = MultiChatRequest(**payload)
            # ── Redis 대화기억(서버측 보관/조회): 같은 방/세션의 최근 대화를 message 앞에
            #    [이전 대화 기억] 블록으로 주입한다(→Ollama 프롬프트). 실패해도 흐름 불변.
            try:
                chat_request, mem_meta = await _mem.attach_memory_to_request(chat_request)
            except Exception as _attach_exc:
                logger.warning("multi-chat memory attach 실패(turn=%s): %s", turn_id, type(_attach_exc).__name__)
            # 원본 제너레이터를 contract 래퍼로 감싼다(동일 {"event","data"} 형태 유지).
            #  → 모든 이벤트에 turnId/eventId/stage/fingerprint 부착 + 중복/지연 answer drop + 내부 버스 경유.
            gen = stream_with_contract(
                build_stream_generator(chat_request),
                mode=mode, turn_id=turn_id, bus=bus,
            )

            while True:
                task = asyncio.create_task(asyncio.to_thread(next, gen, _STREAM_SENTINEL))

                while True:
                    done, _ = await asyncio.wait({task}, timeout=heartbeat_s)
                    if done:
                        item = task.result()
                        break

                    yield _emit("heartbeat", {
                        "type": "heartbeat",
                        "requestId": route_request_id,
                        "agentIndex": last_agent_index,
                        "agentName": last_agent_name,
                        "elapsedMs": int((time.time() - started) * 1000),
                        "message": "답변 생성 중입니다.",
                    })

                if item is _STREAM_SENTINEL:
                    break

                event = item.get("event") or "message"
                data = item.get("data") or {}  # 이미 contract 래퍼가 envelope를 부착함

                if isinstance(data, dict):
                    if event in {"agent_answer", "agent_message", "agent_start", "agent_error"}:
                        data = _enrich_stream_event(data, agent_by_id, agent_by_name, mode)
                    if event == "agent_answer":
                        emitted_ids.add(str(data.get("agentId") or ""))
                        emitted_names.add(str(data.get("agentName") or ""))
                        executed_ids.add(str(data.get("agentId") or ""))
                        executed_names.add(str(data.get("agentName") or ""))
                    if data.get("dialogueAct"):
                        dialogue_act = data.get("dialogueAct")
                    if event == "all_complete":
                        # all_complete는 정확히 1회. 내부/레거시 중복 all_complete는 흡수한다.
                        if all_complete_sent:
                            continue
                        # selectedAgents N명 중 agent_answer 누락분을 실제 SSE로 보강 emit한다.
                        # 단, @멘션으로 1명을 지목한 경우(target_id)엔 누락 보강을 하지 않는다(그 1명만 답해야 함).
                        synth_answers = []
                        # suppressAgentFill: 참여자 수가 모드 계약으로 정해진 경우(토론 2명,
                        # 정리 요청 WRAP 1명, 기억 회상 1명, direct reply 1건 등).
                        # 이때 나머지 선택 에이전트를 채우면 참여하지 않은 발언이 섞인다.
                        _suppress = bool(data.get("suppressAgentFill"))
                        _route = data.get("route") or ("target_agent" if target_id else "multi_agent")
                        if data.get("dialogueAct"):
                            dialogue_act = data.get("dialogueAct")
                        for i, a in enumerate(selected_agents if not (target_id or _suppress) else []):
                            if str(a.get("agentId") or "") in emitted_ids or str(a.get("agentName") or "") in emitted_names:
                                continue
                            syn = _synth_agent_answer(a, i, mode)
                            emitted_ids.add(str(a.get("agentId") or ""))
                            emitted_names.add(str(a.get("agentName") or ""))
                            synth_answers.append(syn)
                            last_agent_index = syn.get("agentIndex", last_agent_index)
                            last_agent_name = syn.get("agentName", last_agent_name)
                            yield _emit("agent_answer", syn)

                        # ── 라우팅/커버리지 계측(필수 로그) ──────────────────────
                        # 계약: 정상 multi-agent 는 selected == executed == emitted.
                        #       의도적 partial 은 executed < selected 이되 suppress_agent_fill=True.
                        _selected_ids = [str(a.get("agentId") or "") for a in selected_agents]
                        logger.info(
                            "[MULTI-CHAT-ROUTE] turn=%s mode=%s route=%s selected_agent_ids=%s "
                            "executed_agent_ids=%s emitted_agent_ids=%s suppress_agent_fill=%s dialogue_act=%s",
                            turn_id, mode, _route, _selected_ids,
                            sorted(x for x in executed_ids if x), sorted(x for x in emitted_ids if x),
                            _suppress, dialogue_act,
                        )
                        if synth_answers:
                            # 억제되지 않은 경로에서 필러가 나갔다는 건 '실제 실행 누락'이다.
                            # 조용한 성공 위장 금지 → ERROR 로그 + degraded 카드로 드러낸다.
                            logger.error(
                                "[AGENT-FILL] turn=%s mode=%s route=%s 실행 누락 %d명 "
                                "(selected=%d executed=%d) missing=%s — degraded 카드로 대체",
                                turn_id, mode, _route, len(synth_answers),
                                len(selected_agents), len([x for x in executed_ids if x]),
                                [s.get("agentName") for s in synth_answers],
                            )
                            data["degraded"] = True
                            data["missingAgentIds"] = [s.get("agentId") for s in synth_answers]

                        data.setdefault("success", True)
                        data.setdefault("groupId", payload.get("groupId") or payload.get("group_id"))
                        data.setdefault("roomId", payload.get("roomId") or payload.get("room_id"))
                        data.setdefault("agentRoomId", payload.get("agentRoomId") or payload.get("agent_room_id"))
                        data["mode"] = mode
                        if synth_answers:
                            existing = data.get("answers") if isinstance(data.get("answers"), list) else []
                            data["answers"] = existing + synth_answers
                        data["messages"] = _messages_from_complete_payload(data, payload, agent_by_id, agent_by_name)
                        # 최종 답변 텍스트를 추출해 둔다(스트림 종료 후 Redis 저장 입력).
                        final_assistant_text = _mem.extract_assistant_text_from_complete_event(data) or final_assistant_text
                    last_agent_index = data.get("agentIndex", last_agent_index)
                    last_agent_name = data.get("agentName", last_agent_name)

                yield _sse(event, data)
                if event == "all_complete":
                    all_complete_sent = True
                    # done은 종료 신호만(작은 legacy signal). all_complete payload를 재전송하지 않는다
                    # (재전송 시 type:all_complete가 중복 카운트되어 all_complete==1 계약을 깨뜨림).
                    yield _emit("done", {
                        "type": "done",
                        "requestId": route_request_id,
                        "phase": "DONE",
                        "visible": False,
                        "status": "done",
                        "elapsedMs": int((time.time() - started) * 1000),
                    })
                    sent_done = True

        except Exception as exc:
            errored = True
            # 실패 원인은 서버 로그로 남기고, 사용자에겐 stacktrace 대신 code/reason만 노출.
            logger.exception("multi-chat stream 오류(turn=%s): %s", turn_id, type(exc).__name__)
            yield _emit("error", {
                "type": "error",
                "requestId": route_request_id,
                "phase": "ERROR",
                "visible": True,
                "status": "error",
                "code": "STREAM_ERROR",
                "reason": type(exc).__name__,  # 예외 타입만(원문 메시지/스택트레이스 비노출)
                "message": "AI 스트리밍 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
            })
        finally:
            # ── Redis 대화기억: 이번 턴(사용자 질문 + 최종 답변)을 저장한다.
            #    user_message 는 meta.original_message(주입 전 원문)를 모듈이 사용한다.
            if mem_meta is not None and getattr(mem_meta, "enabled", False) and final_assistant_text:
                try:
                    await _mem.persist_turn(mem_meta, None, final_assistant_text)
                except Exception as _persist_exc:
                    logger.warning("multi-chat memory persist 실패(turn=%s): %s", turn_id, type(_persist_exc).__name__)
            # 정상 종료(all_complete→done)가 아닌 경로(예외/타임아웃/중단)에서도
            # placeholder loading이 무한 지속되지 않도록 종료 이벤트를 반드시 보낸다.
            if not sent_done:
                yield _emit("done", {
                    "type": "done",
                    "requestId": route_request_id,
                    "phase": "DONE",
                    "visible": False,
                    "status": "error" if errored else "done",
                    "elapsedMs": int((time.time() - started) * 1000),
                })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/predict-study-time")
async def predict_study_time_compat(request: Request):
    payload = await request.json()
    port = os.getenv("FASTAPI_PORT", "8000")
    url = f"http://127.0.0.1:{port}/api/ai/predict/study-time"

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload)

    try:
        return response.json()
    except Exception:
        return {"status": response.status_code, "body": response.text}
