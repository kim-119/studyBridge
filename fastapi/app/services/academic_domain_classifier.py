"""
학문 도메인 분류기.
규칙 기반 1차 분류 → confidence 부족 시 LLM fallback.
materialId가 있으면 RAG 키워드도 활용한다.
"""
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_policy_cache: Optional[Dict[str, Any]] = None


def _load_policy() -> Dict[str, Any]:
    global _policy_cache
    if _policy_cache is not None:
        return _policy_cache
    try:
        import yaml
        path = Path(__file__).parent.parent / "core" / "academic_domain_policy.yaml"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                _policy_cache = data
                return _policy_cache
    except Exception as e:
        logger.warning("academic_domain_policy.yaml 로드 실패: %s", e)
    _policy_cache = {}
    return _policy_cache


def _rule_based_classify(text: str) -> Dict[str, float]:
    """키워드 매칭으로 도메인별 점수 계산. 반환: {domain: score}"""
    policy = _load_policy()
    keyword_rules = policy.get("keyword_rules", {})
    if not keyword_rules:
        return {}

    text_lower = text.lower()
    scores: Dict[str, float] = {}

    for domain, cfg in keyword_rules.items():
        keywords: List[str] = cfg.get("keywords", [])
        weight: float = cfg.get("weight", 1.0)
        hit = sum(1 for kw in keywords if kw.lower() in text_lower)
        if hit > 0:
            scores[domain] = min(1.0, (hit / max(len(keywords), 1)) * weight * 3.0)

    return scores


def _llm_classify(text: str) -> Optional[str]:
    """LLM fallback 분류. 도메인 이름만 반환. 실패 시 None."""
    try:
        from app.services.llm_engine_router import call_primary_llm
        domain_list = ", ".join([
            "computer_science", "mathematics", "physics", "chemistry", "biology",
            "medicine_health", "psychology", "philosophy", "economics", "business",
            "law", "education", "sociology", "history", "literature", "linguistics",
            "art_design", "engineering", "environment", "general_study",
        ])
        system = (
            "너는 학문 도메인 분류 전문가다. "
            "주어진 텍스트의 학문 분야를 아래 목록 중 하나로만 답하라. "
            f"목록: {domain_list}\n"
            "한 단어만 답하라. 설명 금지."
        )
        result = call_primary_llm(
            system_prompt=system,
            user_prompt=f"텍스트: {text[:300]}",
            max_tokens=20,
            temperature=0.1,
        )
        if result:
            domain = result.strip().lower().replace(" ", "_")
            # 유효한 도메인인지 확인
            policy = _load_policy()
            valid_domains = policy.get("domains", [])
            if domain in valid_domains:
                return domain
    except Exception as e:
        logger.warning("LLM 도메인 분류 실패: %s", e)
    return None


def classify(
    question: str,
    material_title: Optional[str] = None,
    rag_chunks: Optional[List[str]] = None,
) -> "AcademicDomainResult":  # noqa: F821
    """
    질문과 선택적 컨텍스트로 학문 도메인을 분류한다.
    반환: AcademicDomainResult
    """
    from app.schemas.academic_domain_schema import AcademicDomainResult

    policy = _load_policy()
    cls_cfg = policy.get("classification", {})
    rule_threshold = cls_cfg.get("rule_based_threshold", 0.40)
    unknown_threshold = cls_cfg.get("unknown_threshold", 0.25)
    high_stakes_domains = set(cls_cfg.get("high_stakes_domains", ["medicine_health", "law"]))

    # 분류 대상 텍스트 조합
    text_parts = [question]
    if material_title:
        text_parts.append(material_title)
    if rag_chunks:
        text_parts.extend(rag_chunks[:3])
    combined_text = " ".join(text_parts)

    # 1차: 규칙 기반
    scores = _rule_based_classify(combined_text)
    used_llm = False

    if scores:
        top_domain = max(scores, key=lambda k: scores[k])
        top_score = scores[top_domain]
    else:
        top_domain = "unknown"
        top_score = 0.0

    # confidence 부족 시 LLM fallback
    if top_score < rule_threshold:
        llm_domain = _llm_classify(combined_text)
        if llm_domain:
            top_domain = llm_domain
            top_score = 0.55  # LLM 분류 신뢰도 기본값
            used_llm = True

    # unknown 처리
    if top_score < unknown_threshold:
        top_domain = "general_study"
        top_score = 0.30

    is_high_stakes = top_domain in high_stakes_domains
    # 최신 정보가 중요한 분야 (의학, 법, 환경, 경제)
    requires_recent = top_domain in {"medicine_health", "law", "environment", "economics"}

    # 권장 소스 결정
    try:
        from app.core.policy_loader import get_source_policy
        source_policy = get_source_policy()
        routing = source_policy.get("domain_source_routing", {}).get(top_domain, {})
        recommended = list(routing.get("primary", ["rag", "wikipedia"]))
    except Exception:
        recommended = ["rag", "wikipedia"]

    return AcademicDomainResult(
        domain=top_domain,
        confidence=round(min(1.0, top_score), 3),
        subdomain=None,
        is_high_stakes=is_high_stakes,
        requires_recent_sources=requires_recent,
        recommended_sources=recommended,
        used_llm_fallback=used_llm,
    )


def invalidate_cache() -> None:
    global _policy_cache
    _policy_cache = None
