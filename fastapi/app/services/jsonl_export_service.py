"""
[레거시 호환] JSONL 내보내기 서비스.

예전 구현은 API 가 준 output_path 에 그대로 썼다(임의 경로 쓰기/상위 경로/symlink/덮어쓰기/크기 무제한/동시 경합)
그리고 auto_approved(휴리스틱 90점) 행을 학습 데이터로 내보냈다. 이제는:
  - output_path 지정 불가(기본값/None 만 허용) → app.training_pipeline.export_service 의 고정 비공개 디렉터리.
  - TRAIN_ELIGIBLE(동의·권리·PII·사실 검증 통과) 후보만, 사용자/문서 그룹 분할 + 누출 검사 + manifest.
"""
import logging

logger = logging.getLogger(__name__)

LEGACY_DEFAULT_OUTPUT_PATH = "exported_training_data.jsonl"


class OutputPathNotAllowed(ValueError):
    pass


async def export_approved_candidates(
    output_path: str | None = None,
    min_score: int = 90,
    *,
    actor: str = "legacy-caller",
    request_id: str = "legacy-export",
) -> dict:
    """
    Returns:
        {"output_path": str|None(데이터셋 루트 기준 상대 경로), "exported_count": int,
         "status": "completed"|"empty"|"busy"|"failed", "dataset_id": str|None, "error_code": str|None}
    """
    if output_path not in (None, "", LEGACY_DEFAULT_OUTPUT_PATH):
        raise OutputPathNotAllowed("output_path 는 지정할 수 없습니다(고정 비공개 디렉터리만 사용).")
    from app.training_pipeline.export_service import export_dataset
    from app.training_pipeline.repository import get_repository

    res = await export_dataset(get_repository(), actor=actor, request_id=request_id)
    logger.info("JSONL 내보내기: status=%s count=%d dataset=%s", res.status, res.total, res.dataset_id)
    return {"output_path": res.relative_path, "exported_count": res.total, "status": res.status,
            "dataset_id": res.dataset_id, "error_code": res.error_code}
