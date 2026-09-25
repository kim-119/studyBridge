"""
증류(distillation) 학습 준비도 체크.
distillation-ready 후보가 충분히 쌓였는지, 안전성 기준을 통과했는지 확인한다.
실제 student 학습은 이 체크 통과 후에만 수행한다.
"""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

_READINESS_CRITERIA = {
    "min_verified_candidates": 300,
    "min_domain_coverage": 3,          # 최소 3개 이상 도메인 포함
    "max_pii_ratio": 0.01,              # PII 포함 비율 1% 이하
    "min_knowledge_level_diversity": 2, # 최소 2개 이상 지식수준 포함
    "require_teacher_label": True,
    "auto_train": False,                # 자동 학습 기본 비활성
    "auto_deploy": False,               # 자동 배포 기본 비활성
}


def check(candidates: list) -> Dict[str, Any]:
    """
    후보 목록의 준비도를 검사한다.
    반환: {"ready": bool, "reasons": [...], "stats": {...}}
    """
    reasons = []
    stats: Dict[str, Any] = {}

    # 후보 수
    total = len(candidates)
    stats["total_candidates"] = total
    if total < _READINESS_CRITERIA["min_verified_candidates"]:
        reasons.append(
            f"후보 부족: {total}/{_READINESS_CRITERIA['min_verified_candidates']}개"
        )

    # 도메인 다양성
    domains = set(c.get("domain", "unknown") for c in candidates)
    stats["unique_domains"] = len(domains)
    if len(domains) < _READINESS_CRITERIA["min_domain_coverage"]:
        reasons.append(f"도메인 다양성 부족: {len(domains)}개 도메인")

    # 지식수준 다양성
    levels = set(c.get("knowledge_level", "학사") for c in candidates)
    stats["unique_knowledge_levels"] = len(levels)
    if len(levels) < _READINESS_CRITERIA["min_knowledge_level_diversity"]:
        reasons.append(f"지식수준 다양성 부족: {len(levels)}개 수준")

    # teacher label 확인
    if _READINESS_CRITERIA["require_teacher_label"]:
        labeled = sum(1 for c in candidates if c.get("teacher_answer"))
        stats["teacher_labeled"] = labeled
        if labeled < total * 0.5:
            reasons.append(f"teacher label 부족: {labeled}/{total}건")

    # PII 검사
    try:
        from app.utils.pii_filter import has_pii
        pii_count = sum(
            1 for c in candidates
            if has_pii(c.get("question", "")) or has_pii(c.get("answer", ""))
        )
        pii_ratio = pii_count / max(total, 1)
        stats["pii_count"] = pii_count
        stats["pii_ratio"] = round(pii_ratio, 4)
        if pii_ratio > _READINESS_CRITERIA["max_pii_ratio"]:
            reasons.append(f"PII 비율 초과: {pii_ratio:.2%}")
    except Exception as e:
        logger.warning("PII 검사 실패: %s", e)

    ready = len(reasons) == 0
    stats["auto_train"] = _READINESS_CRITERIA["auto_train"]
    stats["auto_deploy"] = _READINESS_CRITERIA["auto_deploy"]

    return {
        "ready": ready,
        "reasons": reasons,
        "stats": stats,
        "criteria": _READINESS_CRITERIA,
    }
