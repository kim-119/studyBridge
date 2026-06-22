"""에이전트 SSE 이벤트 표준 envelope + content fingerprint.

목적(외부 계약 불변):
  - /api/ai/multi-chat/stream 의 기존 SSE 이벤트명/페이로드를 깨지 않는다.
  - 모든 이벤트 data에 turnId/eventId/stage/fingerprint/createdAt/isFinal 을 *추가*만 한다.
  - fingerprint = turnId + stage + agentId + canonicalize(content) 의 안정 해시.
    → 같은 turn에서 같은 (stage, agent, content) 재발행을 결정적으로 식별(중복 방어).

C/native 재사용(target D):
  - 긴 content의 canonicalization(공백 정규화/UTF-8 안전)은 native_textprep(C 엔진,
    secret_sauce_engine/textprep)을 재사용한다. .so 미존재/실패 시 Python fallback.
  - 짧은 문자열(대부분의 에이전트 답변)은 순수 Python이 더 빠르므로 native를 쓰지 않는다.
    (LLM 추론 대비 이 구간 비용은 무시 가능 — 과장하지 않는다.)
"""
from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from typing import Any, Dict, Optional

# 표준 stage(기본모드 계약). 그 외 모드는 stageType 원형을 보존한다.
STAGE_FIRST_ANSWER = "FIRST_ANSWER"
STAGE_VALIDATION = "VALIDATION"
STAGE_PEER_FEEDBACK = "PEER_FEEDBACK"
STAGE_ERROR = "ERROR"
STAGE_ALL_COMPLETE = "ALL_COMPLETE"

# content가 비어 있을 때 fingerprint 입력으로 쓸 후보 키(우선순위)
_CONTENT_KEYS = ("content", "answer", "feedback", "question", "hint", "message")

# 이벤트명 → 고정 stage. 매핑에 없으면 data.stageType 또는 event명 대문자.
_EVENT_STAGE = {
    "all_complete": STAGE_ALL_COMPLETE,
    "done": STAGE_ALL_COMPLETE,
    "error": STAGE_ERROR,
    "agent_error": STAGE_ERROR,
    "turn_start": "TURN_START",
    "heartbeat": "HEARTBEAT",
    "phase_progress": "PHASE_PROGRESS",
}

_TERMINAL_EVENTS = {"all_complete", "done"}

_WS = re.compile(r"\s+")

# native canonicalization은 이 길이 초과 content에서만 시도(짧은 문자열은 Python이 빠름).
_NATIVE_CANON_MIN_CHARS = int(os.getenv("AGENT_FINGERPRINT_NATIVE_MIN_CHARS", "4000"))
_FINGERPRINT_MAX_CHARS = int(os.getenv("AGENT_FINGERPRINT_MAX_CHARS", "8000"))


def new_turn_id() -> str:
    return f"turn_{uuid.uuid4().hex[:16]}"


def new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:16]}"


def _native_normalize(text: str) -> Optional[str]:
    """native_textprep(C 엔진) 재사용. 실패/미존재 시 None → Python fallback."""
    try:
        from app.services.native_textprep import preprocess_and_chunk
        result = preprocess_and_chunk(text, chunk_size=2000, overlap=0)
        cleaned = result.get("cleaned_text")
        if isinstance(cleaned, str):
            return cleaned
    except Exception:
        return None
    return None


def canonicalize_content(text: Any) -> str:
    """fingerprint 입력 표준화: 대소문자/공백 차이 제거 + 길이 상한.

    긴 content는 native_textprep(C, UTF-8 안전)로 1차 정규화 후 Python 마감.
    """
    if not text:
        return ""
    s = text if isinstance(text, str) else str(text)
    if len(s) >= _NATIVE_CANON_MIN_CHARS:
        native = _native_normalize(s)
        if native is not None:
            s = native
    # Python str 슬라이싱은 코드포인트 단위라 UTF-8 안전. 상한으로 해시 비용 고정.
    if len(s) > _FINGERPRINT_MAX_CHARS:
        s = s[:_FINGERPRINT_MAX_CHARS]
    return _WS.sub(" ", s).strip().lower()


def compute_fingerprint(turn_id: str, stage: str, agent_id: Any, content: Any) -> str:
    canon = canonicalize_content(content)
    raw = "\x1f".join([str(turn_id or ""), str(stage or ""), str(agent_id or ""), canon])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _extract_content(data: Dict[str, Any]) -> str:
    for k in _CONTENT_KEYS:
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def resolve_stage(event_name: str, data: Dict[str, Any]) -> str:
    name = (event_name or "").strip().lower()
    if name in _EVENT_STAGE:
        return _EVENT_STAGE[name]
    stage_type = data.get("stageType") if isinstance(data, dict) else None
    if isinstance(stage_type, str) and stage_type.strip():
        return stage_type.strip()
    return name.upper() or "EVENT"


def is_terminal(event_name: str) -> bool:
    return (event_name or "").strip().lower() in _TERMINAL_EVENTS


def enrich_event(
    event_name: str,
    data: Optional[Dict[str, Any]],
    *,
    turn_id: str,
    mode: str,
    event_id: Optional[str] = None,
) -> Dict[str, Any]:
    """기존 data에 envelope 키를 *추가*해 새 dict를 반환(원본 비변형, 기존 키 보존)."""
    out: Dict[str, Any] = dict(data or {})
    stage = resolve_stage(event_name, out)
    content = _extract_content(out)
    agent_id = out.get("agentId")
    agent_name = out.get("agentName") or out.get("name")

    out["eventId"] = event_id or new_event_id()
    out["turnId"] = turn_id
    out["mode"] = mode
    out["stage"] = stage
    out.setdefault("agentId", agent_id)
    if agent_name is not None:
        out.setdefault("agentName", agent_name)
    out.setdefault("content", content)
    out.setdefault("createdAt", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    out["isFinal"] = bool(out.get("isFinal")) or is_terminal(event_name)
    out["fingerprint"] = compute_fingerprint(turn_id, stage, agent_id, content)
    return out
