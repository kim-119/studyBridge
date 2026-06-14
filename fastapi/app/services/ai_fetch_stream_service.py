"""
Fetch Streaming(NDJSON) 서비스 — 기존 SSE 고속도로와 완전히 분리된 "우회도로".

핵심 규칙:
  - 응답 media_type = application/x-ndjson. 각 줄은 독립 JSON + "\n".
  - orjson으로 직렬화(=ensure_ascii 없이 UTF-8, 한글 안전 + native 가속). orjson 부재 시 json fallback.
  - SSE의 "data:" 접두어/"text/event-stream"을 절대 쓰지 않는다.
  - 기존 SSE 서비스 코드(multi_chat_stream_compat 등)를 수정하지 않고, 검증된
    build_stream_generator / rag_retriever를 "재사용"만 한다.
  - 어떤 예외에서도 error 라인 + done 라인으로 정상 종료한다(스트림이 끊겨도 클라이언트 파서가 살아있게).

Hot Path:
  - 단순 인사/잡담/명백한 위협은 deterministic fast path로 LLM 없이 즉시 응답.
  - 각 구간을 PerfTimer로 계측하고 [AI_PERF] 로그를 남긴다.

Native Acceleration:
  - orjson: NDJSON 직렬화. (FFI 후보 "JSON validation/serialization")
  - RAG 검색은 pgvector(DB측 ANN)를 그대로 사용 → Python cosine loop 없음.
  - 토큰 스트리밍(stream_ollama)으로 첫 토큰 지연(llm_first_token_ms)을 단축.
"""
import logging
import os
import time
from typing import Any, Dict, Iterator, List, Optional

import requests

logger = logging.getLogger("studybridge.fetch_stream")

# orjson 우선(native 가속), 부재 시 표준 json fallback
try:
    import orjson

    def _dumps(obj: Any) -> bytes:
        # orjson은 항상 UTF-8로 직렬화하며 비ASCII를 escape하지 않는다(=ensure_ascii=False).
        return orjson.dumps(obj)
    _NATIVE_JSON = "orjson"
except Exception:  # pragma: no cover - orjson은 설치돼 있음
    import json as _json

    def _dumps(obj: Any) -> bytes:
        return _json.dumps(obj, ensure_ascii=False).encode("utf-8")
    _NATIVE_JSON = "json"


# ── 환경변수 (하드코딩 금지, 호출 시점 평가) ──────────────────────────────────
def _flag(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() == "true"


def _intf(name: str, default: str) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return int(default)


def is_fetch_stream_enabled() -> bool:
    return _flag("AI_FETCH_STREAM_ENABLED", "true")


def native_acceleration_label() -> str:
    bits = [_NATIVE_JSON]
    if _flag("AI_NATIVE_ACCELERATION_ENABLED", "true"):
        bits.append("enabled")
    else:
        bits.append("disabled")
    return "+".join(bits)


# ── NDJSON 이벤트 헬퍼 ────────────────────────────────────────────────────────
def line(obj: Dict[str, Any]) -> bytes:
    """dict → NDJSON 한 줄(bytes)."""
    return _dumps(obj) + b"\n"


def ev_status(feature: str, phase: str, message: str, **extra) -> bytes:
    return line({"type": "status", "feature": feature, "phase": phase, "message": message, **extra})


def ev_delta(feature: str, phase: str, content: str, **extra) -> bytes:
    return line({"type": "delta", "feature": feature, "phase": phase, "content": content, **extra})


def ev_done(feature: str, **extra) -> bytes:
    return line({"type": "done", "feature": feature, **extra})


def ev_error(feature: str, phase: str, message: str, **extra) -> bytes:
    return line({"type": "error", "feature": feature, "phase": phase, "message": message, **extra})


# ── 토큰 스트리밍 Ollama 호출 (additive — ollama_client는 건드리지 않음) ──────
def stream_ollama(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    first_token_timeout: Optional[int] = None,
    total_timeout: Optional[int] = None,
) -> Iterator[str]:
    """
    Ollama /api/chat 를 stream=True로 호출해 content 조각을 순차 yield한다.
    ollama_client.ask_ollama는 stream=False라 첫 토큰까지 전체를 기다린다 → 여기서만 별도 스트리밍.
    qwen3 thinking은 첫 토큰을 크게 지연시키므로 기본 think=false(환경변수로 조정).
    오류/타임아웃 시 예외를 던진다(호출부가 error 라인으로 변환).
    """
    from app.core.config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TEMPERATURE, OLLAMA_NUM_PREDICT, OLLAMA_CONTEXT_LENGTH

    _model = model or os.getenv("INTENT_ROUTER_MODEL", OLLAMA_MODEL)
    _temp = temperature if temperature is not None else OLLAMA_TEMPERATURE
    _max = max_tokens or OLLAMA_NUM_PREDICT
    _ftt = first_token_timeout or _intf("AI_FIRST_TOKEN_TIMEOUT_SEC", "30")
    _total = total_timeout or _intf("AI_TOTAL_TIMEOUT_SEC", "90")
    _think = _flag("AI_FETCH_STREAM_THINK", "false")

    payload = {
        "model": _model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": True,
        "think": _think,
        "options": {"temperature": _temp, "num_predict": _max, "num_ctx": OLLAMA_CONTEXT_LENGTH},
    }

    started = time.perf_counter()
    # (connect timeout, read timeout). read timeout=첫 토큰/토큰간 최대 대기.
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/chat", json=payload, stream=True, timeout=(5, _ftt)
    )
    resp.raise_for_status()
    for raw in resp.iter_lines(decode_unicode=False):
        if not raw:
            continue
        if (time.perf_counter() - started) > _total:
            resp.close()
            raise TimeoutError(f"total stream timeout {_total}s")
        try:
            obj = orjson.loads(raw) if _NATIVE_JSON == "orjson" else __import__("json").loads(raw)
        except Exception:
            continue
        piece = (obj.get("message") or {}).get("content") or ""
        if piece:
            yield piece
        if obj.get("done"):
            break


# ── 공통: persona/level 해석 (코드 내 고정 하드코딩 금지) ──────────────────────
def _resolve_persona(payload: Dict[str, Any], agent: Optional[Dict[str, Any]] = None) -> str:
    src = agent or payload
    return str(
        src.get("persona") or src.get("personality") or payload.get("persona")
        or os.getenv("AI_DEFAULT_PERSONALITY", "friendly")
    )


def _resolve_level(payload: Dict[str, Any], agent: Optional[Dict[str, Any]] = None) -> str:
    """사용자가 선택한 지식수준을 그대로 사용한다. 질문 난이도로 임의 하향 금지."""
    src = agent or payload
    return str(
        src.get("level") or src.get("knowledgeLevel") or payload.get("level")
        or payload.get("knowledgeLevel") or os.getenv("AI_DEFAULT_KNOWLEDGE_LEVEL", "학사")
    )


def _level_instruction(level: str) -> str:
    try:
        from app.services.knowledge_level_controller import get_level_instruction
        return get_level_instruction(level)
    except Exception:
        return f"학습자의 지식수준은 '{level}'이다. 그 수준에 맞춰 설명하라."


def _context_max_chars() -> int:
    return _intf("AI_CONTEXT_MAX_CHARS", "6000")


# ── deterministic fast path (LLM 없이 즉시 응답) ──────────────────────────────
def _fast_path(feature: str, text: str, surface: str) -> Optional[List[bytes]]:
    """
    단순 인사/잡담/명백한 위협을 LLM 없이 즉시 NDJSON으로 처리.
    intent_router의 deterministic fallback(검증된 안전망)을 재사용한다.
    해당 없으면 None → 정상 LLM 경로로 진행.
    """
    if not _flag("AI_FAST_PATH_ENABLED", "true"):
        return None
    try:
        from app.api.intent_router_routes import _fallback_decision, IntentContext
        d = _fallback_decision(text, surface, IntentContext())
    except Exception:
        return None

    route = d.get("routeAction")
    if route == "DIRECT_REPLY" and d.get("directReply"):
        return [
            ev_status(feature, "fast_path", "빠른 응답 경로로 처리합니다.", intent=d["intent"]),
            ev_delta(feature, "answer", d["directReply"]),
            ev_done(feature, fastPath=True, intent=d["intent"]),
        ]
    if route == "BLOCK":
        return [
            ev_status(feature, "safety", "안전 점검 결과 요청을 차단했습니다.", intent=d["intent"]),
            ev_error(feature, "safety", d.get("reason") or "안전하지 않은 요청입니다.",
                     intent=d["intent"], riskLevel=d.get("riskLevel")),
            ev_done(feature, fastPath=True, blocked=True),
        ]
    return None


# ── 1) 멀티에이전트 채팅 — build_stream_generator 재사용 + NDJSON 변환 ─────────
# event(SSE 내부 표현) → NDJSON phase 매핑. 기존 생성기 출력을 변형 없이 번역만 한다.
_ANSWER_EVENTS = {"agent_answer", "agent_message"}
_STATUS_EVENTS = {"turn_start", "agent_start", "heartbeat", "validation_summary",
                  "debate_section", "socratic_step", "simulation_stage"}


def agent_chat_stream(payload: Dict[str, Any]) -> Iterator[bytes]:
    from app.utils.perf_timer import PerfTimer
    feature = "agent_chat"
    perf = PerfTimer(feature, request_id=payload.get("requestId"))
    text = str(payload.get("message") or payload.get("question") or "").strip()

    # fast path
    with perf.section("intent_routing_ms"):
        fp = _fast_path(feature, text, "learning_mate")
    if fp is not None:
        for b in fp:
            yield b
        perf.log(fastPath=True, native=native_acceleration_label())
        return

    yield ev_status(feature, "intent_routing", "질문 의도를 분석 중입니다.")
    try:
        from app.schemas.multi_chat_schema import MultiChatRequest
        from app.services.multi_agent_service import build_stream_generator

        with perf.section("prompt_build_ms"):
            chat_request = MultiChatRequest(**payload)
            gen = build_stream_generator(chat_request)

        first_token_logged = False
        for item in gen:
            event = item.get("event") or "message"
            data = item.get("data") or {}
            if event == "all_complete":
                yield ev_done(feature, summary=_safe_small(data))
                break
            if event == "agent_error":
                yield ev_error(feature, "draft", str(data.get("message") or data.get("error") or "agent error"),
                               agentId=data.get("agentId"))
                continue
            if event in _ANSWER_EVENTS:
                if not first_token_logged:
                    perf.mark("llm_first_token_ms")
                    first_token_logged = True
                content = data.get("content") or data.get("answer") or data.get("feedback") or ""
                phase = str(data.get("stage") or data.get("phase") or "draft")
                yield ev_delta(feature, phase, content, agentId=data.get("agentId"),
                               agentName=data.get("agentName"), role=data.get("role"))
            elif event in _STATUS_EVENTS:
                yield ev_status(feature, event, str(data.get("message") or _phase_message(event)),
                                agentId=data.get("agentId"), agentName=data.get("agentName"))
            else:
                yield ev_status(feature, event, _phase_message(event))
        else:
            yield ev_done(feature)
    except Exception as exc:
        logger.warning("agent_chat_stream 오류: %s", exc)
        yield ev_error(feature, "draft", f"{type(exc).__name__}: {exc}")
        yield ev_done(feature)
    finally:
        perf.mark("llm_total_ms")
        perf.log(native=native_acceleration_label())


def _phase_message(event: str) -> str:
    return {
        "turn_start": "답변 생성을 시작합니다.",
        "agent_start": "에이전트가 답변을 작성 중입니다.",
        "heartbeat": "답변 생성 중입니다.",
        "validation_summary": "검증 중입니다.",
    }.get(event, "처리 중입니다.")


def _safe_small(data: Any) -> Any:
    """all_complete 페이로드가 거대할 수 있어 핵심만 추려 done에 싣는다."""
    if not isinstance(data, dict):
        return None
    return {k: data.get(k) for k in ("success", "mode", "requestId") if k in data}


# ── 공통: 단일 LLM 답변 스트리밍 (group/material/roadmap/task 공용) ───────────
def _simple_llm_stream(
    feature: str,
    perf,
    system_prompt: str,
    user_prompt: str,
    phase: str = "answer",
    temperature: Optional[float] = None,
) -> Iterator[bytes]:
    first = False
    try:
        for piece in stream_ollama(system_prompt, user_prompt, temperature=temperature):
            if not first:
                perf.mark("llm_first_token_ms")
                first = True
            yield ev_delta(feature, phase, piece)
        if not first:
            yield ev_error(feature, phase, "LLM이 빈 응답을 반환했습니다.")
    except requests.Timeout:
        yield ev_error(feature, phase, "Ollama request timeout")
    except requests.ConnectionError:
        yield ev_error(feature, phase, "Ollama 서버에 연결할 수 없습니다.")
    except Exception as exc:
        logger.warning("%s LLM 스트리밍 오류: %s", feature, exc)
        yield ev_error(feature, phase, f"{type(exc).__name__}: {exc}")


# ── 2) 그룹스터디 AI ──────────────────────────────────────────────────────────
def group_study_stream(payload: Dict[str, Any]) -> Iterator[bytes]:
    from app.utils.perf_timer import PerfTimer
    feature = "group_study"
    perf = PerfTimer(feature, request_id=payload.get("requestId"))
    room_id = payload.get("roomId") if payload.get("roomId") is not None else payload.get("room_id")
    text = str(payload.get("message") or "").strip()

    if room_id is None:
        yield ev_error(feature, "validate", "roomId가 필요합니다.")
        yield ev_done(feature)
        perf.log()
        return

    with perf.section("intent_routing_ms"):
        fp = _fast_path(feature, text, "group_study_chat")
    if fp is not None:
        for b in fp:
            yield b
        perf.log(fastPath=True, roomId=room_id, native=native_acceleration_label())
        return

    yield ev_status(feature, "prepare", "그룹스터디 맥락을 정리하는 중입니다.", roomId=room_id)
    with perf.section("context_compress_ms"):
        history = _compress_history(payload.get("history") or payload.get("previousMessages") or [])
    level = _resolve_level(payload)
    persona = _resolve_persona(payload)
    system = (
        "너는 그룹스터디를 돕는 학습 조력자다. 토론/협력 학습 맥락에서 답한다.\n"
        f"성격: {persona}. {_level_instruction(level)}\n"
        "한국어로, 그룹 토론에 도움이 되도록 명확하게 답하라."
    )
    user = (f"## 이전 대화(요약)\n{history}\n\n" if history else "") + f"## 질문\n{text}"
    yield ev_status(feature, "draft_start", "답변 생성 중입니다.", roomId=room_id)
    for b in _simple_llm_stream(feature, perf, system, user):
        yield b
    yield ev_done(feature, roomId=room_id)
    perf.mark("llm_total_ms")
    perf.log(roomId=room_id, native=native_acceleration_label())


def _compress_history(history: List[Any], max_items: int = 8) -> str:
    """그룹스터디 이전 로그를 필요한 만큼만 압축(최근 N개, 길이 제한)."""
    if not isinstance(history, list) or not history:
        return ""
    recent = history[-max_items:]
    lines: List[str] = []
    cap = _context_max_chars()
    for h in recent:
        if isinstance(h, dict):
            who = h.get("senderType") or h.get("role") or h.get("sender") or "USER"
            content = h.get("content") or h.get("message") or h.get("text") or ""
        else:
            who, content = "USER", str(h)
        content = str(content).strip().replace("\n", " ")
        if content:
            lines.append(f"- {who}: {content[:300]}")
        if sum(len(x) for x in lines) > cap:
            break
    return "\n".join(lines)


# ── 3) 자료보관함 RAG 채팅 ────────────────────────────────────────────────────
def material_chat_stream(material_id: int, payload: Dict[str, Any]) -> Iterator[bytes]:
    from app.utils.perf_timer import PerfTimer
    feature = "material_chat"
    perf = PerfTimer(feature, request_id=payload.get("requestId"))
    text = str(payload.get("message") or payload.get("question") or "").strip()

    with perf.section("intent_routing_ms"):
        fp = _fast_path(feature, text, "archive_chat")
    if fp is not None:
        for b in fp:
            yield b
        perf.log(fastPath=True, materialId=material_id, native=native_acceleration_label())
        return

    yield ev_status(feature, "rag_start", "자료에서 관련 내용을 검색 중입니다.", materialId=material_id)
    top_k = _intf("AI_RAG_TOP_K", "5")
    chunks: List[dict] = []
    try:
        from app.services.rag_retriever import retrieve_similar_chunks
        with perf.section("rag_retrieve_ms"):
            chunks = retrieve_similar_chunks(text, material_id=material_id, top_k=top_k) or []
    except Exception as exc:
        logger.warning("material RAG 검색 실패: %s", exc)

    with perf.section("context_compress_ms"):
        context = _build_rag_context(chunks)

    yield ev_status(feature, "rag_done", f"관련 청크 {len(chunks)}개를 찾았습니다.",
                    materialId=material_id, chunkCount=len(chunks))

    level = _resolve_level(payload)
    persona = _resolve_persona(payload)
    if context:
        system = (
            "너는 업로드된 학습 자료(PDF) 기반 Q&A 도우미다.\n"
            f"성격: {persona}. {_level_instruction(level)}\n"
            "PDF_CONTEXT에 없는 내용은 단정하지 말고 '자료에 없는 내용'이라고 밝혀라. 한국어로 답하라."
        )
        user = f"## PDF_CONTEXT\n{context}\n\n## 질문\n{text}\n\n근거를 들어 정확히 답하라."
    else:
        system = (
            "너는 학습 도우미다. 관련 자료를 찾지 못했으므로 일반 지식으로 신중히 답하되, "
            f"자료 근거가 없음을 밝혀라. 성격: {persona}. {_level_instruction(level)} 한국어로 답하라."
        )
        user = f"## 질문\n{text}"

    yield ev_status(feature, "draft_start", "답변 생성 중입니다.", materialId=material_id)
    for b in _simple_llm_stream(feature, perf, system, user):
        yield b
    yield ev_done(feature, materialId=material_id, chunkCount=len(chunks))
    perf.mark("llm_total_ms")
    perf.log(materialId=material_id, rag_chunks=len(chunks), native=native_acceleration_label())


def _build_rag_context(chunks: List[dict]) -> str:
    if not chunks:
        return ""
    cap = _context_max_chars()
    parts: List[str] = []
    total = 0
    for c in chunks:
        content = str(c.get("content") or "").strip()
        if not content:
            continue
        piece = f"[청크 {c.get('chunk_index', 0)}] {content}"
        if total + len(piece) > cap:
            piece = piece[: max(0, cap - total)]
        parts.append(piece)
        total += len(piece)
        if total >= cap:
            break
    return "\n".join(parts)


# ── 4) 로드맵 AI 설명/채팅 ────────────────────────────────────────────────────
def roadmap_chat_stream(material_id: int, payload: Dict[str, Any]) -> Iterator[bytes]:
    from app.utils.perf_timer import PerfTimer
    feature = "roadmap_chat"
    perf = PerfTimer(feature, request_id=payload.get("requestId"))
    text = str(payload.get("message") or "").strip()

    with perf.section("intent_routing_ms"):
        fp = _fast_path(feature, text, "learning_mate")
    if fp is not None:
        for b in fp:
            yield b
        perf.log(fastPath=True, materialId=material_id, native=native_acceleration_label())
        return

    yield ev_status(feature, "prepare", "로드맵 맥락을 불러오는 중입니다.", materialId=material_id)
    # 자료 컨텍스트를 RAG로 보강(있으면). 없어도 진행.
    chunks: List[dict] = []
    try:
        from app.services.rag_retriever import retrieve_similar_chunks
        with perf.section("rag_retrieve_ms"):
            chunks = retrieve_similar_chunks(text or "학습 로드맵", material_id=material_id,
                                             top_k=_intf("AI_RAG_TOP_K", "5")) or []
    except Exception as exc:
        logger.warning("roadmap RAG 검색 실패: %s", exc)
    with perf.section("context_compress_ms"):
        context = _build_rag_context(chunks)

    level = _resolve_level(payload)
    roadmap_ctx = payload.get("roadmap") or payload.get("roadmapJson")
    system = (
        "너는 학습 로드맵을 설명하고 개인화하는 학습 코치다. 로드맵 구조(주차/주제/목표)를 "
        "근거로 설명·조정한다. 주차 수/기간 변경 요청이 있으면 그에 맞게 재구성해 설명한다.\n"
        f"{_level_instruction(level)} 한국어로 답하라."
    )
    parts = []
    if roadmap_ctx:
        parts.append(f"## 현재 로드맵\n{str(roadmap_ctx)[:_context_max_chars()]}")
    if context:
        parts.append(f"## 자료 컨텍스트\n{context}")
    parts.append(f"## 요청\n{text}")
    user = "\n\n".join(parts)

    yield ev_status(feature, "draft_start", "로드맵 설명을 생성 중입니다.", materialId=material_id)
    for b in _simple_llm_stream(feature, perf, system, user):
        yield b
    yield ev_done(feature, materialId=material_id)
    perf.mark("llm_total_ms")
    perf.log(materialId=material_id, native=native_acceleration_label())


# ── 5) 통합 AI 작업 endpoint ──────────────────────────────────────────────────
def tasks_stream(payload: Dict[str, Any]) -> Iterator[bytes]:
    """feature/task 필드로 적절한 스트림으로 위임한다."""
    feature_req = str(payload.get("feature") or payload.get("task") or "").strip().lower()

    if feature_req in ("agent_chat", "agent", "multi_agent", "chat"):
        yield from agent_chat_stream(payload)
        return
    if feature_req in ("group_study", "group", "group_study_chat"):
        yield from group_study_stream(payload)
        return
    if feature_req in ("material_chat", "material", "archive", "archive_chat"):
        mid = payload.get("materialId") or payload.get("material_id")
        if mid is None:
            yield ev_error("task", "validate", "material_chat에는 materialId가 필요합니다.")
            yield ev_done("task")
            return
        yield from material_chat_stream(int(mid), payload)
        return
    if feature_req in ("roadmap_chat", "roadmap"):
        mid = payload.get("materialId") or payload.get("material_id")
        if mid is None:
            yield ev_error("task", "validate", "roadmap_chat에는 materialId가 필요합니다.")
            yield ev_done("task")
            return
        yield from roadmap_chat_stream(int(mid), payload)
        return

    # 미지정/기타: 일반 학습 질문으로 LLM 스트리밍
    from app.utils.perf_timer import PerfTimer
    perf = PerfTimer("task", request_id=payload.get("requestId"))
    text = str(payload.get("message") or payload.get("question") or "").strip()
    fp = _fast_path("task", text, "learning_mate")
    if fp is not None:
        for b in fp:
            yield b
        perf.log(fastPath=True, native=native_acceleration_label())
        return
    level = _resolve_level(payload)
    system = f"너는 학습 도우미다. {_level_instruction(level)} 한국어로 정확히 답하라."
    yield ev_status("task", "draft_start", "답변 생성 중입니다.", feature=feature_req or "generic")
    for b in _simple_llm_stream("task", perf, system, text):
        yield b
    yield ev_done("task")
    perf.mark("llm_total_ms")
    perf.log(native=native_acceleration_label())
