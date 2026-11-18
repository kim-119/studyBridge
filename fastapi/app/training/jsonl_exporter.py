"""
검증 통과 학습 데이터 JSONL 내보내기.

흐름:
  1. DB 후보 조회 (db_training_data_collector)
  2. 다중 기준 검증 (training_data_validator)
  3. 중복 제거
  4. messages 구조 정규화
  5. JSONL 파일 저장
  6. export 이력 DB 저장

기존 jsonl_export_service.py 는 건드리지 않는다.
이 모듈은 검증 파이프라인을 거친 고품질 데이터만 내보내는 강화 버전이다.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from app.training.training_data_validator import (
    ValidationCriteria,
    validate_candidates_batch,
)

logger = logging.getLogger(__name__)

_EXPORT_DIR = os.path.join(
    os.path.dirname(__file__),   # app/training/
    "..", "..", "training_exports"  # fastapi/training_exports/
)


def _export_dir() -> Path:
    p = Path(os.path.normpath(_EXPORT_DIR))
    p.mkdir(parents=True, exist_ok=True)
    return p


async def export_validated_jsonl(
    output_filename: str | None = None,
    criteria: ValidationCriteria | None = None,
    min_db_score: int = 70,
    dry_run: bool = False,
) -> dict:
    """
    DB 후보 → 검증 → JSONL export.

    Args:
        output_filename: 저장할 파일명 (None이면 자동 생성)
        criteria:        검증 기준 (None이면 DEFAULT_CRITERIA)
        min_db_score:    DB에서 읽을 최소 quality_score (0~100)
        dry_run:         True이면 파일을 쓰지 않고 통계만 반환

    Returns:
        {
            "exported_count": int,
            "total_candidates": int,
            "passed_count": int,
            "failed_count": int,
            "output_file": str | None,
            "status": "completed" | "dry_run" | "empty",
            "failure_summary": {"이유": count, ...},
            "dataset_version": str,
        }
    """
    from app.training.db_training_data_collector import fetch_candidates, save_export_job

    # 1. DB 후보 조회
    rows = await fetch_candidates(
        statuses=["auto_approved", "holdout"],
        min_score=min_db_score,
    )
    total = len(rows)
    logger.info("DB 후보 조회: %d건", total)

    if total == 0:
        return {
            "exported_count": 0,
            "total_candidates": 0,
            "passed_count": 0,
            "failed_count": 0,
            "output_file": None,
            "status": "empty",
            "failure_summary": {},
            "dataset_version": "",
            "message": "학습 후보 데이터가 없습니다.",
        }

    # 2. 다중 기준 검증
    results = validate_candidates_batch(rows, criteria)
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]
    logger.info("검증 결과: 통과=%d, 탈락=%d", len(passed), len(failed))

    # 실패 이유 집계
    failure_summary: dict[str, int] = {}
    for r in failed:
        for reason in r.failure_reasons:
            failure_summary[reason] = failure_summary.get(reason, 0) + 1

    if not passed:
        return {
            "exported_count": 0,
            "total_candidates": total,
            "passed_count": 0,
            "failed_count": len(failed),
            "output_file": None,
            "status": "empty",
            "failure_summary": failure_summary,
            "dataset_version": "",
            "message": "검증 통과 데이터가 없습니다. 기준을 낮추거나 데이터를 추가하세요.",
        }

    # 3. uuid 기반 중복 제거 (같은 후보가 두 번 들어오는 경우 방지)
    seen_uuids: set[str] = set()
    passed_rows = []
    for vr in passed:
        if vr.candidate_uuid not in seen_uuids:
            seen_uuids.add(vr.candidate_uuid)
            passed_rows.append(vr)

    # row dict 매핑 (uuid → row)
    uuid_to_row = {str(r.get("candidate_uuid", "")): r for r in rows}

    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    dataset_version = f"studybridge_sft_{date_str}"

    if dry_run:
        return {
            "exported_count": len(passed_rows),
            "total_candidates": total,
            "passed_count": len(passed_rows),
            "failed_count": len(failed),
            "output_file": None,
            "status": "dry_run",
            "failure_summary": failure_summary,
            "dataset_version": dataset_version,
            "message": f"dry_run 모드: 실제 파일 저장 없음. {len(passed_rows)}건 export 예정.",
        }

    # 4. JSONL 저장
    if output_filename is None:
        output_filename = f"{dataset_version}.jsonl"
    output_path = _export_dir() / output_filename

    exported_count = 0
    with output_path.open("w", encoding="utf-8") as f:
        for vr in passed_rows:
            row = uuid_to_row.get(vr.candidate_uuid, {})
            messages = _build_messages(row)
            if not messages:
                continue
            line = {"messages": messages}
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
            exported_count += 1

    logger.info("JSONL 저장 완료: %d건 → %s", exported_count, output_path)

    # 5. export 이력 저장
    await save_export_job(str(output_path), exported_count)

    return {
        "exported_count": exported_count,
        "total_candidates": total,
        "passed_count": len(passed_rows),
        "failed_count": len(failed),
        "output_file": str(output_path),
        "status": "completed",
        "failure_summary": failure_summary,
        "dataset_version": dataset_version,
        "message": f"{exported_count}건 export 완료.",
    }


def _build_messages(row: dict) -> list[dict] | None:
    """DB row를 messages 구조 리스트로 변환한다."""
    question   = str(row.get("question", "") or "").strip()
    answer     = str(row.get("answer", "") or "").strip()
    sys_prompt = str(row.get("system_prompt", "") or "").strip()

    # 필수 필드 없으면 제외
    if not question or not answer:
        return None

    messages = []
    if sys_prompt:
        messages.append({"role": "system", "content": sys_prompt})
    messages.append({"role": "user", "content": question})
    messages.append({"role": "assistant", "content": answer})
    return messages
