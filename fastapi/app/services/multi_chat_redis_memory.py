from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("studybridge.fastapi.memory")

MEMORY_ENABLED = os.getenv("MULTI_CHAT_REDIS_MEMORY_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
REDIS_URL = os.getenv("MULTI_CHAT_REDIS_URL") or os.getenv("REDIS_URL") or "redis://127.0.0.1:16379/0"

TTL_SECONDS = int(os.getenv("MULTI_CHAT_MEMORY_TTL_SECONDS", str(7 * 24 * 3600)))
MAX_MESSAGES = int(os.getenv("MULTI_CHAT_MEMORY_MAX_MESSAGES", "20"))
LOAD_MESSAGES = int(os.getenv("MULTI_CHAT_MEMORY_LOAD_MESSAGES", "8"))
MAX_CHARS_PER_MESSAGE = int(os.getenv("MULTI_CHAT_MEMORY_MAX_CHARS_PER_MESSAGE", "900"))
MAX_CONTEXT_CHARS = int(os.getenv("MULTI_CHAT_MEMORY_MAX_CONTEXT_CHARS", "3600"))

_redis = None
_redis_tried = False


@dataclass
class MemoryMeta:
    enabled: bool
    key: Optional[str] = None
    scope: Optional[str] = None
    scope_id: Optional[str] = None
    loaded_count: int = 0
    original_message: Optional[str] = None


def _safe_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in {"none", "null", "undefined"}:
        return None
    return s


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _scope_from_request(request: Any) -> Tuple[Optional[str], Optional[str]]:
    candidates = [
        ("room", _get(request, "roomId") or _get(request, "room_id")),
        ("agentRoom", _get(request, "agentRoomId") or _get(request, "agent_room_id")),
        ("session", _get(request, "sessionId") or _get(request, "session_id")),
        ("conversation", _get(request, "conversationId") or _get(request, "conversation_id")),
        ("group", _get(request, "groupId") or _get(request, "group_id")),
        ("user", _get(request, "userId") or _get(request, "user_id")),
    ]

    for scope, value in candidates:
        value = _safe_str(value)
        if value:
            return scope, value

    return None, None


def _memory_key(scope: str, scope_id: str) -> str:
    safe = "".join(ch for ch in scope_id if ch.isalnum() or ch in {"-", "_", ":"})[:120]
    return f"studybridge:multi-chat:memory:{scope}:{safe}"


async def _get_redis():
    global _redis, _redis_tried

    if not MEMORY_ENABLED:
        return None
    if _redis is not None:
        return _redis
    if _redis_tried:
        return _redis

    _redis_tried = True

    try:
        import redis.asyncio as redis_async

        client = redis_async.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
        await client.ping()
        _redis = client
        logger.info("multi-chat Redis memory connected url=%s", REDIS_URL)
        return _redis
    except Exception as e:
        logger.warning("multi-chat Redis memory disabled: %s", type(e).__name__)
        _redis = None
        return None


def _clip(text: Any, limit: int = MAX_CHARS_PER_MESSAGE) -> str:
    s = "" if text is None else str(text)
    s = s.replace("\x00", "").strip()
    return s[:limit] + "…" if len(s) > limit else s


def _as_message(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        role = obj.get("role") or obj.get("senderType") or obj.get("type") or "unknown"
        content = obj.get("content") or obj.get("answer") or obj.get("message") or ""
        ts = obj.get("ts") or obj.get("createdAt") or int(time.time())
        return {"role": str(role), "content": _clip(content), "ts": ts}

    return {"role": "unknown", "content": _clip(obj), "ts": int(time.time())}


async def load_memory(request: Any) -> Tuple[List[Dict[str, Any]], MemoryMeta]:
    scope, scope_id = _scope_from_request(request)

    if not scope or not scope_id:
        return [], MemoryMeta(enabled=False)

    key = _memory_key(scope, scope_id)
    meta = MemoryMeta(
        enabled=True,
        key=key,
        scope=scope,
        scope_id=scope_id,
        original_message=_safe_str(_get(request, "message")),
    )

    r = await _get_redis()
    if r is None:
        meta.enabled = False
        return [], meta

    try:
        raw_items = await r.lrange(key, -LOAD_MESSAGES, -1)
        items: List[Dict[str, Any]] = []

        for raw in raw_items:
            try:
                items.append(_as_message(json.loads(raw)))
            except Exception:
                items.append(_as_message(raw))

        meta.loaded_count = len(items)
        return items, meta
    except Exception as e:
        logger.warning("multi-chat memory load failed key=%s err=%s", key, type(e).__name__)
        meta.enabled = False
        return [], meta


def build_memory_block(items: List[Dict[str, Any]]) -> str:
    if not items:
        return ""

    lines = [
        "[이전 대화 기억]",
        "아래 내용은 같은 방/세션의 최근 대화 맥락이다. 현재 질문에 필요한 경우에만 반영하고, 불필요하면 무시한다.",
    ]

    for item in items:
        role = str(item.get("role") or "unknown")
        content = _clip(item.get("content") or "")
        if content:
            lines.append(f"- {role}: {content}")

    block = "\n".join(lines).strip()
    if len(block) > MAX_CONTEXT_CHARS:
        block = "[이전 대화 기억]\n" + block[-MAX_CONTEXT_CHARS:]

    return block


async def attach_memory_to_request(request: Any) -> Tuple[Any, MemoryMeta]:
    items, meta = await load_memory(request)

    if not items:
        return request, meta

    original = _safe_str(_get(request, "message"))
    if not original:
        return request, meta

    augmented = f"{build_memory_block(items)}\n\n[현재 질문]\n{original}"

    if hasattr(request, "model_copy"):
        return request.model_copy(update={"message": augmented}), meta

    if hasattr(request, "copy"):
        return request.copy(update={"message": augmented}), meta

    try:
        setattr(request, "message", augmented)
    except Exception:
        logger.warning("multi-chat memory attach skipped: request immutable")

    return request, meta


def extract_assistant_text_from_complete_event(event: Any) -> str:
    data = event

    if isinstance(event, str):
        payload_lines = [
            line[5:].strip()
            for line in event.splitlines()
            if line.startswith("data:")
        ]
        if payload_lines:
            try:
                data = json.loads("\n".join(payload_lines))
            except Exception:
                return ""

    if not isinstance(data, dict):
        return ""

    if isinstance(data.get("data"), dict):
        data = data["data"]

    answers = data.get("answers") or []
    chunks = []

    if isinstance(answers, list):
        for ans in answers:
            if isinstance(ans, dict):
                txt = ans.get("answer") or ans.get("content")
                if txt:
                    name = ans.get("agentName") or ans.get("name") or "assistant"
                    chunks.append(f"{name}: {_clip(txt)}")

    if chunks:
        return "\n".join(chunks)

    for key in ("answer", "content", "message"):
        if data.get(key):
            return _clip(data.get(key))

    return ""


async def persist_turn(meta: MemoryMeta, user_message: Optional[str], assistant_message: str) -> bool:
    if not meta.enabled or not meta.key:
        return False

    r = await _get_redis()
    if r is None:
        return False

    user_message = _clip(user_message or meta.original_message or "")
    assistant_message = _clip(assistant_message or "")

    if not user_message and not assistant_message:
        return False

    now = int(time.time())
    records = []

    if user_message:
        records.append(json.dumps({"role": "user", "content": user_message, "ts": now}, ensure_ascii=False))

    if assistant_message:
        records.append(json.dumps({"role": "assistant", "content": assistant_message, "ts": now}, ensure_ascii=False))

    try:
        await r.rpush(meta.key, *records)
        await r.ltrim(meta.key, -MAX_MESSAGES, -1)
        await r.expire(meta.key, TTL_SECONDS)
        return True
    except Exception as e:
        logger.warning("multi-chat memory persist failed key=%s err=%s", meta.key, type(e).__name__)
        return False
