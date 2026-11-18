"""
Expert Answer Orchestrator.

사용자 질문을 "전문가가 후배에게 강의하듯" 깊이 있는 답변으로 변환하는 파이프라인.
OpenAI를 단순 답변 생성기로 쓰지 않고 "질문 해석기 + 답변 설계자 + 검증자"로 분리하고,
Qwen(Ollama)을 본문 생성기로 사용한다. (level_policy의 'Qwen 생성 / OpenAI 검토' 원칙과 일치)

파이프라인:
  1. Intent Analysis     — 질문을 ExpertAnswerPlan(JSON)으로 구조화 (deterministic + OpenAI 보강)
  2. Retrieval Planning  — Wikipedia(개념) / Tavily(최신) / 내부 RAG(자료) 선택
  3. Evidence Selection  — relevance/authority/freshness/redundancy로 평가 후 top 3~5 선별
  4. Expert Synthesis    — 9개 섹션 구조 + 전문용어 풀이 + 다관점을 강제하는 본문 생성 (Qwen, think=False)
  5. Quality Validation  — 로컬 휴리스틱 검증 → 부족하면 1회 보강(augment)

설계 원칙:
- 어떤 단계가 실패해도 서버가 죽지 않는다. 최악의 경우 None을 반환하고 caller가 기존 경로로 폴백한다.
- 기존 라우터/스키마/UI를 바꾸지 않는다. /api/ai/chat 응답의 answer 문자열 '내용'만 깊어진다.
- 모든 동작은 환경변수로 on/off + 튜닝 가능 (EXPERT_ANSWER_*).
- OLLAMA_MODEL이 qwen3 계열이면 thinking이 num_predict를 소진하므로 think=False로 호출한다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 환경설정 헬퍼
# ──────────────────────────────────────────────────────────────────────────────
def _flag(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def enabled() -> bool:
    """전문가 오케스트레이터 전체 on/off. false면 caller가 기존 단일 호출 경로 사용."""
    return _flag("EXPERT_ANSWER_ENABLED", True)


# ──────────────────────────────────────────────────────────────────────────────
# 지식수준 매핑
# ──────────────────────────────────────────────────────────────────────────────
_DEPTH_ORDER = ("beginner", "undergraduate", "graduate", "phd", "expert")
_KO_TO_DEPTH = {
    "입문": "beginner", "초급": "beginner",
    "학사": "undergraduate", "학부": "undergraduate",
    "석사": "graduate", "대학원": "graduate",
    "박사": "phd",
    "전문가": "expert",
}
_DEPTH_TO_KO = {
    "beginner": "입문", "undergraduate": "학사", "graduate": "석사",
    "phd": "박사", "expert": "전문가",
}


def _depth_index(depth: str) -> int:
    try:
        return _DEPTH_ORDER.index(depth)
    except ValueError:
        return 1  # undergraduate


def _max_depth(*depths: Optional[str]) -> str:
    best = "undergraduate"
    for d in depths:
        if d and _depth_index(d) > _depth_index(best):
            best = d
    return best


# ──────────────────────────────────────────────────────────────────────────────
# ExpertAnswerPlan 스키마
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class ExpertAnswerPlan:
    topic: str
    domain: str = "general"
    depth: str = "undergraduate"          # beginner|undergraduate|graduate|phd|expert
    knowledge_level_ko: str = "학사"        # 입문|학사|석사|박사|전문가
    format_hint: str = "markdown"          # plain|markdown|json|table|code
    needs_web_search: bool = False
    needs_wikipedia: bool = True
    needs_internal_rag: bool = False
    multi_perspective: bool = False
    perspectives: List[str] = field(default_factory=list)
    required_terms: List[str] = field(default_factory=list)
    answer_sections: List[str] = field(default_factory=list)
    quality_checks: List[str] = field(default_factory=list)
    clean_question: str = ""               # 형식 prefix 제거한 질문
    search_query: str = ""                 # 검색용 정제 쿼리

    def summary(self) -> str:
        return (
            f"topic={self.topic!r} domain={self.domain} depth={self.depth} "
            f"format={self.format_hint} web={self.needs_web_search} "
            f"wiki={self.needs_wikipedia} rag={self.needs_internal_rag} "
            f"multiPerspective={self.multi_perspective} "
            f"perspectives={self.perspectives} terms={self.required_terms[:6]}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 1. Intent Analysis (deterministic 우선 + OpenAI 보강)
# ──────────────────────────────────────────────────────────────────────────────
_FORMAT_PREFIX = re.compile(r"^\s*(json|table|code|markdown|md|표|코드|테이블)\s*[:：]\s*(.+)$", re.I | re.S)
_FORMAT_MAP = {
    "json": "json", "table": "table", "테이블": "table", "표": "table",
    "code": "code", "코드": "code", "markdown": "markdown", "md": "markdown",
}

_DEPTH_PATTERNS = [
    (re.compile(r"전문가\s*(수준|급)?|expert|현업|실무\s*전문가", re.I), "expert"),
    (re.compile(r"박사\s*(수준|급)?|ph\.?\s*d", re.I), "phd"),
    (re.compile(r"석사\s*(수준)?|대학원", re.I), "graduate"),
    (re.compile(r"학부생?|학사\s*(수준)?", re.I), "undergraduate"),
    (re.compile(r"입문|초보|초심자|쉽게\s*설명|초등", re.I), "beginner"),
]
# "전문적/심화/깊이/고급" 류는 명시적 수준은 아니지만 최소 박사급 깊이를 요구하는 신호
_PROF_SIGNAL = re.compile(r"전문적|심화|깊이\s*있게|깊게|고급|디테일|자세히\s*전문|advanced|in\s*depth|deep\s*dive", re.I)

_MULTI_PERSPECTIVE_SIGNAL = re.compile(
    r"여러\s*견해|여러\s*관점|다양한\s*관점|다각도|여러\s*각도|비판적|비판|반론|반박|"
    r"찬반|토론|관점으로|관점에서|perspectives?|multi-?perspective|다관점",
    re.I,
)
_EXPLICIT_PERSPECTIVES = re.compile(r"([\w가-힣]+(?:\s*/\s*[\w가-힣]+){1,5})\s*관점", re.I)

_FRESHNESS_SIGNAL = re.compile(
    r"최신|요즘|최근|현재|지금|올해|트렌드|동향|뉴스|업데이트|출시|신규|"
    r"20(2[3-9]|3\d)|latest|recent|trend|news",
    re.I,
)
_DOC_SIGNAL = re.compile(r"이\s*(파일|자료|문서|pdf)|첨부|업로드|강의자료|자료에서|문서에서|본문", re.I)

# 도메인 감지 (관점/용어 시드용)
_DOMAIN_KEYWORDS: List[Tuple[str, re.Pattern]] = [
    ("software", re.compile(r"oop|객체\s*지향|클래스|상속|다형성|캡슐화|디자인\s*패턴|solid|spring|java|코틀린|kotlin|"
                            r"리팩터|아키텍처|마이크로서비스|interface|인터페이스|함수형|동시성|thread", re.I)),
    ("ai_ml", re.compile(r"(?<![a-z])rag(?![a-z])|llm|머신러닝|딥러닝|인공지능|신경망|트랜스포머|transformer|임베딩|embedding|"
                         r"파인튜닝|fine-?tun|prompt|에이전트\s*ai|gradient|tensor", re.I)),
    ("database", re.compile(r"(?<![a-z])sql(?![a-z])|데이터베이스|database|rdbms|인덱스|트랜잭션|정규화|join|조인|nosql|샤딩|쿼리", re.I)),
    ("network_security", re.compile(r"네트워크|tcp|http|tls|ssl|보안|인증|authentication|authorization|jwt|oauth|암호화|방화벽", re.I)),
    ("os_system", re.compile(r"운영체제|프로세스|스레드|메모리|스케줄|커널|동기화|deadlock|교착", re.I)),
]

# '관점'이 아니라 정의/개요 섹션과 중복되는 일반 라벨 — 관점 목록에서 제외한다.
_GENERIC_PERSPECTIVE = re.compile(r"개요|개념\s*적?\s*이해|기본\s*이해|소개|^정의$|일반\s*적", re.I)
_DEFAULT_PERSPECTIVES = ["이론적 관점", "실무적 관점", "설계/아키텍처 관점", "비판적 관점"]
_DOMAIN_PERSPECTIVES = {
    "software": ["컴퓨터과학 이론 관점", "소프트웨어 공학 관점", "실무 유지보수 관점",
                 "디자인 패턴/SOLID 관점", "함수형 프로그래밍 진영의 비판 관점"],
    "ai_ml": ["이론/수식 관점", "시스템·엔지니어링 관점", "실무 적용 관점", "한계·비판 관점"],
    "database": ["관계대수 이론 관점", "쿼리 최적화/실무 관점", "스키마 설계 관점", "분산/확장성 비판 관점"],
}
# 주제 한정 핵심 용어 시드(없으면 모델이 스스로 도출하도록 프롬프트로 강제).
# 'software' 도메인은 OOP·Spring·동시성·아키텍처를 모두 포함하는 넓은 버킷이므로,
# OOP 전용 용어 시드는 질문이 실제로 OOP를 다룰 때만(_OOP_SIGNAL) 주입한다.
# (예: 'Spring Security ... 관점' 질문에 다형성/상속을 필수 용어로 강제하지 않도록)
_OOP_SIGNAL = re.compile(r"oop|객체\s*지향|object[\s-]*orient", re.I)
_OOP_TERM_SEED = ["추상화(abstraction)", "캡슐화(encapsulation)", "상속(inheritance)",
                  "다형성(polymorphism)", "동적 디스패치(dynamic dispatch)", "인터페이스(interface)",
                  "SOLID", "상속보다 합성(composition over inheritance)"]


def _seed_terms(domain: str, body: str) -> List[str]:
    if domain == "software" and _OOP_SIGNAL.search(body):
        return list(_OOP_TERM_SEED)
    return []

_DEFAULT_SECTIONS = [
    "한 줄 결론", "핵심 개념 정의", "전문적 설명", "전문용어 풀이",
    "여러 관점 비교", "예시", "흔한 오해", "요약", "참고 근거",
]
_DEFAULT_QUALITY_CHECKS = [
    "전문용어가 충분한가", "전문용어 뜻풀이가 있는가", "여러 관점 비교가 있는가",
    "예시가 있는가", "너무 추상적이지 않은가", "질문 형식을 반영했는가",
    "검색 근거를 합성했는가",
]

_PARTICLE_TAIL = re.compile(
    r"(에\s*대해(서)?|에\s*관해(서)?|를|을|에\s*대한|에\s*관한|는|은|이|가|로|으로|관점으로|관점에서)?\s*"
    r"(전문적(으로)?|심화(해서|로)?|자세히|깊이\s*있게|깊게|"
    r"여러\s*견해(로|에서)?|여러\s*관점(으로|에서)?|다양한\s*관점(으로|에서)?|다각도(로|에서)?|"
    r"박사\s*(수준|급)?(으로|에서)?|전문가\s*(수준|급)?(으로|에서)?|석사\s*(수준)?(으로)?|"
    r"학부(생)?\s*(수준)?(으로)?|입문(자)?\s*(수준)?(으로)?|"
    r"설명(해\s*줘|해줘|해\s*주세요|해라|좀\s*해줘|부탁)?|알려\s*줘|알려줘|가르쳐\s*줘|정리해\s*줘)*"
    r"\s*[.?!~]*$"
)


def _detect_domain(text: str) -> str:
    for name, pat in _DOMAIN_KEYWORDS:
        if pat.search(text):
            return name
    return "general"


_PERSPECTIVE_PHRASE = re.compile(
    r"[\w가-힣]+(?:\s*/\s*[\w가-힣]+)*\s*관점(\s*(으로|에서|에서의|으로의|에))?", re.I
)


def _extract_topic(text: str) -> str:
    """질문에서 검색/표기용 핵심 주제를 best-effort로 추출한다(관점·수준·요청 꼬리 제거)."""
    t = text.strip()
    # 관점/수준/요청 신호구를 먼저 제거 → 검색 주제만 남긴다
    t = _PERSPECTIVE_PHRASE.sub(" ", t)
    t = _MULTI_PERSPECTIVE_SIGNAL.sub(" ", t)
    t = _PROF_SIGNAL.sub(" ", t)
    for pat, _d in _DEPTH_PATTERNS:
        t = pat.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # 남은 요청 꼬리(particle + 요청문)를 반복 제거
    prev = None
    while prev != t:
        prev = t
        t = _PARTICLE_TAIL.sub("", t).strip()
    t = t.strip(" .?!~,:/")
    return t or text.strip()


def _parse_explicit_perspectives(text: str) -> List[str]:
    out: List[str] = []
    for m in _EXPLICIT_PERSPECTIVES.finditer(text):
        chunk = m.group(1)
        for part in re.split(r"\s*/\s*", chunk):
            part = part.strip()
            if not part:
                continue
            label = part if part.endswith("관점") else f"{part} 관점"
            if label not in out:
                out.append(label)
    return out


def _deterministic_plan(
    question: str,
    knowledge_level_ko: str,
    material_id: Optional[int],
    has_rag_context: bool,
) -> ExpertAnswerPlan:
    raw = (question or "").strip()

    # 형식 prefix ("json:oop") 파싱
    fmt = "markdown"
    body = raw
    m = _FORMAT_PREFIX.match(raw)
    if m:
        fmt = _FORMAT_MAP.get(m.group(1).lower(), "markdown")
        body = m.group(2).strip()

    selected_depth = _KO_TO_DEPTH.get((knowledge_level_ko or "").strip(), "undergraduate")

    # 본문 텍스트에서 명시적 수준 감지
    explicit_depth = None
    for pat, d in _DEPTH_PATTERNS:
        if pat.search(body):
            explicit_depth = _max_depth(explicit_depth, d)
    prof_depth = "phd" if _PROF_SIGNAL.search(body) else None
    depth = _max_depth(selected_depth, explicit_depth, prof_depth)

    # 다관점 여부
    explicit_perspectives = _parse_explicit_perspectives(body)
    multi = bool(
        explicit_perspectives
        or _MULTI_PERSPECTIVE_SIGNAL.search(body)
        or _depth_index(depth) >= _depth_index("phd")
    )

    domain = _detect_domain(body)
    topic = _extract_topic(body)

    # 관점 구성
    if explicit_perspectives:
        perspectives = explicit_perspectives
    elif multi:
        perspectives = list(_DOMAIN_PERSPECTIVES.get(domain, _DEFAULT_PERSPECTIVES))
    else:
        perspectives = []

    # 용어 시드(있으면 강제, 없으면 모델 자율). OOP 시드는 OOP 주제일 때만 적용.
    required_terms = _seed_terms(domain, body) if multi or _depth_index(depth) >= _depth_index("graduate") else []

    needs_rag = bool(material_id) or has_rag_context or bool(_DOC_SIGNAL.search(body))
    needs_web = bool(_FRESHNESS_SIGNAL.search(body))
    # 개념/정의 질문은 위키로 정의를 보강. 순수 자료질문(RAG)일 땐 생략.
    needs_wiki = _flag("EXPERT_ANSWER_USE_WIKI", True) and not (needs_rag and not _FRESHNESS_SIGNAL.search(body) and material_id)

    return ExpertAnswerPlan(
        topic=topic,
        domain=domain,
        depth=depth,
        knowledge_level_ko=_DEPTH_TO_KO.get(depth, knowledge_level_ko or "학사"),
        format_hint=fmt,
        needs_web_search=needs_web,
        needs_wikipedia=needs_wiki,
        needs_internal_rag=needs_rag,
        multi_perspective=multi,
        perspectives=perspectives,
        required_terms=required_terms,
        answer_sections=list(_DEFAULT_SECTIONS),
        quality_checks=list(_DEFAULT_QUALITY_CHECKS),
        clean_question=body,
        search_query=topic,
    )


def _refine_plan_with_llm(plan: ExpertAnswerPlan, logs: List[str]) -> ExpertAnswerPlan:
    """OpenAI를 '질문 해석기/답변 설계자'로 사용해 plan을 보강한다(라우팅 플래그는 deterministic 유지).

    실패/미설정 시 deterministic plan을 그대로 사용한다.
    """
    if not _flag("EXPERT_ANSWER_LLM_PLAN", True):
        return plan
    sys = (
        "너는 학습 질문 분석가다. 입력 질문을 분석해 답변 설계에 필요한 메타데이터만 JSON으로 출력한다. "
        "설명/마크다운/코드블록 없이 순수 JSON 하나만 출력한다."
    )
    user = (
        f"질문: {plan.clean_question}\n"
        f"감지된 주제: {plan.topic}\n"
        f"감지된 도메인: {plan.domain}\n\n"
        "아래 형식의 JSON만 출력하라(키 추가/누락 금지):\n"
        "{\n"
        '  "topic": "핵심 주제(짧게)",\n'
        '  "domain": "주제가 속한 분야(한국어, 한 단어~짧은 구)",\n'
        '  "required_terms": ["이 주제를 전문적으로 설명할 때 반드시 정의해야 할 핵심 전문용어 6~12개"],\n'
        '  "perspectives": ["이 주제를 다각도로 볼 때 유효한 관점 라벨 3~6개"]\n'
        "}"
    )
    txt = _openai_json(sys, user)
    if not txt:
        return plan
    data = _safe_json(txt)
    if not isinstance(data, dict):
        return plan
    try:
        if isinstance(data.get("topic"), str) and data["topic"].strip():
            plan.topic = data["topic"].strip()[:80]
            plan.search_query = plan.topic
        if isinstance(data.get("domain"), str) and data["domain"].strip():
            plan.domain = (plan.domain if plan.domain != "general" else data["domain"].strip()[:40])
        terms = [str(t).strip() for t in (data.get("required_terms") or []) if str(t).strip()]
        if terms:
            merged = list(dict.fromkeys([*plan.required_terms, *terms]))
            plan.required_terms = merged[:14]
        persp = [str(p).strip() for p in (data.get("perspectives") or []) if str(p).strip()]
        persp = [p for p in persp if not _GENERIC_PERSPECTIVE.search(p)]  # 정의 섹션과 중복되는 일반 라벨 제외
        if persp and plan.multi_perspective and not _parse_explicit_perspectives(plan.clean_question):
            merged_p = list(dict.fromkeys([*plan.perspectives, *persp]))
            plan.perspectives = merged_p[:5]
        logs.append("질문 분석(OpenAI)으로 답변 설계를 보강했습니다.")
    except Exception as e:  # noqa: BLE001
        logger.info("plan 보강 파싱 실패(무시): %s", e)
    return plan


def analyze_query(
    question: str,
    knowledge_level_ko: str,
    material_id: Optional[int],
    has_rag_context: bool,
    logs: List[str],
) -> ExpertAnswerPlan:
    plan = _deterministic_plan(question, knowledge_level_ko, material_id, has_rag_context)
    plan = _refine_plan_with_llm(plan, logs)
    logs.append(f"의도 분석 완료: {plan.summary()}")
    return plan


# ──────────────────────────────────────────────────────────────────────────────
# 2~3. Retrieval + Evidence Selection
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Evidence:
    source: str        # rag | wikipedia | tavily
    title: str
    url: str
    content: str
    raw_score: float = 0.0
    final_score: float = 0.0


_AUTHORITY = {"rag": 1.0, "wikipedia": 0.8, "tavily": 0.62}
_FRESHNESS = {"rag": 0.6, "wikipedia": 0.45, "tavily": 0.85}
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")


def _tokens(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 1]


def _relevance(topic_tokens: set, text: str) -> float:
    toks = set(_tokens(text))
    if not toks or not topic_tokens:
        return 0.0
    overlap = len(topic_tokens & toks)
    return min(1.0, overlap / max(2, len(topic_tokens)))


def _gather_evidence(plan: ExpertAnswerPlan, material_id: Optional[int], rag_context: str, logs: List[str]) -> List[Evidence]:
    out: List[Evidence] = []
    budget = max(2.0, float(_int("EXPERT_ANSWER_RETRIEVAL_TIMEOUT", 6)))

    # 내부 RAG: caller가 넘겨준 컨텍스트 우선 사용, 없으면 material_id로 조회
    if plan.needs_internal_rag:
        try:
            if rag_context and rag_context.strip():
                out.append(Evidence(source="rag", title="업로드 자료(RAG)", url="", content=rag_context.strip()[:1600], raw_score=1.0))
                logs.append("내부 RAG 컨텍스트를 근거로 사용했습니다.")
            elif material_id is not None:
                from app.services.pdf_rag_service import search_pdf_context
                for c in (search_pdf_context(plan.clean_question or plan.topic, material_id, top_k=5) or []):
                    out.append(Evidence(
                        source="rag",
                        title=c.get("document_title", "") or "업로드 자료",
                        url="",
                        content=(c.get("content", "") or "")[:700],
                        raw_score=float(c.get("similarity", 0.0)),
                    ))
                if out:
                    logs.append(f"내부 RAG에서 {len(out)}개 청크를 검색했습니다.")
        except Exception as e:  # noqa: BLE001
            logs.append(f"내부 RAG 검색 생략(계속 진행): {e}")

    # 외부 검색(Wikipedia/Tavily)을 병렬 best-effort 수집
    tasks = []
    if plan.needs_wikipedia:
        tasks.append(("wikipedia", lambda: _fetch_wikipedia(plan.search_query)))
    if plan.needs_web_search:
        tasks.append(("tavily", lambda: _fetch_tavily(plan.search_query)))

    if tasks:
        t0 = time.time()
        try:
            with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
                futs = {ex.submit(fn): name for name, fn in tasks}
                for fut in as_completed(futs, timeout=budget + 1):
                    name = futs[fut]
                    remaining = max(1.0, budget - (time.time() - t0))
                    try:
                        got = fut.result(timeout=remaining) or []
                        out.extend(got)
                        if got:
                            logs.append(f"{name} 근거 {len(got)}건 수집")
                    except Exception as e:  # noqa: BLE001
                        logs.append(f"{name} 검색 생략: {type(e).__name__}")
        except Exception as e:  # noqa: BLE001
            logs.append(f"외부 검색 일부 생략(타임아웃 등): {type(e).__name__}")

    return out


def _fetch_wikipedia(query: str) -> List[Evidence]:
    from app.services.wikipedia_service import search_wikipedia
    res = []
    for r in (search_wikipedia(query, limit=3) or []):
        snippet = (r.get("snippet", "") or "").strip()
        if not snippet:
            continue
        res.append(Evidence(source="wikipedia", title=r.get("title", ""), url=r.get("url", ""),
                            content=snippet[:600], raw_score=0.6))
    return res


def _fetch_tavily(query: str) -> List[Evidence]:
    from app.services.tavily_service import search_web
    res = []
    for r in (search_web(query, max_results=4) or []):
        content = (r.get("content", "") or "").strip()
        if not content:
            continue
        res.append(Evidence(source="tavily", title=r.get("title", ""), url=r.get("url", ""),
                            content=content[:600], raw_score=float(r.get("score", 0.0) or 0.0)))
    return res


def _select_evidence(plan: ExpertAnswerPlan, items: List[Evidence], logs: List[str]) -> List[Evidence]:
    """relevance/authority/freshness로 점수화하고 중복 제거 후 top N만 남긴다."""
    if not items:
        return []
    topic_tokens = set(_tokens(f"{plan.topic} {plan.clean_question}"))
    fresh_weight = 0.25 if plan.needs_web_search else 0.05

    for ev in items:
        rel = _relevance(topic_tokens, f"{ev.title} {ev.content}")
        auth = _AUTHORITY.get(ev.source, 0.5)
        fresh = _FRESHNESS.get(ev.source, 0.5)
        ev.final_score = 0.55 * rel + (0.40 - fresh_weight) * auth + fresh_weight * fresh

    # 점수순 정렬 후 중복(내용 유사) 제거
    items.sort(key=lambda e: e.final_score, reverse=True)
    selected: List[Evidence] = []
    seen_sigs: List[set] = []
    top_n = max(3, min(5, _int("EXPERT_ANSWER_MAX_EVIDENCE", 5)))
    for ev in items:
        sig = set(_tokens(ev.content)[:40])
        if any(sig and len(sig & s) / max(1, len(sig)) > 0.6 for s in seen_sigs):
            continue  # 기존 근거와 60% 이상 겹치면 중복으로 간주
        selected.append(ev)
        seen_sigs.append(sig)
        if len(selected) >= top_n:
            break
    if selected:
        logs.append(f"근거 {len(items)}건 중 {len(selected)}건을 선별했습니다(중복 제거·관련성 우선).")
    return selected


# ──────────────────────────────────────────────────────────────────────────────
# 4. Expert Synthesis
# ──────────────────────────────────────────────────────────────────────────────
def _format_hint_instruction(fmt: str) -> str:
    if fmt == "json":
        return ("- 사용자가 JSON 형식을 선호했다. '예시' 섹션에 해당 개념을 표현하는 구조를 "
                "```json 코드블록으로 반드시 포함하라. 단, 전체 답변은 마크다운 설명을 유지한다.")
    if fmt == "table":
        return "- '여러 관점 비교'는 마크다운 표(| 관점 | 핵심 | 장점 | 한계 |)로 정리하라."
    if fmt == "code":
        return "- '예시' 섹션에 실행 가능한 코드 예시를 코드블록으로 포함하라."
    return "- 마크다운 헤딩(##)과 글머리표로 가독성 있게 구성하라."


def _build_synthesis_system_prompt(base_system_prompt: str, plan: ExpertAnswerPlan, level_directive: str,
                                   mode_cfg: Any = None, effective_multi: Optional[bool] = None,
                                   sections_override: Optional[List[str]] = None) -> str:
    multi = plan.multi_perspective if effective_multi is None else effective_multi
    persp_line = ""
    if multi:
        labels = plan.perspectives or _DEFAULT_PERSPECTIVES
        persp_line = (
            "[다관점 정책]\n"
            "- 이 질문은 다각도 설명을 요구한다. 아래 관점을 각각 소제목으로 나눠 비교하라(각 관점의 핵심 주장과 한계 포함):\n"
            f"  {', '.join(labels)}\n"
            "- 관점들이 서로 어디서 충돌하고 어디서 보완되는지 명시하라.\n"
        )
    terms_line = ""
    if plan.required_terms:
        terms_line = (
            "[필수 용어]\n"
            f"- 다음 전문용어를 답변에서 반드시 사용하고, 각 용어 첫 등장 시 뜻을 즉시 풀어라: {', '.join(plan.required_terms)}\n"
        )

    terminology_policy = (
        "[전문용어 정책]\n"
        "- 전문용어를 회피하지 말고 정확히 사용하되, 처음 나올 때 괄호나 짧은 문장으로 뜻을 즉시 풀어라.\n"
        "  예) 캡슐화(encapsulation): 객체 내부 상태를 외부에서 직접 훼손하지 못하게 보호하는 경계.\n"
        "  예) 다형성(polymorphism): 같은 인터페이스 호출이 객체 타입에 따라 다른 구현으로 실행되는 성질.\n"
        "  예) 동적 디스패치(dynamic dispatch): 런타임에 실제 객체 타입으로 호출 메서드를 결정하는 메커니즘.\n"
    )

    # ── 모드 정책 경로: 모드 계약(역할+answer_sections+품질규칙)을 SSOT로 사용한다 ──
    if mode_cfg is not None:
        from app.services import mode_ai_config as _mc
        head = (base_system_prompt or "").strip() or \
            (getattr(mode_cfg, "system_prompt", "") or _mc.COMMON_SYSTEM_HEADER).strip()
        contract = _mc.build_answer_contract(mode_cfg, sections=sections_override)
        quality = _mc.build_quality_rules(mode_cfg)
        include_terms = bool(getattr(mode_cfg, "require_terminology_explanation", True))
        grounding = (
            "[근거 합성 정책]\n"
            "- [수집 근거]가 주어지면 단순 나열하지 말고 설명 속에 자연스럽게 녹여 종합하라.\n"
            "- 근거에 없고 확실하지 않은 사실은 단정하지 말고 추정임을 밝혀라.\n"
        )
        if getattr(mode_cfg, "use_quality_validator", False):
            grounding += "- 얕은 요약이 아니라 원리·구조까지 깊이 있게 설명하라.\n"
        parts = [
            head,
            contract,
            quality,
            (terminology_policy if include_terms else ""),
            persp_line,
            terms_line,
            grounding,
            _format_hint_instruction(plan.format_hint),
            (level_directive or "").strip(),
        ]
        return "\n\n".join(p for p in parts if p and str(p).strip())

    # ── 기본 경로(모드 미지정): 기존 9섹션 전문가 구조를 그대로 유지(하위 호환) ──
    structure = (
        "[답변 구조 — 반드시 이 순서의 섹션을 모두 채운다]\n"
        "1) 한 줄 결론: 질문에 대한 핵심 답을 한 문장으로.\n"
        "2) 핵심 개념 정의: 주제를 정확히 정의.\n"
        "3) 전문적 설명: 작동 원리·구조를 깊이 있게.\n"
        "4) 전문용어 풀이: 등장한 전문용어를 '용어(영문): 한 줄 정의' 형식으로 정리.\n"
        "5) 여러 관점 비교: (다관점 요청 시) 이론/실무/설계/비판 등 관점별로 비교.\n"
        "6) 예시: 코드·JSON·객체 모델·시나리오 중 적절한 형식으로 구체적 예시.\n"
        "7) 흔한 오해: 학습자가 자주 틀리는 지점과 바로잡기.\n"
        "8) 요약: 3~5개 글머리표로 핵심 재정리.\n"
        "9) 참고 근거: 사용한 근거(제공된 자료/출처)를 간단히 정리. 근거가 없으면 '모델 지식 기반'이라고 밝힌다.\n"
    )
    grounding_policy = (
        "[근거 합성 정책]\n"
        "- 아래 [수집 근거]가 주어지면 단순 나열하지 말고 네 설명 속에 자연스럽게 녹여 종합하라.\n"
        "- 근거에 없고 확실하지 않은 사실은 단정하지 말고 추정임을 밝혀라.\n"
        "- 후배 개발자에게 강의하듯, 얕은 요약이 아니라 깊이 있게 설명하라.\n"
    )

    parts = [
        (base_system_prompt or "너는 StudyBridge의 전문 학습 에이전트다.").strip(),
        "",
        "지금부터 너는 해당 주제를 깊이 이해한 전문가로서, 후배에게 강의하듯 답한다. 반드시 한국어로 답한다.",
        "",
        structure,
        terminology_policy,
        persp_line,
        terms_line,
        grounding_policy,
        _format_hint_instruction(plan.format_hint),
        (level_directive or "").strip(),
    ]
    return "\n".join(p for p in parts if p is not None and str(p).strip() != "" or p == "")


def _build_synthesis_user_prompt(plan: ExpertAnswerPlan, evidence: List[Evidence]) -> str:
    ev_block = ""
    if evidence:
        lines = []
        for i, ev in enumerate(evidence, 1):
            head = f"[근거{i} · {ev.source}] {ev.title}".strip()
            url = f" ({ev.url})" if ev.url else ""
            lines.append(f"{head}{url}\n{ev.content}".strip())
        ev_block = "## 수집 근거\n" + "\n\n".join(lines) + "\n\n"
    persp = ""
    if plan.multi_perspective and (plan.perspectives or True):
        persp = f"- 요청 관점: {', '.join(plan.perspectives or _DEFAULT_PERSPECTIVES)}\n"
    return (
        f"{ev_block}"
        f"## 요청 정보\n"
        f"- 주제: {plan.topic}\n"
        f"- 원본 질문: {plan.clean_question}\n"
        f"- 목표 수준: {plan.knowledge_level_ko}\n"
        f"- 요청 형식: {plan.format_hint}\n"
        f"{persp}"
        f"\n## 작성 지시\n"
        "위 근거와 너의 전문 지식을 종합하여, 시스템 프롬프트가 지정한 섹션 구조와 답변 계약을 "
        "그대로 따라 답변을 작성하라. 섹션 제목을 그대로 사용하라."
    )


def _synthesis_max_tokens(plan: ExpertAnswerPlan) -> int:
    base = 1600
    try:
        from app.services import level_policy
        base = level_policy.max_tokens(plan.knowledge_level_ko)
    except Exception:  # noqa: BLE001
        base = {"beginner": 1300, "undergraduate": 1600, "graduate": 2800, "phd": 3800, "expert": 3800}.get(plan.depth, 1600)
    # 캡은 level_policy의 레벨별 예산(박사/전문가=3800)을 깎지 않도록 정렬한다.
    # (2600으로 두면 9섹션+다관점 박사 답변이 '요약/참고 근거' 직전에 잘렸음)
    cap = _int("EXPERT_ANSWER_MAX_TOKENS", 3800)
    return max(900, min(base, cap))


def _level_directive(plan: ExpertAnswerPlan) -> str:
    try:
        from app.services import level_policy
        return level_policy.directive(plan.knowledge_level_ko)
    except Exception:  # noqa: BLE001
        return ""


def _synthesize(plan: ExpertAnswerPlan, evidence: List[Evidence], base_system_prompt: str, logs: List[str],
                mode_cfg: Any = None, effective_multi: Optional[bool] = None,
                max_tokens_override: Optional[int] = None,
                sections_override: Optional[List[str]] = None) -> str:
    system_prompt = _build_synthesis_system_prompt(
        base_system_prompt, plan, _level_directive(plan),
        mode_cfg=mode_cfg, effective_multi=effective_multi, sections_override=sections_override,
    )
    user_prompt = _build_synthesis_user_prompt(plan, evidence)
    max_tokens = _synthesis_max_tokens(plan)
    temperature = 0.45
    if mode_cfg is not None:
        # 방 모드 정책의 temperature를 따른다. max_tokens는 Ollama 보호용 하드캡
        # (_synthesis_max_tokens의 EXPERT_ANSWER_MAX_TOKENS) 이내에서 모드 예산을 허용한다.
        temperature = float(getattr(mode_cfg, "temperature", temperature))
        try:
            mode_budget = int(getattr(mode_cfg, "max_tokens", max_tokens))
            hard_cap = _int("EXPERT_ANSWER_MAX_TOKENS", 3800)
            max_tokens = max(max_tokens, min(mode_budget, hard_cap))
        except (TypeError, ValueError):
            pass
    # 게이트(depth)가 준 토큰 예산이 있으면 그것을 우선한다(light=짧게/expert=길게). Ollama 보호 하드캡 유지.
    if max_tokens_override:
        try:
            hard_cap = _int("EXPERT_ANSWER_MAX_TOKENS", 3800)
            max_tokens = max(700, min(int(max_tokens_override), hard_cap))
        except (TypeError, ValueError):
            pass
    answer = _generate(system_prompt, user_prompt, max_tokens=max_tokens, temperature=temperature)
    logs.append(f"전문가 답변을 합성했습니다(max_tokens={max_tokens}, temp={temperature}).")
    return answer


# ──────────────────────────────────────────────────────────────────────────────
# 5. Quality Validation + Augmentation
# ──────────────────────────────────────────────────────────────────────────────
_TERM_DEF_RE = re.compile(r"[가-힣A-Za-z][^\n()]{0,18}\([A-Za-z][^)\n]{1,40}\)")  # 캡슐화(encapsulation)
_CODE_FENCE_RE = re.compile(r"```")
_JSON_FENCE_RE = re.compile(r"```json", re.I)
_PERSPECTIVE_MARKERS = ("이론", "실무", "설계", "아키텍처", "비판", "관점", "유지보수", "함수형")
_SECTION_MARKERS = ("결론", "정의", "설명", "용어", "관점", "예시", "오해", "요약", "근거", "출처")


def _validate(plan: ExpertAnswerPlan, answer: str) -> Tuple[bool, List[str]]:
    issues: List[str] = []
    a = answer or ""

    term_defs = len(_TERM_DEF_RE.findall(a))
    min_terms = 1 if plan.depth == "beginner" else 3
    if term_defs < min_terms:
        issues.append(f"전문용어 뜻풀이가 부족함(감지 {term_defs}<{min_terms}). '용어(영문): 정의' 형식을 더 넣어라")

    if plan.multi_perspective:
        marks = sum(1 for m in _PERSPECTIVE_MARKERS if m in a)
        if marks < 3:
            issues.append("여러 관점 비교가 약함. 이론/실무/설계/비판 관점을 각각 소제목으로 분리하라")

    if not _CODE_FENCE_RE.search(a) and "예시" not in a:
        issues.append("구체적 예시가 없음. 코드/JSON/시나리오 예시를 추가하라")

    if plan.format_hint == "json" and not _JSON_FENCE_RE.search(a):
        issues.append("요청한 JSON 예시(```json 블록)가 빠졌다. 예시 섹션에 추가하라")

    sections = sum(1 for m in _SECTION_MARKERS if m in a)
    if sections < 5:
        issues.append("요구한 9개 섹션 구조가 충분히 반영되지 않음. 섹션 제목을 명시하라")

    # 분량(너무 추상/짧음 방지): 수준별 최소치의 절반을 하한으로
    try:
        from app.services import level_policy
        floor = int(level_policy.min_chars(plan.knowledge_level_ko) * 0.5)
    except Exception:  # noqa: BLE001
        floor = 600
    if len(a) < max(450, floor):
        issues.append(f"설명이 짧고 추상적임(현재 {len(a)}자). 더 깊고 구체적으로 확장하라")

    return (len(issues) == 0, issues)


def _quality_issues(plan: ExpertAnswerPlan, answer: str, mode_cfg: Any = None,
                    effective_multi: Optional[bool] = None,
                    min_terms_override: Optional[int] = None) -> Tuple[List[str], str]:
    """(issues, rewrite_instructions) 반환.
    mode_cfg가 있으면 전용 검증기(answer_quality_validator)를, 없으면 내부 _validate를 사용한다."""
    if mode_cfg is not None:
        try:
            from app.services import answer_quality_validator as aqv
            mt = min_terms_override if min_terms_override is not None else (1 if plan.depth == "beginner" else None)
            res = aqv.validate(
                answer, mode_cfg,
                multi_perspective=effective_multi,
                format_hint=plan.format_hint,
                min_terms_override=mt,
            )
            return (list(res.get("missing") or []), str(res.get("rewrite_instructions") or ""))
        except Exception as e:  # noqa: BLE001
            logger.info("전용 검증기 실패 → 내부 검증 사용: %s", e)
    _, issues = _validate(plan, answer)
    return (issues, "")


def _augment(plan: ExpertAnswerPlan, draft: str, issues: List[str], base_system_prompt: str, logs: List[str],
             mode_cfg: Any = None, effective_multi: Optional[bool] = None, rewrite_instructions: str = "",
             sections_override: Optional[List[str]] = None, max_tokens_override: Optional[int] = None,
             min_terms_override: Optional[int] = None) -> str:
    """검증에서 발견된 부족분만 보강해 재작성한다(1회)."""
    if not _flag("EXPERT_ANSWER_AUGMENT", True) or not issues:
        return draft
    system_prompt = _build_synthesis_system_prompt(
        base_system_prompt, plan, _level_directive(plan),
        mode_cfg=mode_cfg, effective_multi=effective_multi, sections_override=sections_override,
    )
    instr = rewrite_instructions.strip() if (rewrite_instructions and rewrite_instructions.strip()) \
        else ("- " + "\n- ".join(issues))
    temperature = float(getattr(mode_cfg, "temperature", 0.4)) if mode_cfg is not None else 0.4
    aug_tokens = _synthesis_max_tokens(plan)
    if max_tokens_override:
        try:
            aug_tokens = max(700, min(int(max_tokens_override), _int("EXPERT_ANSWER_MAX_TOKENS", 3800)))
        except (TypeError, ValueError):
            pass
    user_prompt = (
        "아래는 같은 질문에 대한 1차 초안이다. 좋은 부분은 유지하되, 지적된 부족분을 반드시 보강해 "
        "더 전문적이고 구조적인 최종본으로 다시 작성하라. 한국어로, 지정된 섹션 구조를 따른다.\n\n"
        f"## 주제\n{plan.topic}\n\n"
        f"## 보강해야 할 점\n{instr}\n\n"
        f"## 1차 초안\n{draft[:3500]}"
    )
    improved = _generate(system_prompt, user_prompt, max_tokens=aug_tokens, temperature=temperature)
    if _looks_failed(improved):
        return draft
    # 보강본이 더 낫거나(부족분 감소) 더 길면 채택
    new_issues, _ = _quality_issues(plan, improved, mode_cfg, effective_multi, min_terms_override=min_terms_override)
    if len(new_issues) <= len(issues) or len(improved) > len(draft) * 1.05:
        logs.append(f"검증 보강 1회 적용(이슈 {len(issues)}→{len(new_issues)}).")
        return improved
    return draft


# ──────────────────────────────────────────────────────────────────────────────
# LLM 호출 헬퍼 (Ollama think=False 본문 / OpenAI JSON·검토)
# ──────────────────────────────────────────────────────────────────────────────
_FAIL_MARKERS = (
    "현재 Ollama", "AI 응답이", "Ollama 응답", "Ollama 서버", "[Ollama", "[GPT",
    "현재 AI 서비스", "일시적인 오류", "OPENAI_API_KEY", "비활성화",
)


def _looks_failed(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 15:
        return True
    return any(t.startswith(m) or m in t[:48] for m in _FAIL_MARKERS)


def _looks_truncated(text: str) -> bool:
    """답변이 단어/문장 중간에서 끊겼는지(토큰 소진 등) 추정한다."""
    t = (text or "").rstrip()
    if not t:
        return False
    if t.count("```") % 2 == 1:          # 미닫힌 코드펜스 = 명백한 절단
        return True
    last_line = t.splitlines()[-1].strip()
    if not last_line or last_line[0] in "#|>" or set(last_line) <= set("-=*"):
        return False                     # 헤딩/표/구분선으로 끝나면 정상 종료
    if t[-1] in "。.!?…:\"'`)»】」』”’":     # 종결 부호로 끝나면 정상
        return False
    return True                          # 그 외(글자/미닫힌 강조 중간) = 절단으로 간주


def _finalize_answer(text: str, logs: List[str]) -> str:
    """절단된 답변을 사용자에게 깔끔히 보이도록 마무리(코드펜스 닫기·불완전 말미 정리·미닫힌 강조 제거)."""
    if not text:
        return text
    t = text.rstrip()
    if not _looks_truncated(t):
        return t
    changed = False
    if t.count("```") % 2 == 1:           # 1) 미닫힌 코드펜스 닫기
        t = t + "\n```"
        changed = True
    else:                                 # 2) 불완전한 마지막 문장 잘라내기(60%+ 보존될 때만)
        ends = list(re.finditer(r"[。.!?…][)\"'”’」』]?(?:\s|$)", t))
        if ends and ends[-1].end() >= len(t) * 0.6:
            t = t[:ends[-1].end()].rstrip()
            changed = True
    if t.count("**") % 2 == 1:            # 3) 말미의 미닫힌 굵게(**) 정리
        idx = t.rfind("**")
        if idx >= len(t) - 80:
            t = t[:idx].rstrip()
            changed = True
    if changed:
        logs.append("답변이 잘린 것으로 보여 말미를 정리했습니다.")
    return t


def _generate(system_prompt: str, user_prompt: str, max_tokens: int, temperature: float) -> str:
    """본문 생성: Ollama(qwen think=False) 우선 → OpenAI fallback."""
    timeout = _int("EXPERT_ANSWER_OLLAMA_TIMEOUT", 110)
    try:
        from app.services.ollama_client import ask_ollama, is_ollama_available
        if is_ollama_available():
            txt = ask_ollama(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                think=False,          # qwen3 thinking이 num_predict를 소진하는 것 방지
                timeout=timeout,
            )
            if not _looks_failed(txt):
                return txt
            logger.info("Ollama 본문 생성 실패/빈응답 → OpenAI fallback")
    except Exception as e:  # noqa: BLE001
        logger.warning("Ollama 본문 생성 예외 → OpenAI fallback: %s", e)

    # OpenAI fallback
    try:
        from app.services.openai_client import chat_sync, is_enabled
        if is_enabled():
            txt = chat_sync(system=system_prompt, user=user_prompt,
                            temperature=temperature, max_tokens=min(max_tokens, 4000))
            if not _looks_failed(txt):
                return txt
    except Exception as e:  # noqa: BLE001
        logger.warning("OpenAI 본문 fallback 예외: %s", e)
    return ""


def _openai_json(system_prompt: str, user_prompt: str) -> str:
    """질문 분석/설계용 JSON 호출. OpenAI 우선, 미설정 시 Ollama think=False."""
    try:
        from app.services.openai_client import chat_sync, is_enabled
        if is_enabled():
            txt = chat_sync(system=system_prompt, user=user_prompt, temperature=0.0, max_tokens=600)
            if not _looks_failed(txt):
                return txt
    except Exception as e:  # noqa: BLE001
        logger.info("OpenAI plan 호출 실패: %s", e)
    # Ollama fallback (think=False로 JSON 오염 방지)
    try:
        from app.services.ollama_client import ask_ollama, is_ollama_available
        if is_ollama_available():
            txt = ask_ollama(system_prompt=system_prompt, user_prompt=user_prompt,
                             max_tokens=600, temperature=0.0, think=False,
                             timeout=_int("EXPERT_ANSWER_OLLAMA_TIMEOUT", 110))
            if not _looks_failed(txt):
                return txt
    except Exception as e:  # noqa: BLE001
        logger.info("Ollama plan fallback 실패: %s", e)
    return ""


def _safe_json(text: str) -> Optional[Any]:
    if not text:
        return None
    s = text.strip()
    # 코드펜스 제거
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.I | re.M).strip()
    # 첫 {...} 블록 추출
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        s = s[start:end + 1]
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────────────────────────────────
def generate_expert_answer(
    question: str,
    knowledge_level: str = "학사",
    personality: str = "친절_설명형",
    agent_name: str = "StudyBridge",
    custom_instruction: Optional[str] = None,
    material_id: Optional[int] = None,
    rag_context: str = "",
    base_system_prompt: str = "",
    mode: Optional[str] = None,
    gate_overrides: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    질문을 전문가 수준 답변으로 변환한다.

    Returns:
        성공 시 {"answer": str, "plan": dict, "evidence": list, "process_logs": list, "engine": str}
        실패/비활성 시 None (caller가 기존 단일 호출 경로로 폴백해야 함)
    """
    if not enabled():
        return None
    q = (question or "").strip()
    if not q:
        return None

    logs: List[str] = []
    t0 = time.time()
    try:
        # 1. Intent Analysis
        plan = analyze_query(q, knowledge_level, material_id, bool(rag_context and rag_context.strip()), logs)

        # 1b. 방 모드 정책(ModeAIConfig) 적용 — mode가 주어졌고 정책이 켜졌을 때만.
        #     (mode 미지정 시 기존 동작과 100% 동일하게 유지한다.)
        mode_cfg = None
        effective_multi = plan.multi_perspective
        try:
            from app.services import mode_ai_config as _mc
            if mode and _mc.config_enabled():
                mode_cfg = _mc.get_mode_config(mode)
                # 도구 사용 상한: 모드가 끈 도구는 질문 신호와 무관하게 끈다.
                plan.needs_wikipedia = plan.needs_wikipedia and bool(mode_cfg.use_wikipedia)
                plan.needs_web_search = plan.needs_web_search and bool(mode_cfg.use_tavily)
                plan.needs_internal_rag = plan.needs_internal_rag and bool(mode_cfg.use_rag)
                # 1순위 도구 강제(예: research→Tavily, rag→RAG). 키/자료 없으면 수집 단계에서 자동 생략.
                if mode_cfg.primary_tool == "tavily" and mode_cfg.use_tavily:
                    plan.needs_web_search = True
                if mode_cfg.primary_tool == "rag" and mode_cfg.use_rag and (
                    material_id or (rag_context and rag_context.strip())
                ):
                    plan.needs_internal_rag = True
                # 다관점: 모드 요구(floor) ∪ 질문 신호(escalation)
                effective_multi = bool(plan.multi_perspective or mode_cfg.require_multiple_perspectives)
                plan.multi_perspective = effective_multi
                logs.append(
                    f"방 모드 정책 적용: {mode_cfg.mode}({mode_cfg.display_name}) "
                    f"wiki={plan.needs_wikipedia} web={plan.needs_web_search} rag={plan.needs_internal_rag} "
                    f"multi={effective_multi} validator={mode_cfg.use_quality_validator}"
                )
        except Exception as e:  # noqa: BLE001
            logger.info("mode 정책 적용 생략(계속 진행): %s", e)
            mode_cfg = None

        # 1c. 게이트 오버라이드 적용(mode_gate.should_use_expert_orchestrator 결과).
        #     도구/다관점/토큰/섹션/검증 강도를 게이트가 최종 결정한다(없으면 위 모드 정책 유지).
        sections_override: Optional[List[str]] = None
        max_tokens_override: Optional[int] = None
        min_terms_override: Optional[int] = None
        use_validator_override: Optional[bool] = None
        ov = gate_overrides or {}
        if ov:
            if "use_wikipedia" in ov:
                plan.needs_wikipedia = bool(ov["use_wikipedia"])
            if "use_tavily" in ov:
                plan.needs_web_search = bool(ov["use_tavily"])
            if "use_rag" in ov:
                plan.needs_internal_rag = bool(ov["use_rag"])
            if "multi_perspective" in ov:
                effective_multi = bool(ov["multi_perspective"])
                plan.multi_perspective = effective_multi
            secs = ov.get("sections")
            max_secs = ov.get("max_sections")
            if secs:
                sections_override = list(secs)
            elif max_secs and mode_cfg is not None:
                sections_override = list(mode_cfg.answer_sections)
            if sections_override and max_secs:
                try:
                    sections_override = sections_override[:max(1, int(max_secs))]
                except (TypeError, ValueError):
                    pass
            if ov.get("max_tokens"):
                max_tokens_override = ov.get("max_tokens")
            if ov.get("min_terms") is not None:
                min_terms_override = ov.get("min_terms")
            if ov.get("use_validator") is not None:
                use_validator_override = bool(ov.get("use_validator"))
            logs.append(
                "게이트 오버라이드: "
                f"depth={ov.get('depth')} sections={len(sections_override) if sections_override else '-'} "
                f"max_tokens={max_tokens_override or '-'} wiki={plan.needs_wikipedia} "
                f"web={plan.needs_web_search} rag={plan.needs_internal_rag} multi={effective_multi}"
            )

        # 2~3. Retrieval + Evidence Selection
        evidence = _select_evidence(plan, _gather_evidence(plan, material_id, rag_context, logs), logs)

        # 4. Expert Synthesis (모드 정책 + 게이트 오버라이드의 temperature/max_tokens/섹션 반영)
        draft = _synthesize(plan, evidence, base_system_prompt, logs,
                            mode_cfg=mode_cfg, effective_multi=effective_multi,
                            max_tokens_override=max_tokens_override, sections_override=sections_override)
        if _looks_failed(draft):
            logs.append("본문 생성에 실패하여 기본 답변 경로로 폴백합니다.")
            return None

        # 5. Validation (+ optional augmentation). 모드/게이트가 검증을 끄면 생략한다.
        if use_validator_override is not None:
            use_validator = use_validator_override
        else:
            use_validator = mode_cfg.use_quality_validator if mode_cfg is not None else True
        if use_validator:
            issues, rewrite = _quality_issues(plan, draft, mode_cfg, effective_multi,
                                              min_terms_override=min_terms_override)
            if issues:
                logs.append("품질 검증 미충족 항목: " + "; ".join(issues))
                draft = _augment(plan, draft, issues, base_system_prompt, logs,
                                 mode_cfg=mode_cfg, effective_multi=effective_multi,
                                 rewrite_instructions=rewrite, sections_override=sections_override,
                                 max_tokens_override=max_tokens_override, min_terms_override=min_terms_override)
            else:
                logs.append("품질 검증 통과(전문용어·다관점·예시·구조·분량).")
        else:
            logs.append(f"이 모드({getattr(mode_cfg, 'mode', '?')})는 품질 검증을 생략합니다.")

        # 토큰 소진 등으로 말미가 잘렸으면 깔끔히 마무리(사용자가 단어 중간 절단을 보지 않도록)
        draft = _finalize_answer(draft, logs)

        logs.append(f"전문가 오케스트레이터 완료({time.time() - t0:.1f}s).")
        return {
            "answer": draft.strip(),
            "mode": getattr(mode_cfg, "mode", None),
            "plan": asdict(plan),
            "evidence": [
                {"source": e.source, "title": e.title, "url": e.url, "score": round(e.final_score, 3)}
                for e in evidence
            ],
            "process_logs": logs,
            "engine": "expert_answer_orchestrator",
        }
    except Exception as e:  # noqa: BLE001
        logger.error("expert_answer_orchestrator 실패(폴백): %s", e, exc_info=True)
        return None
