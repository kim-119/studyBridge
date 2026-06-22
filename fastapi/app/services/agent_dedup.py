"""turn 단위 이벤트 중복 방어 + all_complete 게이트.

순수 Python(외부 의존성 없음). 멀티에이전트 SSE 제너레이터가 발행하는 enriched 이벤트에
대해 결정적으로 중복/지연 이벤트를 걸러낸다.

규칙:
  1. 같은 fingerprint 재발행 → drop.
  2. all_complete/done 이후의 answer류 이벤트 → drop(지연/경합으로 늦게 도착한 답변 차단).
  3. 제어(turn_start/heartbeat/phase_progress)·종료(all_complete/done)·error 는 항상 통과.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Set

# 게이트/중복판정에서 제외(항상 통과)
_CONTROL_EVENTS = {"turn_start", "heartbeat", "phase_progress", "validation_summary"}
_TERMINAL_EVENTS = {"all_complete", "done"}
_ERROR_EVENTS = {"error"}

# all_complete 이후 차단 대상(콘텐츠/답변류)
_ANSWER_EVENTS = {
    "agent_answer", "agent_message", "agent_start", "agent_error",
    "socratic_step", "validation", "peer_feedback",
}


class TurnDeduper:
    """한 turn(요청) 동안의 상태. 요청마다 새 인스턴스를 만든다."""

    def __init__(self, turn_id: Optional[str] = None) -> None:
        self.turn_id = turn_id
        self.completed = False
        self._seen: Set[str] = set()
        self.dropped = 0

    def should_emit(self, event_name: str, data: Dict[str, Any]) -> bool:
        name = (event_name or "").strip().lower()

        if name in _CONTROL_EVENTS:
            return True
        if name in _ERROR_EVENTS:
            return True
        if name in _TERMINAL_EVENTS:
            self.completed = True
            return True

        # 콘텐츠/답변류 이벤트
        if self.completed and name in _ANSWER_EVENTS:
            self.dropped += 1
            return False

        fp = data.get("fingerprint") if isinstance(data, dict) else None
        if fp is not None:
            if fp in self._seen:
                self.dropped += 1
                return False
            self._seen.add(fp)
        return True
