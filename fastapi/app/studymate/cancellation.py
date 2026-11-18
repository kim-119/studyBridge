"""요청 단위 협조적 취소 토큰.

asyncio 취소는 to_thread 안의 동기 제너레이터에 닿지 않는다. 그래서 compat 가
클라이언트 절단을 감지하면 이 토큰을 set 하고, 파이프라인은 새 LLM 호출·새 라운드·
새 grounding·새 repair 를 시작하기 전에 반드시 확인한다. 진행 중인 Ollama 스트림은
llm_gateway 가 청크마다 확인해 연결을 닫는다(=Ollama 쪽 생성도 중단된다).
"""
from __future__ import annotations

import threading
from typing import Optional


class CancelledByClient(RuntimeError):
    """클라이언트 절단/턴 예산 소진으로 더 이상 추론을 시작하지 않는다."""

    def __init__(self, reason: str = "client_disconnected"):
        super().__init__(reason)
        self.reason = reason


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self.reason: Optional[str] = None

    def cancel(self, reason: str = "client_disconnected") -> None:
        if not self._event.is_set():
            self.reason = reason
            self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise CancelledByClient(self.reason or "cancelled")


def fresh_token() -> CancelToken:
    """취소 주체가 없는 호출(레거시/테스트)용 새 토큰. 전역 공유 토큰은 두지 않는다."""
    return CancelToken()
