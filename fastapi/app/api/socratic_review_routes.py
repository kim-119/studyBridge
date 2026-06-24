"""
소크라테스 복습 세션 API (자료 상세용, 문서 기반 coverage 복습).

  POST /api/ai/socratic-review/sessions                      세션 시작 + 첫 질문
  POST /api/ai/socratic-review/sessions/{sessionId}/answers  학생 답변 제출 → 꼬리질문/다음질문
  POST /api/ai/socratic-review/sessions/{sessionId}/finish   세션 완료 → mastery/복습추천
  GET  /api/ai/socratic-review/sessions/{sessionId}          세션 상태 조회

설계:
  - 일반 RAG QA가 아니라 하나의 자료(material_id) 전체 청크를 page/chunk_index 순서로
    빠짐없이 순회하는 coverage 복습이다.
  - 모든 청크/벡터 조회는 반드시 WHERE material_id 고정(전체 코퍼스 검색 금지).
  - 출제 순서는 벡터 검색이 아니라 순회로 정하고, 벡터 검색은 답변 평가 grounding 전용.
  - 학생에게 정답을 직접 말하지 않으며 한 번에 질문 하나만 한다.
  - 내부 평가/요약 JSON, <think> reasoning 은 React 에 노출하지 않는다(debug=null).

기존 채팅방 소크라테스 모드(socratic_mode_service)와 독립된 별도 기능이다.
folderId 등 다른 식별자는 무시한다. Spring 에서 materialId 소유권 검증 후 호출하는 전제.
"""
import logging
from typing import Any, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.services import socratic_review_service as svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai/socratic-review", tags=["Socratic Review Session"])


# ── 요청 스키마 ───────────────────────────────────────────────────────────────
class StartSessionRequest(BaseModel):
    materialId: Optional[int] = Field(None, description="자료 ID (documentId와 둘 중 하나 필수)")
    documentId: Optional[str] = Field(None, description="문서 ID(doc_50 형태 또는 숫자)")
    title: Optional[str] = Field(None, description="세션 제목(표시용)")
    maxTurnsPerChunk: int = Field(2, ge=1, le=5, description="청크당 최대 대화 턴")
    maxChunks: Optional[int] = Field(None, ge=1, description="출제 청크 상한(미지정시 기본 12, 최대 15)")
    difficulty: str = Field("auto", description="auto|easy|medium|hard")


class AnswerRequest(BaseModel):
    answer: str = Field(..., description="학생 답변")


# ── 라우트 ────────────────────────────────────────────────────────────────────
@router.post("/sessions", summary="소크라테스 복습 세션 시작")
def start_session(req: StartSessionRequest) -> Any:
    try:
        return svc.start_session(
            material_id=req.materialId,
            document_id=req.documentId,
            title=req.title,
            max_turns_per_chunk=req.maxTurnsPerChunk,
            max_chunks=req.maxChunks,
            difficulty=req.difficulty,
        )
    except svc.SessionError as e:
        # 문서/청크 부재 등은 전체 코퍼스로 넘어가지 않고 명확한 사유와 함께 실패 반환.
        # status 는 provisioner reason 코드(PDF_TEXT_EMPTY/S3_NOT_FOUND/OCR_REQUIRED/...)를 그대로 전달.
        return JSONResponse(status_code=200, content={
            "status": e.status,
            "reason": e.status,
            "canStart": False,
            "chunkCount": 0,
            "textLength": 0,
            "message": e.message,
        })
    except Exception as e:
        logger.error("socratic-review start 실패: %s", type(e).__name__)
        return JSONResponse(
            status_code=200,
            content={"status": "FAILED", "message": "복습 세션을 시작하지 못했습니다."},
        )


@router.post("/sessions/{session_id}/answers", summary="학생 답변 제출")
def submit_answer(session_id: str, req: AnswerRequest) -> Any:
    try:
        return svc.submit_answer(session_id, req.answer)
    except svc.SessionError as e:
        return JSONResponse(status_code=200, content={"status": e.status, "message": e.message})
    except Exception as e:
        logger.error("socratic-review answer 실패: %s", type(e).__name__)
        return JSONResponse(
            status_code=200,
            content={"status": "FAILED", "message": "답변 처리에 실패했습니다."},
        )


@router.post("/sessions/{session_id}/finish", summary="세션 완료 + 복습일 추천")
def finish_session(session_id: str) -> Any:
    try:
        return svc.finish_session(session_id)
    except svc.SessionError as e:
        return JSONResponse(status_code=200, content={"status": e.status, "message": e.message})
    except Exception as e:
        logger.error("socratic-review finish 실패: %s", type(e).__name__)
        return JSONResponse(
            status_code=200,
            content={"status": "FAILED", "message": "세션 완료 처리에 실패했습니다."},
        )


@router.get("/sessions/{session_id}", summary="세션 상태 조회")
def get_session(session_id: str) -> Any:
    try:
        return svc.get_session_state(session_id)
    except svc.SessionError as e:
        return JSONResponse(status_code=200, content={"status": e.status, "message": e.message})
    except Exception as e:
        logger.error("socratic-review state 실패: %s", type(e).__name__)
        return JSONResponse(
            status_code=200,
            content={"status": "FAILED", "message": "세션 조회에 실패했습니다."},
        )
