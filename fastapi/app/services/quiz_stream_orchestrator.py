"""
자료보관함 PDF 기반 퀴즈 streaming 오케스트레이터.

공통 event contract(stream_events)를 따르는 async generator를 제공한다.
Fetch Streaming(NDJSON)과 SSE(EventSource) 라우트가 동일한 generator를 공유한다.

보장(스펙 F/H/I/J/K/L):
  - 90초 안에 반드시 complete 또는 error event 로 종료(무한 로딩 금지).
  - 난이도 검증을 통과한 문항만 partial_validated 로 전송(검증 전 초안 표시 금지).
  - batch(5문항) 단위 생성 → 검증 → 통과분만 누적 → 부족분 repair/fallback.
  - 65초 이후 C fallback(선택) → 실패 시 Python deterministic fallback.
  - 항상 사용자가 선택한 난이도를 지킨다(빠르게 보여주려고 검증을 포기하지 않는다).
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.services import pdf_quiz_service as pq
from app.services.stream_events import (
    FALLBACK_START_SEC, GENERATION_DEADLINE_SEC, HEARTBEAT_SEC,
    QUIZ_MESSAGES, event_payload,
)

logger = logging.getLogger(__name__)

BATCH_SIZE = pq.QUIZ_BATCH_SIZE
PER_BATCH_TIMEOUT = int(__import__("os").getenv("AI_QUIZ_BATCH_TIMEOUT_SEC", "25"))


def _gate_and_finalize(raw_qs: List[Dict[str, Any]], ctx: Dict[str, Any], doc_type: str,
                       diff: str, is_syllabus: bool, admin_keys: List[str],
                       allow_admin: bool, seen: set) -> List[Dict[str, Any]]:
    """검증 통과(형식+난이도+중복+행정정보 금지) 문항만 sanitize+source_trace 부착해 반환."""
    out: List[Dict[str, Any]] = []
    for q in raw_qs or []:
        if not pq._question_difficulty_ok(q, diff, is_syllabus):
            continue
        if is_syllabus and not allow_admin and pq.is_admin_question(q.get("question") or ""):
            continue
        key = pq._norm_q(q.get("question"))
        if not key or key in seen:
            continue
        src = dict(q)
        sq = pq._sanitize_question(dict(q))
        # C fallback 등 이미 source_trace 가 있으면 보존, 없으면 PDF 기반으로 생성
        sq["source_trace"] = src.get("source_trace") or pq._build_source_trace(src, ctx, doc_type, admin_keys)
        sq.pop("_concept", None)
        seen.add(key)
        out.append(sq)
    return out


async def _produce_quiz(queue: "asyncio.Queue", body: Dict[str, Any], request_id: str,
                        job_id: Optional[str], started: float) -> None:
    """생성 파이프라인을 단계별로 실행하며 event 를 queue 에 push 한다."""
    def ev(event: str, **extra: Any) -> Dict[str, Any]:
        msg = extra.pop("message", None) or QUIZ_MESSAGES.get(event)
        return event_payload(event, request_id, "quiz", job_id=job_id, started=started,
                             message=msg, **extra)

    async def push(event: str, **extra: Any) -> None:
        await queue.put(ev(event, **extra))

    try:
        await push("start")

        ctx = pq.build_material_context(body)
        if not ctx["has_pdf_context"]:
            await push("error", success=False, error_code="PDF_CONTEXT_REQUIRED",
                       message="PDF 기반 퀴즈를 생성하려면 자료에서 추출된 텍스트나 요약이 필요합니다.")
            return

        difficulty = body.get("difficulty") or "normal"
        diff = pq.normalize_difficulty(difficulty)
        raw_count = body.get("count")
        if raw_count is None:
            raw_count = body.get("num_questions")
        if raw_count is None:
            raw_count = body.get("numQuestions")
        requested_count, applied_count = pq.normalize_quiz_count(raw_count)
        count_meta = {"requested_count": requested_count, "applied_count": applied_count,
                      "min_count": pq.QUIZ_MIN_COUNT, "max_count": pq.QUIZ_MAX_COUNT}

        doc_type = pq.detect_document_type(ctx)
        is_syllabus = doc_type in ("SYLLABUS", "LECTURE_PLAN")
        allow_admin = bool(body.get("generate_admin_quiz") or body.get("admin_quiz"))
        admin_info: Dict[str, str] = {}
        weekly: List[Dict[str, Any]] = []
        if is_syllabus:
            admin_info, academic = pq.split_syllabus_content(ctx)
            weekly = academic["weekly_schedule"]
            if not weekly and not academic["lecture_topics"]:
                await push("error", success=False, error_code="SYLLABUS_WEEKLY_CONTENT_REQUIRED",
                           message="강의계획서에서 주차별 학습 내용을 찾지 못했습니다.", **count_meta)
                return
        admin_keys = list(admin_info.keys())

        wikipedia_used = False
        wiki_context = ""
        if (not is_syllabus) and diff == "hard":
            wiki_context, wikipedia_used = await asyncio.to_thread(
                pq.fetch_wikipedia_context, pq.extract_concepts(ctx))
        provider_policy = pq.resolve_provider_policy(diff, is_syllabus, wikipedia_used)

        await push("context_ready", documentType=doc_type, isSyllabus=is_syllabus, **count_meta)
        await push("generation_started", targetCount=applied_count,
                   difficultyApplied=diff, providerPolicy=provider_policy)

        validated: List[Dict[str, Any]] = []
        seen: set = set()

        # ── 1) LLM batch 생성 (65초 예산까지) ──
        num_batches = math.ceil(applied_count / BATCH_SIZE)
        attempts = 0
        max_attempts = num_batches + 3
        while (len(validated) < applied_count and attempts < max_attempts
               and (time.monotonic() - started) < FALLBACK_START_SEC):
            attempts += 1
            await push("batch_generated", batch=attempts, validatedCount=len(validated),
                       targetCount=applied_count)
            try:
                llm_qs = await asyncio.wait_for(
                    asyncio.to_thread(pq._llm_generate, ctx, doc_type, diff, BATCH_SIZE,
                                      weekly, wiki_context),
                    timeout=PER_BATCH_TIMEOUT)
            except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
                logger.info("quiz batch %s LLM 실패/지연: %s", attempts, e)
                llm_qs = []
            if not llm_qs:
                break  # LLM 경로가 죽어 있으면 fallback 단계로 전환
            await push("validating", validatedCount=len(validated), targetCount=applied_count)
            newly = _gate_and_finalize(llm_qs, ctx, doc_type, diff, is_syllabus,
                                       admin_keys, allow_admin, seen)
            if newly:
                validated.extend(newly[:applied_count - len(validated)])
                await push("partial_validated", validatedCount=len(validated),
                           targetCount=applied_count, questions=newly[:applied_count])

        # ── 2) 65초 이후 / 부족분 → C fallback(선택) → Python deterministic ──
        if len(validated) < applied_count:
            need = applied_count - len(validated)
            await push("fallback_started", validatedCount=len(validated), targetCount=applied_count)
            candidates: List[Dict[str, Any]] = []
            concepts = pq.extract_concepts(ctx, limit=max(8, need))
            # C fallback 은 candidate. concepts 없으면 건너뛰고 Python 으로.
            try:
                from app.fallback.c_fallback_runner import run_c_quiz_fallback
                c_result = await asyncio.to_thread(run_c_quiz_fallback, diff, need, concepts, 3)
                candidates = c_result.get("questions", []) if isinstance(c_result, dict) else []
                logger.info("quiz C fallback candidate %s개", len(candidates))
            except Exception as e:  # noqa: BLE001
                logger.info("C fallback 미사용/실패 → Python deterministic: %s", e)
                candidates = []
            newly = _gate_and_finalize(candidates, ctx, doc_type, diff, is_syllabus,
                                       admin_keys, allow_admin, seen)
            if newly:
                validated.extend(newly[:applied_count - len(validated)])
                await push("partial_validated", validatedCount=len(validated),
                           targetCount=applied_count, questions=newly[:applied_count])

        # ── 3) 그래도 부족하면 Python deterministic 으로 확정 채움(항상 검증 통과) ──
        if len(validated) < applied_count:
            det = pq.deterministic_questions(ctx, doc_type, diff, applied_count * 2, weekly)
            if is_syllabus and not allow_admin:
                det = pq._replace_admin_questions(det, ctx, doc_type, diff, weekly)
            newly = _gate_and_finalize(det, ctx, doc_type, diff, is_syllabus,
                                       admin_keys, allow_admin, seen)
            if newly:
                validated.extend(newly[:applied_count - len(validated)])
                await push("partial_validated", validatedCount=len(validated),
                           targetCount=applied_count, questions=newly[:applied_count])

        # ── 4) 최종 response 검증 (J) → complete / error ──
        final_q = validated[:applied_count]
        response = {
            "success": True, "error_code": None, "source_mode": pq.SOURCE_MODE,
            "document_type": doc_type, "is_syllabus": is_syllabus,
            "material_id": ctx.get("material_id"), "material_title": ctx.get("title"),
            "difficulty_requested": difficulty, "difficulty_applied": diff,
            "provider_policy": provider_policy, "questions": final_q,
            "_allow_admin_quiz": allow_admin, **count_meta,
        }
        check = pq.validate_quiz_response(response, difficulty, applied_count)
        response.pop("_allow_admin_quiz", None)
        if check["passed"]:
            await push("complete", success=True, questions=final_q,
                       totalCount=applied_count, validation=check, providerPolicy=provider_policy,
                       documentType=doc_type, **count_meta)
        else:
            await push("error", success=False, error_code="QUIZ_GENERATE_FAILED",
                       message="제한 시간 내에 난이도 조건을 만족하는 문제를 생성하지 못했습니다.",
                       validation=check, **count_meta)
    except Exception as e:  # noqa: BLE001
        logger.error("quiz stream producer 예외: %s", e)
        await queue.put(event_payload("error", request_id, "quiz", job_id=job_id, started=started,
                                      success=False, error_code="QUIZ_GENERATE_FAILED",
                                      message="퀴즈 생성 중 오류가 발생했습니다."))
    finally:
        await queue.put(None)  # 종료 sentinel


async def quiz_event_stream(body: Dict[str, Any], request_id: str,
                            job_id: Optional[str] = None) -> AsyncGenerator[Dict[str, Any], None]:
    """
    퀴즈 생성 event 를 yield 하는 async generator.
    - HEARTBEAT_SEC(10초)마다 heartbeat
    - GENERATION_DEADLINE_SEC(90초) 초과 시 강제 error 후 종료(무한 로딩 방지)
    """
    started = time.monotonic()
    queue: asyncio.Queue = asyncio.Queue()
    producer = asyncio.create_task(_produce_quiz(queue, body, request_id, job_id, started))
    terminated = False
    try:
        while True:
            elapsed = time.monotonic() - started
            if elapsed >= GENERATION_DEADLINE_SEC:
                yield event_payload("error", request_id, "quiz", job_id=job_id, started=started,
                                    success=False, error_code="QUIZ_GENERATE_FAILED",
                                    message="제한 시간(90초)을 초과했습니다. 다시 시도해 주세요.")
                terminated = True
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SEC)
            except asyncio.TimeoutError:
                yield event_payload("heartbeat", request_id, "quiz", job_id=job_id, started=started)
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
    if not terminated:  # 방어
        yield event_payload("error", request_id, "quiz", job_id=job_id, started=started,
                            success=False, error_code="QUIZ_GENERATE_FAILED",
                            message="스트림이 비정상 종료되었습니다.")
