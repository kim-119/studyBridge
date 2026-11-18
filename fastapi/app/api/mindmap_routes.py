"""POST /api/ai/mindmap/semantic-graph — Semantic Learning Concept Map (additive).

AI07 owns concept extraction + graph semantics; Spring relays, the frontend renders.
Contract: app.mindmap.graph_builder (schemaVersion "mindmap.semantic.v1").

HTTP / status mapping (the body always carries the full mindmap.semantic.v1 shape, except
FastAPI's own schema-validation 422 which is {"detail": [...]}):
  200  status=OK        LLM (or deterministic when useLlm=false) + kiwi analyzer, graph valid
  200  status=DEGRADED  graph valid, but LLM failed/unusable -> deterministic extractor, and/or
                        kiwipiepy missing -> rule analyzer (degradedReasons lists every cause)
  422  {"detail": ...}  request body violates the schema (types / lengths / answers count)
  422  status=FAILED    EMPTY_ANSWER (every answer blank) | NO_VALID_CONCEPTS (input has none)
  500  status=FAILED    GRAPH_VALIDATION_FAILED (internal invariant broken; never shown as OK)
                        | INTERNAL_ERROR (builder raised)
  504  status=FAILED    TIMEOUT (whole build exceeded MINDMAP_TIMEOUT_SECONDS)
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Optional, Union

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.core.security import verify_internal_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["MindMap"], dependencies=[Depends(verify_internal_token)])

MAX_QUESTION_CHARS = 2000
MAX_ANSWERS = 12
MAX_ANSWER_CHARS = 20000
MINDMAP_TIMEOUT_SECONDS = float(os.getenv("MINDMAP_TIMEOUT_SECONDS", "90"))

_FAILED_HTTP_STATUS = {
    "EMPTY_ANSWER": 422,
    "NO_VALID_CONCEPTS": 422,
    "GRAPH_VALIDATION_FAILED": 500,
    "TIMEOUT": 504,
    "INTERNAL_ERROR": 500,
}


class MindmapAnswer(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    agentId: Optional[Union[int, str]] = Field(None, validation_alias=AliasChoices("agentId", "agent_id"))
    agentName: Optional[str] = Field(None, max_length=100,
                                     validation_alias=AliasChoices("agentName", "agent_name", "senderName"))
    role: Optional[str] = Field(None, max_length=100)
    content: str = Field("", max_length=MAX_ANSWER_CHARS, validation_alias=AliasChoices("content", "answer", "text"))


class MindmapRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    question: str = Field("", max_length=MAX_QUESTION_CHARS)
    answers: List[MindmapAnswer] = Field(..., min_length=1, max_length=MAX_ANSWERS)
    useLlm: bool = Field(True, validation_alias=AliasChoices("useLlm", "use_llm"))


def _failed_response(question: str, reason: str) -> JSONResponse:
    from app.mindmap.graph_builder import failed_graph
    return JSONResponse(status_code=_FAILED_HTTP_STATUS.get(reason, 500), content=failed_graph(question, reason))


@router.post("/mindmap/semantic-graph", summary="답변 → 학습 개념 마인드맵(semantic graph)")
async def semantic_graph(request: MindmapRequest):
    from app.mindmap.graph_builder import build_semantic_graph

    answers = [a.model_dump() for a in request.answers]
    for a in answers:
        if a.get("agentId") is not None:
            a["agentId"] = str(a["agentId"])
    try:
        # The worker thread is not cancelled on timeout; its LLM call has its own 45s cap.
        graph = await asyncio.wait_for(
            asyncio.to_thread(build_semantic_graph, request.question, answers, request.useLlm),
            timeout=MINDMAP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("[mindmap] build timed out after %ss", MINDMAP_TIMEOUT_SECONDS)
        return _failed_response(request.question, "TIMEOUT")
    except Exception as e:  # noqa: BLE001 — never a 200 with a broken graph
        logger.exception("[mindmap] build crashed: %s", type(e).__name__)
        return _failed_response(request.question, "INTERNAL_ERROR")
    if graph.get("status") == "FAILED":
        return JSONResponse(status_code=_FAILED_HTTP_STATUS.get(graph.get("degradedReason"), 500), content=graph)
    return JSONResponse(status_code=200, content=graph)
