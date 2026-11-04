"""외부 전송(egress) 중앙 정책 — 사용자 데이터가 ai07 밖(제3자 API)으로 나가는 모든 호출의 단일 관문.

배경(2026-11-04 감사): 운영 코드는 사용자 입력·PDF 본문·학습 메모·대화 기록을 OpenAI/Tavily/Wikipedia/OpenAlex
로 마스킹 없이(비전 제외) 보내고 있었다. 기능별 스위치(ENABLE_OPENAI_REFINER, VISION_EXTERNAL_LLM_ENABLED,
AI_LEARNING_LOOP_EXTERNAL_LLM_ENABLED …)가 흩어져 있었고 기본값도 제각각이었다. 이 모듈은 그 위에 놓이는
'기본 차단' 마스터 정책이다. 기존 기능별 스위치는 그대로 유지되며(AND 조건), 이 정책이 허용하지 않으면
기존 스위치가 켜져 있어도 외부 호출은 일어나지 않는다.

환경변수 (호출 시점에 읽는다 — 재시작 없이 테스트/운영 토글 가능):

  AI_EXTERNAL_EGRESS_ENABLED   마스터 스위치. 기본 false. false 면 AI_EGRESS_ALLOW 와 무관하게 전부 차단.
  AI_EGRESS_ALLOW              허용 목록. 쉼표 구분 "destination:feature" 항목.
                               예) "openai:vision_answer,wikipedia:keyword_define"
                               - destination: openai | tavily | wikipedia | openalex (와일드카드 불가)
                               - feature: [a-z0-9_]{1,64} 또는 "*"(그 destination 의 모든 기능)
                               - 형식이 틀린 항목(콜론 없음/알 수 없는 destination/빈 feature/허용되지 않는 문자,
                                 "*:..." 등)은 무시되고 경고 로그(값 자체가 아니라 '몇 번째 항목'만)를 남긴다.

  판정: egress_allowed(destination, feature) == master AND (destination:feature ∈ allow
                                                          OR destination:* ∈ allow)

  현재(정책 도입 전) 동작을 그대로 유지하려면:
      AI_EXTERNAL_EGRESS_ENABLED=true
      AI_EGRESS_ALLOW=openai:*,tavily:*,wikipedia:*,openalex:*
  (각 기능의 기존 스위치·API 키 조건은 여전히 적용된다.)

로그 정책: destination / feature / decision 만 남긴다. 프롬프트·질문·URL 쿼리·응답 본문·키는 절대 남기지 않는다.
차단 로그는 (destination, feature)별 60초에 1회로 제한한다. 누적 카운터는 snapshot() 으로 조회한다.

범위: 제3자 처리자(OpenAI/Tavily/Wikipedia/OpenAlex)로의 전송. 로컬 Ollama(127.0.0.1), 자기 자신(127.0.0.1:8000),
Redis/PostgreSQL, 그리고 서비스 자체 저장소인 S3(boto3 — 사용자 자료 원본을 '가져오는' 내부 인프라)는 대상이 아니다.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger("studybridge.egress")

DESTINATIONS: FrozenSet[str] = frozenset({"openai", "tavily", "wikipedia", "openalex"})
WILDCARD = "*"
UNSPECIFIED = "unspecified"   # feature 를 넘기지 않은 레거시 호출 — destination:* 일 때만 허용된다.

_FEATURE_RE = re.compile(r"^[a-z0-9_]{1,64}$")
_TRUE = {"1", "true", "yes", "on", "y"}
_BLOCK_LOG_INTERVAL_S = 60.0


class EgressBlocked(RuntimeError):
    """정책에 의해 외부 전송이 차단됨. RuntimeError 하위라 기존 `except RuntimeError/Exception` 경로로 흡수된다."""

    def __init__(self, destination: str, feature: str, reason: str = "policy") -> None:
        self.destination = destination
        self.feature = feature
        self.reason = reason
        super().__init__(f"external egress blocked: {destination}:{feature} ({reason})")


# ── 파싱 ─────────────────────────────────────────────────────────────────────
def parse_allowlist(spec: Optional[str]) -> Tuple[FrozenSet[Tuple[str, str]], List[int]]:
    """'dest:feat,...' → ({(dest, feat)}, [잘못된 항목의 1-based 위치]). 값 자체는 반환/로그하지 않는다."""
    allowed = set()
    rejected: List[int] = []
    for idx, raw in enumerate((spec or "").split(","), start=1):
        item = raw.strip().lower()
        if not item:
            continue
        dest, sep, feat = item.partition(":")
        dest, feat = dest.strip(), feat.strip()
        if (not sep or dest not in DESTINATIONS or not feat or ":" in feat
                or not (feat == WILDCARD or _FEATURE_RE.match(feat))):
            rejected.append(idx)
            continue
        allowed.add((dest, feat))
    return frozenset(allowed), rejected


_parse_cache: Dict[str, Tuple[FrozenSet[Tuple[str, str]], List[int]]] = {}
_parse_lock = threading.Lock()


def _allowlist() -> FrozenSet[Tuple[str, str]]:
    spec = os.getenv("AI_EGRESS_ALLOW") or ""
    with _parse_lock:
        hit = _parse_cache.get(spec)
        if hit is None:
            hit = parse_allowlist(spec)
            if len(_parse_cache) > 32:
                _parse_cache.clear()
            _parse_cache[spec] = hit
            if hit[1]:
                logger.warning("[EGRESS] AI_EGRESS_ALLOW 의 잘못된 항목 무시: positions=%s", hit[1])
    return hit[0]


def master_enabled() -> bool:
    return (os.getenv("AI_EXTERNAL_EGRESS_ENABLED") or "false").strip().lower() in _TRUE


# ── 판정 ─────────────────────────────────────────────────────────────────────
_counters: Dict[Tuple[str, str, str], int] = {}
_last_block_log: Dict[Tuple[str, str], float] = {}
_state_lock = threading.Lock()


def _norm_feature(feature: Optional[str]) -> str:
    f = (feature or "").strip().lower()
    return f if _FEATURE_RE.match(f) else UNSPECIFIED


def _decide(destination: str, feature: str) -> Tuple[bool, str]:
    if destination not in DESTINATIONS:
        return False, "unknown_destination"
    if not master_enabled():
        return False, "master_off"
    allow = _allowlist()
    if (destination, WILDCARD) in allow:
        return True, "allowlisted_wildcard"
    if feature != UNSPECIFIED and (destination, feature) in allow:
        return True, "allowlisted"
    return False, "not_allowlisted"


def _record(destination: str, feature: str, allowed: bool, reason: str) -> None:
    decision = "ALLOW" if allowed else "BLOCK"
    with _state_lock:
        key = (destination, feature, decision)
        _counters[key] = _counters.get(key, 0) + 1
        if allowed:
            should_log_info = False
        else:
            now = time.monotonic()
            last = _last_block_log.get((destination, feature), 0.0)
            should_log_info = (now - last) >= _BLOCK_LOG_INTERVAL_S
            if should_log_info:
                _last_block_log[(destination, feature)] = now
    if should_log_info:
        logger.info("[EGRESS] destination=%s feature=%s decision=%s reason=%s",
                    destination, feature, decision, reason)
    else:
        logger.debug("[EGRESS] destination=%s feature=%s decision=%s reason=%s",
                     destination, feature, decision, reason)


def egress_allowed(destination: str, feature: Optional[str]) -> bool:
    """외부 전송 허용 여부. 판정 중 예외는 차단으로 처리한다(fail-closed)."""
    dest = (destination or "").strip().lower()
    feat = _norm_feature(feature)
    try:
        allowed, reason = _decide(dest, feat)
    except Exception:  # noqa: BLE001 — 보안 장치는 fail-closed
        allowed, reason = False, "evaluation_error"
    _record(dest, feat, allowed, reason)
    return allowed


def would_allow(destination: str, feature: Optional[str]) -> bool:
    """판정만 미리 본다(카운터/로그 없음). 경로 선택·타임아웃 계산 같은 사전 조회용 — 실제 호출 직전엔 egress_allowed."""
    try:
        return _decide((destination or "").strip().lower(), _norm_feature(feature))[0]
    except Exception:  # noqa: BLE001
        return False


def require_egress(destination: str, feature: Optional[str]) -> None:
    """허용되지 않으면 EgressBlocked 를 던진다."""
    if not egress_allowed(destination, feature):
        raise EgressBlocked((destination or "").strip().lower(), _norm_feature(feature))


def snapshot() -> Dict[str, object]:
    """운영 확인용 상태(비밀값 없음): 마스터 스위치, 허용 항목, 잘못된 항목 위치, 누적 판정 카운터."""
    allow = sorted(f"{d}:{f}" for d, f in _allowlist())
    _, rejected = parse_allowlist(os.getenv("AI_EGRESS_ALLOW") or "")
    with _state_lock:
        counters = {f"{d}:{f}:{dec}": n for (d, f, dec), n in sorted(_counters.items())}
    return {"masterEnabled": master_enabled(), "allow": allow,
            "rejectedPositions": rejected, "decisions": counters}


def reset_counters_for_tests() -> None:
    with _state_lock:
        _counters.clear()
        _last_block_log.clear()
    with _parse_lock:
        _parse_cache.clear()
