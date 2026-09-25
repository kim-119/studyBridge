"""
OpenAlex — 라이브 멀티에이전트 SSE 전용 "optional enrichment" 도구.

설계 의도:
  - OpenAlex는 박사/전문가 수준에서 보조 근거를 가져오는 도구일 뿐,
    라이브 SSE 답변을 막는 blocking dependency가 아니다.
  - 실패(timeout/network/429/5xx/parse/empty)해도 답변 생성은 계속되고,
    실패 사실은 metadata(toolsFailed / openalex.status)에 정직하게 남긴다.
  - 결과를 실제로 받지 못하면 "논문으로 확인했다"는 식의 근거를 만들지 않는다.

책임 분리:
  - 설정(_LiveConfig / _ReportConfig)  : timeout / per_page / select / cache_ttl
  - OpenAlexCache                       : Redis(sync) → process memory TTL fallback
  - _OpenAlexClient.search              : 단일 list 호출 + 방어적 파싱
  - enrich()                            : 사용 조건 판단 → 캐시 → 호출 → outcome/status 조립

기존 openalex_service.py(비스트리밍/보고서 경로)는 건드리지 않는다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 라이브에서 가져올 최소 필드(응답 크기 최소화). abstract_inverted_index 등 대형 필드 제외.
_DEFAULT_LIVE_SELECT = "id,doi,display_name,publication_year,cited_by_count"
# 보고서 경로는 넉넉히 허용(저자/위치/오픈액세스 추가).
_DEFAULT_REPORT_SELECT = "id,doi,display_name,publication_year,cited_by_count,authorships,primary_location,open_access"

# 연구/근거/학술 성격 질문 신호(한국어+영어). 환경변수로 확장 가능.
_DEFAULT_RESEARCH_HINTS = (
    "최근 연구", "연구 흐름", "연구 동향", "동향", "최신 동향", "선행연구", "선행 연구",
    "논문", "근거", "학술", "쟁점", "한계", "반례", "비교", "메타분석", "메타 분석",
    "체계적 문헌", "실증", "인용", "사례 연구",
    "citation", "state of the art", "state-of-the-art", "research trend", "empirical",
    "systematic review", "meta-analysis", "literature", "prior work", "recent advances",
    "research", "evidence", "study", "studies", "recent", "survey", "benchmark",
)

_TOKEN_RE = re.compile(r"[a-z0-9]+|[가-힣]{2,}")
# cache key 정규화에서 버릴 흔한 한국어 조사/어미성 토큰(과도한 NLP 없이 단순 처리)
_KEY_STOPWORDS = {
    "에서", "그리고", "하지만", "그러나", "대해", "대한", "관련", "설명", "알려줘",
    "무엇", "뭐야", "어떻게", "최근", "요즘", "the", "and", "for", "with", "what",
    "explain", "about", "please", "tell",
}


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# ── 설정 ──────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class OpenAlexProfile:
    name: str
    timeout: float
    per_page: int
    select: str


def live_profile() -> OpenAlexProfile:
    return OpenAlexProfile(
        name="live",
        timeout=_f("OPENALEX_LIVE_TIMEOUT_SECONDS", 2.5),
        per_page=max(1, min(_i("OPENALEX_LIVE_PER_PAGE", 5), 10)),  # 라이브는 10 초과 금지
        select=os.getenv("OPENALEX_LIVE_SELECT", _DEFAULT_LIVE_SELECT),
    )


def report_profile() -> OpenAlexProfile:
    return OpenAlexProfile(
        name="report",
        timeout=_f("OPENALEX_REPORT_TIMEOUT_SECONDS", 7.0),
        per_page=max(1, min(_i("OPENALEX_REPORT_PER_PAGE", 10), 25)),
        select=os.getenv("OPENALEX_REPORT_SELECT", _DEFAULT_REPORT_SELECT),
    )


def is_enabled() -> bool:
    return os.getenv("OPENALEX_ENABLED", "false").strip().lower() == "true"


def _base_url() -> str:
    return os.getenv("OPENALEX_BASE_URL", "https://api.openalex.org")


def _min_date() -> str:
    return os.getenv("OPENALEX_MIN_PUBLICATION_DATE", "2020-01-01")


def _sort() -> str:
    return os.getenv("OPENALEX_SORT", "cited_by_count:desc")


def _api_key() -> Optional[str]:
    key = os.getenv("OPENALEX_API_KEY", "").strip()
    return key or None


def _cache_ttl() -> int:
    # 최소 24h, 기본 7일
    return max(86400, _i("OPENALEX_CACHE_TTL_SECONDS", 604800))


def _research_hints() -> tuple:
    extra = os.getenv("OPENALEX_RESEARCH_KEYWORDS", "")
    extras = tuple(h.strip().lower() for h in extra.split(",") if h.strip())
    return _DEFAULT_RESEARCH_HINTS + extras


# ── 사용 조건 판단 ────────────────────────────────────────────────────────────
def is_research_question(question: str) -> bool:
    """연구/논문/근거/학술 쟁점/최신 동향 성격이면 True. 단순 개념 설명이면 False."""
    q = (question or "").strip().lower()
    if not q:
        return False
    return any(h in q for h in _research_hints())


# ── cache key ─────────────────────────────────────────────────────────────────
def _keywords(question: str) -> List[str]:
    """질문에서 핵심 키워드 토큰만 추출(조사/흔한 단어 제거, 순서 유지, 중복 제거)."""
    q = (question or "").lower()
    seen: List[str] = []
    for t in _TOKEN_RE.findall(q):
        if len(t) >= 2 and t not in _KEY_STOPWORDS and t not in seen:
            seen.append(t)
    return seen


def search_terms(question: str) -> str:
    """
    OpenAlex 검색에 넘길 정제 질의. 원문 한국어 문장을 그대로 보내면 결과가 거의 없어
    핵심 키워드만 공백으로 연결한다(복잡한 NLP 미도입, 기존 토큰 로직 재사용).
    """
    return " ".join(_keywords(question)[:8])


def cache_key(question: str) -> str:
    """
    질문 원문을 그대로 쓰지 않고 핵심 키워드 기반으로 정규화한다.
    정렬로 어순 변형을 흡수한다.
    예: 'OOP에서 상속 vs composition 최근 연구' -> openalex:v1:composition|oop|상속|연구
    """
    return "openalex:v1:" + "|".join(sorted(_keywords(question))[:8])


# ── 캐시 (Redis sync → process memory TTL) ────────────────────────────────────
class OpenAlexCache:
    """동기 컨텍스트(스레드) 안전 캐시. Redis 실패 시 프로세스 메모리 TTL로 자동 강등."""

    def __init__(self) -> None:
        self._mem: Dict[str, tuple] = {}   # key -> (expire_ts, value)
        self._redis: Any = None
        self._redis_tried = False

    def _get_redis(self):
        if self._redis_tried:
            return self._redis
        self._redis_tried = True
        try:
            from app.core.config import REDIS_URL
            if not REDIS_URL:
                return None
            import redis  # 기존 의존성(redis.asyncio와 동일 패키지의 sync 클라이언트)
            client = redis.from_url(
                REDIS_URL, decode_responses=True,
                socket_connect_timeout=2, socket_timeout=2,
            )
            client.ping()
            self._redis = client
            logger.info("[openalex] Redis 캐시 사용")
        except Exception as e:  # noqa: BLE001
            logger.info("[openalex] Redis 사용 불가 → 메모리 캐시 (%s)", type(e).__name__)
            self._redis = None
        return self._redis

    def get(self, key: str) -> Optional[List[Dict[str, Any]]]:
        r = self._get_redis()
        if r is not None:
            try:
                raw = r.get(key)
                if raw:
                    return json.loads(raw)
            except Exception as e:  # noqa: BLE001
                logger.info("[openalex] Redis get 실패 → 메모리 (%s)", type(e).__name__)
        item = self._mem.get(key)
        if item and item[0] > time.time():
            return item[1]
        if item:
            self._mem.pop(key, None)
        return None

    def set(self, key: str, value: List[Dict[str, Any]], ttl: int) -> None:
        # 메모리는 항상 기록(레디스 실패 대비)
        self._mem[key] = (time.time() + ttl, value)
        r = self._get_redis()
        if r is not None:
            try:
                r.setex(key, ttl, json.dumps(value, ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                logger.info("[openalex] Redis set 실패 (메모리만 유지): %s", type(e).__name__)


_cache = OpenAlexCache()


# ── OpenAlex 클라이언트 (단일 list 호출 + 방어적 파싱) ─────────────────────────
class _OpenAlexClient:
    def search(self, query: str, profile: OpenAlexProfile) -> List[Dict[str, Any]]:
        """
        works list 1회 호출. query는 정제된 키워드 질의(search_terms 결과).
        select로 최소 필드만 받고, schema가 바뀌어도 죽지 않게 방어적으로 파싱한다.
        예외는 호출자가 분류하도록 그대로 올린다(타입만 보존).
        """
        import httpx

        params = {
            "search": (query or "")[:200],
            "filter": f"from_publication_date:{_min_date()}",
            "per_page": profile.per_page,
            "sort": _sort(),
            "select": profile.select,
        }
        key = _api_key()
        if key:
            params["api_key"] = key

        with httpx.Client(timeout=profile.timeout) as client:
            resp = client.get(f"{_base_url()}/works", params=params)
            resp.raise_for_status()
            data = resp.json()

        works: List[Dict[str, Any]] = []
        for item in (data.get("results") or []):
            if not isinstance(item, dict):
                continue
            works.append({
                "id": item.get("id"),
                "doi": item.get("doi"),  # null 가능 — 안전 처리
                "title": item.get("display_name") or "",
                "year": item.get("publication_year"),
                "citedByCount": item.get("cited_by_count"),
            })
        return works


_client = _OpenAlexClient()


# ── 결과 컨테이너 ─────────────────────────────────────────────────────────────
@dataclass
class OpenAlexOutcome:
    # outcome: used | cache | skipped | failed  (toolsUsed/Failed/Skipped 매핑 키)
    outcome: str
    sources: List[Dict[str, Any]] = field(default_factory=list)  # 근거 evidence (없으면 빈 리스트)
    status: Dict[str, Any] = field(default_factory=dict)         # metadata.openalex 블록


def _sources_from_works(works: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """works → evidence source dict. abstract가 없으므로 제목/연도/인용수만 힌트로."""
    out: List[Dict[str, Any]] = []
    for w in works:
        title = (w.get("title") or "").strip()
        if not title:
            continue
        year = w.get("year")
        cited = w.get("citedByCount")
        bits = [title]
        if year:
            bits.append(f"({year})")
        if isinstance(cited, int):
            bits.append(f"피인용 {cited}회")
        out.append({
            "title": title,
            "url": w.get("doi") or w.get("id") or "",
            "snippet": " ".join(bits),
            "source": "OpenAlex",
        })
    return out


# ── 진입점: enrich ────────────────────────────────────────────────────────────
def enrich(question: str, profile_name: str = "live") -> OpenAlexOutcome:
    """
    OpenAlex optional enrichment. 절대 예외를 밖으로 던지지 않는다(라이브 SSE 보호).
    호출 조건(연구성 질문)은 여기서 판단한다. 수준 게이팅(DOCTOR/EXPERT)은 호출자가 한다.
    """
    profile = report_profile() if profile_name == "report" else live_profile()
    base_status: Dict[str, Any] = {
        "enabled": is_enabled(),
        "needed": None,
        "cacheHit": False,
        "timeoutSeconds": profile.timeout,
        "perPage": profile.per_page,
        "select": profile.select.split(","),
        "resultCount": 0,
        "elapsedMs": 0,
        "status": "skipped",
    }

    if not is_enabled():
        base_status.update({"status": "disabled"})
        return OpenAlexOutcome("skipped", [], base_status)

    needed = is_research_question(question)
    base_status["needed"] = needed
    if not needed:
        base_status["status"] = "skipped"
        return OpenAlexOutcome("skipped", [], base_status)

    terms = search_terms(question)
    if not terms:
        base_status["status"] = "skipped"
        return OpenAlexOutcome("skipped", [], base_status)

    key = cache_key(question)
    try:
        cached = _cache.get(key)
    except Exception:  # noqa: BLE001  (캐시 장애가 답변을 막지 않게)
        cached = None
    if cached is not None:
        base_status.update({"cacheHit": True, "resultCount": len(cached), "status": "cache_hit"})
        return OpenAlexOutcome("cache", _sources_from_works(cached), base_status)

    t0 = time.time()
    try:
        works = _client.search(terms, profile)
    except Exception as e:  # noqa: BLE001  (timeout/network/4xx/5xx/parse 모두 흡수)
        elapsed = int((time.time() - t0) * 1000)
        status = _classify_error(e)
        base_status.update({"elapsedMs": elapsed, "status": status})
        logger.info("[openalex] enrich 실패 status=%s elapsedMs=%d err=%s",
                    status, elapsed, type(e).__name__)
        return OpenAlexOutcome("failed", [], base_status)

    elapsed = int((time.time() - t0) * 1000)
    base_status["elapsedMs"] = elapsed
    if not works:
        base_status.update({"resultCount": 0, "status": "empty"})
        return OpenAlexOutcome("failed", [], base_status)

    try:
        _cache.set(key, works, _cache_ttl())
    except Exception:  # noqa: BLE001
        pass
    base_status.update({"resultCount": len(works), "status": "ok"})
    logger.info("[openalex] enrich ok results=%d elapsedMs=%d", len(works), elapsed)
    return OpenAlexOutcome("used", _sources_from_works(works), base_status)


def _classify_error(e: Exception) -> str:
    """예외를 metadata용 짧은 status 문자열로 분류(원문/비밀값 미기록)."""
    name = type(e).__name__
    if "Timeout" in name:
        return "timeout"
    # httpx.HTTPStatusError → 상태코드 포함
    code = getattr(getattr(e, "response", None), "status_code", None)
    if code:
        return f"error_{code}"
    if "Connect" in name or "Network" in name or "Transport" in name:
        return "network_error"
    if "JSON" in name or "Decode" in name:
        return "parse_error"
    return "error"
