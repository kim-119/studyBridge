"""SSE 타입드 계약 + 순서/짝 불변식 시퀀서 + dedup.

외부 호환(EC2 수정 불가)
  - SSE 이벤트 '이름'은 기존과 같다(turn_start/agent_start/agent_answer/agent_error/heartbeat/
    follow_up_suggestions/all_complete/done). 턴 단위 치명 오류는 이벤트 이름 'error' 를 유지하고
    eventType='stream_error' 로 타입을 명시한다(Spring 은 agentId/agentIndex 가 없는 'error' 를 fatal 로
    보고 failover 한다 — 의도된 동작).
  - Spring 은 all_complete 가 없으면 업스트림 불완전으로 보고 보조 서버로 재생성한다.
    → 정상/부분실패/예산초과 모두 all_complete 를 반드시 1회 보낸다.

불변식
  turn_start 정확히 1회(첫 이벤트) / all_complete ≤ 1 / done 정확히 1회(정상 연결) /
  done 이후 business event 없음 / 발화마다 agent_start → agent_answer|agent_error
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger("studybridge.studymate.sse")

CONTRACT_VERSION = "studymate-sse-2"

CORE_EVENTS = ("turn_start", "agent_start", "agent_answer", "agent_error", "heartbeat",
               "follow_up_suggestions", "all_complete", "stream_error", "done")
# 모드 엔진이 내보내는 확장 이벤트(프론트가 이미 처리). 계약 필드는 동일하게 부착한다.
EXTENSION_EVENTS = ("phase_progress", "debate_round", "debate_section", "debate_topic_candidates",
                    "socratic_step", "validation_summary", "direct_reply", "professor_motion",
                    "interaction_event", "synthesis_diff", "stage_complete", "route_notice")
CONTROL_EVENTS = {"heartbeat", "phase_progress", "professor_motion"}
TERMINAL_EVENTS = {"all_complete", "done"}


class SSEEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    contractVersion: str
    eventId: str
    requestId: str
    turnId: str
    eventType: str
    mode: str
    stage: str
    agentId: Optional[Any] = None       # 원본 타입 보존(int/str)
    agentIndex: Optional[int] = None
    agentName: Optional[str] = None
    status: Optional[str] = None
    code: Optional[str] = None
    degraded: bool = False
    isFinal: bool = False
    createdAt: str
    content: str = ""


_STAGE_BY_EVENT = {
    "turn_start": "TURN_START", "agent_start": "AGENT_START", "agent_answer": "AGENT_ANSWER",
    "agent_error": "AGENT_ERROR", "heartbeat": "HEARTBEAT", "follow_up_suggestions": "FOLLOW_UP",
    "all_complete": "ALL_COMPLETE", "stream_error": "ERROR", "done": "DONE",
}


def _content(data: Dict[str, Any]) -> str:
    for k in ("content", "answer", "feedback", "question", "hint", "message"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def envelope(event_name: str, data: Dict[str, Any], *, request_id: str, turn_id: str, mode: str) -> Dict[str, Any]:
    out = dict(data or {})
    etype = "stream_error" if event_name == "error" else event_name
    out.setdefault("type", event_name)
    out["contractVersion"] = CONTRACT_VERSION
    out["eventId"] = f"evt_{uuid.uuid4().hex[:16]}"
    out["requestId"] = request_id
    out["turnId"] = turn_id
    out["eventType"] = etype
    out["mode"] = out.get("mode") or mode
    st = out.get("stageType") if isinstance(out.get("stageType"), str) and out.get("stageType") else None
    out["stage"] = st or _STAGE_BY_EVENT.get(etype) or etype.upper()
    aid = out.get("agentId")
    out["agentId"] = None if aid in (None, "") else aid
    ai = out.get("agentIndex")
    try:
        out["agentIndex"] = int(ai) if ai not in (None, "") else None
    except (TypeError, ValueError):
        out["agentIndex"] = None
    out.setdefault("agentName", None)
    out.setdefault("status", None)
    out.setdefault("code", None)
    out["degraded"] = bool(out.get("degraded"))
    out["isFinal"] = etype in TERMINAL_EVENTS
    out.setdefault("createdAt", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    if not isinstance(out.get("content"), str):
        out["content"] = _content(out)
    elif not out["content"]:
        out["content"] = _content(out)
    out["fingerprint"] = fingerprint(event_name, out)
    return out


def validate_event(data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    try:
        SSEEvent(**data)
        return True, None
    except Exception as e:
        return False, str(e)[:200]


def serialize(event_name: str, data: Dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def fingerprint(event_name: str, data: Dict[str, Any]) -> str:
    content = re.sub(r"\s+", " ", _content(data)).strip().lower()[:6000]
    parts = [str(data.get(k) or "") for k in ("turnId", "agentId", "stage", "stageType", "phase", "actType",
                                              "displayOrder", "round", "sequence", "code")]
    raw = "\x1f".join([event_name] + parts + [content])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class Sequencer:
    """한 턴의 이벤트 순서/짝/중복을 강제한다. 위반은 '수리 + 계수 + 로그'로 드러낸다."""

    def __init__(self, request_id: str, turn_id: str, mode: str):
        self.request_id, self.turn_id, self.mode = request_id, turn_id, mode
        self.turn_started = False
        self.all_complete_sent = False
        self.done_sent = False
        self.pending: Dict[str, List[Dict[str, Any]]] = {}   # agentId → 열린 agent_start 들
        self.seen: set = set()
        self.dedup_dropped = 0
        self.contract_repairs: List[str] = []
        self.invalid_events = 0
        self.answers: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []
        self.started_ids: List[str] = []
        self.counts: Dict[str, int] = {}

    def _env(self, name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        out = envelope(name, data, request_id=self.request_id, turn_id=self.turn_id, mode=self.mode)
        ok, err = validate_event(out)
        if not ok:
            self.invalid_events += 1
            logger.error("[SSE-CONTRACT] invalid event=%s err=%s", name, err)
        return out

    def _count(self, name: str) -> None:
        self.counts[name] = self.counts.get(name, 0) + 1

    def feed(self, name: str, data: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
        """업스트림 이벤트 1개 → 실제로 내보낼 (event, data) 목록(0..n)."""
        out: List[Tuple[str, Dict[str, Any]]] = []
        if self.done_sent:
            self.contract_repairs.append(f"after_done_drop:{name}")
            return out
        data = dict(data or {})
        if name == "done":
            return out   # done 은 compat 가 단독으로 1회 보낸다
        if name == "turn_start":
            if self.turn_started:
                self.contract_repairs.append("duplicate_turn_start_drop")
                return out
            self.turn_started = True
            out.append(("turn_start", self._env("turn_start", data)))
            self._count("turn_start")
            return out
        if not self.turn_started and name not in CONTROL_EVENTS:
            self.turn_started = True
            self.contract_repairs.append("turn_start_injected")
            out.append(("turn_start", self._env("turn_start", {"type": "turn_start", "phase": "TURN_START",
                                                                "visible": True, "message": "답변을 준비하고 있습니다..."})))
            self._count("turn_start")
        if self.all_complete_sent and name != "heartbeat":
            self.contract_repairs.append(f"after_all_complete_drop:{name}")
            return out
        if name == "heartbeat":
            hb = {"type": "heartbeat", "phase": "HEARTBEAT", "visible": False,
                  "elapsedMs": data.get("elapsedMs"), "message": data.get("message") or "답변 생성 중입니다.",
                  # 프론트는 agentIndex 로 '이미 열린' 대기 말풍선의 상태 문구만 갱신한다(새 메시지 생성 안 함).
                  "agentIndex": data.get("agentIndex")}
            out.append(("heartbeat", self._env("heartbeat", hb)))
            return out
        env = self._env(name, data)
        if name not in CONTROL_EVENTS and name != "all_complete":
            fp = fingerprint(name, env)
            if fp in self.seen:
                self.dedup_dropped += 1
                logger.info("[SSE-DEDUP] drop event=%s agent=%s stage=%s", name, env.get("agentId"), env.get("stage"))
                return out
            self.seen.add(fp)
        aid = "" if env.get("agentId") is None else str(env.get("agentId"))
        if name == "agent_start":
            self.pending.setdefault(aid, []).append(env)
            self.started_ids.append(aid)
        elif name in ("agent_answer", "agent_error"):
            if self.pending.get(aid):
                self.pending[aid].pop(0)
            else:
                self.contract_repairs.append(f"agent_start_injected:{aid}")
                start = {k: env.get(k) for k in ("agentId", "agentIndex", "agentName", "phase", "actType",
                                                 "stageType", "displayOrder", "personality", "personalityKey",
                                                 "personalityLabel", "knowledgeLevel", "knowledgeLevelKey",
                                                 "knowledgeLevelLabel") if env.get(k) is not None}
                start.update({"type": "agent_start", "visible": True})
                out.append(("agent_start", self._env("agent_start", start)))
                self._count("agent_start")
                self.started_ids.append(aid)
            (self.answers if name == "agent_answer" else self.errors).append(env)
        elif name == "all_complete":
            for pid, starts in list(self.pending.items()):
                for st in starts:
                    self.contract_repairs.append(f"missing_result_error_injected:{pid}")
                    err = {"type": "agent_error", "agentId": st.get("agentId"), "agentIndex": st.get("agentIndex"),
                           "agentName": st.get("agentName"), "phase": st.get("phase"), "actType": st.get("actType"),
                           "displayOrder": st.get("displayOrder"), "status": "FAILED", "degraded": True,
                           "code": "AGENT_ANSWER_MISSING", "message": "이 교수의 답변을 받지 못했어요."}
                    e_env = self._env("agent_error", err)
                    self.errors.append(e_env)
                    out.append(("agent_error", e_env))
                    self._count("agent_error")
                starts.clear()
            self.all_complete_sent = True
        out.append((name, env))
        self._count(name)
        return out

    def open_starts(self) -> List[Dict[str, Any]]:
        return [s for starts in self.pending.values() for s in starts]

    def done(self, status: str, elapsed_ms: int, extra: Optional[Dict[str, Any]] = None) -> Tuple[str, Dict[str, Any]]:
        self.done_sent = True
        self._count("done")
        data = {"type": "done", "phase": "DONE", "visible": False, "status": status, "elapsedMs": elapsed_ms}
        if extra:
            data.update(extra)
        return "done", envelope("done", data, request_id=self.request_id, turn_id=self.turn_id, mode=self.mode)

    def stats(self) -> Dict[str, Any]:
        return {"counts": dict(self.counts), "dedupDropped": self.dedup_dropped,
                "contractRepairs": list(self.contract_repairs), "invalidEvents": self.invalid_events}
