"""
Wikipedia 검색 클라이언트.
API Key 불필요. 멀티 에이전트에서 일반 개념 보완 시 사용.
기존 wikipedia_service.py의 thin wrapper.
"""
from app.services.wikipedia_service import search_wikipedia


def search(query: str, limit: int = 3) -> list[dict]:
    """
    Wikipedia에서 개념을 검색한다.

    Returns:
        [{"title": str, "snippet": str, "pageid": int, "url": str}, ...]
    """
    return search_wikipedia(query, limit=limit)


def is_available() -> bool:
    """Wikipedia는 API Key 없이 항상 사용 가능하다."""
    return True
