"""
중복 Q/A 검사 유틸리티.

- exact: content_hash(SHA-256, NFKC+공백 정규화) 일치.
- near-duplicate: 문자 3-gram SimHash(64bit) 해밍거리 ≤ NEAR_DUP_MAX_HAMMING.
- DB 조회 실패/미접속 → UNKNOWN. UNKNOWN 은 '중복 아님'이 아니다(저장·승인 불가/보류, fail-closed).
- 최종 race 방어는 DB 유니크 제약(content_hash)과 INSERT ... ON CONFLICT 가 담당한다
  (app/training_pipeline/migrations/001_training_pipeline_v2.sql).
"""
from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

NEAR_DUP_MAX_HAMMING = 6

UNIQUE = "UNIQUE"
EXACT_DUPLICATE = "EXACT_DUPLICATE"
NEAR_DUPLICATE = "NEAR_DUPLICATE"
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class DuplicateResult:
    status: str
    matched_id: Optional[str] = None
    hamming: Optional[int] = None
    error: Optional[str] = None

    @property
    def storable(self) -> bool:
        return self.status == UNIQUE


def normalize_text(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = re.sub(r"[^\w가-힣]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def simhash64(text: str) -> int:
    t = normalize_text(text).replace(" ", "")
    grams = [t[i:i + 3] for i in range(max(1, len(t) - 2))] if t else []
    if not grams:
        return 0
    acc = [0] * 64
    for g in grams:
        h = int.from_bytes(hashlib.blake2b(g.encode("utf-8"), digest_size=8).digest(), "big")
        for b in range(64):
            acc[b] += 1 if (h >> b) & 1 else -1
    out = 0
    for b in range(64):
        if acc[b] > 0:
            out |= 1 << b
    # Postgres BIGINT 범위로 맞춘다(부호 있는 64bit).
    return out - (1 << 64) if out >= (1 << 63) else out


def hamming(a: int, b: int) -> int:
    return bin((a ^ b) & ((1 << 64) - 1)).count("1")


def find_near_duplicate(sim: int, candidates: Iterable[tuple]) -> Optional[tuple]:
    """candidates: (id, simhash) 반복자. 가장 가까운 near-dup (id, distance) 또는 None."""
    best = None
    for cid, other in candidates:
        if other is None:
            continue
        d = hamming(sim, int(other))
        if d <= NEAR_DUP_MAX_HAMMING and (best is None or d < best[1]):
            best = (cid, d)
    return best


async def check_duplicate(content_hash: str, text_for_similarity: str, repository) -> DuplicateResult:
    """repository.find_by_content_hash / iter_simhashes 를 쓰는 중복 판정. 실패 → UNKNOWN."""
    try:
        existing = await repository.find_by_content_hash(content_hash)
        if existing is not None:
            return DuplicateResult(status=EXACT_DUPLICATE, matched_id=existing.candidate_id)
        sim = simhash64(text_for_similarity)
        near = find_near_duplicate(sim, await repository.iter_simhashes())
        if near is not None:
            return DuplicateResult(status=NEAR_DUPLICATE, matched_id=near[0], hamming=near[1])
        return DuplicateResult(status=UNIQUE)
    except Exception as e:  # noqa: BLE001
        logger.warning("중복 검사 실패 → UNKNOWN(저장 보류): %s", type(e).__name__)
        return DuplicateResult(status=UNKNOWN, error=type(e).__name__)


async def is_duplicate(content_hash: str) -> bool:
    """[레거시 호환] content_hash 가 ai.training_candidate 에 있으면 True.

    DB 연결 실패 시 예전에는 False(중복 아님)로 통과시켰다(fail-open). 이제는 True 를 반환해
    호출자가 저장하지 않게 한다(확인 불가 = 저장 불가).
    """
    try:
        from app.db.postgres import get_conn
        async with get_conn() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM ai.training_candidate WHERE content_hash=$1",
                content_hash,
            )
        return (count or 0) > 0
    except Exception as e:  # noqa: BLE001
        logger.warning("중복 검사 실패 → 저장 보류(True 반환): %s", type(e).__name__)
        return True
