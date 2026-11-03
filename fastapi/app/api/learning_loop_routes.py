"""
StudyBridge 학습 왕복 루프(Learning Loop) 통합 endpoint.

  POST /api/ai/learning-loop   taskType 기반 단일 진입점

Spring 이 materialId/documentId 소유권을 검증한 뒤, taskType 과 learningLoopContext 를
실어 호출한다. FastAPI 는 RAG 본문 근거 + 학습 이력을 결합해 구조화 JSON 을 생성·검증해
반환하고, DB 저장은 Spring 이 담당한다.

기존 /api/ai/multi-chat/stream, /ai/chat, /ai/summary, /ai/roadmap, /ai/quiz,
/ai/question, /api/rag/query 및 review-note/* 계열과는 별개의 신규 additive 경로다.
어떤 taskType/필드가 비어 있어도 요청이 실패하지 않도록 모든 컨텍스트 필드는 optional 이다.
"""
import asyncio
import logging
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.security import verify_internal_token

logger = logging.getLogger(__name__)
# 내부 인증 필수(fail-closed). Spring 호출자는 아직 없다(2026-11-04 backend 코드 grep 기준) → 회귀 없음.
router = APIRouter(tags=["Learning Loop"], dependencies=[Depends(verify_internal_token)])

LEARNING_LOOP_TIMEOUT = int(os.getenv("AI_LEARNING_LOOP_TIMEOUT_SECONDS", "120"))


class LearningLoopContext(BaseModel):
    """학습 이력 컨텍스트. 모든 필드 optional — 없으면 기존 방식대로 동작한다."""
    summaries: List[Any] = Field(default_factory=list)
    wrongNotes: List[Any] = Field(default_factory=list)
    quizResults: List[Any] = Field(default_factory=list)
    plannerReviews: List[Any] = Field(default_factory=list)
    userMemos: List[Any] = Field(default_factory=list)
    recentChatHistory: List[Any] = Field(default_factory=list)
    agentFeedback: List[Any] = Field(default_factory=list)


class LearningLoopRequest(BaseModel):
    taskType: str = ""
    userQuestion: Optional[str] = ""
    materialId: Optional[Any] = None
    documentId: Optional[Any] = None
    sourceText: Optional[str] = ""
    title: Optional[str] = ""
    # 생성 옵션
    count: Optional[int] = None
    difficulty: Optional[str] = ""
    # 에이전트 모드(AGENT_CHAT_WITH_FEEDBACK)
    mode: Optional[str] = ""
    personality: Optional[str] = ""
    knowledgeLevel: Optional[str] = ""
    learningLoopContext: Optional[LearningLoopContext] = None

    model_config = {"extra": "ignore"}


@router.post("/api/ai/learning-loop", summary="학습 왕복 루프 통합 처리 (taskType 디스패치)")
async def learning_loop(req: LearningLoopRequest,
                        x_ai_scope: Optional[str] = Header(default=None, alias="X-AI-Scope"),
                        x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id"),
                        x_consent: Optional[str] = Header(default=None, alias="X-AI-Training-Consent")):
    from app.services.learning_loop_service import RAG_SCOPE, run_learning_loop

    started = time.time()
    request_id = x_request_id if (x_request_id and _RID_RE.match(x_request_id)) else f"ll-{uuid.uuid4().hex}"
    scope, scope_warning = _verify_scope(x_ai_scope, request_id, req)
    token = RAG_SCOPE.set(scope)
    try:
        if _gate_enabled():
            return await _run_gated(req, request_id, x_consent, scope, scope_warning, started)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(run_learning_loop, req), timeout=LEARNING_LOOP_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("[learning-loop] timeout taskType=%s", req.taskType)
            from app.services.learning_loop_service import _new_used  # type: ignore
            # 예전: success:true + 빈 answer → 사용자 노출 계약에서 '정상'으로 오인될 수 있었다.
            return JSONResponse(status_code=200, content={
                "success": False,
                "taskType": (req.taskType or "").strip().upper() or "UNKNOWN",
                "errorCode": "LEARNING_LOOP_TIMEOUT",
                "qualityStatus": "VALIDATION_ERROR",
                "usedContext": _new_used(),
                "warnings": ["LLM 응답 지연으로 결과를 생성하지 못했습니다."],
            })
        except Exception as e:  # noqa: BLE001
            logger.error("[learning-loop] 실패 taskType=%s: %s", req.taskType, type(e).__name__)
            return JSONResponse(status_code=200, content={
                "success": False,
                "taskType": (req.taskType or "").strip().upper() or "UNKNOWN",
                "errorCode": "LEARNING_LOOP_FAILED",
                "warnings": [f"처리 중 오류가 발생했습니다: {type(e).__name__}"],
            })
    finally:
        RAG_SCOPE.reset(token)

    result.pop("_evidence", None)
    if scope_warning:
        result.setdefault("warnings", []).append(scope_warning)
    # 게이트 off: 생성물은 '미검증'임을 명시한다(EC2 는 APPROVED 만 노출 가능 계약).
    result["qualityStatus"] = "NOT_EVALUATED"
    result["fallbackUsed"] = _fallback_used(result)
    elapsed = int((time.time() - started) * 1000)
    logger.info("[learning-loop] taskType=%s success=%s elapsedMs=%d warnings=%d",
                result.get("taskType"), result.get("success"), elapsed, len(result.get("warnings") or []))
    status = 200 if result.get("success") else 422
    return JSONResponse(status_code=status, content=result)


_RID_RE = re.compile(r"^[A-Za-z0-9._:\-]{8,128}$")


def _gate_enabled() -> bool:
    return (os.getenv("AI_RESPONSE_QUALITY_GATE_ENABLED") or "false").strip().lower() in ("1", "true", "yes", "on")


def _fallback_used(result: Dict[str, Any]) -> bool:
    return any("fallback" in str(w).lower() for w in (result.get("warnings") or []))


def _verify_scope(token: Optional[str], request_id: str, req: "LearningLoopRequest") -> Tuple[Optional[frozenset], Optional[str]]:
    """서명된 scope 토큰 → 허용 materialId 집합. 실패/누락 → None(pgvector 검색 안 함) + 경고 코드."""
    if req.materialId is None:
        return None, None
    from app.contracts.signing import SignatureError, verify_scope_token
    try:
        sc = verify_scope_token(token)
    except SignatureError as e:
        return None, f"SCOPE_UNVERIFIED:{e.code}"
    if sc.request_id and sc.request_id != request_id:
        return None, "SCOPE_UNVERIFIED:SCOPE_REQUEST_MISMATCH"
    try:
        mid = int(req.materialId)
    except (TypeError, ValueError):
        return None, "SCOPE_UNVERIFIED:MATERIAL_ID_INVALID"
    if not sc.allows_material(mid):
        return None, "SCOPE_MISMATCH"
    return sc.material_ids, None


# taskType → (품질 프로파일, 출력 종류, 평가 대상 추출기). 매핑 없는 taskType 은 게이트 on 일 때 노출 불가.
def _text(*keys):
    def f(r):
        return "\n".join(str(r.get(k) or "") for k in keys if r.get(k)).strip()
    return f


def _summary(r):
    return ((r.get("summary") or "") + "\n" + "\n".join(str(x) for x in r.get("keyPoints") or [])).strip()


def _quiz(r):
    return {"questions": [{"question": it.get("question"), "options": it.get("choices"),
                           "answerIndex": it.get("answerIndex"), "explanation": it.get("explanation")}
                          for it in r.get("items") or []]}


_GATE_MAP = {
    "AI_CHAT_WITH_LEARNING_LOOP": ("CHAT", "text", _text("answer")),
    "AGENT_CHAT_WITH_FEEDBACK": ("STUDYMATE_BASIC", "agent_message", _text("answer")),
    "SUMMARY_WITH_LEARNING_LOOP": ("PDF_SUMMARY", "text", _summary),
    "QUIZ_WITH_LEARNING_LOOP": ("PDF_QUIZ", "quiz_json", _quiz),
    "WRONG_NOTE_EXPLANATION": ("WRONG_NOTE_EXPLANATION", "text", _text("answer", "whyWrong", "correctConcept")),
    "SIMILAR_QUESTION_FROM_WRONG_NOTE": ("SIMILAR_QUESTION", "quiz_json", _quiz),
}


async def _run_gated(req: "LearningLoopRequest", request_id: str, consent_token: Optional[str],
                     scope: Optional[frozenset], scope_warning: Optional[str], started: float) -> JSONResponse:
    from app.contracts.response_quality_v1 import (SCHEMA_VERSION, GroundingEvidence, OutputKind, QualityConstraints,
                                                   QualityInput, TaskType)
    from app.quality_gate.judge import get_judge
    from app.quality_gate.regeneration import render_regeneration_block, run_quality_gated_generation
    from app.services.learning_loop_service import QUALITY_FEEDBACK, run_learning_loop

    task = (req.taskType or "").strip().upper()
    mapping = _GATE_MAP.get(task)
    if mapping is None:
        return JSONResponse(status_code=200, content={
            "success": False, "taskType": task or "UNKNOWN", "errorCode": "QUALITY_PROFILE_UNMAPPED",
            "qualityStatus": "REJECTED", "warnings": ["품질 게이트 프로파일이 없는 작업은 노출할 수 없습니다."]})
    profile_name, kind, extract = mapping
    holder: Dict[str, Any] = {}

    def _evidence() -> List[GroundingEvidence]:
        ev = []
        for c in holder.get("evidence") or []:
            ev.append(GroundingEvidence(sourceType="PDF_ORIGINAL", materialId=c.get("material_id"),
                                        chunkId=f"m{c.get('material_id')}-c{c.get('chunk_index')}",
                                        page=c.get("page"), text=(c.get("content") or "")[:8000]))
        if (req.sourceText or "").strip():
            ev.append(GroundingEvidence(sourceType="USER_PROVIDED_TEXT", evidenceId="sourceText",
                                        text=req.sourceText.strip()[:8000]))
        return ev

    async def generate(regen):
        remaining = max(5.0, LEARNING_LOOP_TIMEOUT - (time.time() - started))
        tok = QUALITY_FEEDBACK.set(render_regeneration_block(regen))
        try:
            res = await asyncio.wait_for(asyncio.to_thread(run_learning_loop, req), timeout=remaining)
        finally:
            QUALITY_FEEDBACK.reset(tok)
        if not res.get("success"):
            raise RuntimeError(str(res.get("errorCode")))
        holder["evidence"] = res.pop("_evidence", [])
        holder["result"] = res
        return extract(res)

    def build_input(output, attempt):
        ev = _evidence()
        if profile_name == "CHAT":
            task_type = TaskType.PDF_QA if ev else TaskType.GENERAL_EXPLANATION
        else:
            task_type = TaskType(profile_name)
        cons = QualityConstraints(
            allowedMaterialIds=sorted(scope) if scope else None,
            expectedQuestionCount=(req.count if task_type in (TaskType.PDF_QUIZ, TaskType.SIMILAR_QUESTION) and req.count else None))
        return QualityInput(schemaVersion=SCHEMA_VERSION, requestId=request_id, taskType=task_type,
                            outputKind=OutputKind(kind), modelDigest=os.getenv("AI_PRODUCTION_MODEL_DIGEST"),
                            originalRequest=(req.userQuestion or req.title or task)[:8000], proposedOutput=output,
                            groundingEvidence=ev, constraints=cons, attemptIndex=attempt)

    outcome = await run_quality_gated_generation(generate=generate, build_input=build_input, judge=get_judge(),
                                                 budget_seconds=LEARNING_LOOP_TIMEOUT * 0.8)
    q = outcome.final_evaluation
    quality = {"qualityStatus": outcome.status.value, "score": q.score if q else None,
               "hardFail": q.hardFail if q else None, "attempts": outcome.attempts,
               "evaluatorVersion": q.evaluatorVersion if q else None,
               "codes": sorted({v.code for v in q.violations})[:12] if q else []}
    logger.info("[learning-loop] gated taskType=%s status=%s score=%s attempts=%d elapsedMs=%d", task,
                outcome.status.value, quality["score"], outcome.attempts, int((time.time() - started) * 1000))
    if not outcome.approved:
        # 미승인 본문은 절대 내보내지 않는다(검증 없는 답 표시 금지).
        return JSONResponse(status_code=200, content={
            "success": False, "taskType": task,
            "errorCode": "QUALITY_VALIDATION_ERROR" if outcome.status.value == "VALIDATION_ERROR" else "QUALITY_GATE_REJECTED",
            "qualityStatus": outcome.status.value, "quality": quality,
            "usedContext": (holder.get("result") or {}).get("usedContext"),
            "warnings": ["품질 기준을 통과한 답변을 만들지 못했습니다."] + ([scope_warning] if scope_warning else [])})
    result = holder["result"]
    result["qualityStatus"] = "APPROVED"
    result["quality"] = quality
    result["fallbackUsed"] = _fallback_used(result)
    if scope_warning:
        result.setdefault("warnings", []).append(scope_warning)
    _submit_for_training(req, request_id, consent_token, q, outcome.output, _evidence())
    return JSONResponse(status_code=200, content=result)


def _submit_for_training(req, request_id, consent_token, quality, output, evidence) -> None:
    """승인된 응답을 학습 후보 큐에 넣는다(논블로킹, 어떤 실패도 응답에 영향 없음)."""
    try:
        from app.contracts.signing import SignatureError, verify_consent_token
        from app.training_pipeline.collection_hook import ResponseCollectionEvent, submit
        try:
            consent = verify_consent_token(consent_token, expected_request_id=request_id) if consent_token else None
        except SignatureError:
            consent = None
        submit(ResponseCollectionEvent(request_id=request_id, task_type=quality.taskType,
                                       question=(req.userQuestion or req.title or "")[:4000], output=output,
                                       evidence=[e.model_dump(mode="json") for e in evidence],
                                       quality=quality, consent=consent,
                                       model_digest=os.getenv("AI_PRODUCTION_MODEL_DIGEST")))
    except Exception as e:  # noqa: BLE001
        logger.warning("[learning-loop] training submit skipped: %s", type(e).__name__)
