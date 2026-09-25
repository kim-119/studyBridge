"""
박사/전문가 수준 답변의 학문적 깊이를 검증한다.
domain_depth_profiles.yaml의 doctoral_expectations를 기준으로 검사한다.
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_profile_cache: Optional[Dict[str, Any]] = None


def _load_profiles() -> Dict[str, Any]:
    global _profile_cache
    if _profile_cache is not None:
        return _profile_cache
    try:
        import yaml
        path = Path(__file__).parent.parent / "core" / "domain_depth_profiles.yaml"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                _profile_cache = data
                return _profile_cache
    except Exception as e:
        logger.warning("domain_depth_profiles.yaml 로드 실패: %s", e)
    _profile_cache = {}
    return _profile_cache


def _get_domain_profile(domain: str) -> Dict[str, Any]:
    profiles = _load_profiles()
    domains = profiles.get("domains", {})
    if domain in domains:
        return domains[domain]
    return profiles.get("default_academic_rubric", {})


def _score_coverage(answer: str, expectations: List[str]) -> tuple[float, List[str]]:
    """답변이 doctoral_expectations 항목을 얼마나 커버하는지 점수화."""
    if not expectations:
        return 0.5, []

    answer_lower = answer.lower()
    missing = []
    hits = 0

    # 간단한 키워드 기반 커버리지 (LLM 검증 없이 빠른 1차 검사)
    expectation_keywords = {
        "엄밀한 정의": ["정의", "개념", "엄밀"],
        "이론적 배경": ["이론", "배경", "원리"],
        "방법론적 한계": ["한계", "제약", "문제점", "약점"],
        "반례 또는 예외": ["반례", "예외", "경계"],
        "논쟁점": ["논쟁", "쟁점", "비판", "반론"],
        "증명 전략": ["증명", "증", "유도"],
        "필요조건/충분조건": ["필요", "충분", "조건"],
        "일반화 가능성": ["일반화", "확장"],
        "측정 타당도": ["타당도", "신뢰도", "측정"],
        "실험 설계": ["실험", "연구 설계", "방법론"],
        "상관과 인과": ["인과", "상관"],
        "모형의 가정": ["가정", "전제", "모형"],
        "병태생리": ["기전", "병리", "생리"],
        "요건사실": ["요건", "사실"],
        "판례 법리": ["판례", "법리"],
        "논증의 전제": ["전제", "논증"],
    }

    for exp in expectations:
        # exp 자체 키워드 직접 검사
        exp_parts = exp.replace("/", " ").split()
        exp_hit = any(part.lower() in answer_lower for part in exp_parts if len(part) > 1)

        # 추가 키워드 매핑 검사
        extra_keys = expectation_keywords.get(exp, [])
        extra_hit = any(kw.lower() in answer_lower for kw in extra_keys)

        if exp_hit or extra_hit:
            hits += 1
        else:
            missing.append(exp)

    coverage = hits / len(expectations)
    return coverage, missing


def verify(
    answer: str,
    domain: str,
    knowledge_level: str,
) -> "DepthVerificationResult":  # noqa: F821
    """
    답변의 학문적 깊이를 검증한다.
    박사/전문가 수준이 아니면 즉시 passed 반환.
    """
    from app.schemas.academic_depth_schema import DepthVerificationResult
    from app.services.source_leakage_guard import detect as detect_leakage

    # 박사/전문가 수준 이외는 검증 불필요
    if knowledge_level not in ("박사", "전문가"):
        return DepthVerificationResult(
            domain=domain,
            knowledge_level=knowledge_level,
            domain_depth_coverage=1.0,
            rewrite_required=False,
        )

    profile = _get_domain_profile(domain)
    expectations: List[str] = profile.get("doctoral_expectations", [])
    min_coverage: float = profile.get("min_depth_coverage", 0.65)

    if not expectations:
        return DepthVerificationResult(
            domain=domain,
            knowledge_level=knowledge_level,
            domain_depth_coverage=0.7,
            rewrite_required=False,
        )

    coverage, missing = _score_coverage(answer, expectations)

    # 간단 점수 계산 (답변 길이 기반 보정)
    answer_len = len(answer)
    length_bonus = min(0.15, answer_len / 3000)  # 긴 답변에 약간 보너스
    adjusted_coverage = min(1.0, coverage + length_bonus)

    leakage_detected, _ = detect_leakage(answer)

    rewrite_required = (
        adjusted_coverage < min_coverage
        or leakage_detected
    )

    logger.debug(
        "depth verify: domain=%s level=%s coverage=%.2f threshold=%.2f rewrite=%s",
        domain, knowledge_level, adjusted_coverage, min_coverage, rewrite_required,
    )

    return DepthVerificationResult(
        domain=domain,
        knowledge_level=knowledge_level,
        domain_depth_coverage=round(adjusted_coverage, 3),
        source_leakage_detected=leakage_detected,
        rewrite_required=rewrite_required,
        missing_requirements=missing[:5],  # 최대 5개만
    )


def invalidate_cache() -> None:
    global _profile_cache
    _profile_cache = None
