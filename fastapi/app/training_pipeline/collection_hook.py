"""응답 경로 → 학습 후보 비동기 수집 훅.

흐름: 생성 → Quality Gate APPROVED → (사용자 표시) → submit() 로 큐에 넣기만 함 → 워커가 동의/권리/근거 확인 후
candidate_service.collect_sample 로 COLLECTED→NEEDS_REVIEW 저장. 학습 자격(TRAIN_ELIGIBLE)은 별도 검증 단계.

- submit() 는 동기·논블로킹이며 예외를 던지지 않는다. 큐 포화/저장 실패/저장소 미구성은 카운터로만 남는다
  → 수집 실패가 AI 응답을 지연시키거나 실패시키지 않는다.
- EC2 가 서명한 동의 claim(X-AI-Training-Consent)이 없으면 내용을 저장하지 않는다(SKIPPED_NO_CONSENT).
- PDF 계열은 원문(PDF_ORIGINAL) 근거 + EC2 권리 확인이 있어야 후보가 된다.
- 기본 OFF: AI_TRAINING_COLLECTION_ENABLED=false.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.contracts.response_quality_v1 import QualityOutput, TaskType, is_displayable
from app.contracts.signing import ConsentClaim
from app.contracts.training_sample_v1 import (RIGHTS_OK, SCHEMA_VERSION, RightsStatus, TrainingSampleV1,
                                              compute_content_hash)

logger = logging.getLogger(__name__)

_PDF_TASKS = {TaskType.PDF_SUMMARY, TaskType.PDF_QA, TaskType.PDF_QUIZ}
_SOURCE_KIND = {
    TaskType.PDF_SUMMARY: "PDF_SUMMARY", TaskType.PDF_QA: "PDF_QA", TaskType.PDF_QUIZ: "PDF_QUIZ",
    TaskType.MATH_SOLUTION: "MATH", TaskType.WRONG_NOTE_EXPLANATION: "WRONG_NOTE", TaskType.SIMILAR_QUESTION: "WRONG_NOTE",
    TaskType.GENERAL_EXPLANATION: "GENERAL_QA", TaskType.STUDYMATE_BASIC: "GENERAL_QA",
}


def collection_enabled() -> bool:
    return (os.getenv("AI_TRAINING_COLLECTION_ENABLED") or "false").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class ResponseCollectionEvent:
    request_id: str
    task_type: TaskType
    question: str
    output: Any
    evidence: List[Dict[str, Any]]
    quality: Optional[QualityOutput]
    consent: Optional[ConsentClaim]
    model_name: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "qwen3:14b"))
    model_digest: Optional[str] = None
    prompt_template_version: Optional[str] = None
    source_revision_hash: Optional[str] = None


class _Stats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counts: Dict[str, int] = {}

    def inc(self, key: str) -> None:
        with self._lock:
            self.counts[key] = self.counts.get(key, 0) + 1

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return dict(self.counts)

    def reset(self) -> None:
        with self._lock:
            self.counts.clear()


STATS = _Stats()
# 큐/워커는 '현재 이벤트 루프'에 묶인다. 루프가 바뀌면(테스트/재기동) 새로 만든다(id 재사용으로 죽은 워커에 쌓이지 않게).
_state: Dict[str, Any] = {"loop": None, "queue": None, "worker": None}


def _queue(loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
    if _state["loop"] is not loop or _state["queue"] is None:
        _state.update(loop=loop, queue=asyncio.Queue(maxsize=int(os.getenv("AI_TRAINING_COLLECTION_QUEUE_MAX", "256"))),
                      worker=None)
    w = _state["worker"]
    if w is None or w.done():
        _state["worker"] = loop.create_task(_worker(_state["queue"]))
    return _state["queue"]


def _pdf_evidence_ok(ev: List[Dict[str, Any]]) -> bool:
    prim = [e for e in ev if str(e.get("sourceType")).upper() == "PDF_ORIGINAL"]
    return bool(prim) and all(e.get("text") and e.get("page") and e.get("chunkId") and e.get("materialId") for e in prim)


def _rights_for(event: ResponseCollectionEvent) -> Optional[str]:
    if event.task_type not in _PDF_TASKS:
        return RightsStatus.NO_THIRD_PARTY_CONTENT.value if not event.evidence else None
    statuses = set()
    for e in event.evidence:
        if str(e.get("sourceType")).upper() != "PDF_ORIGINAL":
            continue
        s = (event.consent.rights if event.consent else {}).get(str(e.get("materialId")))
        statuses.add(s)
    if len(statuses) == 1:
        s = next(iter(statuses))
        try:
            return s if RightsStatus(s) in RIGHTS_OK else None
        except ValueError:
            return None
    return None


def submit(event: ResponseCollectionEvent) -> str:
    """논블로킹 수집 요청. 반환값은 처리 구분 코드(로그/메트릭용). 예외를 던지지 않는다."""
    try:
        if not collection_enabled():
            code = "SKIPPED_DISABLED"
        elif not is_displayable(event.quality):
            code = "SKIPPED_NOT_APPROVED"
        elif event.consent is None:
            code = "SKIPPED_NO_CONSENT"
        elif "MODEL_TRAINING" not in event.consent.scope:
            code = "SKIPPED_CONSENT_SCOPE"
        elif event.task_type in _PDF_TASKS and not _pdf_evidence_ok(event.evidence):
            code = "SKIPPED_UNGROUNDED_PDF"
        elif _rights_for(event) is None:
            code = "SKIPPED_RIGHTS_UNVERIFIED"
        else:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                code = "SKIPPED_NO_LOOP"
            else:
                try:
                    _queue(loop).put_nowait(event)
                    code = "ENQUEUED"
                except asyncio.QueueFull:
                    code = "DROPPED_QUEUE_FULL"
    except Exception as e:  # noqa: BLE001
        logger.warning("[collect] submit error: %s", type(e).__name__)
        code = "FAILED_SUBMIT"
    STATS.inc(code)
    return code


def _to_sample(ev: ResponseCollectionEvent) -> TrainingSampleV1:
    import json
    answer = ev.output if isinstance(ev.output, str) else json.dumps(ev.output, ensure_ascii=False, sort_keys=True)
    c = ev.consent
    ch = compute_content_hash(ev.question, answer)
    return TrainingSampleV1(
        schemaVersion=SCHEMA_VERSION,
        eventId=f"resp-{ev.request_id[:80]}-{ch[:12]}",
        pseudonymousUserKey=c.sub, consentVersion=c.consent_version,
        consentTimestamp=datetime.fromisoformat(c.consent_timestamp.replace("Z", "+00:00")),
        sourceKind=_SOURCE_KIND.get(ev.task_type, "FREE_RESPONSE"),
        sourceRevisionHash=ev.source_revision_hash or next((e.get("sourceRevisionHash") for e in ev.evidence
                                                            if e.get("sourceRevisionHash")), None),
        rightsStatus=_rights_for(ev),
        question=ev.question, candidateAnswer=answer,
        evidence=[{"sourceType": str(e.get("sourceType")), "materialId": e.get("materialId"),
                   "documentId": e.get("documentId"), "sourceRevisionHash": e.get("sourceRevisionHash"),
                   "page": e.get("page"), "chunkId": e.get("chunkId"), "quote": (e.get("text") or "")[:4000] or None}
                  for e in ev.evidence],
        qualityEvaluatorVersion=ev.quality.evaluatorVersion if ev.quality else None,
        modelName=ev.model_name, modelDigest=ev.model_digest, promptTemplateVersion=ev.prompt_template_version,
        contentHash=ch, createdAt=datetime.now(timezone.utc), deletionTrackingId=c.deletion_tracking_id,
        retentionPolicy=os.getenv("AI_TRAINING_RETENTION_POLICY", "TRAINING_CANDIDATE_365D"),
        trainingEligibility={"consentGranted": True, "consentScope": sorted(c.scope), "consentWithdrawn": False,
                             "decidedAt": datetime.fromisoformat(c.consent_timestamp.replace("Z", "+00:00"))},
    )


async def _persist(ev: ResponseCollectionEvent) -> str:
    from app.training_pipeline.candidate_service import collect_sample
    from app.training_pipeline.repository import RepositoryUnavailable, get_repository
    try:
        repo = get_repository()
    except RepositoryUnavailable:
        return "FAILED_REPOSITORY_UNAVAILABLE"
    sample = _to_sample(ev)
    res = await collect_sample(repo, sample, task_type=ev.task_type.value,
                               display_quality={"score": ev.quality.score, "qualityStatus": ev.quality.qualityStatus.value})
    return f"RESULT_{res.status}"


async def _worker(q: asyncio.Queue) -> None:
    while True:
        ev = await q.get()
        try:
            STATS.inc(await _persist(ev))
        except Exception as e:  # noqa: BLE001 — 워커는 죽지 않는다
            STATS.inc("FAILED_PERSIST")
            logger.warning("[collect] persist failed requestId=%s type=%s", ev.request_id, type(e).__name__)
        finally:
            q.task_done()


async def drain() -> None:
    """테스트/종료용: 현재 루프의 큐가 비워질 때까지 대기."""
    if _state["loop"] is asyncio.get_running_loop() and _state["queue"] is not None:
        await _state["queue"].join()


def content_fingerprint(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]
