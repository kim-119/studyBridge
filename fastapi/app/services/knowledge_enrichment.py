"""
지식 보강 모듈 (기본개념모드 답변 grounding).

한국어 위키백과(다중 문서) + (TAVILY_API_KEY 있을 때)Tavily 웹검색을 단일 "[참고자료]"
블록으로 합쳐 LLM 프롬프트에 주입한다.

설계 원칙:
- graceful: Tavily 키 없음/실패 → 위키만, 위키도 없음 → 빈 문자열. 어떤 예외도 위로 새지 않는다.
- 턴당 1회 fetch + 메모리 캐시(같은 질문 재호출 비용 0).
- 외부 호출 timeout 짧게(기본 3s).
- content-free: 특정 도메인 주제어를 로직/폴백에 하드코딩하지 않는다(반복 유발 회피).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 3.0
_WIKI_DOC_LIMIT = 3           # 참조 위키 문서 수
_WIKI_EXTRACT_CHARS = 1200    # 위키 본문 합산 상한(인트로 위주)
_TAVILY_MAX_RESULTS = 3

_cache: Dict[str, str] = {}


def clear_cache() -> None:
    """테스트/운영 리셋용 캐시 비우기."""
    _cache.clear()


def _tavily_enabled() -> bool:
    return bool((os.getenv("TAVILY_API_KEY") or "").strip())


def _fetch_wiki(query: str, timeout: float) -> str:
    """한국어 위키 다중 문서 인트로를 합산 상한 내로 반환한다(실패/없음→빈문자열)."""
    encoded = urllib.parse.quote(query)
    search_url = (
        "https://ko.wikipedia.org/w/api.php?action=query&list=search"
        f"&srsearch={encoded}&utf8=&format=json&srlimit={_WIKI_DOC_LIMIT}"
    )
    req = urllib.request.Request(search_url, headers={"User-Agent": "StudyBridge/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    results = data.get("query", {}).get("search", [])
    titles = [r["title"] for r in results if r.get("title")]
    if not titles:
        return ""

    titles_param = urllib.parse.quote("|".join(titles))
    extract_url = (
        "https://ko.wikipedia.org/w/api.php?format=json&action=query&prop=extracts"
        f"&exintro=true&explaintext=true&redirects=1&titles={titles_param}"
    )
    req2 = urllib.request.Request(extract_url, headers={"User-Agent": "StudyBridge/1.0"})
    with urllib.request.urlopen(req2, timeout=timeout) as resp2:
        data2 = json.loads(resp2.read().decode())

    pages = data2.get("query", {}).get("pages", {})
    parts: List[str] = []
    used = 0
    for _pid, page in pages.items():
        extract = (page.get("extract") or "").strip()
        if not extract:
            continue
        room = _WIKI_EXTRACT_CHARS - used
        if room <= 0:
            break
        snippet = extract[:room]
        parts.append(f"▶ {page.get('title', '')}: {snippet}")
        used += len(snippet)
    return "\n".join(parts).strip()


def _fetch_tavily(query: str, timeout: float) -> str:
    """Tavily 웹검색 요약(키 있을 때만 호출됨). 실패→예외(호출측에서 graceful 처리)."""
    api_key = (os.getenv("TAVILY_API_KEY") or "").strip()
    if not api_key:
        return ""
    payload = json.dumps({
        "api_key": api_key,
        "query": query,
        "max_results": _TAVILY_MAX_RESULTS,
        "search_depth": "basic",
        "include_answer": True,
    }).encode()
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())

    parts: List[str] = []
    answer = (data.get("answer") or "").strip()
    if answer:
        parts.append(f"• {answer}")
    for item in (data.get("results") or [])[:_TAVILY_MAX_RESULTS]:
        title = (item.get("title") or "").strip()
        content = (item.get("content") or "").strip()
        if content:
            parts.append(f"• {title}: {content[:300]}" if title else f"• {content[:300]}")
    return "\n".join(parts).strip()


def _safe(fetch, query: str, timeout: float, label: str) -> str:
    try:
        return (fetch(query, timeout) or "").strip()
    except Exception as e:  # 어떤 예외도 위로 새지 않는다
        logger.warning("[KnowledgeEnrichment] %s 실패: %s", label, e)
        return ""


def build_knowledge_context(query: str, *, timeout: float = _DEFAULT_TIMEOUT) -> str:
    """위키(+Tavily)를 단일 [참고자료] 블록으로 반환한다. 근거 없으면 빈 문자열."""
    q = (query or "").strip()
    if not q:
        return ""
    if q in _cache:
        return _cache[q]

    blocks: List[str] = []
    wiki = _safe(_fetch_wiki, q, timeout, "위키")
    if wiki:
        blocks.append("[위키백과]\n" + wiki)

    if _tavily_enabled():
        web = _safe(_fetch_tavily, q, timeout, "Tavily")
        if web:
            blocks.append("[웹 검색]\n" + web)

    if not blocks:
        _cache[q] = ""
        return ""

    out = (
        "[참고자료] 아래는 사용자 질문과 관련된 신뢰 가능한 자료다. 이 내용을 근거로 더 정확하고 "
        "풍부하게 설명하되, 자료에 없는 사실을 지어내지 마라.\n" + "\n\n".join(blocks)
    )
    _cache[q] = out
    return out
