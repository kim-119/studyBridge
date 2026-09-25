"""
학문 도메인 + 지식수준에 따라 사용할 소스를 결정하는 라우터.
source_policy.yaml을 참조한다.
"""
import logging
import os
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
        path = Path(__file__).parent.parent / "core" / "source_policy.yaml"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                _policy_cache = data
                return _policy_cache
    except Exception as e:
        logger.warning("source_policy.yaml 로드 실패: %s", e)
    _policy_cache = {}
    return _policy_cache


def get_sources(
    domain: str,
    knowledge_level: str,
    has_material: bool = False,
    requires_recent: bool = False,
) -> List[str]:
    """
    도메인 + 지식수준 조합으로 사용할 소스 목록을 반환한다.
    반환 순서: 우선순위 높은 순.
    """
    policy = _load_policy()
    routing = policy.get("domain_source_routing", {})
    domain_routing = routing.get(domain, routing.get("general_study", {}))

    primary: List[str] = list(domain_routing.get("primary", ["rag", "wikipedia"]))
    doctoral_extra: List[str] = list(domain_routing.get("doctoral_extra", []))

    selected = list(primary)

    # 박사 수준이면 doctoral_extra 추가
    if knowledge_level == "박사" and doctoral_extra:
        selected.extend([s for s in doctoral_extra if s not in selected])

    # 자료가 있으면 RAG 최우선
    if has_material and "rag" in selected:
        selected = ["rag"] + [s for s in selected if s != "rag"]

    # 최신 정보 필요 시 tavily 우선
    if requires_recent and "tavily" in selected:
        idx = selected.index("tavily")
        if idx > 0:
            selected.insert(0, selected.pop(idx))

    # OpenAlex는 박사 수준이 아니면 항상 제외
    if knowledge_level != "박사" and "openalex" in selected:
        selected.remove("openalex")

    # OPENALEX_ENABLED=false이면 openalex 제외
    if "openalex" in selected:
        if os.getenv("OPENALEX_ENABLED", "false").lower() != "true":
            selected.remove("openalex")

    # 외부 API key 없으면 해당 소스 제외
    if "tavily" in selected:
        if not os.getenv("TAVILY_API_KEY", ""):
            selected.remove("tavily")

    return selected


def invalidate_cache() -> None:
    global _policy_cache
    _policy_cache = None
