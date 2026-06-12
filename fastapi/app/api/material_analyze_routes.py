"""
자료보관함 전용 분석 라우터 — 구조화 요약 + 빠른 체감 응답(async job / SSE).

이 라우터는 기존 멀티에이전트/그룹스터디 SSE와 파일/함수/라우터를 공유하지 않는다.
자료보관함 요약(core/detailed/keywords)만 담당하며, 기존 /api/ai/summary(non-stream)는
그대로 정상 동작한다(EC2가 streaming을 붙이지 않아도 무방).

  POST /api/ai/material/analyze              동기 구조화 요약 (전체 결과 1회 반환)
  POST /api/ai/material/analyze-job          비동기 작업 생성 -> {job_id, status:"queued"}
  GET  /api/ai/material/analyze-job/{job_id} 진행 상태/부분 결과/최종 결과 폴링
  POST /api/ai/material/analyze-stream        SSE 진행 스트리밍 (progress/partial/done)
"""
import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Path
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai/material", tags=["Material AI (analyze)"])

SUMMARY_TIMEOUT = min(int(os.getenv("AI_SUMMARY_TIMEOUT_SECONDS", "90")),
                      int(os.getenv("AI_GLOBAL_TIMEOUT_SECONDS", "120")) - 5)
JOB_TTL_SECONDS = int(os.getenv("AI_JOB_TTL_SECONDS", "1800"))

# 인메모리 작업 저장소 (단일 프로세스 uvicorn 기준). 운영 다중 워커면 Redis로 교체 가능.
_JOBS: Dict[str, Dict[str, Any]] = {}


# ── 공통 헬퍼 ────────────────────────────────────────────────────────────────

async def _prepare_context(material_id: Optional[int], text: Optional[str]) -> tuple[str, Dict[str, Any]]:
    """추출 텍스트 검증 + chunk 기반 bounded context 생성. (context, text_status)"""
    from app.services.material_ai_manager import validate_extracted_text, build_summary_context
    from app.services.chunk_cache import get_or_build_chunks

    ts = validate_extracted_text(text)
    text_status = {
        "hasText": ts["ok"] and ts["status"] != "empty",
        "textLength": ts["textLength"],
        "status": ts["status"],
    }
    if not ts["ok"]:
        return "", {**text_status, "ok": False}
    cache = await get_or_build_chunks(material_id, text)
    context = build_summary_context(cache["chunks"]) or (text or "")[:6000]
    text_status["chunkCount"] = len(cache["chunks"])
    text_status["ok"] = True
    return context, text_status


def _run_builder(document_title: str, context: str, progress_cb=None) -> Dict[str, Any]:
    from app.services.material_summary_builder import build_structured_summary
    return build_structured_summary(document_title, context, progress_cb=progress_cb)


def _purge_expired_jobs() -> None:
    now = time.time()
    for jid in [k for k, v in _JOBS.items() if now - v.get("createdAt", now) > JOB_TTL_SECONDS]:
        _JOBS.pop(jid, None)


# ── POST /api/ai/material/analyze (동기) ──────────────────────────────────────

@router.post("/analyze", summary="자료 구조화 요약 (동기, core 10+/detail 40+)")
async def analyze(body: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    text = body.get("text") or body.get("pdf_text")
    title = body.get("document_title") or body.get("title") or "자료"
    material_id = body.get("material_id") or body.get("materialId")

    context, ts = await _prepare_context(material_id, text)
    if not ts.get("ok"):
        return {"error_code": "PDF_TEXT_EMPTY",
                "message": "PDF에서 추출된 텍스트가 없습니다. 텍스트 추출을 다시 시도해주세요.",
                "textStatus": ts}
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_run_builder, title, context), timeout=SUMMARY_TIMEOUT)
    except asyncio.TimeoutError:
        return {"error_code": "AI_TIMEOUT", "message": "AI 응답 시간이 초과되었습니다.", "textStatus": ts}
    except Exception as e:
        logger.error("analyze 실패: %s", e)
        return {"error_code": "AI_GENERATION_FAILED", "message": "요약 생성에 실패했습니다.", "textStatus": ts}
    result["textStatus"] = ts
    return result


# ── 비동기 job ────────────────────────────────────────────────────────────────

async def _job_worker(job_id: str, document_title: str, context: str) -> None:
    job = _JOBS.get(job_id)
    if job is None:
        return
    loop = asyncio.get_event_loop()

    def progress_cb(stage: str, pct: int) -> None:
        j = _JOBS.get(job_id)
        if j is not None:
            j["stage"] = stage
            j["progress"] = pct

    job["status"] = "running"
    job["stage"] = "summarizing"
    job["progress"] = 10
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_run_builder, document_title, context, progress_cb),
            timeout=SUMMARY_TIMEOUT)
        job["result"] = result
        job["partial"] = {"overview": result.get("overview", ""),
                          "keywords": result.get("keywords", [])}
        job["status"] = "done"
        job["stage"] = "done"
        job["progress"] = 100
    except asyncio.TimeoutError:
        job["status"] = "failed"
        job["error_code"] = "AI_TIMEOUT"
    except Exception as e:
        logger.error("analyze-job 실패 job_id=%s: %s", job_id, e)
        job["status"] = "failed"
        job["error_code"] = "AI_GENERATION_FAILED"


@router.post("/analyze-job", summary="자료 구조화 요약 비동기 작업 생성")
async def analyze_job(body: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    _purge_expired_jobs()
    text = body.get("text") or body.get("pdf_text")
    title = body.get("document_title") or body.get("title") or "자료"
    material_id = body.get("material_id") or body.get("materialId")

    context, ts = await _prepare_context(material_id, text)
    job_id = uuid.uuid4().hex
    if not ts.get("ok"):
        _JOBS[job_id] = {
            "job_id": job_id, "status": "failed", "progress": 0, "stage": "extracting",
            "error_code": "PDF_TEXT_EMPTY", "textStatus": ts, "createdAt": time.time(),
            "partial": {}, "result": None,
        }
        return {"job_id": job_id, "status": "failed", "error_code": "PDF_TEXT_EMPTY"}

    _JOBS[job_id] = {
        "job_id": job_id, "status": "queued", "progress": 0, "stage": "extracting",
        "error_code": None, "textStatus": ts, "createdAt": time.time(),
        "partial": {}, "result": None,
    }
    asyncio.create_task(_job_worker(job_id, title, context))
    return {"job_id": job_id, "status": "queued"}


@router.get("/analyze-job/{job_id}", summary="자료 구조화 요약 작업 상태 조회")
async def analyze_job_status(job_id: str = Path(...)) -> Dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없거나 만료되었습니다.")
    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": job.get("progress", 0),
        "stage": job.get("stage", "extracting"),
        "partial": job.get("partial", {}),
        "result": job.get("result"),
        "error_code": job.get("error_code"),
        "textStatus": job.get("textStatus"),
    }


# ── SSE 스트리밍 ──────────────────────────────────────────────────────────────

def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/analyze-stream", summary="자료 구조화 요약 SSE 스트리밍")
async def analyze_stream(body: Dict[str, Any] = Body(default_factory=dict)) -> StreamingResponse:
    text = body.get("text") or body.get("pdf_text")
    title = body.get("document_title") or body.get("title") or "자료"
    material_id = body.get("material_id") or body.get("materialId")

    async def event_gen():
        yield _sse("progress", {"stage": "extracting", "progress": 5})
        context, ts = await _prepare_context(material_id, text)
        if not ts.get("ok"):
            yield _sse("error", {"error_code": "PDF_TEXT_EMPTY",
                                 "message": "PDF에서 추출된 텍스트가 없습니다.", "textStatus": ts})
            return

        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def progress_cb(stage: str, pct: int) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, ("progress", {"stage": stage, "progress": pct}))

        async def _produce():
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(_run_builder, title, context, progress_cb),
                    timeout=SUMMARY_TIMEOUT)
                loop.call_soon_threadsafe(queue.put_nowait, ("partial", {
                    "overview": result.get("overview", ""), "keywords": result.get("keywords", [])}))
                result["textStatus"] = ts
                loop.call_soon_threadsafe(queue.put_nowait, ("done", result))
            except asyncio.TimeoutError:
                loop.call_soon_threadsafe(queue.put_nowait, ("error", {"error_code": "AI_TIMEOUT"}))
            except Exception as e:
                logger.error("analyze-stream 실패: %s", e)
                loop.call_soon_threadsafe(queue.put_nowait, ("error", {"error_code": "AI_GENERATION_FAILED"}))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, ("__end__", None))

        task = asyncio.create_task(_produce())
        try:
            while True:
                event, data = await queue.get()
                if event == "__end__":
                    break
                yield _sse(event, data)
        finally:
            task.cancel()

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
