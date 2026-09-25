"""
한국어 토큰 겹침 판정 유틸(조사 때문에 정확히 일치하지 않는 어절 비교).

'토큰/토큰이고', 'key/key를' 처럼 조사·어미가 붙으면 정확 일치 비교가 실패한다.
형태소 분석기를 새로 들이지 않고 공통 접두 길이로 같은 어절인지 판단한다.
여러 모듈(소크라테스 정답 노출 검사, 상황극 사용자 답변 참조 검사)이 같은 규칙을 쓴다.
"""
from __future__ import annotations

import re
from typing import Iterable, Set

_TOKEN = re.compile(r"[가-힣A-Za-z0-9]{2,}")

# 어느 문장에나 나오는 기능어 — 겹침 근거로 쓰지 않는다.
DEFAULT_STOPWORDS = {
    "그리고", "하지만", "그러나", "그래서", "그러면", "때문", "경우", "이것", "그것", "저것",
    "무엇", "어떻게", "하는", "되는", "이다", "있다", "없다", "합니다", "습니다", "입니다",
    "생각", "정도", "부분", "라면", "인가", "일까", "될까", "한다",
}

MIN_PREFIX = 2


def tokens(text: str, stopwords: Set[str] = None) -> Set[str]:
    stop = DEFAULT_STOPWORDS if stopwords is None else stopwords
    return {t for t in _TOKEN.findall(text or "") if t not in stop}


def common_prefix_len(x: str, y: str) -> int:
    n = 0
    for cx, cy in zip(x, y):
        if cx != cy:
            break
        n += 1
    return n


def same_word(x: str, y: str) -> bool:
    """조사/어미 차이를 무시하고 같은 어절로 볼 수 있는가."""
    return x == y or common_prefix_len(x, y) >= MIN_PREFIX


def overlap_count(a: Iterable[str], b: Iterable[str]) -> int:
    b_list = list(b)
    hits = 0
    for x in a:
        if any(same_word(x, y) for y in b_list):
            hits += 1
    return hits


def subtract(a: Set[str], b: Set[str]) -> Set[str]:
    """a 에서 b 와 같은 어절을 제거한다(정확 일치가 아니라 어절 기준)."""
    b_list = list(b)
    return {x for x in a if not any(same_word(x, y) for y in b_list)}


def covered_ratio(needle: Set[str], haystack: Set[str]) -> float:
    """needle 어절 중 haystack 에 등장한 비율."""
    if not needle:
        return 0.0
    return overlap_count(needle, haystack) / len(needle)


def similar(a: str, b: str, threshold: float = 0.8) -> bool:
    """두 문장이 사실상 같은 말인지(반복 감지). 공백 정규화 후 시퀀스 유사도."""
    import difflib
    x = re.sub(r"\s+", " ", (a or "").strip())
    y = re.sub(r"\s+", " ", (b or "").strip())
    if not x or not y:
        return False
    return difflib.SequenceMatcher(None, x, y).ratio() >= threshold


def repeats_any(text: str, previous, threshold: float = 0.8) -> bool:
    return any(similar(text, p, threshold) for p in (previous or []))


_QUESTION_TAIL = re.compile(
    r"("
    r"\?|"
    r"까요|나요|ㄹ까|을까|를까|는가|인가|던가|"          # 의문형 어미
    r"세요|십시오|시오|해라|하라|보라|해봐|해 봐|보세요|" # 지시형(면접·발표 상황의 요구)
    r"습니까|십니까|겠습니까|나요|되나|하나|인가|는지|은지|ㄴ지"
    r")\s*[.!]?\s*$"
)


_INTERROGATIVE = re.compile(r"(무엇|뭐|어떻게|어떤|왜|언제|누가|누구|어디|어느|몇|얼마)")


def is_question_like(text: str) -> bool:
    """물음표가 없어도 질문/요구로 읽히는 한국어 문장인가.

    한국어 응답은 '설명해보라', '어떤 상황에서 사용되나'처럼 물음표 없이 끝나는 경우가 흔하다.
    어미 패턴 또는 의문사 포함 여부로 판단한다(도메인 단어는 보지 않는다).
    """
    t = (text or "").strip()
    if not t:
        return False
    return bool(_QUESTION_TAIL.search(t)) or bool(_INTERROGATIVE.search(t))
