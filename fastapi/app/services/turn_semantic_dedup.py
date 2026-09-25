"""turn 내부 '같은 에이전트의 의미 중복 답변' 탐지 (순수 Python, 외부 의존성 없음).

배경
----
기본/개념 모드 라이브 경로는 확률적 다중답변 플래너(_run_discussion_plan)를 탄다.
에이전트 1명일 때 플래너는 [DIRECT_ANSWER, WRAP] 를 만들고, WRAP 가 직전 정의를
표현만 바꿔 다시 말해(예: "SSH는 ... 암호화 프로토콜이다") 같은 교수가 의미상 같은
답변을 2개 렌더링하게 한다. 기존 dedup(agent_dedup.TurnDeduper + content fingerprint)
은 *바이트 동일*만 잡으므로, 패러프레이즈(다른 표현·같은 의미)는 통과해 버린다.

이 모듈은 fingerprint(정확 일치) 위에 얹는 **의미 근접 중복** 판정 계층이다.

한국어 형태소(조사/어미 부착) 때문에 공백 토큰 Jaccard 는 과소탐지한다
("암호화된" vs "암호화"가 다른 토큰). 그래서 **문자 n-gram(기본 trigram)** 기반
novelty(새로움) 비율로 판정한다:

  novelty(candidate, priors) = |candidate.ngrams - union(priors.ngrams)| / |candidate.ngrams|

  → candidate 의 n-gram 중 '이전에 한 번도 안 나온' 비율.
  → 낮을수록(=새로운 내용이 적을수록) 의미 중복.

실측 보정(SSH 케이스, 2026-06-23):
  - 정의 → 정의-재진술(WRAP)         novelty ≈ 0.60~0.68  → 중복(suppress)
  - 정의 → 보안 심화 / 명령어 예시   novelty ≈ 0.96~0.98  → 신규(keep)
  임계 0.78 이 둘을 안전한 마진으로 분리한다.

스코프 규칙(필수): 비교는 **같은 turn 안의 같은 화자(speaker)** 가 직전에 한 발화로만
한정한다. 다른 에이전트가 비슷한 말을 하는 건 토론이므로 막지 않는다. 사용자가 같은
질문을 새 turn 에 다시 해도(turn 이 바뀌면 prior 가 비므로) 막지 않는다.
"""
from __future__ import annotations

import os
import re
from typing import Iterable, List, Sequence, Set

_PUNCT = re.compile(r"[^\w가-힣]+", re.UNICODE)
_WS = re.compile(r"\s+")

# 문자 n-gram 크기. trigram 이 한국어 어절-부분일치(암호화된/암호화)를 잘 잡는다.
_NGRAM_N = 3


def _enabled() -> bool:
    """off/false/0 이면 의미 dedup 비활성(escape hatch). 기본 on."""
    val = os.getenv("TURN_SEMANTIC_DEDUP", "on").strip().lower()
    return val not in ("off", "false", "0", "no", "")


def _min_novelty() -> float:
    """이 값 미만이면 '새로운 내용 부족'으로 보고 중복 처리. env 로 조정 가능."""
    try:
        v = float(os.getenv("TURN_SEMANTIC_DEDUP_MIN_NOVELTY", "0.78"))
    except (TypeError, ValueError):
        v = 0.78
    return min(max(v, 0.0), 1.0)


def normalize_text(text) -> str:
    """소문자화 + 구두점/기호를 공백으로 + 공백 정규화."""
    s = str(text or "").strip().lower()
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


def char_ngrams(text, n: int = _NGRAM_N) -> Set[str]:
    """정규화 후 공백 제거한 문자열의 문자 n-gram 집합."""
    s = normalize_text(text).replace(" ", "")
    if not s:
        return set()
    if len(s) < n:
        return {s}
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def token_jaccard(a, b) -> float:
    """공백 토큰 Jaccard (보조 지표 / 호환용)."""
    sa = set(normalize_text(a).split())
    sb = set(normalize_text(b).split())
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def char_jaccard(a, b, n: int = _NGRAM_N) -> float:
    ga, gb = char_ngrams(a, n), char_ngrams(b, n)
    if not ga and not gb:
        return 1.0
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def novelty_ratio(candidate, priors: Sequence) -> float:
    """candidate 의 문자 n-gram 중 priors(union)에 없던 '새로운' 비율 [0,1].

    priors 가 비어 있으면 전부 새로움(1.0). candidate 가 비어 있으면 0.0.
    """
    gc = char_ngrams(candidate)
    if not gc:
        return 0.0
    prior_union: Set[str] = set()
    for p in priors or []:
        prior_union |= char_ngrams(p)
    if not prior_union:
        return 1.0
    return len(gc - prior_union) / len(gc)


def is_near_duplicate(
    candidate,
    priors: Sequence,
    *,
    min_novelty: float = None,
) -> bool:
    """candidate 가 같은 화자의 priors 와 의미상 거의 같은 재진술이면 True.

    판정: (1) 정규화 후 완전 동일, 또는 (2) novelty_ratio < min_novelty.
    비활성(env)·빈 candidate·priors 없음 이면 항상 False(=중복 아님, 통과).
    """
    if not _enabled():
        return False
    cand_norm = normalize_text(candidate)
    if not cand_norm:
        return False
    priors = [p for p in (priors or []) if normalize_text(p)]
    if not priors:
        return False
    for p in priors:
        if cand_norm == normalize_text(p):
            return True
    threshold = _min_novelty() if min_novelty is None else min_novelty
    return novelty_ratio(candidate, priors) < threshold
