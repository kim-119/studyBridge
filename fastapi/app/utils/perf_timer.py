"""
Hot Path 계측 유틸 — AI 요청 전후 구간 소요시간(ms)을 측정해 [AI_PERF] 한 줄 로그로 남긴다.

설계 원칙:
  - 기존 코드 경로/응답을 바꾸지 않는다. 순수 부가 계측이다.
  - AI_HOT_PATH_LOG_ENABLED=false면 로그를 남기지 않는다(측정 자체 오버헤드는 microsecond 수준).
  - 예외가 나도 본 작업을 방해하지 않는다(측정 실패가 기능 실패가 되면 안 됨).

사용 예:
    perf = PerfTimer("material_chat", request_id="req-123")
    with perf.section("rag_retrieve_ms"):
        chunks = retrieve_similar_chunks(...)
    perf.mark("llm_first_token_ms")     # 첫 토큰 시점 기록
    ...
    perf.log()  # [AI_PERF] feature=material_chat request_id=... rag_retrieve_ms=41 ...

표준 구간 키(공통 계측):
  request_parse_ms, intent_routing_ms, prompt_build_ms, rag_retrieve_ms,
  context_compress_ms, llm_first_token_ms, llm_total_ms, verify_ms,
  feedback_ms, json_validate_ms, postprocess_ms, total_ms
"""
import logging
import os
import time
import uuid
from contextlib import contextmanager
from typing import Dict, Optional

logger = logging.getLogger("studybridge.ai_perf")


def _enabled() -> bool:
    # 호출 시점에 평가 → 테스트/운영에서 monkeypatch·환경변경 즉시 반영.
    return os.getenv("AI_HOT_PATH_LOG_ENABLED", "true").strip().lower() == "true"


class PerfTimer:
    """단일 AI 요청의 구간별 소요시간을 모아 한 줄로 로깅한다."""

    def __init__(self, feature: str, request_id: Optional[str] = None):
        self.feature = feature
        self.request_id = request_id or f"req_{uuid.uuid4().hex[:12]}"
        self._t0 = time.perf_counter()
        self._marks: Dict[str, float] = {}

    # ── 구간 측정 ────────────────────────────────────────────────────────────
    @contextmanager
    def section(self, key: str):
        """with 블록의 소요시간(ms)을 key에 누적 기록한다."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - start) * 1000.0
            self._marks[key] = round(self._marks.get(key, 0.0) + elapsed, 1)

    def mark(self, key: str, value_ms: Optional[float] = None) -> None:
        """
        시점 마킹. value_ms가 없으면 timer 시작 이후 경과시간(ms)을 기록한다.
        (예: 첫 토큰까지 걸린 시간 llm_first_token_ms)
        """
        if value_ms is None:
            value_ms = (time.perf_counter() - self._t0) * 1000.0
        self._marks[key] = round(value_ms, 1)

    def set(self, key: str, value_ms: float) -> None:
        self._marks[key] = round(value_ms, 1)

    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000.0, 1)

    # ── 출력 ────────────────────────────────────────────────────────────────
    def snapshot(self, **extra) -> Dict[str, object]:
        data = {"feature": self.feature, "request_id": self.request_id}
        data.update(self._marks)
        data.update({k: v for k, v in extra.items() if v is not None})
        return data

    def log(self, **extra) -> None:
        """total_ms를 채우고 [AI_PERF] 한 줄을 남긴다. 비활성/예외 시 조용히 무시."""
        try:
            if not _enabled():
                return
            self._marks.setdefault("total_ms", self.elapsed_ms())
            parts = [f"feature={self.feature}", f"request_id={self.request_id}"]
            for k, v in self._marks.items():
                if k in ("feature", "request_id"):
                    continue
                parts.append(f"{k}={v}")
            for k, v in extra.items():
                if v is not None:
                    parts.append(f"{k}={v}")
            logger.info("[AI_PERF] %s", " ".join(parts))
        except Exception:  # 계측 실패가 본 기능을 막지 않는다
            pass
