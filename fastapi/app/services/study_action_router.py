"""
StudyBridge AI 내부 Action Router (MCP "처럼" — 실제 MCP 서버가 아니라 서버 내부 tool router).

자료보관함("문서 이해 AI")과 공부 플래너("학습 실행 관리 AI")를 분리해서
구조가 강제된 학습 계획을 생성한다.

핵심 보장(테스트 성공 기준):
  - 플래너 주간 확장: daily_plans 정확히 7개 (1일차~7일차)
  - 12주 로드맵: weeks 12개 × days 7개 = total_days 84개
  - 각 day.tasks >= AI_TASKS_PER_DAY_MIN(기본 3)
  - 각 day.review_questions >= 2

설계:
  1차 구조화/초안 = Ollama(call_primary_llm),
  품질 보정/심화 = OpenAI(call_verifier_llm, OpenAI 장애 시 Ollama fallback).
  LLM 출력은 "deterministic skeleton" 위에 overlay 한다 → LLM이 흔들려도 구조는 절대 깨지지 않는다.

모델명/temperature/max_tokens/provider 사용 여부는 전부 .env로 제어한다(하드코딩 금지).
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# PDF 메타데이터(날짜/연도/교수명/표지/footer)를 학습 주제로 쓰지 못하게 하는 LLM 규칙
_NOISE_RULES = (
    "PDF의 날짜·연도(예: 2026)·교수명/강사명/작성자·강의자료 표지/footer/header·슬라이드 번호는 "
    "학습 주제로 절대 사용하지 마라. '2026.04 조수연' 같은 날짜+이름 문구를 출력에 포함하지 마라. "
    "반복되는 강의명은 자료명으로만 참고하고, 학습 항목은 개념·구조·원리·구현·비교·적용·테스트 단위로 작성하라."
)


# ─────────────────────────────────────────────────────────────────────────────
# 환경변수 기반 설정 (하드코딩 금지)
# ─────────────────────────────────────────────────────────────────────────────
def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).strip().lower() in ("1", "true", "yes", "on")


def cfg() -> Dict[str, Any]:
    """매 호출 시 .env를 다시 읽어 런타임 변경을 반영한다."""
    return {
        "primary_provider": os.getenv("AI_PRIMARY_PROVIDER", "ollama"),
        "refiner_provider": os.getenv("AI_REFINER_PROVIDER", "openai"),
        "weeks": _env_int("AI_ROADMAP_WEEKS", 12),
        "days_per_week": _env_int("AI_DAYS_PER_WEEK", 7),
        "tasks_per_day_min": _env_int("AI_TASKS_PER_DAY_MIN", 3),
        "temperature": _env_float("AI_TEMPERATURE", 0.35),
        "max_tokens": _env_int("AI_MAX_TOKENS", 8192),
        "enable_openai_refiner": _env_bool("ENABLE_OPENAI_REFINER", True),
        "enable_ollama_fallback": _env_bool("ENABLE_OLLAMA_FALLBACK", True),
    }


# ─────────────────────────────────────────────────────────────────────────────
# LLM 호출 (provider 추상화)
# ─────────────────────────────────────────────────────────────────────────────
def primary_llm(system: str, user: str, max_tokens: Optional[int] = None) -> str:
    """1차 구조화/초안 — Ollama 우선(call_primary_llm 내부에서 Ollama→OpenAI)."""
    c = cfg()
    from app.services.llm_engine_router import call_primary_llm
    try:
        out = call_primary_llm(
            system_prompt=system,
            user_prompt=user,
            max_tokens=max_tokens or c["max_tokens"],
            temperature=c["temperature"],
        )
        return out or ""
    except Exception as e:  # noqa: BLE001
        logger.warning("primary_llm 예외: %s", e)
        return ""


def refiner_llm(system: str, user: str, max_tokens: Optional[int] = None) -> str:
    """품질 보정/심화 — OpenAI 우선, 장애 시 Ollama fallback."""
    c = cfg()
    if not c["enable_openai_refiner"]:
        return primary_llm(system, user, max_tokens)
    from app.services.llm_engine_router import call_verifier_llm
    try:
        out = call_verifier_llm(system_prompt=system, user_prompt=user, max_tokens=max_tokens or c["max_tokens"])
        if out and not out.strip().startswith(("[GPT", "[Ollama", "[")):
            return out
    except Exception as e:  # noqa: BLE001
        logger.warning("refiner_llm 예외: %s", e)
    if c["enable_ollama_fallback"]:
        return primary_llm(system, user, max_tokens)
    return ""


def _llm_failed(raw: str) -> bool:
    return (not raw) or raw.strip().startswith(("[GPT", "[Ollama", "["))


def _parse_json(raw: str) -> Optional[Any]:
    if _llm_failed(raw):
        return None
    try:
        from app.utils.json_parser import extract_json
        return extract_json(raw)
    except Exception:  # noqa: BLE001
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 입력 정규화 유틸
# ─────────────────────────────────────────────────────────────────────────────
def listify(v: Any) -> List[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [s.strip() for s in v.replace("\n", ",").split(",") if s.strip()]
    return []


_STOP_KEYWORDS = {"page", "수정", "추가", "삭제", "변경", "내용", "다음", "기타", "관련", "참고",
                  "슬라이드", "slide", "목차", "그림", "표", "예시", ""}

# 문서 노이즈 토큰(페이지 태그/날짜/순수 숫자/저자명 흔적) 제거용
_PAGE_TAG = re.compile(r"[\[(]?\s*(page|p|slide|페이지|쪽|슬라이드)\.?\s*\d+\s*[\])]?", re.IGNORECASE)
_BRACKET_PAGE = re.compile(r"[\[(][^\])]*\d+[^\])]*[\])]")  # [Page 1], (3쪽) 등
_DATE_LIKE = re.compile(r"^\d{4}[.\-/]\d{1,2}([.\-/]\d{1,2})?$")  # 2026.04 / 2026-04-12


def _strip_doc_noise(token: str) -> str:
    """키워드에서 페이지 태그/날짜 조각을 제거해 실제 개념만 남긴다."""
    t = _BRACKET_PAGE.sub(" ", token)
    t = _PAGE_TAG.sub(" ", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" -·,/")
    return t


def clean_keywords(kw: Any, repeated: Any = None) -> List[str]:
    """'Page', 날짜, '[Page 1]' 같은 문서 노이즈 제거, 개념 단위만 남긴다(스펙 F).

    추가로 PDF 메타데이터(날짜+교수명/연도/반복 표지)도 학습 개념에서 제외한다.
    'Activity 생명주기'처럼 기술 용어에 날짜/이름이 섞이면 날짜/이름만 제거하고 살린다.
    """
    from app.utils.pdf_noise_filter import clean_topic, is_metadata_noise
    out: List[str] = []
    for k in listify(kw):
        norm = _strip_doc_noise(k.strip())
        if not norm or norm.lower() in _STOP_KEYWORDS:
            continue
        if len(norm) <= 1:
            continue
        if _DATE_LIKE.match(norm) or re.fullmatch(r"\d+", norm):
            continue
        # 한글/영문/숫자가 하나도 없는 순수 기호 제거
        if not re.search(r"[가-힣A-Za-z0-9]", norm):
            continue
        # PDF 메타데이터(날짜/연도/교수명/표지/footer) 제외 + 정제(기술 용어 보존)
        if is_metadata_noise(norm, repeated=repeated):
            continue
        norm = clean_topic(norm, repeated=repeated) or norm
        if norm and norm not in out:
            out.append(norm)
    return out


# ── 난이도(level) 정책: beginner / intermediate / advanced (스펙 E) ───────────
_LEVEL_NORMALIZE = {
    "beginner": "beginner", "입문": "beginner", "초급": "beginner", "초급자": "beginner",
    "기초": "beginner", "쉬움": "beginner", "easy": "beginner", "하": "beginner",
    "intermediate": "intermediate", "중급": "intermediate", "중급자": "intermediate", "학사": "intermediate",
    "보통": "intermediate", "normal": "intermediate", "medium": "intermediate", "중": "intermediate",
    "advanced": "advanced", "고급": "advanced", "상급": "advanced", "상급자": "advanced", "석사": "advanced",
    "박사": "advanced", "전문가": "advanced", "어려움": "advanced", "hard": "advanced", "상": "advanced",
}


def level_is_recognized(level: Any) -> bool:
    """입력 난이도 값이 허용 목록에 매핑되는지 여부(스펙 B: 미허용 값 경고용)."""
    s = str(level or "").strip()
    if not s:
        return True  # 미입력은 기본값 보정이며 경고 대상이 아님
    return s.lower() in _LEVEL_NORMALIZE or s in _LEVEL_NORMALIZE


def normalize_level(level: Any) -> str:
    s = str(level or "").strip()
    return _LEVEL_NORMALIZE.get(s.lower(), _LEVEL_NORMALIZE.get(s, "intermediate"))


# 레벨별 일일 학습 초점(스펙 E·F: "기초 개념 이해"만 반복 금지)
_DAY_FOCUS_BY_LEVEL = {
    "beginner": [
        "용어와 정의 정리", "기본 역할 이해", "환경 설정 따라하기", "기본 흐름 따라하기",
        "예제 그대로 실행", "헷갈리는 용어 비교", "오늘 배운 내용 복습",
    ],
    "intermediate": [
        "동작 원리 분석", "코드 흐름 추적", "구조 비교와 선택", "오류 원인 추론",
        "간단한 리팩토링", "실제 프로젝트 적용", "응용 문제와 복습",
    ],
    "advanced": [
        "아키텍처 설계 판단", "책임 분리 설계", "예외 처리 전략", "테스트 가능성 확보",
        "상태 관리와 동시성", "성능과 유지보수 고려", "설계 회고와 트레이드오프 정리",
    ],
}

# 레벨별 task 템플릿: (title, description, difficulty, minutes)
_TASK_TEMPLATES_BY_LEVEL = {
    "beginner": [
        ("{concept} 용어 정의 정리", "{concept}의 정의와 기본 역할을 문서에서 찾아 본인 말로 한 문단 정리한다.", "easy", 25),
        ("{concept} 기본 흐름 따라하기", "문서에 나온 {concept}의 기본 동작 순서를 그대로 따라가며 단계별로 적는다.", "easy", 30),
        ("{concept} 예제 실행", "{concept} 관련 가장 단순한 예제를 그대로 실행하고 결과를 확인한다.", "normal", 30),
        ("{concept} 핵심 용어 5개 암기", "{subject}에서 {concept}과 함께 나오는 핵심 용어 5개를 카드로 만들어 외운다.", "easy", 20),
        ("오늘 학습 3문장 요약", "오늘 배운 {concept} 내용을 초보자도 이해하게 3문장으로 요약한다.", "easy", 15),
    ],
    "intermediate": [
        ("{concept} 동작 원리 분석", "{concept}이(가) 내부적으로 어떻게 동작하는지 입력·처리·출력 흐름으로 분석해 정리한다.", "normal", 40),
        ("{concept} 코드 흐름 추적", "{subject}의 {concept} 관련 코드 흐름을 따라가며 호출 순서와 데이터 변화를 메모한다.", "normal", 40),
        ("{concept} 구조 비교", "{concept}을(를) 대체 가능한 방식과 비교해 장단점과 선택 기준을 표로 정리한다.", "normal", 35),
        ("{concept} 오류 원인 추론", "{concept} 사용 시 발생하기 쉬운 오류 상황 1가지를 정하고 원인과 해결 가설을 적는다.", "hard", 40),
        ("{concept} 간단 리팩토링", "{concept}을(를) 쓰는 예제 코드를 더 읽기 쉽게 한 부분 리팩토링하고 이유를 적는다.", "hard", 45),
    ],
    "advanced": [
        ("{concept} 책임 분리 설계", "{concept}을(를) 중심으로 ViewModel/Repository/UseCase 등 계층 책임을 어떻게 나눌지 설계하고 근거를 적는다. (문서 기반 확장 학습)", "hard", 50),
        ("{concept} 예외 처리 전략", "{concept}에서 발생 가능한 예외를 분류하고 계층별 예외 처리·전파 전략을 설계한다. (문서 기반 확장 학습)", "hard", 45),
        ("{concept} 테스트 가능성 확보", "{concept} 로직을 단위 테스트하기 쉽게 의존성을 분리하고 테스트 케이스 3개를 설계한다.", "hard", 50),
        ("{concept} 성능·유지보수 점검", "{subject}에서 {concept}의 성능 병목과 유지보수 위험을 찾아 개선안을 제시한다. (문서 기반 확장 학습)", "hard", 45),
        ("{concept} 설계 판단 회고", "{concept} 도입의 트레이드오프(복잡도 대비 이점)를 평가하고 대안과 비교해 결론을 적는다.", "hard", 40),
    ],
}

_LEVEL_POLICY_TEXT = {
    "beginner": "기본 개념 이해·용어 정리·환경 설정·따라하기 실습 중심(문서 직접 내용 위주, 설계/테스트 최소화)",
    "intermediate": "문서 기반 + 응용(코드 흐름 분석·구조 비교·오류 원인 추론·간단한 리팩토링·실제 적용)",
    "advanced": "문서 기반 + 고급 확장(아키텍처 설계 판단·책임 분리·테스트 가능성·예외 처리·상태 관리·유지보수·성능). 문서 밖 고급 내용은 '문서 기반 확장 학습'으로 표시",
}


def _int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic skeleton — 구조를 절대 깨지지 않게 보장하는 백본
# ─────────────────────────────────────────────────────────────────────────────
_DIFFS = ["easy", "normal", "hard"]
_PHASE = [  # 1주차 기초 → 중반 적용/실습 → 후반 복습/프로젝트/시험
    "기초 개념 이해",
    "핵심 원리 정리",
    "구조와 흐름 파악",
    "실전 적용 연습",
    "심화 실습",
    "응용 문제 풀이",
    "프로젝트 적용",
    "통합 정리",
    "약점 보완",
    "모의 점검",
    "복습과 시험 대비",
    "최종 정리 및 회고",
]

_TASK_TEMPLATES = [
    ("{concept} 핵심 개념 정리", "{concept}의 정의와 역할을 본인 언어로 노트에 정리한다.", "easy", 30),
    ("{concept} 동작 흐름 분석", "{concept}이(가) 실제로 어떻게 동작하는지 단계별로 그림 또는 문장으로 정리한다.", "normal", 40),
    ("{subject} 관점에서 {concept} 적용", "{subject} 맥락에서 {concept}을(를) 어떻게 활용하는지 예시를 만든다.", "normal", 35),
    ("{concept} 실습/코드 따라하기", "{concept} 관련 예제를 직접 실행하고 결과와 오류를 메모한다.", "hard", 45),
    ("{concept} 오개념 점검", "{concept}에서 헷갈리기 쉬운 부분을 찾아 질문 형태로 정리한다.", "normal", 25),
    ("오늘 학습 5문장 요약", "오늘 학습한 {concept} 핵심을 5문장으로 요약한다.", "easy", 15),
]

_DAY_FOCUS = [  # 한 주(7일) 안에서 날짜마다 서로 다른 학습 각도를 보장
    "개념 정의 이해",
    "동작 원리 분석",
    "구조와 관계 정리",
    "실습/예제 적용",
    "응용·문제 풀이",
    "오류·약점 디버깅",
    "정리와 복습",
]

_REVIEW_TEMPLATES = [
    "{concept}이(가) 해결하는 문제는 무엇인가?",
    "{concept}의 핵심 구성 요소는 무엇인가?",
    "{subject}에서 {concept}을(를) 사용하는 이유는 무엇인가?",
    "{concept}과(와) 비슷하지만 다른 개념은 무엇이고 어떻게 구분하는가?",
    "{concept}을(를) 실제로 적용할 때 주의할 점은 무엇인가?",
]

_REVIEW_TEMPLATES_ADVANCED = [
    "{concept}의 책임을 다른 계층과 어떻게 분리해야 하며 그 근거는 무엇인가?",
    "{concept}에서 발생 가능한 예외와 장애 상황을 어떻게 처리할 것인가?",
    "{concept} 로직을 테스트 가능하게 만들려면 어떤 의존성을 분리해야 하는가?",
    "{subject}가 커질 때 {concept}이(가) 유지보수와 성능에 미치는 영향은 무엇인가?",
    "{concept} 도입의 트레이드오프(복잡도 대비 이점)는 무엇인가?",
]


def _rot(items: List[str], idx: int, fallback: str) -> str:
    if not items:
        return fallback
    return items[idx % len(items)]


def build_day(day_index: int, *, subject: str, keywords: List[str],
              week: int = 1, tasks_min: int = 3, date: Optional[str] = None,
              title: Optional[str] = None, objective: Optional[str] = None,
              level: str = "intermediate") -> Dict[str, Any]:
    """단일 일차 스켈레톤. tasks>=tasks_min, review_questions>=2 보장. level별 깊이 차등(스펙 E·G)."""
    subject = subject or "학습"
    lvl = normalize_level(level)
    kws = keywords or [subject]
    templates = _TASK_TEMPLATES_BY_LEVEL[lvl]
    focuses = _DAY_FOCUS_BY_LEVEL[lvl]
    # 날짜/주차 전역 순번으로 개념·문구를 회전시켜 중복(단순 반복) 방지
    seq = (week - 1) * 7 + (day_index - 1)
    concept = _rot(kws, seq, subject)
    concept2 = _rot(kws, seq + 1, subject)
    phase = _PHASE[(week - 1) % len(_PHASE)]
    focus = focuses[(day_index - 1) % len(focuses)]

    day_title = title or f"{concept} — {focus}"
    day_obj = objective or f"{subject}의 {concept}을(를) {focus} 중심으로 학습한다. (주차 흐름: {phase})"

    core = []
    for off in range(3):
        c = _rot(kws, seq + off, subject)
        if c not in core:
            core.append(c)
    if not core:
        core = [subject]

    tasks: List[Dict[str, Any]] = []
    for i in range(max(tasks_min, 3)):
        tmpl = templates[(seq + i) % len(templates)]
        c = _rot(kws, seq + i, subject)
        tasks.append({
            "index": i + 1,
            "title": tmpl[0].format(concept=c, subject=subject),
            "description": tmpl[1].format(concept=c, subject=subject),
            "estimated_minutes": tmpl[3],
            "difficulty": tmpl[2],
        })

    review_pool = list(_REVIEW_TEMPLATES)
    if lvl == "advanced":
        review_pool = _REVIEW_TEMPLATES_ADVANCED + review_pool
    reviews: List[str] = []
    for i in range(2):
        rt = review_pool[(seq + i) % len(review_pool)]
        reviews.append(rt.format(concept=_rot(kws, seq + i, subject), subject=subject))
    # 보장: 최소 2개, 중복 제거 후 부족하면 보충
    reviews = list(dict.fromkeys(reviews))
    while len(reviews) < 2:
        reviews.append(f"{concept}에 대해 오늘 새로 알게 된 것은 무엇인가?")

    return {
        "day_index": day_index,
        "day_label": f"{day_index}일차",
        "date": date,
        "title": day_title,
        "objective": day_obj,
        "core_concepts": core,
        "tasks": tasks,
        "practice": f"{concept}을(를) {subject} 상황에 직접 적용하는 간단한 과제를 수행한다.",
        "review_questions": reviews,
        "checkpoint": f"{concept}의 핵심을 본인 말로 설명할 수 있다.",
        "deliverable": f"{concept} 정리 노트 또는 {concept2} 비교 표",
    }


def build_week(week: int, *, subject: str, keywords: List[str],
               days_per_week: int, tasks_min: int,
               start_date: Optional[datetime] = None,
               level: str = "intermediate") -> Dict[str, Any]:
    phase = _PHASE[(week - 1) % len(_PHASE)]
    days: List[Dict[str, Any]] = []
    for d in range(1, days_per_week + 1):
        date_str = None
        if start_date is not None:
            date_str = (start_date + timedelta(days=(week - 1) * days_per_week + (d - 1))).strftime("%Y-%m-%d")
        days.append(build_day(d, subject=subject, keywords=keywords, week=week,
                              tasks_min=tasks_min, date=date_str, level=level))
    return {
        "week": week,
        "title": f"{week}주차 — {subject} {phase}",
        "objective": f"{week}주차에는 {subject}을(를) {phase} 단계로 학습한다.",
        "week_summary": f"{week}주차는 {phase}에 집중하여 {subject}의 이해도를 한 단계 끌어올린다.",
        "core_topics": (keywords or [subject])[:4],
        "days": days,
        # backward compatibility: 일부 클라이언트가 week.tasks만 기대할 수 있음
        "tasks": [t["title"] for d in days for t in d["tasks"]][:tasks_min],
        "week_checkpoint": f"{week}주차 학습 목표를 모두 달성하고 핵심 개념을 설명할 수 있다.",
        "week_deliverable": f"{week}주차 학습 정리 노트 및 복습 산출물",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Overlay — LLM 부분 출력을 스켈레톤 위에 덮어쓴다(구조 유지)
# ─────────────────────────────────────────────────────────────────────────────
def _overlay_day(skeleton: Dict[str, Any], llm: Any, tasks_min: int) -> Dict[str, Any]:
    if not isinstance(llm, dict):
        return skeleton
    out = dict(skeleton)
    for k in ("title", "objective", "practice", "checkpoint", "deliverable"):
        v = llm.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
    cc = clean_keywords(llm.get("core_concepts"))
    if cc:
        out["core_concepts"] = cc

    # tasks overlay (구조 검증 후 부족분은 스켈레톤 유지)
    lt = llm.get("tasks")
    norm_tasks: List[Dict[str, Any]] = []
    if isinstance(lt, list):
        for t in lt:
            if isinstance(t, dict) and str(t.get("title") or "").strip():
                norm_tasks.append({
                    "title": str(t.get("title")).strip(),
                    "description": str(t.get("description") or t.get("title")).strip(),
                    "estimated_minutes": _int(t.get("estimated_minutes"), 30),
                    "difficulty": str(t.get("difficulty") or "normal").strip().lower(),
                })
            elif isinstance(t, str) and t.strip():
                norm_tasks.append({"title": t.strip(), "description": t.strip(),
                                   "estimated_minutes": 30, "difficulty": "normal"})
    if len(norm_tasks) >= tasks_min:
        out["tasks"] = norm_tasks
    elif norm_tasks:  # 부분만 → 스켈레톤 task로 채워 최소 보장
        out["tasks"] = norm_tasks + skeleton["tasks"][len(norm_tasks):]
        while len(out["tasks"]) < tasks_min:
            out["tasks"].append(skeleton["tasks"][len(out["tasks"]) % len(skeleton["tasks"])])
    # task index 재부여(1-based, 스펙 C)
    for ti, t in enumerate(out.get("tasks", []), start=1):
        if isinstance(t, dict):
            t["index"] = ti

    rq = listify(llm.get("review_questions"))
    if len(rq) >= 2:
        out["review_questions"] = rq
    practice = llm.get("practice")
    if isinstance(practice, str) and practice.strip():
        out["practice"] = practice.strip()
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Validators (스펙 H)
# ─────────────────────────────────────────────────────────────────────────────
def validate_week_expand(resp: Dict[str, Any], tasks_min: int = 3) -> bool:
    days = resp.get("daily_plans")
    if not isinstance(days, list) or len(days) != 7:
        return False
    for d in days:
        if not isinstance(d, dict):
            return False
        if len(d.get("tasks") or []) < tasks_min:
            return False
        if len(d.get("review_questions") or []) < 2:
            return False
    return True


def validate_12week_roadmap(resp: Dict[str, Any], weeks_n: int = 12,
                            days_n: int = 7, tasks_min: int = 3) -> bool:
    weeks = resp.get("weeks")
    if not isinstance(weeks, list) or len(weeks) != weeks_n:
        return False
    total = 0
    for w in weeks:
        days = w.get("days") if isinstance(w, dict) else None
        if not isinstance(days, list) or len(days) != days_n:
            return False
        for d in days:
            if not isinstance(d, dict):
                return False
            if len(d.get("tasks") or []) < tasks_min:
                return False
            if len(d.get("review_questions") or []) < 2:
                return False
        total += len(days)
    return total == weeks_n * days_n


# ─────────────────────────────────────────────────────────────────────────────
# 84일 로드맵 표준 입력 방어 / 검증 / 응답 (스펙 B·C·D)
# ─────────────────────────────────────────────────────────────────────────────
# title/objective 가 이 정도로만 채워져 있으면 "얕은 문구"로 보고 repair 대상으로 본다.
_SHALLOW_PATTERNS = [
    re.compile(r"page\s*\d+", re.I),
    re.compile(r"^\s*\d+\s*(주차|일차)\s*$"),
    re.compile(r"^\s*핵심\s*개념\s*정리\s*$"),
    re.compile(r"^\s*내용\s*정리\s*$"),
]
_MD_LEFTOVER = re.compile(r"\*\*|`|^\s*#{1,6}\s|<[^>]+>", re.M)


def build_roadmap_ctx(body: Dict[str, Any]) -> Dict[str, Any]:
    """로드맵 요청 body 입력 방어(스펙 B). 누락값을 안전한 기본값으로 채운다."""
    if not isinstance(body, dict):
        body = {}

    def g(*keys: str) -> Any:
        for k in keys:
            v = body.get(k)
            if v not in (None, "", []):
                return v
        return None

    weeks = _int(g("weeks", "total_weeks", "totalWeeks"), _env_int("AI_ROADMAP_WEEKS", 12)) or 12
    dpw = _int(g("days_per_week", "daysPerWeek"), _env_int("AI_DAYS_PER_WEEK", 7)) or 7
    # difficulty(beginner/intermediate/advanced 또는 easy/normal/hard)도 level로 매핑
    raw_level = g("level", "difficulty", "knowledgeLevel", "knowledge_level")
    level = normalize_level(raw_level)
    level_warning = None
    if not level_is_recognized(raw_level):
        level_warning = f"허용하지 않는 난이도 '{raw_level}' → 기본값 intermediate로 보정했습니다."
    title = g("material_title", "materialTitle", "title", "file_name", "fileName")
    summary = g("document_text", "documentText", "context", "summary", "material_summary",
                "materialSummary", "extractedText", "extracted_text")
    return {
        "title": title,
        "subject": g("subject") or title,
        "summary": summary,
        "material_summary": g("material_summary", "materialSummary") or summary,
        "keywords": g("keywords"),
        "user_goal": g("user_goal", "userGoal", "goal"),
        "goal": g("goal", "user_goal", "userGoal"),
        "level": level,
        "level_warning": level_warning,
        "week": g("week"),
        "weeks": weeks,
        "days_per_week": dpw,
        "date": g("start_date", "startDate", "date"),
        "start_date": g("start_date", "startDate", "date"),
        "material_id": g("material_id", "materialId"),
    }


def _has_markdown_deep(obj: Any) -> bool:
    if isinstance(obj, str):
        return bool(_MD_LEFTOVER.search(obj))
    if isinstance(obj, dict):
        return any(_has_markdown_deep(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_markdown_deep(v) for v in obj)
    return False


def _is_shallow(text: str) -> bool:
    s = str(text or "").strip()
    if len(s) < 4:
        return True
    return any(p.search(s) for p in _SHALLOW_PATTERNS)


def validate_roadmap_84(resp: Dict[str, Any], weeks_n: int = 12,
                        days_n: int = 7, tasks_min: int = 3) -> Dict[str, Any]:
    """스펙 D 강화 검증. {passed, reason} 반환."""
    if not isinstance(resp, dict):
        return {"passed": False, "reason": "응답이 객체가 아님"}
    if resp.get("total_weeks") != weeks_n:
        return {"passed": False, "reason": f"total_weeks != {weeks_n}"}
    if resp.get("days_per_week") != days_n:
        return {"passed": False, "reason": f"days_per_week != {days_n}"}
    if resp.get("total_days") != weeks_n * days_n:
        return {"passed": False, "reason": f"total_days != {weeks_n * days_n}"}
    weeks = resp.get("weeks")
    if not isinstance(weeks, list) or len(weeks) != weeks_n:
        return {"passed": False, "reason": f"weeks 길이 != {weeks_n}"}
    shallow_hits = 0
    total_days = 0
    for w in weeks:
        if not isinstance(w, dict):
            return {"passed": False, "reason": "week 항목이 객체가 아님"}
        days = w.get("days")
        if not isinstance(days, list) or len(days) != days_n:
            return {"passed": False, "reason": f"week.days 길이 != {days_n}"}
        for d in days:
            if not isinstance(d, dict):
                return {"passed": False, "reason": "day 항목이 객체가 아님"}
            if not str(d.get("title") or "").strip() or not str(d.get("objective") or "").strip():
                return {"passed": False, "reason": "day.title/objective 비어 있음"}
            if len(d.get("tasks") or []) < tasks_min:
                return {"passed": False, "reason": f"day.tasks < {tasks_min}"}
            if len(d.get("review_questions") or []) < 2:
                return {"passed": False, "reason": "day.review_questions < 2"}
            if _is_shallow(d.get("title")) and _is_shallow(d.get("objective")):
                shallow_hits += 1
            total_days += 1
    if total_days != weeks_n * days_n:
        return {"passed": False, "reason": "총 일수 불일치"}
    if _has_markdown_deep(resp):
        return {"passed": False, "reason": "응답에 마크다운 기호 잔존"}
    if shallow_hits > total_days // 2:
        return {"passed": False, "reason": "얕은 문구(Page N/핵심 개념 정리)만 과다"}
    return {"passed": True, "reason": f"{weeks_n}주 × {days_n}일 = {weeks_n * days_n}일 구조 검증 통과"}


def finalize_roadmap_response(result: Dict[str, Any], weeks_n: int = 12, days_n: int = 7) -> Dict[str, Any]:
    """generate_12week_7day_roadmap 결과를 스펙 C 표준 성공 스키마로 변환(마크다운 제거 + validation)."""
    from app.utils.sanitize import sanitize_obj
    result = sanitize_obj(result) if isinstance(result, dict) else {}
    v = validate_roadmap_84(result, weeks_n, days_n)
    if result.get("level_warning"):
        v = {**v, "warning": result["level_warning"]}
    return {
        "success": True,
        "error_code": None,
        "total_weeks": result.get("total_weeks", weeks_n),
        "days_per_week": result.get("days_per_week", days_n),
        "total_days": result.get("total_days", weeks_n * days_n),
        "level": result.get("level", "intermediate"),
        "title": result.get("title") or "자료 기반 84일 학습 로드맵",
        "subject": result.get("subject"),
        "level_policy": result.get("level_policy"),
        "user_goal": result.get("user_goal", ""),
        "weeks": result.get("weeks", []),
        "isFallback": bool(result.get("fallback_used")),
        "fallback_used": bool(result.get("fallback_used")),
        "assumption_notice": result.get("assumption_notice"),
        "validation": v,
    }


def roadmap_failure_response(message: str, debug_hint: str, reason: str,
                             error_code: str = "ROADMAP_GENERATE_FAILED") -> Dict[str, Any]:
    """스펙 C 표준 실패 스키마."""
    return {
        "success": False,
        "error_code": error_code,
        "message": message,
        "recoverable": True,
        "debug_hint": debug_hint,
        "validation": {"passed": False, "reason": reason},
        "weeks": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Action: 플래너 1주일 7일 확장 (expand_planner_week)
# ─────────────────────────────────────────────────────────────────────────────
def expand_planner_week(ctx: Dict[str, Any]) -> Dict[str, Any]:
    c = cfg()
    tasks_min = c["tasks_per_day_min"]
    subject = (ctx.get("subject") or ctx.get("title") or "학습").strip()
    level = normalize_level(ctx.get("level"))
    keywords = clean_keywords(ctx.get("keywords")) or clean_keywords(ctx.get("goal")) or [subject]
    start_dt = _parse_date(ctx.get("start_date") or ctx.get("date"))

    # 1) 스켈레톤(구조 보장)
    skeleton_days = [
        build_day(i, subject=subject, keywords=keywords, week=1, tasks_min=tasks_min, level=level,
                  date=(start_dt + timedelta(days=i - 1)).strftime("%Y-%m-%d") if start_dt else None)
        for i in range(1, 8)
    ]

    # 2) LLM 초안(Ollama) → 보정(OpenAI) 시도
    llm_days = _llm_week_days(ctx, subject, keywords, level)
    fallback_used = llm_days is None or len(llm_days) == 0
    final_days = []
    for i in range(7):
        llm = llm_days[i] if (llm_days and i < len(llm_days)) else None
        final_days.append(_overlay_day(skeleton_days[i], llm, tasks_min))

    week_goal, week_strategy = _llm_week_meta(ctx, subject)
    resp: Dict[str, Any] = {
        "planner_title": ctx.get("title") or "공부 플래너",
        "subject": subject,
        "level": level,
        "level_policy": _LEVEL_POLICY_TEXT[level],
        "week": ctx.get("week") or "",
        "week_goal": week_goal or f"이번 주에는 {subject}의 핵심 개념을 이해하고 {ctx.get('goal') or '목표'}을(를) 달성한다.",
        "week_strategy": week_strategy or f"1~2일차는 기초, 3~5일차는 실습/적용, 6~7일차는 복습과 점검으로 진행한다.",
        "daily_plans": final_days,
        "risk_points": _llm_risks(ctx) or ["시간 부족", "개념 혼동 가능성", "실습 환경 오류"],
        "reflection_prompts": ["오늘 가장 헷갈린 개념은 무엇인가?", "내일 보완해야 할 부분은 무엇인가?"],
        "assumption_notice": (
            "입력 정보가 부족한 부분은 사용자의 목표와 과목명을 기준으로 보수적으로 확장했습니다."
            if fallback_used else None
        ),
        "error_code": None,
    }

    # 3) 검증 → 실패 시 스켈레톤으로 강제 복구
    if not validate_week_expand(resp, tasks_min):
        resp["daily_plans"] = skeleton_days
        resp["error_code"] = "AI_REPAIRED_FALLBACK"
        resp["warning"] = "AI 응답 구조가 불완전하여 결정적(deterministic) 7일 계획으로 보정했습니다."
        fallback_used = True
    resp["fallback_used"] = fallback_used
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# Action: 12주 × 7일 로드맵 (generate_12week_7day_roadmap / planner 기반)
# ─────────────────────────────────────────────────────────────────────────────
def generate_12week_7day_roadmap(ctx: Dict[str, Any]) -> Dict[str, Any]:
    c = cfg()
    weeks_n = c["weeks"]
    days_n = c["days_per_week"]
    tasks_min = c["tasks_per_day_min"]
    subject = (ctx.get("subject") or ctx.get("title") or "학습").strip()
    level = normalize_level(ctx.get("level"))
    # PDF 메타데이터(매 페이지 반복되는 표지/날짜/교수명) 탐지 → 학습 개념 오염 차단
    from app.utils.pdf_noise_filter import (
        clean_topic, conceptual_fallback_items, detect_repeated_lines,
        find_noise_violations, sanitize_text_fields,
    )
    _summary = str(ctx.get("summary") or ctx.get("material_summary") or "")
    repeated = detect_repeated_lines([_summary, str(ctx.get("title") or "")])
    subject = clean_topic(subject, repeated=repeated) or subject
    keywords = clean_keywords(ctx.get("keywords"), repeated) or clean_keywords(ctx.get("summary"), repeated) \
        or clean_keywords(ctx.get("material_summary"), repeated)
    if not keywords:
        # 키워드가 메타데이터뿐이라 비면 자료 제목 기반 개념형으로 대체(날짜/교수명 사용 금지)
        keywords = conceptual_fallback_items(subject, count=8) or [subject]
    start_dt = _parse_date(ctx.get("start_date") or ctx.get("date"))

    # 1) 주차 아웃라인 LLM 초안(주차별 제목/목표/일자 타이틀) — 토큰 제어
    #    _no_llm=True 이면 LLM 생략하고 결정적 스켈레톤만 사용(타임아웃/검증 실패 복구용)
    outline = None if ctx.get("_no_llm") else _llm_week_outline(ctx, subject, keywords, weeks_n, days_n, level)
    fallback_used = outline is None

    # 2) 스켈레톤 + 아웃라인 overlay 로 12×7 빌드(구조 보장)
    weeks: List[Dict[str, Any]] = []
    for w in range(1, weeks_n + 1):
        wk = build_week(w, subject=subject, keywords=keywords, level=level,
                        days_per_week=days_n, tasks_min=tasks_min, start_date=start_dt)
        ol = outline.get(w) if isinstance(outline, dict) else None
        if isinstance(ol, dict):
            if ol.get("title"):
                wk["title"] = str(ol["title"]).strip()
            if ol.get("objective"):
                wk["objective"] = str(ol["objective"]).strip()
            if ol.get("week_summary"):
                wk["week_summary"] = str(ol["week_summary"]).strip()
            day_titles = ol.get("day_titles") or []
            for di, d in enumerate(wk["days"]):
                if di < len(day_titles) and str(day_titles[di]).strip():
                    d["title"] = str(day_titles[di]).strip()
        weeks.append(wk)

    title = ctx.get("title") or f"{subject} {weeks_n}주 학습 로드맵"
    resp: Dict[str, Any] = {
        "title": f"문서 기반 {weeks_n}주 학습 로드맵" if ctx.get("summary") else f"플래너 기반 {weeks_n}주 학습 로드맵",
        "subject": subject,
        "level": level,
        "level_policy": _LEVEL_POLICY_TEXT[level],
        "user_goal": ctx.get("user_goal") or ctx.get("goal") or "",
        "total_weeks": weeks_n,
        "days_per_week": days_n,
        "total_days": weeks_n * days_n,
        "weeks": weeks,
        "assumption_notice": (
            "상급(advanced) 로드맵의 설계 판단·테스트·예외 처리 등 일부 항목은 문서 밖 고급 관점을 "
            "'문서 기반 확장 학습'으로 표시해 포함했습니다." if level == "advanced" else None
        ),
        "level_warning": ctx.get("level_warning"),
        "error_code": None,
    }
    if not validate_12week_roadmap(resp, weeks_n, days_n, tasks_min):
        # 스켈레톤만으로 재빌드(절대 구조 보장)
        resp["weeks"] = [
            build_week(w, subject=subject, keywords=keywords, days_per_week=days_n,
                       tasks_min=tasks_min, start_date=start_dt, level=level)
            for w in range(1, weeks_n + 1)
        ]
        resp["error_code"] = "AI_REPAIRED_FALLBACK"
        resp["warning"] = f"AI 응답 구조가 불완전하여 결정적 {weeks_n}주×{days_n}일 로드맵으로 보정했습니다."
        fallback_used = True
    resp["fallback_used"] = fallback_used

    # 최종 정제: LLM overlay 가 끼워넣은 날짜/연도/교수명/표지문구를 학습 주제에서 제거
    before = find_noise_violations(resp["weeks"], repeated=repeated)
    resp["weeks"] = sanitize_text_fields(resp["weeks"], repeated=repeated, title=subject)
    if before:
        resp["warning"] = (resp.get("warning") or "") + f" 메타데이터 노이즈 {len(before)}건 제거됨."
        logger.info("[ROADMAP_NOISE] %d건 제거: %s", len(before), before[:5])
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# LLM 프롬프트 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
def _ctx_block(ctx: Dict[str, Any]) -> str:
    fields = [
        ("제목", ctx.get("title")), ("과목", ctx.get("subject")),
        ("학기", ctx.get("semester")), ("주차", ctx.get("week")),
        ("학습 유형", ctx.get("study_type")), ("우선순위", ctx.get("priority")),
        ("목표 시간", ctx.get("target_time")), ("실제 시간", ctx.get("actual_time")),
        ("마감", ctx.get("deadline")), ("목표", ctx.get("goal")),
        ("할 일", ctx.get("todo")), ("메모", ctx.get("memo")),
        ("요약", ctx.get("summary") or ctx.get("material_summary")),
        ("수준", ctx.get("level")),
    ]
    return "\n".join(f"- {k}: {v}" for k, v in fields if v)


def _level_guide(level: str) -> str:
    return f"학습 수준은 {level}이다. 정책: {_LEVEL_POLICY_TEXT.get(level, _LEVEL_POLICY_TEXT['intermediate'])}"


def _llm_week_days(ctx: Dict[str, Any], subject: str, keywords: List[str],
                   level: str = "intermediate") -> Optional[List[Dict[str, Any]]]:
    system = (
        "너는 학습 실행 코치다. 학생의 공부 플래너를 받아 '하루 단위 실행 계획' 7일치를 만든다. "
        "각 날짜는 서로 다른 학습 주제/할 일을 가져야 하고, 단순 반복 문구와 'Page 1' 같은 페이지 번호 나열은 금지한다. "
        f"{_NOISE_RULES} "
        f"{_level_guide(level)}. 상급이면 설계 판단·책임 분리·테스트·예외 처리·성능 관점을 포함하고, "
        "문서에 없는 고급 내용은 '문서 기반 확장 학습'으로 표시한다. 반드시 한국어로, JSON으로만 응답한다."
    )
    user = (
        f"## 플래너\n{_ctx_block(ctx)}\n핵심 키워드: {', '.join(keywords)}\n\n"
        "아래 JSON 형식으로만 응답하라(설명/마크다운 금지):\n"
        '{ "days": [ { "title": "...", "objective": "...", "core_concepts": ["..."], '
        '"tasks": [ {"title":"...","description":"...","estimated_minutes":30,"difficulty":"easy|normal|hard"} ], '
        '"practice": "...", "review_questions": ["...","..."] } ] }\n'
        "days 배열은 정확히 7개. 각 day의 tasks는 3개 이상, review_questions는 2개 이상."
    )
    raw = primary_llm(system, user)
    parsed = _parse_json(raw)
    days = None
    if isinstance(parsed, dict):
        days = parsed.get("days")
    elif isinstance(parsed, list):
        days = parsed
    if isinstance(days, list) and days:
        return days[:7]
    return None


def _llm_week_meta(ctx: Dict[str, Any], subject: str) -> tuple[Optional[str], Optional[str]]:
    raw = refiner_llm(
        "너는 학습 코치다. 한국어로 JSON만 응답한다.",
        f"## 플래너\n{_ctx_block(ctx)}\n\n"
        '{ "week_goal": "1주일 전체 학습 목표 1~2문장", "week_strategy": "7일을 어떤 순서로 학습할지 2~3문장" } 형식으로만 응답하라.',
        max_tokens=400,
    )
    parsed = _parse_json(raw)
    if isinstance(parsed, dict):
        return (str(parsed.get("week_goal") or "").strip() or None,
                str(parsed.get("week_strategy") or "").strip() or None)
    return None, None


def _llm_risks(ctx: Dict[str, Any]) -> Optional[List[str]]:
    raw = primary_llm(
        "너는 학습 코치다. 한국어로 JSON 배열만 응답한다.",
        f"## 플래너\n{_ctx_block(ctx)}\n\n학습 실패/지연 위험 요소 3개를 [\"...\",\"...\",\"...\"] 형식 JSON 배열로만 응답하라.",
        max_tokens=300,
    )
    parsed = _parse_json(raw)
    risks = listify(parsed)
    return risks[:5] if risks else None


def _llm_week_outline(ctx: Dict[str, Any], subject: str, keywords: List[str],
                      weeks_n: int, days_n: int, level: str = "intermediate") -> Optional[Dict[int, Dict[str, Any]]]:
    focus = ""
    wk = ctx.get("week")
    if wk:
        focus = f"\n사용자가 입력한 '{wk}'는 다른 주차보다 더 구체적으로 작성하라."
    system = (
        f"너는 학습 커리큘럼 설계자다. {subject}에 대한 {weeks_n}주 학습 로드맵의 '주차 개요'를 만든다. "
        "전체 흐름은 1주차 기초 → 중반 적용/실습 → 후반 복습/프로젝트/시험 대비로 잡는다. "
        f"{_level_guide(level)}. 상급이면 후반부에 아키텍처 설계 판단·책임 분리·테스트·예외 처리를 배치한다. "
        "각 주차/일자 제목은 서로 달라야 하고, 페이지 번호('Page 1')를 학습 목표처럼 쓰지 않는다. "
        f"{_NOISE_RULES} "
        "한국어로 JSON만 응답한다."
    )
    user = (
        f"## 입력\n{_ctx_block(ctx)}\n핵심 키워드: {', '.join(keywords)}{focus}\n\n"
        "아래 JSON 형식으로만 응답하라(설명/마크다운 금지):\n"
        '{ "weeks": [ { "week": 1, "title": "...", "objective": "...", "week_summary": "...", '
        f'"day_titles": ["1일차 제목", ... 총 {days_n}개] }} ] }}\n'
        f"weeks 배열은 정확히 {weeks_n}개, 각 day_titles는 {days_n}개."
    )
    raw = refiner_llm(system, user)
    parsed = _parse_json(raw)
    weeks = None
    if isinstance(parsed, dict):
        weeks = parsed.get("weeks")
    elif isinstance(parsed, list):
        weeks = parsed
    if not isinstance(weeks, list) or not weeks:
        return None
    out: Dict[int, Dict[str, Any]] = {}
    for i, w in enumerate(weeks[:weeks_n]):
        if isinstance(w, dict):
            out[i + 1] = {
                "title": w.get("title"),
                "objective": w.get("objective"),
                "week_summary": w.get("week_summary"),
                "day_titles": listify(w.get("day_titles")),
            }
    return out or None


def _parse_date(v: Any) -> Optional[datetime]:
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None
