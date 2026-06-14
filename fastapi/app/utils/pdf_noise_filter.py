"""
PDF 메타데이터 노이즈 필터 — 로드맵/플래너 학습 주제 오염 차단.

문제(재현):
  PDF의 날짜/연도/교수명/슬라이드 번호/강의자료 표지·header·footer가
  학습 개념으로 오인되어 아래 같은 말이 안 되는 학습 항목이 생성된다.
    - "2026.04 조수연 예외 처리 전략"
    - "Modern Android Development 2026 책임 분리 설계"
    - "조수연 비교 표"

이 모듈은 로드맵/플래너 생성 전·후에 공통으로 사용하는 도구를 제공한다.
  1. is_metadata_noise(line)            : 한 줄/토큰이 통째로 메타데이터인지
  2. detect_repeated_lines(texts/pages) : 여러 페이지에서 반복되는 header/footer 탐지
  3. clean_topic(text, repeated)        : 날짜/연도/교수명/표지문구만 제거하고 기술 용어는 보존
  4. is_valid_topic(text, repeated)     : 정제 후에도 학습 개념으로 의미가 있는지 검증
  5. filter_keywords(keywords, ...)     : 키워드 목록에서 노이즈 제거(+정제)
  6. conceptual_fallback_items(title)   : 내용 부족 시 자료 제목 기반 개념형 학습 항목 생성
  7. sanitize_text_fields(obj, ...)     : 로드맵/플래너 JSON 전체를 재귀 정제
  8. find_noise_violations(obj, ...)    : 최종 응답 직전 노이즈 잔존 검사(error code 판단용)

핵심 원칙(사용자 요구):
  - 날짜/연도/교수명/표지/footer/header 는 학습 주제로 승격 금지.
  - 기술 용어와 날짜/이름이 섞이면 날짜/이름만 제거하고 기술 용어는 살린다.
      "2026.04 조수연 Activity 생명주기" → "Activity 생명주기"
  - 내용 부족 시 메타데이터를 억지로 쓰지 말고 자료 제목 기반 개념형 항목을 만든다.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ── 노이즈 패턴 ───────────────────────────────────────────────────────────────
# 연도 단독: "2026", "2025"
_YEAR_ONLY = re.compile(r"^\s*20\d{2}\s*$")
# 연도 토큰(문장 내): \b2024~2099\b
_YEAR_TOKEN = re.compile(r"\b20\d{2}\b")
# 날짜형: 2026.04, 2026-04, 2026/04, 2026.04.03, 2026. 4. 3
_DATE_TOKEN = re.compile(r"\b20\d{2}\s*[.\-/]\s*\d{1,2}(?:\s*[.\-/]\s*\d{1,2})?\.?")
# 월/일만: 04.03, 4/3 (앞뒤가 숫자 식별자가 아닌 경우)
_MONTH_DAY = re.compile(r"(?<!\d)\d{1,2}\s*[./-]\s*\d{1,2}(?!\s*[./-]?\d)")
# 페이지/슬라이드 번호 단독: "12", "- 12 -", "03", "08"
_PAGE_ONLY = re.compile(r"^\s*[-–]?\s*\d{1,3}\s*[-–]?\s*$")
_PAGE_WORD = re.compile(r"^\s*(?:page|p|slide|쪽|페이지)\s*\.?\s*\d+\s*$", re.IGNORECASE)
_PAGE_FRACTION = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")  # "3 / 10"
# 슬라이드/챕터 번호 접두어: "08. View Model", "1) ...", "03 ViewModel"
_SLIDE_PREFIX = re.compile(r"^\s*\d{1,3}\s*[.)\-]\s*")
# 학사 메타 표지 키워드(이 단어가 줄의 핵심이면 메타데이터)
_COVER_WORDS = re.compile(
    r"(교수|강사|지도|담당|작성자|저자|발표자|학과|학부|대학|강의\s*자료|강의명|수업명|과목명|"
    r"제출일|발표일|작성일|날짜|일자|목차|차례|표지|copyright|all\s*rights\s*reserved)",
    re.IGNORECASE,
)
# 흔한 한국인 성씨(교수명/강사명 추정용). 보수적으로만 사용한다.
#  주의: "정규화"(정+규화), "조건문"(조+건문) 같은 기술 용어가 성씨로 시작할 수 있으므로
#  인명 제거는 (a) 날짜에 인접한 경우, (b) 여러 페이지 반복(author), (c) 표지 라벨 뒤에서만
#  수행한다. 단독 한글 토큰을 무조건 인명으로 보고 지우지 않는다(기술어 보호).
_KOREAN_SURNAMES = (
    "김이박최정강조윤장임한오서신권황안송전홍유고문양손배백허남심노하곽성차주우구민류"
    "나진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용"
)
# "조수연" 처럼 성+이름(2~3음절). 날짜 인접/반복/표지 문맥에서만 인명으로 취급한다.
_NAME_TOKEN = re.compile(rf"[{_KOREAN_SURNAMES}][가-힣]{{1,2}}")
# 날짜+인명 클러스터(보고된 핵심 케이스: "2026.04 조수연", "조수연 2026.04")
_DATE_STR = r"20\d{2}\s*[.\-/]\s*\d{1,2}(?:\s*[.\-/]\s*\d{1,2})?\.?"
_DATE_NAME = re.compile(
    rf"(?:{_DATE_STR})\s*[{_KOREAN_SURNAMES}][가-힣]{{1,2}}|"
    rf"[{_KOREAN_SURNAMES}][가-힣]{{1,2}}\s*(?:{_DATE_STR})"
)

# 정제 후 학습 개념으로 인정하기 위한 최소 글자 수(한글/영문)
_MIN_LETTERS = 2


def _letters(text: str) -> str:
    return "".join(re.findall(r"[가-힣A-Za-z]", text or ""))


def _norm_line(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


# ══════════════════════════════════════════════════════════════════════════════
# [1] 한 줄/토큰이 통째로 메타데이터 노이즈인지
# ══════════════════════════════════════════════════════════════════════════════
def is_metadata_noise(line: str, repeated: Optional[Iterable[str]] = None) -> bool:
    """이 줄/후보가 학습 주제로 쓰면 안 되는 순수 메타데이터인지 판정한다."""
    s = _norm_line(line)
    if not s:
        return True
    if _YEAR_ONLY.match(s) or _PAGE_ONLY.match(s) or _PAGE_WORD.match(s) or _PAGE_FRACTION.match(s):
        return True
    # 표지/교수/날짜 키워드가 들어 있고 기술 용어(영문 식별자 등)가 없으면 메타데이터
    if _COVER_WORDS.search(s) and not re.search(r"[A-Za-z]{2,}", s):
        return True
    # 날짜+인명/날짜 토큰을 제거한 뒤 남는 의미 글자가 거의 없으면 메타데이터
    #   ("2026.04 조수연" → "" → noise, "2026" → "" → noise)
    stripped = clean_topic(s, repeated=repeated)
    if len(_letters(stripped)) < _MIN_LETTERS:
        return True
    # 반복 header/footer
    if repeated:
        key = re.sub(r"\s+", "", s).lower()
        for r in repeated:
            if key and key == re.sub(r"\s+", "", r).lower():
                return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# [2] 반복 header/footer/표지 탐지
# ══════════════════════════════════════════════════════════════════════════════
def detect_repeated_lines(
    texts: Iterable[str],
    min_repeat: int = 2,
    max_len: int = 60,
) -> List[str]:
    """여러 page/source 에서 동일·유사하게 반복되는 짧은 줄을 metadata 후보로 모은다.

    texts: 페이지/소스별 원문 문자열 목록(또는 페이지 경계 없이 연결된 단일 문자열 목록).
    반복 등장하는 course title/표지/footer/author 가 학습 topic 후보에서 빠지도록 한다.

    페이지가 하나의 문자열로 연결되어 들어와도(페이지 경계 소실) 동작하도록,
    전체에서 동일 줄의 '총 등장 횟수'로 반복 여부를 판단한다. 본문 문장은 보통 그대로
    반복되지 않으므로 header/footer/표지만 걸러진다(max_len 로 짧은 줄에 한정).
    """
    counter: Counter = Counter()
    display: Dict[str, str] = {}
    for block in texts or []:
        for raw in str(block or "").split("\n"):
            s = _norm_line(raw)
            if not s or len(s) > max_len:
                continue
            if len(_letters(s)) < 2:
                continue
            key = re.sub(r"\s+", "", s).lower()
            counter[key] += 1
            display.setdefault(key, s)
    return [display[k] for k, c in counter.items() if c >= min_repeat]


# ══════════════════════════════════════════════════════════════════════════════
# [3] 날짜/연도/교수명/표지문구만 제거(기술 용어 보존)
# ══════════════════════════════════════════════════════════════════════════════
def _author_names(repeated: Optional[Iterable[str]]) -> List[str]:
    """반복 라인/표지 라인에서 실제로 등장한 author(교수/작성자) 이름만 추출한다.

    날짜 또는 표지 라벨이 함께 있는 반복 라인에서만 이름을 뽑으므로,
    '정규화' 같은 기술어가 이름으로 오인될 일이 없다.
    """
    names: set = set()
    for r in repeated or []:
        line = str(r or "")
        if re.search(_DATE_STR, line) or _COVER_WORDS.search(line):
            for m in _NAME_TOKEN.finditer(line):
                names.add(m.group(0))
    return list(names)


def clean_topic(text: str, repeated: Optional[Iterable[str]] = None) -> str:
    """후보 문자열에서 메타데이터(날짜/연도/슬라이드번호/교수명/반복문구)만 제거한다.

    기술 용어는 보존한다.
      "2026.04 조수연 Activity 생명주기" → "Activity 생명주기"
      "08. View Model"                  → "View Model"
    """
    s = _norm_line(text)
    if not s:
        return ""

    # 반복 header/footer/course title 부분 제거 (author 이름이 매 페이지 반복되는 경우도 포함)
    if repeated:
        for r in repeated:
            r = _norm_line(r)
            if r and r in s:
                s = s.replace(r, " ")
        # 반복/표지 라인에서 추출한 author 이름은 단독으로 등장해도 제거
        for nm in _author_names(repeated):
            s = re.sub(rf"(?<![가-힣]){re.escape(nm)}(?![가-힣])", " ", s)

    # 표지/교수/날짜 라벨 + 그 뒤 인명 제거 ("작성자: 조수연", "교수 조수연")
    s = re.sub(
        rf"(교수님?|강사님?|지도교수|담당교수|작성자|발표자|저자|담당)\s*[:：]?\s*"
        rf"(?:[{_KOREAN_SURNAMES}][가-힣]{{1,2}})?",
        " ",
        s,
    )
    # 날짜+인명 클러스터 제거 ("2026.04 조수연" → 통째 제거, 기술어는 보존)
    s = _DATE_NAME.sub(" ", s)
    # 날짜/연도 토큰 제거 (긴 패턴 먼저)
    s = _DATE_TOKEN.sub(" ", s)
    s = _MONTH_DAY.sub(" ", s)
    s = _YEAR_TOKEN.sub(" ", s)
    # 슬라이드/챕터 번호 접두어 제거
    s = _SLIDE_PREFIX.sub("", s)

    # 잔여 구두점/공백 정리
    s = re.sub(r"[·,;:\-–]{1,}", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" .·,-–")
    return s.strip()


# ══════════════════════════════════════════════════════════════════════════════
# [4] 정제 후 학습 개념으로 유효한지 검증
# ══════════════════════════════════════════════════════════════════════════════
def is_valid_topic(text: str, repeated: Optional[Iterable[str]] = None) -> bool:
    """정제 후에도 학습 개념/행동으로서 의미가 있는지 검증한다(스펙 [2])."""
    cleaned = clean_topic(text, repeated=repeated)
    letters = _letters(cleaned)
    if len(letters) < _MIN_LETTERS:
        return False
    # 숫자 비중이 과도하면 reject
    digits = len(re.findall(r"\d", cleaned))
    if digits and digits >= len(letters):
        return False
    return True


# ══════════════════════════════════════════════════════════════════════════════
# [5] 키워드 목록 노이즈 필터
# ══════════════════════════════════════════════════════════════════════════════
def filter_keywords(
    keywords: Iterable[str],
    repeated: Optional[Iterable[str]] = None,
    limit: Optional[int] = None,
) -> List[str]:
    """키워드 후보에서 날짜/연도/페이지/교수명/반복문구를 제거하고 정제한다.

    기술 용어에 날짜/이름이 붙어 있으면 정제해서 살린다.
    """
    out: List[str] = []
    seen = set()
    for kw in keywords or []:
        raw = str(kw or "").strip()
        if not raw:
            continue
        if is_metadata_noise(raw, repeated=repeated):
            continue
        cleaned = clean_topic(raw, repeated=repeated)
        if not is_valid_topic(cleaned, repeated=repeated):
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if limit and len(out) >= limit:
            break
    return out


# ══════════════════════════════════════════════════════════════════════════════
# [6] 내용 부족 시 자료 제목 기반 개념형 학습 항목
# ══════════════════════════════════════════════════════════════════════════════
# 흔한 주제에 대한 개념형 seed(스펙 [3] 예시). 없으면 일반 템플릿으로 생성한다.
_CONCEPT_SEEDS: Dict[str, List[str]] = {
    "안드로이드": [
        "안드로이드란 무엇인가",
        "안드로이드 앱의 기본 구조",
        "Activity의 역할",
        "Fragment의 역할과 사용 시점",
        "Activity와 Fragment의 차이",
        "ViewModel이 필요한 이유",
        "AndroidManifest.xml의 역할",
        "생명주기(Lifecycle) 이해",
    ],
    "android": [
        "안드로이드란 무엇인가",
        "안드로이드 앱의 기본 구조",
        "Activity의 역할",
        "Fragment의 역할과 사용 시점",
        "Activity와 Fragment의 차이",
        "ViewModel이 필요한 이유",
    ],
}

# 제목에서 떼어낼 군더더기(주제 핵심만 남긴다)
_TITLE_TRIM = re.compile(
    r"(이해하기|이해|정리하기|정리|학습하기|학습|개론|입문|기초|기본|개요|소개|강의|수업|자료|특강|과정|튜토리얼)\s*$"
)


def _base_concept(title: str) -> str:
    """자료 제목에서 메타데이터를 걷어내고 핵심 주제어만 남긴다."""
    base = clean_topic(title or "")
    base = re.sub(r"\s*\(.*?\)\s*", " ", base).strip()
    prev = None
    while base and base != prev:
        prev = base
        base = _TITLE_TRIM.sub("", base).strip()
    return base or (clean_topic(title or "") or "학습 주제")


def conceptual_fallback_items(title: str, count: int = 6) -> List[str]:
    """자료 제목/상위 주제 기반 개념형 학습 항목을 생성한다(스펙 [3]).

    메타데이터(날짜/연도/교수명)를 절대 사용하지 않는다.
    """
    concept = _base_concept(title)
    # seed 매칭(부분 일치)
    low = concept.lower()
    for key, seeds in _CONCEPT_SEEDS.items():
        if key in low or key in concept:
            return seeds[:count] if count else list(seeds)
    # 일반 개념형 템플릿
    templates = [
        f"{concept}란 무엇인가",
        f"{concept}의 기본 구조와 구성 요소",
        f"{concept}의 핵심 개념 정리",
        f"{concept}의 동작 원리 이해",
        f"{concept} 활용 사례와 적용 방법",
        f"{concept} 관련 개념 비교 정리",
        f"{concept} 학습 내용 점검과 복습",
    ]
    return templates[:count] if count else templates


def conceptual_fallback_tasks(title: str, n: int = 3) -> List[str]:
    """주차/일자 task 가 비었을 때 채울 개념형 할 일."""
    items = conceptual_fallback_items(title, count=max(n, 3))
    return [f"{it} 정리하기" if not it.endswith(("하기", "정리", "이해")) else it for it in items[:n]]


# ══════════════════════════════════════════════════════════════════════════════
# [7] JSON 전체 재귀 정제
# ══════════════════════════════════════════════════════════════════════════════
# 정제 대상 문자열 필드(학습 topic/task 류). 설명형 문장 필드는 토큰 단위로만 정제.
_TOPIC_FIELDS = {
    "title", "weektitle", "tasks", "task", "keyconcepts", "keywords", "keyword",
    "todo", "todos", "checklist", "outputs", "deliverable", "reviewquestions",
    "schedule", "nextactions", "studyorder", "concepts", "unfinisheditems",
    "nextrecommendations", "taskbreakdown", "expandedtodos", "studyquestions",
    "todaycheckpoints", "coreconcepts", "coretopics", "reviewquestions",
    "daytitles",
}


def _scrub_string(value: str, repeated: Optional[Iterable[str]]) -> Optional[str]:
    """topic 류 문자열을 정제한다. 메타데이터만 남으면 None(드롭)."""
    if is_metadata_noise(value, repeated=repeated):
        return None
    cleaned = clean_topic(value, repeated=repeated)
    if not is_valid_topic(cleaned, repeated=repeated):
        return None
    return cleaned


def _scrub_sentence(value: str, repeated: Optional[Iterable[str]]) -> str:
    """설명형 문장에서 날짜+인명 클러스터/날짜/연도 토큰과 반복 표지문구만 제거.

    문장 자체(기술어 포함)는 유지한다. 단독 한글 토큰을 인명으로 보고 지우지 않는다.
    """
    if repeated:
        for r in repeated:
            r = _norm_line(r)
            if r and len(r) >= 4 and r in value:
                value = value.replace(r, " ")
    s = _DATE_NAME.sub(" ", value)
    s = _DATE_TOKEN.sub(" ", s)
    s = _YEAR_TOKEN.sub(" ", s)
    return re.sub(r"\s{2,}", " ", s).strip(" .·,-–") or value


def sanitize_text_fields(
    obj: Any,
    repeated: Optional[Iterable[str]] = None,
    title: str = "",
    _field: str = "",
) -> Any:
    """로드맵/플래너 JSON 을 재귀 정제한다(스펙 [5]).

    - topic 류 list: 항목별로 메타데이터 제거, 유효하지 않으면 드롭.
      list 가 비면 개념형 fallback 으로 채운다.
    - topic 류 str: 정제(메타데이터만이면 개념형 1개로 대체).
    - 그 외 설명 문장: 날짜/인명 토큰만 제거.
    """
    field = _field.lower().replace("_", "")
    if isinstance(obj, dict):
        return {
            k: sanitize_text_fields(v, repeated=repeated, title=title, _field=str(k))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        if field in _TOPIC_FIELDS:
            cleaned: List[Any] = []
            for item in obj:
                if isinstance(item, str):
                    sc = _scrub_string(item, repeated)
                    if sc:
                        cleaned.append(sc)
                else:
                    cleaned.append(sanitize_text_fields(item, repeated=repeated, title=title, _field=_field))
            if not cleaned and all(isinstance(i, str) for i in obj):
                # 전부 메타데이터로 드롭됨 → 개념형 fallback
                cleaned = conceptual_fallback_tasks(title, n=max(len(obj), 3))
            return cleaned
        return [sanitize_text_fields(v, repeated=repeated, title=title, _field=_field) for v in obj]
    if isinstance(obj, str):
        if field in _TOPIC_FIELDS:
            sc = _scrub_string(obj, repeated)
            if sc:
                return sc
            # topic 단일 문자열이 메타데이터뿐 → 개념형 1개로 대체
            return conceptual_fallback_items(title, count=1)[0]
        # 설명형 문장: 토큰 단위 정제
        return _scrub_sentence(obj, repeated)
    return obj


# ══════════════════════════════════════════════════════════════════════════════
# [8] 최종 응답 직전 노이즈 잔존 검사
# ══════════════════════════════════════════════════════════════════════════════
# 절대 단독으로 등장하면 안 되는 reject 패턴(스펙 [5])
_REJECT_PATTERNS = [
    _DATE_TOKEN,                                   # 2026.04, 2026-04
    re.compile(r"^\s*20\d{2}\s*$"),                # 연도 단독
]


def find_noise_violations(
    obj: Any,
    repeated: Optional[Iterable[str]] = None,
    _field: str = "",
) -> List[str]:
    """정제 후에도 topic/task 류 필드에 메타데이터가 남아 있으면 위반 목록을 반환한다."""
    violations: List[str] = []
    field = _field.lower().replace("_", "")
    if isinstance(obj, dict):
        for k, v in obj.items():
            violations.extend(find_noise_violations(v, repeated=repeated, _field=str(k)))
    elif isinstance(obj, list):
        for v in obj:
            violations.extend(find_noise_violations(v, repeated=repeated, _field=_field))
    elif isinstance(obj, str) and field in _TOPIC_FIELDS:
        if is_metadata_noise(obj, repeated=repeated):
            violations.append(obj)
        elif any(p.search(obj) for p in _REJECT_PATTERNS):
            # topic 류에 날짜/연도 토큰이 남아 있음
            violations.append(obj)
    return violations
