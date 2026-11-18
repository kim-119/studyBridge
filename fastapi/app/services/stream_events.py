"""
자료보관함 퀴즈/로드맵 streaming 공통 event contract.

Fetch Streaming(NDJSON)과 SSE(EventSource) 두 transport가 동일한 event payload를 사용한다.
프론트는 transport만 다르고 같은 reducer로 처리한다(스펙 E/C/V).

event 종류: start, context_ready, generation_started, batch_generated, validating,
            repair_started, fallback_started, partial_validated, complete, error, heartbeat
공통 필드: event, requestId, jobId, type, message, elapsedMs
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Optional

HEARTBEAT_SEC = int(__import__("os").getenv("AI_STREAM_HEARTBEAT_SEC", "10"))
GENERATION_DEADLINE_SEC = int(__import__("os").getenv("AI_STREAM_DEADLINE_SEC", "90"))
FALLBACK_START_SEC = int(__import__("os").getenv("AI_STREAM_FALLBACK_START_SEC", "65"))

# 사용자 표시 문구 (스펙 W)
QUIZ_MESSAGES = {
    "start": "PDF 내용을 분석하고 있습니다.",
    "context_ready": "PDF 내용을 분석하고 있습니다.",
    "generation_started": "문제를 생성하고 있습니다.",
    "validating": "난이도를 검증하고 있습니다.",
    "partial_validated": "검증된 문제를 표시하고 있습니다.",
    "fallback_started": "응답이 지연되어 빠른 생성기로 전환합니다.",
    "complete": "완료되었습니다.",
}
ROADMAP_MESSAGES = {
    "start": "문서 구조를 분석하고 있습니다.",
    "context_ready": "문서 구조를 분석하고 있습니다.",
    "generation_started": "주차별 학습 흐름을 구성하고 있습니다.",
    "validating": "84일 로드맵을 검증하고 있습니다.",
    "fallback_started": "응답이 지연되어 빠른 생성기로 전환합니다.",
    "complete": "완료되었습니다.",
}


def make_request_id(type_: str) -> str:
    """quiz-YYYYMMDD-xxxx 형태의 requestId 생성."""
    return f"{type_}-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"


def make_job_id() -> str:
    return f"job-{uuid.uuid4().hex[:12]}"


def event_payload(event: str, request_id: str, type_: str,
                  job_id: Optional[str] = None, started: Optional[float] = None,
                  message: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
    """공통 event payload dict 생성."""
    payload: Dict[str, Any] = {
        "event": event,
        "requestId": request_id,
        "jobId": job_id,
        "type": type_,
    }
    if message is not None:
        payload["message"] = message
    if started is not None:
        payload["elapsedMs"] = int((time.monotonic() - started) * 1000)
    payload.update(extra)
    return payload


def to_sse(payload: Dict[str, Any]) -> str:
    """SSE(EventSource) 포맷. event: <name>\\ndata: <json>\\n\\n"""
    name = payload.get("event", "message")
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def to_ndjson(payload: Dict[str, Any]) -> str:
    """Fetch Streaming(NDJSON) 포맷. 한 줄당 하나의 JSON event."""
    return json.dumps(payload, ensure_ascii=False) + "\n"
