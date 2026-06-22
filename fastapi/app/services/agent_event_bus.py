"""ai07 내부 에이전트 이벤트 버스(ZeroMQ inproc) + SSE contract 스트림 래퍼.

설계 원칙(태스크 C):
  - ZeroMQ는 ai07 *내부* FastAPI 프로세스 안에서만 쓴다(브라우저/EC2 직결 금지).
  - 외부 SSE 계약(/api/ai/multi-chat/stream)은 그대로. 이벤트명/페이로드 키는 *추가*만 한다.
  - ZeroMQ는 LLM 토큰 생성을 빠르게 하지 않는다. 목적은 (1) 이벤트 패싱 정리,
    (2) 중복 fingerprint 처리, (3) all_complete 게이트, (4) 향후 worker/C helper 연결 seam.
  - 버스 장애는 절대 사용자 응답으로 전파되지 않는다 → 실패 시 순수 Python passthrough.

기본 backend는 `queue`(= 무손실 passthrough, 운영 안전). `AGENT_EVENT_BUS_BACKEND=zmq`로
켜면 inproc PAIR 소켓 왕복을 통해 내부 메시지 패싱을 실제 ZeroMQ로 흘린다. zmq 초기화/왕복이
실패하면 즉시 queue로 강등(degrade)하고 계속 동작한다.
"""
from __future__ import annotations

import logging
import os
import threading
import uuid
from typing import Any, Dict, Iterable, Iterator, Optional

from app.services.agent_dedup import TurnDeduper
from app.services import agent_event_contract as C

logger = logging.getLogger("studybridge.agent_event_bus")

_DEFAULT_ENDPOINT = os.getenv("AGENT_EVENT_BUS_ENDPOINT", "inproc://studybridge-agent-bus")
_DEFAULT_BACKEND = os.getenv("AGENT_EVENT_BUS_BACKEND", "queue").strip().lower()
_BUS_POLL_MS = int(os.getenv("AGENT_EVENT_BUS_POLL_MS", "150"))

# error류 이벤트 기본 code
_DEFAULT_ERROR_CODE = "STREAM_ERROR"
_ERROR_EVENTS = {"error", "agent_error"}


class AgentEventBus:
    """프로세스 내부 이벤트 패싱 transport. zmq 실패 시 queue(passthrough)로 강등된다."""

    def __init__(self, backend: Optional[str] = None, endpoint: Optional[str] = None) -> None:
        self.transport = (backend or _DEFAULT_BACKEND or "queue").strip().lower()
        self._endpoint = endpoint or _DEFAULT_ENDPOINT
        self.healthy = True
        self.degraded_reason: Optional[str] = None
        self._zmq = None
        self._ctx = None
        self._push = None
        self._pull = None
        self._lock = threading.Lock()
        if self.transport == "zmq":
            self._init_zmq()

    # ── zmq lifecycle ──────────────────────────────────────────────────────
    def _init_zmq(self) -> None:
        try:
            import zmq  # pyzmq

            ctx = zmq.Context.instance()
            # 같은 inproc 네임스페이스 충돌 방지를 위해 인스턴스마다 유니크 endpoint.
            ep = f"{self._endpoint}-{uuid.uuid4().hex[:8]}"
            push = ctx.socket(zmq.PAIR)
            push.setsockopt(zmq.LINGER, 0)
            push.bind(ep)
            pull = ctx.socket(zmq.PAIR)
            pull.setsockopt(zmq.LINGER, 0)
            pull.connect(ep)
            self._zmq, self._ctx, self._push, self._pull = zmq, ctx, push, pull
            logger.info("agent_event_bus: zmq inproc 활성 (%s, libzmq=%s)", ep, zmq.zmq_version())
        except Exception as e:  # pyzmq 미설치/초기화 실패 → queue 강등
            self._degrade(f"zmq init 실패: {e!r}")

    def _degrade(self, reason: str) -> None:
        if self.transport != "queue":
            logger.warning("agent_event_bus: %s → queue passthrough 강등", reason)
        self.transport = "queue"
        self.healthy = False
        self.degraded_reason = reason
        self._close_sockets()

    def _close_sockets(self) -> None:
        for sock in (self._push, self._pull):
            try:
                if sock is not None and hasattr(sock, "close"):
                    sock.close(0)
            except Exception:
                pass
        self._push = self._pull = None

    def close(self) -> None:
        self._close_sockets()

    # ── transport ──────────────────────────────────────────────────────────
    def roundtrip(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        """envelope를 내부 transport로 1회 왕복시키고 동치 dict를 반환한다.

        queue backend는 즉시 동일 객체를 반환(passthrough). zmq backend는 inproc PAIR로
        보낸 뒤 받아서 반환한다. 어떤 실패도 입력 그대로 반환 + queue 강등(절대 raise 안 함)."""
        if self.transport != "zmq" or self._push is None:
            return envelope
        with self._lock:
            try:
                self._push.send_json(envelope, flags=self._zmq.NOBLOCK)
                if self._pull.poll(_BUS_POLL_MS):
                    return self._pull.recv_json()
                raise TimeoutError("bus recv timeout")
            except Exception as e:
                self._degrade(f"roundtrip 실패: {e!r}")
                return envelope


_singleton: Optional[AgentEventBus] = None
_singleton_lock = threading.Lock()


def get_bus() -> AgentEventBus:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = AgentEventBus()
    return _singleton


# ── error 이벤트 정규화 ─────────────────────────────────────────────────────
def normalize_error_event(data: Dict[str, Any]) -> Dict[str, Any]:
    """error/agent_error payload에 code/reason 을 보장한다(내부 stacktrace는 reason으로만)."""
    data.setdefault("code", data.get("code") or _DEFAULT_ERROR_CODE)
    reason = data.get("reason") or data.get("detail") or data.get("message") or "unknown"
    data["reason"] = reason
    return data


# ── contract 스트림 래퍼 ────────────────────────────────────────────────────
def stream_with_contract(
    raw: Iterable[Dict[str, Any]],
    *,
    mode: str,
    turn_id: Optional[str] = None,
    bus: Optional[AgentEventBus] = None,
    deduper: Optional[TurnDeduper] = None,
) -> Iterator[Dict[str, Any]]:
    """raw {"event","data"} 제너레이터를 envelope+dedup+버스로 감싼다.

    - 모든 이벤트에 turnId/eventId/mode/stage/fingerprint/createdAt/isFinal 부착(additive).
    - 같은 fingerprint 재발행 / all_complete 이후 answer류 → drop.
    - error류는 code/reason 보장.
    - 내부 버스(zmq) 왕복은 best-effort. 실패해도 스트림은 끊기지 않는다.
    """
    tid = turn_id or C.new_turn_id()
    dd = deduper or TurnDeduper(tid)
    b = bus if bus is not None else get_bus()

    for item in raw:
        if not isinstance(item, dict):
            continue
        event = item.get("event") or "message"
        data = item.get("data") or {}
        enriched = C.enrich_event(event, data if isinstance(data, dict) else {"content": data},
                                  turn_id=tid, mode=mode)
        if (event or "").strip().lower() in _ERROR_EVENTS:
            enriched = normalize_error_event(enriched)

        # 내부 버스 왕복(best-effort). 어떤 예외도 삼키고 Python 경로로 진행.
        try:
            routed = b.roundtrip(enriched)
            if isinstance(routed, dict) and routed:
                enriched = routed
        except Exception as e:  # 버스 어떤 장애도 사용자 스트림으로 전파 금지
            logger.warning("agent_event_bus roundtrip 예외 무시(passthrough): %r", e)

        if dd.should_emit(event, enriched):
            yield {"event": event, "data": enriched}
