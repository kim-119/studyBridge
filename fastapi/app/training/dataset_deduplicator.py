"""
학습 데이터 중복 제거.

SHA256 hash 기반으로 동일한 (system+user+assistant) 조합을 제거한다.
같은 질문에 유사 답변이 반복될 경우 품질 점수가 가장 높은 것만 남긴다.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DeduplicationResult:
    original_count: int
    deduped_count: int
    removed_count: int
    rows: list[dict] = field(default_factory=list)


def compute_sample_hash(system: str, user: str, assistant: str) -> str:
    """system + user + assistant 내용으로 SHA256 해시를 생성한다."""
    content = "\n".join([system.strip(), user.strip(), assistant.strip()])
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def deduplicate_rows(rows: list[dict]) -> DeduplicationResult:
    """
    SHA256 기반으로 동일한 (system+user+assistant) 조합을 제거한다.
    중복 시 quality_score가 높은 것을 우선 보존한다.
    """
    hash_to_best: dict[str, dict] = {}

    for row in rows:
        system    = str(row.get("system_prompt", "") or "")
        user      = str(row.get("question",      "") or "")
        assistant = str(row.get("answer",         "") or "")

        h = compute_sample_hash(system, user, assistant)
        row = {**row, "_sample_hash": h}  # 원본 변경 없이 복사본에 추가

        existing = hash_to_best.get(h)
        if existing is None or row.get("quality_score", 0) > existing.get("quality_score", 0):
            hash_to_best[h] = row

    deduped = list(hash_to_best.values())
    removed = len(rows) - len(deduped)

    if removed > 0:
        logger.info("hash 중복 제거: %d → %d (-%d)", len(rows), len(deduped), removed)

    return DeduplicationResult(
        original_count=len(rows),
        deduped_count=len(deduped),
        removed_count=removed,
        rows=deduped,
    )


def deduplicate_by_question_prefix(rows: list[dict]) -> list[dict]:
    """
    동일 (지식수준 + 성격 + 질문 앞 30자) 조합에서 품질 점수 1위만 남긴다.
    같은 PDF chunk에서 생성된 유사 답변이 과도하게 많은 경우를 처리한다.
    """
    key_to_best: dict[str, dict] = {}

    for row in rows:
        question = str(row.get("question", "")).strip()[:30]
        level    = str(row.get("knowledge_level", "")).strip()
        persona  = str(row.get("personality", "")).strip()
        key      = f"{level}|{persona}|{question}"

        existing = key_to_best.get(key)
        if existing is None or row.get("quality_score", 0) > existing.get("quality_score", 0):
            key_to_best[key] = row

    result = list(key_to_best.values())
    removed = len(rows) - len(result)
    if removed > 0:
        logger.info("질문 접두사 중복 제거: %d → %d (-%d)", len(rows), len(result), removed)
    return result


def deduplicate_pipeline(rows: list[dict]) -> DeduplicationResult:
    """
    전체 중복 제거 파이프라인.
    1단계: hash 기반 완전 중복 제거
    2단계: 질문 접두사 기반 유사 중복 제거
    """
    step1 = deduplicate_rows(rows)
    step2_rows = deduplicate_by_question_prefix(step1.rows)

    total_removed = len(rows) - len(step2_rows)
    logger.info(
        "중복 제거 완료: %d → %d (총 제거: %d건)",
        len(rows), len(step2_rows), total_removed,
    )
    return DeduplicationResult(
        original_count=len(rows),
        deduped_count=len(step2_rows),
        removed_count=total_removed,
        rows=step2_rows,
    )
