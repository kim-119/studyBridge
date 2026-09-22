"""Grounding 정책 — 검색 질의와 생성 컨텍스트를 분리한다.

검색 질의 = current_user_message(기억 블록/이전 대화 제거본). Redis 기억·previousAnswers 전문을
Wiki/Tavily/OpenAI 질의어로 보내지 않는다(2026-09-16 감사: 이전 대화 전문이 OpenAI 로 전송됨).

수준별 소스(교수별):
  beginner: 없음 / bachelor: wiki / master: wiki+tavily / phd: wiki+gpt / expert: gpt+tavily
턴 내 필요한 소스를 합집합으로 모아 '병렬' 1회씩 호출하고(캐시), 실패는 degraded trace 로 남긴다.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from app.studymate.cancellation import CancelToken

logger = logging.getLogger("studybridge.studymate.grounding")

LEVEL_SOURCES = {
    "beginner": (),
    "bachelor": ("wiki",),
    "master": ("wiki", "tavily"),
    "phd": ("wiki", "gpt"),
    "expert": ("gpt", "tavily"),
}

_CACHE: Dict[str, tuple] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 1800.0
_CACHE_MAX = 256
MAX_QUERY_CHARS = 200
ITEM_MAX_CHARS = 700


@dataclass
class GroundingBundle:
    query: str
    by_source: Dict[str, str] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    elapsed_ms: int = 0

    def items_for(self, level: str) -> List[str]:
        out = []
        for src in LEVEL_SOURCES.get(level, ()):
            txt = (self.by_source.get(src) or "").strip()
            if txt:
                out.append(f"({src}) {txt[:ITEM_MAX_CHARS]}")
        return out

    def sources_for(self, level: str) -> List[str]:
        return [s for s in LEVEL_SOURCES.get(level, ()) if (self.by_source.get(s) or "").strip()]

    def evidence_text(self) -> str:
        return "\n".join(self.by_source.values())


def search_query(current_message: str) -> str:
    q = " ".join((current_message or "").split())
    return q[:MAX_QUERY_CHARS]


def _fetch(src: str, query: str) -> str:
    if src == "wiki":
        from app.services.knowledge_enrichment import _fetch_wiki, _DEFAULT_TIMEOUT
        return _fetch_wiki(query, _DEFAULT_TIMEOUT) or ""
    if src == "tavily":
        from app.services.knowledge_enrichment import _fetch_tavily, _tavily_enabled, _DEFAULT_TIMEOUT
        if not _tavily_enabled():
            return ""
        return _fetch_tavily(query, _DEFAULT_TIMEOUT) or ""
    if src == "gpt":
        from app.services.orchestrator_service import _build_gpt_brief
        return _build_gpt_brief(query) or ""
    return ""


def _cache_get(key: str) -> Optional[str]:
    with _CACHE_LOCK:
        v = _CACHE.get(key)
        if v and time.time() - v[0] < _CACHE_TTL:
            return v[1]
    return None


def _cache_put(key: str, text: str) -> None:
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            for k in sorted(_CACHE, key=lambda x: _CACHE[x][0])[: _CACHE_MAX // 4]:
                _CACHE.pop(k, None)
        _CACHE[key] = (time.time(), text)


def gather(current_message: str, levels: Iterable[str], *, cancel: Optional[CancelToken] = None,
           max_wait_s: float = 6.0, fetcher=None) -> GroundingBundle:
    fetch = fetcher or _fetch
    query = search_query(current_message)
    bundle = GroundingBundle(query=query)
    if os.getenv("STUDYMATE_GROUNDING", "on").strip().lower() in ("off", "0", "false") or not query:
        return bundle
    sources = sorted({s for lvl in levels for s in LEVEL_SOURCES.get(lvl, ())})
    if not sources:
        return bundle
    if cancel is not None and cancel.cancelled:
        bundle.skipped = sources
        return bundle
    t0 = time.time()
    todo = []
    for src in sources:
        cached = _cache_get(f"{src}\x1f{query}")
        if cached is not None:
            bundle.by_source[src] = cached
        else:
            todo.append(src)
    if todo:
        pool = ThreadPoolExecutor(max_workers=len(todo), thread_name_prefix="sm-ground")
        futs = {pool.submit(fetch, s, query): s for s in todo}
        done, pending = wait(futs, timeout=max(0.5, max_wait_s))
        for f in done:
            s = futs[f]
            try:
                txt = (f.result() or "").strip()
                bundle.by_source[s] = txt
                if txt:
                    _cache_put(f"{s}\x1f{query}", txt)
                else:
                    bundle.failures.append(f"{s}:empty")
            except Exception as e:
                bundle.failures.append(f"{s}:{type(e).__name__}")
        for f in pending:
            bundle.failures.append(f"{futs[f]}:timeout")
            f.cancel()
        pool.shutdown(wait=False, cancel_futures=True)   # 느린 소스가 턴을 붙잡지 못하게 한다
    bundle.elapsed_ms = int((time.time() - t0) * 1000)
    if bundle.failures:
        logger.warning("[GROUNDING] degraded failures=%s query=%r elapsed=%dms", bundle.failures, query[:60], bundle.elapsed_ms)
    return bundle
