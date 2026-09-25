"""
자료보관함 PDF 기반 12주×7일=84일 로드맵 streaming 오케스트레이터.

quiz_stream_orchestrator 와 동일한 event contract/heartbeat/90초 deadline 정책을 따른다.
84일 구조(total_weeks=12, days_per_week=7, total_days=84)를 검증 통과한 경우에만 complete 한다.
로드맵 생성 실패 시 error event 만 보내고, 기존 정상 로드맵 삭제/교체는 프론트에서 막는다(스펙 U/V).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.services.stream_events import (
    FALLBACK_START_SEC, GENERATION_DEADLINE_SEC, HEARTBEAT_SEC,
    ROADMAP_MESSAGES, event_payload,
)

logger = logging.getLogger(__name__)


async def _produce_roadmap(queue: "asyncio.Queue", body: Dict[str, Any], request_id: str,
                           job_id: Optional[str], started: float) -> None:
    from app.services.study_action_router import (
        build_roadmap_ctx, generate_12week_7day_roadmap,
        finalize_roadmap_response, roadmap_failure_response,
    )

    def ev(event: str, **extra: Any) -> Dict[str, Any]:
        msg = extra.pop("message", None) or ROADMAP_MESSAGES.get(event)
        return event_payload(event, request_id, "roadmap", job_id=job_id, started=started,
                             message=msg, **extra)

    async def push(event: str, **extra: Any) -> None:
        await queue.put(ev(event, **extra))

    try:
        await push("start")
        ctx = build_roadmap_ctx(body if isinstance(body, dict) else {})
        await push("context_ready")
        await push("generation_started")

        # ── 1) LLM 로드맵 생성 (65초 예산) ──
        result: Optional[Dict[str, Any]] = None
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(generate_12week_7day_roadmap, ctx),
                timeout=FALLBACK_START_SEC)
        except asyncio.TimeoutError:
            logger.info("roadmap LLM 65초 초과 → deterministic fallback")
            result = None
        except Exception as e:  # noqa: BLE001
            logger.info("roadmap LLM 실패 → deterministic fallback: %s", e)
            result = None

        await push("validating")
        final = finalize_roadmap_response(result) if isinstance(result, dict) else {"validation": {"passed": False}}

        # ── 2) 검증 실패/타임아웃 → deterministic 84일 재구성 ──
        if not final.get("validation", {}).get("passed"):
            await push("fallback_started")
            try:
                rebuilt = await asyncio.to_thread(generate_12week_7day_roadmap, {**ctx, "_no_llm": True})
                final = finalize_roadmap_response(rebuilt)
            except Exception as e:  # noqa: BLE001
                logger.error("roadmap deterministic fallback 실패: %s", e)

        if final.get("validation", {}).get("passed"):
            weeks = final.get("weeks", [])
            # 검증 통과 week 미리보기(partial_validated) — 검증된 84일 구조에서만 전송
            await push("partial_validated", validatedWeeks=len(weeks), targetWeeks=12,
                       totalDays=final.get("total_days"), weeks=weeks)
            await push("complete", success=True, roadmap=final,
                       totalWeeks=final.get("total_weeks"), daysPerWeek=final.get("days_per_week"),
                       totalDays=final.get("total_days"), validation=final.get("validation"))
        else:
            fail = roadmap_failure_response(
                "제한 시간 내에 84일 로드맵을 생성하지 못했습니다.",
                "84일 구조 검증 실패(재빌드 후에도)",
                final.get("validation", {}).get("reason", "알 수 없음"))
            await push("error", success=False, error_code=fail["error_code"],
                       message=fail["message"], validation=fail["validation"])
    except Exception as e:  # noqa: BLE001
        logger.error("roadmap stream producer 예외: %s", e)
        await queue.put(event_payload("error", request_id, "roadmap", job_id=job_id, started=started,
                                      success=False, error_code="ROADMAP_GENERATE_FAILED",
                                      message="로드맵 생성 중 오류가 발생했습니다."))
    finally:
        await queue.put(None)


async def roadmap_event_stream(body: Dict[str, Any], request_id: str,
                               job_id: Optional[str] = None) -> AsyncGenerator[Dict[str, Any], None]:
    """로드맵 생성 event async generator. heartbeat 10초 / 90초 deadline 보장."""
    started = time.monotonic()
    queue: asyncio.Queue = asyncio.Queue()
    producer = asyncio.create_task(_produce_roadmap(queue, body, request_id, job_id, started))
    terminated = False
    try:
        while True:
            if (time.monotonic() - started) >= GENERATION_DEADLINE_SEC:
                yield event_payload("error", request_id, "roadmap", job_id=job_id, started=started,
                                    success=False, error_code="ROADMAP_GENERATE_FAILED",
                                    message="제한 시간(90초)을 초과했습니다. 기존 로드맵은 그대로 유지됩니다.")
                terminated = True
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SEC)
            except asyncio.TimeoutError:
                yield event_payload("heartbeat", request_id, "roadmap", job_id=job_id, started=started)
                continue
            if item is None:
                terminated = True
                break
            yield item
            if item.get("event") in ("complete", "error"):
                terminated = True
                break
    finally:
        producer.cancel()
        try:
            await producer
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    if not terminated:
        yield event_payload("error", request_id, "roadmap", job_id=job_id, started=started,
                            success=False, error_code="ROADMAP_GENERATE_FAILED",
                            message="스트림이 비정상 종료되었습니다.")
