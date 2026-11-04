"""학습 후보 저장소. InMemory(테스트/격리) + Postgres(psycopg async, 신규 v2 테이블).

운영 RDS 의 기존 ai.training_candidate 는 코드와 스키마가 다르고(candidate_id/user_query/ai_response…) 0행이며,
운영 venv 에 asyncpg 가 없어 레거시 경로는 한 번도 저장에 성공할 수 없었다. v2 는 기존 테이블을 건드리지 않고
별도 테이블(migrations/001_training_pipeline_v2.sql)을 쓴다. 마이그레이션 적용은 EC2/DB 승인 후.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
from dataclasses import asdict, fields
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from app.training_pipeline.records import (CandidateEvent, CandidateRecord, ManifestRecord,
                                           ModelCandidateRecord, utcnow)
from app.training_pipeline.states import CandidateState


class RepositoryUnavailable(Exception):
    pass


class ConcurrentModification(Exception):
    pass


class InMemoryTrainingRepository:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_id: Dict[str, CandidateRecord] = {}
        self._by_hash: Dict[str, str] = {}
        self._by_event: Dict[str, str] = {}
        self._events: List[CandidateEvent] = []
        self._manifests: Dict[str, ManifestRecord] = {}
        self._models: Dict[str, ModelCandidateRecord] = {}
        self.fail_reads = False  # 장애 주입(테스트)

    def _check(self) -> None:
        if self.fail_reads:
            raise RepositoryUnavailable("injected failure")

    async def insert_candidate(self, rec: CandidateRecord) -> bool:
        async with self._lock:
            self._check()
            if rec.content_hash in self._by_hash or rec.event_id in self._by_event:
                return False   # ON CONFLICT DO NOTHING 과 같은 의미(race-safe)
            self._by_id[rec.candidate_id] = copy.deepcopy(rec)
            self._by_hash[rec.content_hash] = rec.candidate_id
            self._by_event[rec.event_id] = rec.candidate_id
            return True

    async def get(self, candidate_id: str) -> Optional[CandidateRecord]:
        self._check()
        r = self._by_id.get(candidate_id)
        return copy.deepcopy(r) if r else None

    async def find_by_content_hash(self, content_hash: str) -> Optional[CandidateRecord]:
        self._check()
        cid = self._by_hash.get(content_hash)
        return await self.get(cid) if cid else None

    async def find_by_event_id(self, event_id: str) -> Optional[CandidateRecord]:
        self._check()
        cid = self._by_event.get(event_id)
        return await self.get(cid) if cid else None

    async def iter_simhashes(self) -> List[Tuple[str, int]]:
        self._check()
        return [(r.candidate_id, r.simhash) for r in self._by_id.values()
                if r.state != CandidateState.DELETED]

    async def update(self, rec: CandidateRecord, expected_version: int) -> CandidateRecord:
        async with self._lock:
            self._check()
            cur = self._by_id.get(rec.candidate_id)
            if cur is None or cur.version != expected_version:
                raise ConcurrentModification(rec.candidate_id)
            new = copy.deepcopy(rec)
            new.version = expected_version + 1
            new.updated_at = utcnow()
            self._by_id[rec.candidate_id] = new
            return copy.deepcopy(new)

    async def append_event(self, ev: CandidateEvent) -> None:
        async with self._lock:
            self._events.append(ev)

    async def last_event_hash(self) -> str:
        return self._events[-1].event_hash if self._events else "GENESIS"

    async def events_for(self, candidate_id: str) -> List[CandidateEvent]:
        return [e for e in self._events if e.candidate_id == candidate_id]

    async def list_by(self, *, states: Optional[Iterable[CandidateState]] = None,
                      pseudonymous_user_key: Optional[str] = None,
                      deletion_tracking_id: Optional[str] = None, limit: int = 100000) -> List[CandidateRecord]:
        self._check()
        st = set(states) if states else None
        out = []
        for r in self._by_id.values():
            if st is not None and r.state not in st:
                continue
            if pseudonymous_user_key and r.pseudonymous_user_key != pseudonymous_user_key:
                continue
            if deletion_tracking_id and r.deletion_tracking_id != deletion_tracking_id:
                continue
            out.append(copy.deepcopy(r))
            if len(out) >= limit:
                break
        return out

    async def counts_by_state(self) -> Dict[str, int]:
        self._check()
        out: Dict[str, int] = {s.value: 0 for s in CandidateState}
        for r in self._by_id.values():
            out[r.state.value] += 1
        return out

    async def save_manifest(self, m: ManifestRecord) -> None:
        async with self._lock:
            if m.dataset_id in self._manifests:
                raise ConcurrentModification(m.dataset_id)
            self._manifests[m.dataset_id] = copy.deepcopy(m)

    async def manifests_containing(self, content_hash: str) -> List[ManifestRecord]:
        return [copy.deepcopy(m) for m in self._manifests.values() if content_hash in m.member_hashes]

    async def invalidate_manifest(self, dataset_id: str, reason: str) -> None:
        async with self._lock:
            m = self._manifests[dataset_id]
            m.status = "INVALIDATED"
            if reason not in m.invalidated_reasons:
                m.invalidated_reasons.append(reason)

    async def get_manifest(self, dataset_id: str) -> Optional[ManifestRecord]:
        m = self._manifests.get(dataset_id)
        return copy.deepcopy(m) if m else None

    async def activate_manifest(self, dataset_id: str) -> bool:
        """PENDING → ACTIVE (CAS). 그 사이 무효화됐으면 False."""
        async with self._lock:
            m = self._manifests.get(dataset_id)
            if m is None or m.status != "PENDING":
                return False
            m.status = "ACTIVE"
            return True

    async def register_model_candidate(self, m: ModelCandidateRecord) -> None:
        async with self._lock:
            self._models[m.adapter_id] = copy.deepcopy(m)

    async def models_for_dataset(self, dataset_id: str) -> List[ModelCandidateRecord]:
        return [copy.deepcopy(m) for m in self._models.values() if m.dataset_id == dataset_id]

    async def set_model_status(self, adapter_id: str, status: str, note: str) -> None:
        async with self._lock:
            m = self._models[adapter_id]
            m.status = status
            m.notes.append(note)


# ── Postgres(psycopg3 async) ────────────────────────────────────────────────────
_DT_FIELDS = {"created_at", "updated_at", "consent_timestamp"}


def _rec_to_json(rec: CandidateRecord) -> str:
    d = asdict(rec)
    d["state"] = rec.state.value
    for k in _DT_FIELDS:
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return json.dumps(d, ensure_ascii=False)


def _rec_from_json(raw) -> CandidateRecord:
    d = raw if isinstance(raw, dict) else json.loads(raw)
    d = {k: v for k, v in d.items() if k in {f.name for f in fields(CandidateRecord)}}
    d["state"] = CandidateState(d["state"])
    for k in _DT_FIELDS:
        if d.get(k):
            d[k] = datetime.fromisoformat(d[k])
    return CandidateRecord(**d)


class PostgresTrainingRepository:
    """ai.training_sample_v2 / _event / _dataset_manifest / _dataset_member / _model_candidate."""

    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise RepositoryUnavailable("dsn missing")
        self._dsn = dsn

    async def _conn(self):
        try:
            import psycopg
            return await psycopg.AsyncConnection.connect(self._dsn, connect_timeout=5, autocommit=True)
        except Exception as e:  # noqa: BLE001
            raise RepositoryUnavailable(type(e).__name__) from e

    async def _fetch(self, sql: str, args: tuple = ()) -> list:
        import psycopg
        conn = await self._conn()
        try:
            async with conn.cursor() as cur:
                await cur.execute(sql, args)
                return await cur.fetchall() if cur.description else []
        except psycopg.Error as e:
            # 예전: 접속 오류만 감싸 마이그레이션 누락/스키마 오류가 500 으로 새어 나갔다. SQL/값은 메시지에 싣지 않는다.
            raise RepositoryUnavailable(f"DB_ERROR:{type(e).__name__}") from e
        finally:
            await conn.close()

    async def insert_candidate(self, rec: CandidateRecord) -> bool:
        rows = await self._fetch(
            """INSERT INTO ai.training_sample_v2
                 (candidate_id, event_id, content_hash, state, simhash, pseudonymous_user_key,
                  deletion_tracking_id, version, record, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s::jsonb,%s,%s)
               ON CONFLICT DO NOTHING RETURNING candidate_id""",
            (rec.candidate_id, rec.event_id, rec.content_hash, rec.state.value, rec.simhash,
             rec.pseudonymous_user_key, rec.deletion_tracking_id, _rec_to_json(rec), rec.created_at, rec.updated_at))
        return bool(rows)

    async def _one(self, where: str, arg) -> Optional[CandidateRecord]:
        rows = await self._fetch(f"SELECT record, version FROM ai.training_sample_v2 WHERE {where} = %s", (arg,))
        if not rows:
            return None
        rec = _rec_from_json(rows[0][0])
        rec.version = rows[0][1]
        return rec

    async def get(self, candidate_id: str):
        import uuid as _uuid
        try:
            _uuid.UUID(str(candidate_id))
        except (ValueError, TypeError, AttributeError):
            return None                                   # InMemory 와 같은 계약: 없는 후보(예전: DB 오류 500)
        return await self._one("candidate_id", candidate_id)

    async def find_by_content_hash(self, content_hash: str):
        return await self._one("content_hash", content_hash)

    async def find_by_event_id(self, event_id: str):
        return await self._one("event_id", event_id)

    async def iter_simhashes(self):
        rows = await self._fetch("SELECT candidate_id::text, simhash FROM ai.training_sample_v2 WHERE state <> 'DELETED'")
        return [(r[0], r[1]) for r in rows]

    async def update(self, rec: CandidateRecord, expected_version: int) -> CandidateRecord:
        rec = copy.deepcopy(rec)
        rec.updated_at = utcnow()
        rows = await self._fetch(
            """UPDATE ai.training_sample_v2 SET state=%s, record=%s::jsonb, version=version+1, updated_at=%s
               WHERE candidate_id=%s AND version=%s RETURNING version""",
            (rec.state.value, _rec_to_json(rec), rec.updated_at, rec.candidate_id, expected_version))
        if not rows:
            raise ConcurrentModification(rec.candidate_id)
        rec.version = rows[0][0]
        return rec

    async def append_event(self, ev: CandidateEvent) -> None:
        await self._fetch(
            """INSERT INTO ai.training_sample_event (event_id, candidate_id, event_type, from_state, to_state, actor,
                 actor_role, request_id, reason_codes, at, prev_hash, event_hash)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (ev.event_id, ev.candidate_id, ev.event_type, ev.from_state, ev.to_state, ev.actor, ev.actor_role,
             ev.request_id, ev.reason_codes, ev.at, ev.prev_hash, ev.event_hash))

    async def last_event_hash(self) -> str:
        rows = await self._fetch("SELECT event_hash FROM ai.training_sample_event ORDER BY seq DESC LIMIT 1")
        return rows[0][0] if rows else "GENESIS"

    async def events_for(self, candidate_id: str):
        rows = await self._fetch(
            """SELECT event_id::text, candidate_id::text, event_type, from_state, to_state, actor, actor_role,
                      request_id, reason_codes, at, prev_hash, event_hash
               FROM ai.training_sample_event WHERE candidate_id=%s ORDER BY seq""", (candidate_id,))
        return [CandidateEvent(*r) for r in rows]

    async def list_by(self, *, states=None, pseudonymous_user_key=None, deletion_tracking_id=None, limit=100000):
        conds, args = [], []
        if states:
            conds.append("state = ANY(%s)")
            args.append([s.value for s in states])
        if pseudonymous_user_key:
            conds.append("pseudonymous_user_key = %s")
            args.append(pseudonymous_user_key)
        if deletion_tracking_id:
            conds.append("deletion_tracking_id = %s")
            args.append(deletion_tracking_id)
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        rows = await self._fetch(f"SELECT record, version FROM ai.training_sample_v2{where} ORDER BY created_at LIMIT %s",
                                 tuple(args) + (limit,))
        out = []
        for raw, ver in rows:
            rec = _rec_from_json(raw)
            rec.version = ver
            out.append(rec)
        return out

    async def counts_by_state(self):
        rows = await self._fetch("SELECT state, count(*) FROM ai.training_sample_v2 GROUP BY state")
        out = {s.value: 0 for s in CandidateState}
        out.update({r[0]: int(r[1]) for r in rows})
        return out

    async def save_manifest(self, m: ManifestRecord) -> None:
        conn = await self._conn()
        try:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        """INSERT INTO ai.training_dataset_manifest (dataset_id, status, manifest_sha256, created_at,
                             invalidated_reasons) VALUES (%s,%s,%s,%s,%s)""",
                        (m.dataset_id, m.status, m.manifest_sha256, m.created_at, m.invalidated_reasons))
                    await cur.executemany(
                        "INSERT INTO ai.training_dataset_member (dataset_id, content_hash) VALUES (%s,%s)",
                        [(m.dataset_id, h) for h in m.member_hashes])
        finally:
            await conn.close()

    async def manifests_containing(self, content_hash: str):
        rows = await self._fetch(
            """SELECT m.dataset_id, m.status, m.manifest_sha256, m.created_at, m.invalidated_reasons
               FROM ai.training_dataset_manifest m JOIN ai.training_dataset_member d USING (dataset_id)
               WHERE d.content_hash=%s""", (content_hash,))
        return [ManifestRecord(dataset_id=r[0], status=r[1], manifest_sha256=r[2], member_hashes=[content_hash],
                               created_at=r[3], invalidated_reasons=list(r[4] or [])) for r in rows]

    async def invalidate_manifest(self, dataset_id: str, reason: str) -> None:
        await self._fetch(
            """UPDATE ai.training_dataset_manifest SET status='INVALIDATED',
                 invalidated_reasons = array_append(invalidated_reasons, %s)
               WHERE dataset_id=%s AND NOT (%s = ANY(invalidated_reasons))""", (reason, dataset_id, reason))

    async def get_manifest(self, dataset_id: str):
        rows = await self._fetch(
            "SELECT dataset_id, status, manifest_sha256, created_at, invalidated_reasons FROM ai.training_dataset_manifest WHERE dataset_id=%s",
            (dataset_id,))
        if not rows:
            return None
        members = await self._fetch("SELECT content_hash FROM ai.training_dataset_member WHERE dataset_id=%s", (dataset_id,))
        r = rows[0]
        return ManifestRecord(dataset_id=r[0], status=r[1], manifest_sha256=r[2], member_hashes=[x[0] for x in members],
                              created_at=r[3], invalidated_reasons=list(r[4] or []))

    async def activate_manifest(self, dataset_id: str) -> bool:
        rows = await self._fetch("UPDATE ai.training_dataset_manifest SET status='ACTIVE' "
                                 "WHERE dataset_id=%s AND status='PENDING' RETURNING dataset_id", (dataset_id,))
        return bool(rows)

    async def register_model_candidate(self, m: ModelCandidateRecord) -> None:
        await self._fetch(
            """INSERT INTO ai.training_model_candidate (adapter_id, dataset_id, base_model, status, candidate_tag, notes)
               VALUES (%s,%s,%s,%s,%s,%s)""", (m.adapter_id, m.dataset_id, m.base_model, m.status, m.candidate_tag, m.notes))

    async def models_for_dataset(self, dataset_id: str):
        rows = await self._fetch(
            "SELECT adapter_id, dataset_id, base_model, status, candidate_tag, notes FROM ai.training_model_candidate WHERE dataset_id=%s",
            (dataset_id,))
        return [ModelCandidateRecord(adapter_id=r[0], dataset_id=r[1], base_model=r[2], status=r[3],
                                     candidate_tag=r[4], notes=list(r[5] or [])) for r in rows]

    async def set_model_status(self, adapter_id: str, status: str, note: str) -> None:
        await self._fetch("UPDATE ai.training_model_candidate SET status=%s, notes=array_append(notes, %s) WHERE adapter_id=%s",
                          (status, note, adapter_id))


_repo = None


def resolve_training_dsn() -> str:
    """학습 저장소 DSN 은 '명시적으로'만 정한다(stage/production 분리).
    - AI_TRAINING_DATABASE_URL 필수: 예전처럼 AI_DATABASE_URL(운영 AI DB)로 조용히 대체하지 않는다.
    - AI_TRAINING_ENV 필수(stage|production). stage 인데 DSN 이 운영 AI_DATABASE_URL 과 같으면 거부."""
    dsn = (os.getenv("AI_TRAINING_DATABASE_URL") or "").strip()
    env = (os.getenv("AI_TRAINING_ENV") or "").strip().lower()
    if not dsn:
        raise RepositoryUnavailable("AI_TRAINING_DATABASE_URL not configured")
    if env not in ("stage", "production"):
        raise RepositoryUnavailable("AI_TRAINING_ENV must be stage or production")
    prod = (os.getenv("AI_DATABASE_URL") or "").strip()
    if env == "stage" and prod and dsn == prod:
        raise RepositoryUnavailable("stage training repository must not use the production AI database")
    return dsn


def get_repository():
    """AI_TRAINING_REPOSITORY=postgres 이고 DSN/환경이 명시됐을 때만 Postgres. 그 외엔 사용 불가(fail-closed)."""
    global _repo
    if _repo is not None:
        return _repo
    kind = (os.getenv("AI_TRAINING_REPOSITORY") or "").strip().lower()
    if kind == "postgres":
        _repo = PostgresTrainingRepository(resolve_training_dsn())
        return _repo
    raise RepositoryUnavailable("AI_TRAINING_REPOSITORY not configured")


def set_repository(repo) -> None:
    """테스트/격리 실행용 주입."""
    global _repo
    _repo = repo
