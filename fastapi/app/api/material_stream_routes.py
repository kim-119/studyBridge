"""
자료보관함 퀴즈/로드맵 streaming 라우터 — Fetch Streaming(NDJSON) + SSE job 두 방식 동시 지원.

  Fetch Streaming (POST, 큰 payload):
    POST /api/ai/quiz/generate-stream      -> application/x-ndjson
    POST /api/ai/roadmap/generate-stream   -> application/x-ndjson

  SSE job (POST 생성 → EventSource 구독):
    POST /api/ai/quiz/jobs                  -> {jobId, eventToken}
    GET  /api/ai/quiz/jobs/{jobId}/events?eventToken=...   (text/event-stream)
    POST /api/ai/roadmap/jobs               -> {jobId, eventToken}
    GET  /api/ai/roadmap/jobs/{jobId}/events?eventToken=...

인증(스펙 B):
  - POST 계열은 verify_internal_token(Spring → FastAPI Bearer).
  - GET events 는 브라우저 EventSource가 헤더를 못 넣으므로, POST /jobs 에서 발급한
    1회성 oneTimeEventToken(짧은 TTL, jobId 매칭)으로만 연결을 허용한다.
    장기 JWT 를 query string 에 노출하지 않는다. 토큰/jobId 불일치 시 403.

이 라우터는 그룹스터디/멀티에이전트/AI채팅 SSE와 파일/함수/엔드포인트를 공유하지 않는다.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from fastapi.responses import StreamingResponse

from app.core.security import verify_internal_token
from app.services.quiz_stream_orchestrator import quiz_event_stream
from app.services.roadmap_stream_orchestrator import roadmap_event_stream
from app.services.stream_events import (
    make_job_id, make_request_id, to_ndjson, to_sse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["Material Stream (quiz/roadmap)"])

JOB_TTL_SEC = int(os.getenv("AI_STREAM_JOB_TTL_SEC", "600"))
_STREAM_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}

# 인메모리 job 저장소(단일 프로세스 기준). 운영 다중 워커면 Redis 로 교체.
_JOBS: Dict[str, Dict[str, Any]] = {}


def _purge_expired() -> None:
    now = time.time()
    for jid in [k for k, v in _JOBS.items() if now - v.get("createdAt", now) > JOB_TTL_SEC]:
        _JOBS.pop(jid, None)


def _create_job(type_: str, body: Dict[str, Any], request_id: str) -> Dict[str, str]:
    _purge_expired()
    job_id = make_job_id()
    event_token = secrets.token_urlsafe(24)  # 1회성·짧은 TTL 토큰
    _JOBS[job_id] = {
        "jobId": job_id, "type": type_, "body": body, "requestId": request_id,
        "eventToken": event_token, "createdAt": time.time(),
        # 폴링(백엔드 통신) 전용 상태. SSE/Fetch Streaming 경로와 독립.
        "events": [], "status": "queued", "bgTask": None,
    }
    return {"jobId": job_id, "eventToken": event_token, "requestId": request_id}


def _resolve_job(job_id: str, event_token: str, type_: str) -> Dict[str, Any]:
    _purge_expired()
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없거나 만료되었습니다.")
    if job.get("type") != type_:
        raise HTTPException(status_code=404, detail="작업 유형이 일치하지 않습니다.")
    if not event_token or not secrets.compare_digest(str(event_token), str(job.get("eventToken", ""))):
        # 다른 유저/위조 토큰으로 job events 구독 차단
        raise HTTPException(status_code=403, detail="유효하지 않은 eventToken 입니다.")
    return job


# ── 폴링(Spring 백엔드 → ai07) 전용 백그라운드 잡 처리 ────────────────────────
#   SSE events 엔드포인트는 구독 시 generator 를 1회 소비한다(스트리밍 전용).
#   폴링은 매 요청마다 generator 를 재실행하면 안 되므로, 최초 poll 시 백그라운드
#   task 1개만 띄워 event 를 job["events"] 에 누적하고, 이후 poll 은 cursor 이후
#   누적분만 스냅샷으로 돌려준다. 두 경로는 서로 간섭하지 않는다.
async def _drain_job(job_id: str, gen_factory: Callable[[], AsyncGenerator[Dict[str, Any], None]]) -> None:
    job = _JOBS.get(job_id)
    if job is None:
        return
    job["status"] = "running"
    try:
        async for ev in gen_factory():
            cur = _JOBS.get(job_id)
            if cur is None:  # 만료/삭제
                return
            cur["events"].append(ev)
            name = ev.get("event")
            if name == "complete":
                cur["status"] = "complete"
            elif name == "error":
                cur["status"] = "error"
    except Exception as exc:  # noqa: BLE001
        logger.warning("poll job %s drain 실패: %s", job_id, exc)
        cur = _JOBS.get(job_id)
        if cur is not None:
            cur["events"].append({
                "event": "error", "jobId": job_id, "type": cur.get("type"),
                "requestId": cur.get("requestId"),
                "message": "생성 중 오류가 발생했습니다. 다시 시도해주세요.",
            })
            cur["status"] = "error"
    finally:
        cur = _JOBS.get(job_id)
        if cur is not None:
            if cur.get("status") == "running":
                cur["status"] = "complete"
            cur["finishedAt"] = time.time()


def _ensure_bg(job_id: str, gen_factory: Callable[[], AsyncGenerator[Dict[str, Any], None]]) -> None:
    job = _JOBS.get(job_id)
    if job is None:
        return
    if job.get("bgTask") is None:
        job["bgTask"] = asyncio.create_task(_drain_job(job_id, gen_factory))


def _poll_snapshot(job: Dict[str, Any], cursor: int) -> Dict[str, Any]:
    events: List[Dict[str, Any]] = job.get("events", [])
    cursor = max(0, int(cursor or 0))
    new_events = events[cursor:]
    status = job.get("status", "queued")
    return {
        "jobId": job["jobId"],
        "type": job.get("type"),
        "requestId": job.get("requestId"),
        "status": status,
        "cursor": cursor + len(new_events),
        "events": new_events,
        "done": status in ("complete", "error"),
    }


async def _ndjson_response(gen_factory: Callable[[], AsyncGenerator[Dict[str, Any], None]]) -> StreamingResponse:
    async def body_iter():
        async for payload in gen_factory():
            yield to_ndjson(payload)
    return StreamingResponse(body_iter(), media_type="application/x-ndjson", headers=_STREAM_HEADERS)


async def _sse_response(gen_factory: Callable[[], AsyncGenerator[Dict[str, Any], None]]) -> StreamingResponse:
    async def body_iter():
        async for payload in gen_factory():
            yield to_sse(payload)
    return StreamingResponse(body_iter(), media_type="text/event-stream", headers=_STREAM_HEADERS)


# ── Fetch Streaming (NDJSON) ──────────────────────────────────────────────────
@router.post("/quiz/generate-stream", dependencies=[Depends(verify_internal_token)],
             summary="퀴즈 Fetch Streaming(NDJSON) — 큰 payload POST + 실시간 진행")
async def quiz_generate_stream(body: Dict[str, Any] = Body(default_factory=dict)) -> StreamingResponse:
    request_id = str(body.get("requestId") or make_request_id("quiz"))
    return await _ndjson_response(lambda: quiz_event_stream(body, request_id))


@router.post("/roadmap/generate-stream", dependencies=[Depends(verify_internal_token)],
             summary="로드맵 Fetch Streaming(NDJSON) — 12주×7일=84일 진행")
async def roadmap_generate_stream(body: Dict[str, Any] = Body(default_factory=dict)) -> StreamingResponse:
    request_id = str(body.get("requestId") or make_request_id("roadmap"))
    return await _ndjson_response(lambda: roadmap_event_stream(body, request_id))


# ── SSE job (POST 생성 → EventSource 구독) ────────────────────────────────────
@router.post("/quiz/jobs", dependencies=[Depends(verify_internal_token)],
             summary="퀴즈 SSE job 생성 → {jobId, eventToken}")
async def quiz_job_create(body: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    request_id = str(body.get("requestId") or make_request_id("quiz"))
    return {**_create_job("quiz", body, request_id), "status": "queued", "type": "quiz"}


@router.get("/quiz/jobs/{job_id}/events", summary="퀴즈 SSE job 구독 (EventSource)")
async def quiz_job_events(job_id: str = Path(...),
                          event_token: str = Query(..., alias="eventToken")) -> StreamingResponse:
    job = _resolve_job(job_id, event_token, "quiz")
    return await _sse_response(lambda: quiz_event_stream(job["body"], job["requestId"], job_id=job_id))


@router.post("/roadmap/jobs", dependencies=[Depends(verify_internal_token)],
             summary="로드맵 SSE job 생성 → {jobId, eventToken}")
async def roadmap_job_create(body: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    request_id = str(body.get("requestId") or make_request_id("roadmap"))
    return {**_create_job("roadmap", body, request_id), "status": "queued", "type": "roadmap"}


@router.get("/roadmap/jobs/{job_id}/events", summary="로드맵 SSE job 구독 (EventSource)")
async def roadmap_job_events(job_id: str = Path(...),
                             event_token: str = Query(..., alias="eventToken")) -> StreamingResponse:
    job = _resolve_job(job_id, event_token, "roadmap")
    return await _sse_response(lambda: roadmap_event_stream(job["body"], job["requestId"], job_id=job_id))


# ── 폴링(POST /jobs 생성 → GET /poll 반복) — Spring 백엔드 릴레이용 ───────────────
#   EventSource/Fetch Streaming 을 못 쓰는 환경(프록시·구버전 브라우저)에서
#   Spring 이 cursor 기반으로 주기 폴링한다. 같은 event contract(partial_validated/
#   complete/error)를 누적 스냅샷으로 반환한다.
@router.get("/quiz/jobs/{job_id}/poll", summary="퀴즈 job 폴링 스냅샷 (cursor 기반)")
async def quiz_job_poll(job_id: str = Path(...),
                        event_token: str = Query(..., alias="eventToken"),
                        cursor: int = Query(0)) -> Dict[str, Any]:
    job = _resolve_job(job_id, event_token, "quiz")
    _ensure_bg(job_id, lambda: quiz_event_stream(job["body"], job["requestId"], job_id=job_id))
    return _poll_snapshot(job, cursor)


@router.get("/roadmap/jobs/{job_id}/poll", summary="로드맵 job 폴링 스냅샷 (cursor 기반)")
async def roadmap_job_poll(job_id: str = Path(...),
                           event_token: str = Query(..., alias="eventToken"),
                           cursor: int = Query(0)) -> Dict[str, Any]:
    job = _resolve_job(job_id, event_token, "roadmap")
    _ensure_bg(job_id, lambda: roadmap_event_stream(job["body"], job["requestId"], job_id=job_id))
    return _poll_snapshot(job, cursor)
