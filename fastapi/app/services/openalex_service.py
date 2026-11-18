"""
OpenAlex API 연동 서비스.
박사(박사) 수준에서만 호출한다.
2020년 이후 자료만 가져온다.
결과는 내부 컨텍스트 보강에만 사용하며, 최종 답변에 출처를 노출하지 않는다.
API 실패 시 서버가 죽지 않는다.
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_OPENALEX_BASE_URL = "https://api.openalex.org"
_OPENALEX_LEVEL = "박사"


def _is_enabled() -> bool:
    return os.getenv("OPENALEX_ENABLED", "false").lower() == "true"


def _get_base_url() -> str:
    return os.getenv("OPENALEX_BASE_URL", _OPENALEX_BASE_URL)


def _get_min_date() -> str:
    return os.getenv("OPENALEX_MIN_PUBLICATION_DATE", "2020-01-01")


def _get_per_page() -> int:
    try:
        return int(os.getenv("OPENALEX_PER_PAGE", "3"))
    except ValueError:
        return 3


def _get_timeout() -> int:
    try:
        return int(os.getenv("OPENALEX_TIMEOUT_SECONDS", "8"))
    except ValueError:
        return 8


def _get_sort() -> str:
    return os.getenv("OPENALEX_SORT", "cited_by_count:desc")


def _get_api_key() -> Optional[str]:
    key = os.getenv("OPENALEX_API_KEY", "")
    return key if key else None


def _decode_abstract(inverted_index: Optional[dict]) -> Optional[str]:
    """OpenAlex abstract_inverted_index를 일반 텍스트로 복원."""
    if not inverted_index or not isinstance(inverted_index, dict):
        return None
    try:
        word_positions = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort(key=lambda x: x[0])
        return " ".join(w for _, w in word_positions)
    except Exception:
        return None


def search(
    question: str,
    knowledge_level: str,
    domain: Optional[str] = None,
) -> "OpenAlexSearchResult":  # noqa: F821
    """
    OpenAlex에서 논문을 검색하여 내부 컨텍스트용 결과를 반환한다.
    박사 수준이 아니거나 OPENALEX_ENABLED=false이면 즉시 skipped 반환.
    """
    from app.schemas.openalex_schema import OpenAlexSearchResult, OpenAlexWork

    if knowledge_level != _OPENALEX_LEVEL:
        return OpenAlexSearchResult(
            query=question, skipped=True, skip_reason="knowledge_level_not_doctoral",
        )

    if not _is_enabled():
        return OpenAlexSearchResult(
            query=question, skipped=True, skip_reason="openalex_disabled",
        )

    api_key = _get_api_key()
    base_url = _get_base_url()
    min_date = _get_min_date()
    per_page = _get_per_page()
    timeout = _get_timeout()
    sort = _get_sort()

    params = {
        "search": question[:200],
        "filter": f"from_publication_date:{min_date}",
        "per_page": per_page,
        "sort": sort,
        "select": "id,display_name,publication_year,cited_by_count,doi,abstract_inverted_index",
    }
    if api_key:
        params["api_key"] = api_key

    try:
        import httpx
        url = f"{base_url}/works"
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("OpenAlex 검색 실패 (계속 진행): %s", e)
        return OpenAlexSearchResult(
            query=question, error=str(e),
            skipped=True, skip_reason="api_error",
        )

    results_raw = data.get("results", [])
    works = []
    for item in results_raw:
        abstract = _decode_abstract(item.get("abstract_inverted_index"))
        works.append(OpenAlexWork(
            title=item.get("display_name", ""),
            publication_year=item.get("publication_year"),
            cited_by_count=item.get("cited_by_count"),
            abstract=abstract,
            doi=item.get("doi"),
        ))

    logger.info("OpenAlex 검색 완료: %d건 (박사 수준, %s 이후)", len(works), min_date)
    return OpenAlexSearchResult(
        query=question,
        works=works,
        total_count=data.get("meta", {}).get("count", len(works)),
        min_publication_date=min_date,
    )
