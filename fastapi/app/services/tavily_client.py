"""
Tavily Search API 클라이언트.
TAVILY_API_KEY 미설정 시 RuntimeError. 멀티 에이전트에서 최신 정보 검색 시 사용.
기존 tavily_service.py의 thin wrapper.
"""
from app.services.tavily_service import search_web


def search(query: str, max_results: int = 5) -> list[dict]:
    """
    Tavily로 웹 검색을 수행한다.

    Returns:
        [{"title": str, "url": str, "content": str, "score": float}, ...]

    Raises:
        RuntimeError: TAVILY_API_KEY 미설정 또는 API 호출 실패
    """
    return search_web(query, max_results=max_results)


def is_available() -> bool:
    """TAVILY_API_KEY 설정 여부를 반환한다."""
    from app.core.config import TAVILY_API_KEY
    return bool(TAVILY_API_KEY)
