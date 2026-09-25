"""
Tavily Search API 서비스.
최신 웹 검색 결과를 가져온다. 최종 답변 생성은 Qwen2.5가 담당한다.
"""
from app.core.config import TAVILY_API_KEY, DEFAULT_SEARCH_DEPTH, DEFAULT_MAX_RESULTS


def search_web(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> list[dict]:
    """
    Tavily Search API를 호출하여 최신 웹 검색 결과를 반환한다.

    Args:
        query:       검색 쿼리
        max_results: 최대 결과 수 (기본값: 환경변수 DEFAULT_MAX_RESULTS)

    Returns:
        [{"title": str, "url": str, "content": str, "score": float}, ...]

    Raises:
        RuntimeError: TAVILY_API_KEY가 없거나 API 호출 실패 시
    """
    if not TAVILY_API_KEY:
        raise RuntimeError(
            "TAVILY_API_KEY 환경변수가 설정되지 않았습니다. "
            ".env 파일에 TAVILY_API_KEY=tvly-... 를 추가하세요."
        )

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=TAVILY_API_KEY)

        response = client.search(
            query=query,
            search_depth=DEFAULT_SEARCH_DEPTH,   # "basic" 또는 "advanced"
            max_results=max_results,
            include_answer=False,       # 최종 답변은 Qwen이 생성
            include_raw_content=False,  # 초반엔 요약만 사용
        )

        results = []
        for item in response.get("results", []):
            results.append({
                "title":   item.get("title", ""),
                "url":     item.get("url", ""),
                "content": item.get("content", ""),
                "score":   item.get("score", 0.0),
            })

        return results

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Tavily 검색 중 오류가 발생했습니다: {e}") from e
