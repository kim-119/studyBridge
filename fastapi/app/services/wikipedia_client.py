"""
Wikipedia 검색 클라이언트.
API Key 불필요. 멀티 에이전트에서 일반 개념 보완 시 사용.
기존 wikipedia_service.py의 thin wrapper.
"""
from app.services.wikipedia_service import search_wikipedia


def search(query: str, limit: int = 3, *, feature: str = "wikipedia_search") -> list[dict]:
    """
    Wikipedia에서 개념을 검색한다.

    Returns:
        [{"title": str, "snippet": str, "pageid": int, "url": str}, ...]
    """
    return search_wikipedia(query, limit=limit, feature=feature)


def is_available(feature: str = "wikipedia_search") -> bool:
    """Wikipedia는 API Key 가 없어도 되지만 외부 전송 정책이 허용해야 사용 가능하다."""
    from app.core.egress_policy import egress_allowed
    return egress_allowed("wikipedia", feature)
