"""
Wikipedia 검색 서비스.
Wikipedia API는 별도 API Key 없이 호출 가능하다.
"""
import re
import requests
from app.core.config import WIKI_LANGUAGE, WIKI_USER_AGENT


def search_wikipedia(query: str, limit: int = 3) -> list[dict]:
    """
    Wikipedia API를 호출하여 개념 설명 후보를 검색한다.

    Args:
        query: 검색 쿼리
        limit: 반환할 최대 결과 수 (기본값 3)

    Returns:
        [{"title": str, "snippet": str, "pageid": int, "url": str}, ...]
    """
    api_url = f"https://{WIKI_LANGUAGE}.wikipedia.org/w/api.php"

    params = {
        "action":   "query",
        "list":     "search",
        "srsearch": query,
        "srlimit":  limit,
        "format":   "json",
        "utf8":     1,
    }

    headers = {
        "User-Agent": WIKI_USER_AGENT,
    }

    try:
        resp = requests.get(api_url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        search_hits = data.get("query", {}).get("search", [])
        results = []

        for hit in search_hits:
            pageid = hit.get("pageid", 0)
            title  = hit.get("title", "")
            snippet = hit.get("snippet", "")

            # TODO: BeautifulSoup 등으로 더 정교하게 제거 가능
            snippet_clean = re.sub(r"<[^>]+>", "", snippet)

            page_url = (
                f"https://{WIKI_LANGUAGE}.wikipedia.org/wiki/"
                + title.replace(" ", "_")
            )

            results.append({
                "title":   title,
                "snippet": snippet_clean,
                "pageid":  pageid,
                "url":     page_url,
            })

        return results

    except requests.RequestException as e:
        raise RuntimeError(f"Wikipedia 검색 중 네트워크 오류가 발생했습니다: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Wikipedia 검색 중 오류가 발생했습니다: {e}") from e
