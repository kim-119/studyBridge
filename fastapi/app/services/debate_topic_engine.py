"""
토론 모드 논제선택 엔진.

토론 모드의 동작 계약:
    개념 질문 입력
    → 핵심 개념 추출 → 개념 청킹 → 토론 가능한 논제 후보 5개 생성   (TOPIC_SELECTION)
    → 사용자가 논제 선택
    → 선택 논제 기준 찬성/반대/반박/쟁점/학습정리 생성                (DEBATE_ROUND)

핵심 불변조건:
  - 토론 모드는 generic explanation이 아니다. 첫 턴엔 절대 본 토론(찬반)을 시작하지 않는다.
  - selectedTopic / debateState.topicSelected 가 없으면 무조건 TOPIC_SELECTION.
  - 논제 후보는 정확히 5개(topicId A~E), 각 후보는 찬반이 갈리는 문장이어야 한다.
  - LLM 실패/JSON 깨짐에도 deterministic fallback으로 동일 schema를 반드시 반환한다.

이 모듈은 라우팅/스트림 계층(multi_agent_service)과 분리된 순수 생성/정규화 계층이다.
(신규 파일 — 기존 endpoint/필드는 건드리지 않는 additive 구조.)
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 생성 파라미터 (스키마 안정성 우선) ────────────────────────────────────────
TOPIC_SELECTION_TEMPERATURE = 0.35
TOPIC_SELECTION_MAX_TOKENS = 1200
TOPIC_SELECTION_TOP_P = 0.9

DEBATE_ROUND_TEMPERATURE = 0.25
DEBATE_ROUND_MAX_TOKENS = 1600
DEBATE_ROUND_TOP_P = 0.85

_TOPIC_IDS = ["A", "B", "C", "D", "E"]

# 잘 알려진 개념의 정규화(설명형 별칭). 없으면 원문 유지.
_CONCEPT_NORMALIZE = {
    "ssh": "Secure Shell",
    "secure shell": "Secure Shell",
    "리버스 ssh": "Reverse SSH",
    "reverse ssh": "Reverse SSH",
    "viewmodel": "ViewModel (MVVM)",
    "객체지향": "객체지향 프로그래밍(OOP)",
    "oop": "객체지향 프로그래밍(OOP)",
}

# SSH 계열 전용 결정론 논제(품질 좋은 찬반 문장).
_SSH_TOPICS = [
    ("SSH는 원격 접속의 표준 도구로 반드시 먼저 배워야 하는가?", "학습 우선순위", "먼저 배워야 한다", "초보자에게는 나중에 배워도 된다"),
    ("SSH는 편리하지만 초보자에게 보안 위험을 더 키울 수 있는가?", "보안성", "편의가 위험을 키운다", "올바로 쓰면 오히려 안전하다"),
    ("비밀번호 로그인보다 공개키 인증을 기본값으로 사용해야 하는가?", "인증 정책", "공개키를 기본으로 해야 한다", "상황에 따라 비밀번호도 유효하다"),
    ("리버스 SSH는 일반 SSH보다 운영 장애 대응에 더 유용한가?", "운영 필요성", "장애 대응에 더 유용하다", "보안·복잡도 때문에 제한적이다"),
    ("SSH 터널링은 초보자가 초기에 배우기에는 과하게 복잡한가?", "복잡도", "초기엔 과하게 복잡하다", "기본만 익히면 충분히 배울 만하다"),
]
_SSH_CHUNKS = ["원격 접속", "보안 프로토콜", "암호화", "인증", "터널링"]
_SSH_AXES = ["보안성", "편의성", "복잡도", "운영 필요성", "학습 우선순위"]

# 일반 개념용 결정론 논제 템플릿. {c} = 개념.
_GENERIC_TOPIC_TEMPLATES = [
    ("{c}은(는) 초보자가 먼저 배워야 하는 핵심 개념인가?", "학습 우선순위", "먼저 배워야 한다", "기초를 먼저 다진 뒤 배워도 된다"),
    ("{c}은(는) 실무에서 이론보다 적용 경험이 더 중요한가?", "실무 적용", "적용 경험이 더 중요하다", "원리 이해가 먼저다"),
    ("{c}을(를) 잘못 이해하면 실제로 큰 문제가 발생하는가?", "오개념 위험", "큰 문제로 이어질 수 있다", "영향은 제한적이다"),
    ("{c}은(는) 다른 개념보다 우선해서 학습해야 하는가?", "학습 순서", "우선 학습해야 한다", "병행 학습이 낫다"),
    ("{c}은(는) 자동화 도구가 사람의 이해를 대체할 수 있는가?", "자동화 가능성", "도구가 상당 부분 대체한다", "이해 없이는 대체 불가다"),
]
_GENERIC_CHUNKS = ["핵심 정의", "동작 원리", "대표 사용 사례", "흔한 오개념", "관련 개념"]
_GENERIC_AXES = ["정확성", "실무 적용성", "학습 우선순위", "오개념 위험"]


# ─────────────────────────────────────────────────────────────────────────────
# 접근 헬퍼 (dict / pydantic / 일반 객체 공통)
# ─────────────────────────────────────────────────────────────────────────────
def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    val = getattr(obj, key, default)
    return val if val is not None else default


def make_debate_session_id() -> str:
    return f"debate-{uuid.uuid4().hex[:12]}"


# ─────────────────────────────────────────────────────────────────────────────
# phase 판별
# ─────────────────────────────────────────────────────────────────────────────
def selected_topic_of(req: Any) -> Optional[Dict[str, Any]]:
    """selectedTopic을 payload 최상위 또는 debateState에서 찾아 dict로 정규화한다."""
    state = _get(req, "debateState") or {}
    raw = _get(req, "selectedTopic") or _get(state, "selectedTopic")
    if not raw:
        return None
    if isinstance(raw, str):
        return {"topicId": None, "title": raw.strip()}
    if isinstance(raw, dict):
        title = (raw.get("title") or raw.get("topic") or raw.get("motion") or "").strip()
        if not title:
            return None
        return {"topicId": raw.get("topicId"), "title": title,
                "axis": raw.get("axis"), "proPosition": raw.get("proPosition"),
                "conPosition": raw.get("conPosition")}
    # pydantic 등 객체
    title = (_get(raw, "title") or "").strip()
    return {"topicId": _get(raw, "topicId"), "title": title} if title else None


def resolve_debate_phase(req: Any) -> str:
    """selectedTopic 또는 topicSelected가 있으면 DEBATE_ROUND, 아니면 TOPIC_SELECTION."""
    state = _get(req, "debateState") or {}
    if selected_topic_of(req):
        return "DEBATE_ROUND"
    if _get(req, "topicSelected") or _get(state, "topicSelected"):
        return "DEBATE_ROUND"
    return "TOPIC_SELECTION"


# ─────────────────────────────────────────────────────────────────────────────
# 개념 추출/정규화
# ─────────────────────────────────────────────────────────────────────────────
def extract_primary_concept(message: str) -> str:
    """설명형 질문에서 핵심 개념어만 뽑는다. (예: 'ssh가 뭐야?' → 'SSH')"""
    m = (message or "").strip()
    for cut in ["가 뭐", "이 뭐", "는 뭐", "란 ", "이란", "에 대해서", "에 대해",
                " 설명", " 알려", "어떤", "뭘", "무엇", "?", "？", "\n"]:
        idx = m.find(cut)
        if idx > 0:
            m = m[:idx]
            break
    concept = m.strip(" ,.!?'\"·-")
    if not concept:
        concept = (message or "").strip() or "이 개념"
    # 짧은 영문 약어는 대문자로 (ssh → SSH). 혼합/한글은 원형 유지.
    ascii_token = concept.replace(" ", "")
    if ascii_token.isascii() and ascii_token.isalpha() and len(ascii_token) <= 5 and ascii_token.islower():
        return concept.upper()
    return concept


def normalize_concept(concept: str) -> str:
    key = (concept or "").strip().lower()
    return _CONCEPT_NORMALIZE.get(key, concept)


# ─────────────────────────────────────────────────────────────────────────────
# JSON repair
# ─────────────────────────────────────────────────────────────────────────────
def strip_json_block(text: str) -> str:
    """LLM 응답에서 JSON 오브젝트만 추출한다.
    - <think>...</think> 제거
    - ```json fenced block 제거
    - 앞뒤 설명문 제거 → 첫 '{' 부터 균형 맞는 '}' 까지 추출
    """
    if not text:
        return ""
    s = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"```(?:json)?", "", s, flags=re.IGNORECASE)
    s = s.replace("```", "")
    start = s.find("{")
    if start == -1:
        return s.strip()
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1].strip()
    return s[start:].strip()


def _try_parse_json(text: str) -> Optional[Dict[str, Any]]:
    block = strip_json_block(text)
    if not block:
        return None
    try:
        data = json.loads(block)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning("[debate] JSON parse 실패: %s", e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 정규화(coerce): LLM 출력을 schema 계약에 맞게 보정
# ─────────────────────────────────────────────────────────────────────────────
def _clip_list(items: Any, lo: int, hi: int, filler: List[str]) -> List[str]:
    out = [str(x).strip() for x in (items or []) if str(x).strip()]
    if len(out) > hi:
        out = out[:hi]
    i = 0
    while len(out) < lo and i < len(filler):
        if filler[i] not in out:
            out.append(filler[i])
        i += 1
    while len(out) < lo:  # filler 부족 시 인덱스로 채움
        out.append(f"쟁점 {len(out) + 1}")
    return out


def coerce_topic_selection(data: Dict[str, Any], raw_question: str) -> Dict[str, Any]:
    """LLM TOPIC_SELECTION 출력을 schema 계약(후보 정확히 5개 등)으로 보정한다."""
    concept = (str(data.get("primaryConcept") or "").strip()
               or extract_primary_concept(raw_question))
    fb = fallback_topic_selection(raw_question)

    cands_in = data.get("debateTopicCandidates") or []
    norm: List[Dict[str, Any]] = []
    for c in cands_in:
        if not isinstance(c, dict):
            continue
        title = str(c.get("title") or c.get("topic") or "").strip()
        if not title:
            continue
        norm.append({
            "title": title,
            "axis": str(c.get("axis") or "").strip(),
            "proPosition": str(c.get("proPosition") or c.get("pro") or "").strip(),
            "conPosition": str(c.get("conPosition") or c.get("con") or "").strip(),
        })
    # 정확히 5개로 맞춘다: 부족하면 fallback 후보로 채우고, 넘치면 5개로 자른다.
    fb_cands = fb["debateTopicCandidates"]
    while len(norm) < 5:
        norm.append({k: v for k, v in fb_cands[len(norm)].items() if k != "topicId"})
    norm = norm[:5]
    for i, c in enumerate(norm):
        c["topicId"] = _TOPIC_IDS[i]
        if not c["axis"]:
            c["axis"] = fb_cands[i]["axis"]
        if not c["proPosition"]:
            c["proPosition"] = fb_cands[i]["proPosition"]
        if not c["conPosition"]:
            c["conPosition"] = fb_cands[i]["conPosition"]

    chunks = _clip_list(data.get("conceptChunks"), 4, 7, fb["conceptChunks"])
    axes = _clip_list(data.get("debateAxes"), 4, 6, fb["debateAxes"])

    return {
        "mode": "debate",
        "phase": "TOPIC_SELECTION",
        "turnIndex": 0,
        "rawQuestion": raw_question,
        "primaryConcept": concept,
        "normalizedConcept": str(data.get("normalizedConcept") or "").strip() or normalize_concept(concept),
        "intent": "concept_explanation",
        "conceptChunks": chunks,
        "debateAxes": axes,
        "debateTopicCandidates": norm,
        "topicSelected": False,
        "content": "토론할 논제를 선택해 주세요. 위 5개 후보 중 하나를 고르면 찬반 토론을 시작합니다.",
    }


def coerce_debate_round(data: Dict[str, Any], raw_question: str,
                        selected_topic: Dict[str, Any]) -> Dict[str, Any]:
    """LLM DEBATE_ROUND 출력을 schema 계약으로 보정한다."""
    fb = fallback_debate_round(raw_question, selected_topic)

    def _side(key: str) -> Dict[str, Any]:
        src = data.get(key) if isinstance(data.get(key), dict) else {}
        fbs = fb[key]
        claim = str(src.get("claim") or "").strip() or fbs["claim"]
        evidence = [str(x).strip() for x in (src.get("evidence") or []) if str(x).strip()]
        if not evidence:
            evidence = fbs["evidence"]
        evidence = evidence[:3]
        example = str(src.get("example") or "").strip() or fbs["example"]
        speaker = str(src.get("speaker") or "").strip() or fbs["speaker"]
        return {"speaker": speaker, "claim": claim, "evidence": evidence, "example": example}

    reb_in = data.get("rebuttal") if isinstance(data.get("rebuttal"), dict) else {}
    rebuttal = {
        "proRebuttal": str(reb_in.get("proRebuttal") or "").strip() or fb["rebuttal"]["proRebuttal"],
        "conRebuttal": str(reb_in.get("conRebuttal") or "").strip() or fb["rebuttal"]["conRebuttal"],
    }
    key_issues = [str(x).strip() for x in (data.get("keyIssues") or []) if str(x).strip()]
    if len(key_issues) < 3:
        for ki in fb["keyIssues"]:
            if ki not in key_issues:
                key_issues.append(ki)
            if len(key_issues) >= 3:
                break
    key_issues = key_issues[:3]
    takeaway = str(data.get("learningTakeaway") or "").strip() or fb["learningTakeaway"]
    next_topics = [str(x).strip() for x in (data.get("nextTopics") or []) if str(x).strip()][:3]
    if not next_topics:
        next_topics = fb["nextTopics"]

    return {
        "mode": "debate",
        "phase": "DEBATE_ROUND",
        "turnIndex": 1,
        "rawQuestion": raw_question,
        "selectedTopic": {"topicId": selected_topic.get("topicId"), "title": selected_topic.get("title")},
        "topicSelected": True,
        "pro": _side("pro"),
        "con": _side("con"),
        "rebuttal": rebuttal,
        "keyIssues": key_issues,
        "learningTakeaway": takeaway,
        "nextTopics": next_topics,
        "content": "선택한 논제에 대한 찬반 토론 결과입니다.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# deterministic fallback
# ─────────────────────────────────────────────────────────────────────────────
def _is_ssh(concept: str, raw_question: str) -> bool:
    blob = f"{concept} {raw_question}".lower()
    return "ssh" in blob


def fallback_topic_selection(raw_question: str, knowledge_level: Optional[str] = None) -> Dict[str, Any]:
    concept = extract_primary_concept(raw_question)
    if _is_ssh(concept, raw_question):
        rows, chunks, axes = _SSH_TOPICS, list(_SSH_CHUNKS), list(_SSH_AXES)
    else:
        rows = [(t.format(c=concept), ax, pp, cp) for (t, ax, pp, cp) in _GENERIC_TOPIC_TEMPLATES]
        chunks, axes = list(_GENERIC_CHUNKS), list(_GENERIC_AXES)
    candidates = [
        {"topicId": _TOPIC_IDS[i], "title": title, "axis": axis,
         "proPosition": pro, "conPosition": con}
        for i, (title, axis, pro, con) in enumerate(rows[:5])
    ]
    return {
        "mode": "debate",
        "phase": "TOPIC_SELECTION",
        "turnIndex": 0,
        "rawQuestion": raw_question,
        "primaryConcept": concept,
        "normalizedConcept": normalize_concept(concept),
        "intent": "concept_explanation",
        "conceptChunks": chunks,
        "debateAxes": axes,
        "debateTopicCandidates": candidates,
        "topicSelected": False,
        "content": "토론할 논제를 선택해 주세요. 위 5개 후보 중 하나를 고르면 찬반 토론을 시작합니다.",
    }


def fallback_debate_round(raw_question: str, selected_topic: Dict[str, Any]) -> Dict[str, Any]:
    concept = extract_primary_concept(raw_question)
    title = (selected_topic or {}).get("title") or f"{concept}에 대한 논제"
    pro_pos = (selected_topic or {}).get("proPosition") or "그렇다"
    con_pos = (selected_topic or {}).get("conPosition") or "그렇지 않다"
    return {
        "mode": "debate",
        "phase": "DEBATE_ROUND",
        "turnIndex": 1,
        "rawQuestion": raw_question,
        "selectedTopic": {"topicId": (selected_topic or {}).get("topicId"), "title": title},
        "topicSelected": True,
        "pro": {
            "speaker": "찬성측",
            "claim": f"'{title}'에 대해 찬성합니다. {concept}은(는) 학습 효율과 실무 적용 관점에서 충분히 지지할 수 있습니다({pro_pos}).",
            "evidence": [f"{concept}의 핵심 원리를 예시와 함께 익히면 이해와 적용이 빨라집니다."],
            "example": f"실제 상황에서 {concept}을(를) 적용하면 학습한 개념을 바로 확인할 수 있습니다.",
        },
        "con": {
            "speaker": "반대측",
            "claim": f"'{title}'에 대해 신중해야 합니다. 조건과 한계를 먼저 검토하지 않으면 오개념 위험이 커집니다({con_pos}).",
            "evidence": [f"기초 개념 없이 {concept}을(를) 다루면 오류 원인을 파악하기 어렵습니다."],
            "example": f"{concept}을(를) 과도하게 단순화하면 실제 예외 상황에서 문제가 생길 수 있습니다.",
        },
        "rebuttal": {
            "proRebuttal": "복잡하더라도 실제로 자주 쓰이므로 기본 흐름은 먼저 익히는 편이 효율적입니다.",
            "conRebuttal": "기본 흐름은 배우되, 조건과 한계를 함께 다루지 않으면 잘못된 일반화로 이어질 수 있습니다.",
        },
        "keyIssues": ["학습 순서", "오개념·위험 통제", "실무 적용 빈도"],
        "learningTakeaway": (
            f"{concept}은(는) 장점과 한계가 모두 있는 개념이다. "
            "먼저 핵심 정의와 동작 원리를 잡고, 이후 대표 예시와 예외·반례로 이해를 정교화하면 균형 있게 학습할 수 있다."
        ),
        "nextTopics": [
            f"{concept}의 대표 오개념은 무엇인가?",
            f"{concept}을(를) 실무에 적용할 때 가장 중요한 조건은?",
            f"{concept}과(와) 비교해서 함께 배우면 좋은 개념은?",
        ],
        "content": "선택한 논제에 대한 찬반 토론 결과입니다.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# LLM 생성 (think=False + JSON repair + deterministic fallback)
# ─────────────────────────────────────────────────────────────────────────────
def _llm_json(system: str, user: str, *, temperature: float, max_tokens: int, top_p: float,
              knowledge_level: Optional[str] = None) -> Optional[Dict[str, Any]]:
    text = ""
    try:
        from app.services.ollama_client import ask_ollama, is_ollama_available
        if is_ollama_available():
            text = ask_ollama(system_prompt=system, user_prompt=user,
                              temperature=temperature, max_tokens=max_tokens,
                              top_p=top_p, knowledge_level=knowledge_level, think=False)
    except Exception as e:
        logger.warning("[debate] ollama 호출 실패: %s", e)
        text = ""
    if not (text or "").strip():
        try:
            from app.services.multi_agent_service import _call_llm_no_think
            text = _call_llm_no_think(system, user, max_tokens=max_tokens, temperature=temperature)
        except Exception as e:
            logger.warning("[debate] _call_llm_no_think fallback 실패: %s", e)
            return None
    return _try_parse_json(text)


_TOPIC_SYSTEM = (
    "너는 일반 설명자가 아니라 학습용 토론 엔진이다. "
    "사용자가 'SSH가 뭐야?'처럼 개념 질문을 하면 바로 설명하지 말고, 먼저 핵심 개념을 추출하고 "
    "토론 가능한 축으로 청킹한 뒤 찬반이 갈릴 수 있는 논제 후보 5개를 제시하라. "
    "사용자가 논제를 선택하기 전에는 찬성/반대 토론을 시작하지 마라. "
    "단순 정의형 질문(예: 'SSH란 무엇인가?')은 논제로 금지한다. 반드시 JSON으로만 응답하라. 한국어."
)


def _topic_user_prompt(raw_question: str) -> str:
    return (
        f"[사용자 질문]\n{raw_question}\n\n"
        "[작업] 위 질문의 핵심 개념을 토론 논제로 바꿔라. 다음 JSON만 출력한다.\n"
        "{\n"
        '  "primaryConcept": "<핵심 개념 1개>",\n'
        '  "normalizedConcept": "<정식/영문 명칭>",\n'
        '  "conceptChunks": ["<개념 청크 4~7개>"],\n'
        '  "debateAxes": ["<토론 축 4~6개>"],\n'
        '  "debateTopicCandidates": [\n'
        '    {"title": "<찬반이 갈리는 논제 문장>", "axis": "<축>", "proPosition": "<찬성 입장 한 줄>", "conPosition": "<반대 입장 한 줄>"}\n'
        "  ]\n"
        "}\n"
        "[규칙] debateTopicCandidates는 정확히 5개. 각 title은 찬반이 갈릴 수 있어야 하며 단순 정의·사용법 질문이 아니어야 한다."
    )


_ROUND_SYSTEM = (
    "너는 선택된 논제에 대해 찬성측과 반대측을 균형 있게 구성하는 학습용 토론 엔진이다. "
    "사용자가 선택한 selectedTopic만 토론하라. 원 질문을 다시 설명하지 마라. "
    "찬성측, 반대측, 상호 반박, 핵심 쟁점, 학습 정리를 구조화하라. "
    "찬성과 반대가 같은 말을 반복하지 마라. 반드시 JSON으로만 응답하라. 한국어."
)


def _round_user_prompt(raw_question: str, selected_topic: Dict[str, Any]) -> str:
    return (
        f"[원 질문]\n{raw_question}\n\n"
        f"[선택된 논제]\n{selected_topic.get('title')}\n\n"
        "[작업] 위 논제에 대해 다음 JSON만 출력한다.\n"
        "{\n"
        '  "pro": {"speaker": "찬성측", "claim": "<핵심 주장 1개>", "evidence": ["<근거 1~3개>"], "example": "<구체 예시 1개>"},\n'
        '  "con": {"speaker": "반대측", "claim": "<핵심 주장 1개>", "evidence": ["<근거 1~3개>"], "example": "<구체 예시 1개>"},\n'
        '  "rebuttal": {"proRebuttal": "<찬성의 반박 1개>", "conRebuttal": "<반대의 반박 1개>"},\n'
        '  "keyIssues": ["<핵심 쟁점 3개>"],\n'
        '  "learningTakeaway": "<학습 정리 2~4문장>",\n'
        '  "nextTopics": ["<이어서 토론할 논제 2~3개>"]\n'
        "}\n"
        "[규칙] 불필요한 장문·도입부 금지. 찬성/반대가 같은 논거를 반복하지 마라."
    )


def build_topic_selection(req: Any) -> Dict[str, Any]:
    """첫 턴: 논제 후보 5개 생성. LLM 실패/JSON 깨짐 → deterministic fallback."""
    raw_question = (_get(req, "message") or "").strip()
    kl = _get(req, "knowledgeLevel")
    data = _llm_json(_TOPIC_SYSTEM, _topic_user_prompt(raw_question),
                     temperature=TOPIC_SELECTION_TEMPERATURE, max_tokens=TOPIC_SELECTION_MAX_TOKENS,
                     top_p=TOPIC_SELECTION_TOP_P, knowledge_level=kl)
    if not data or not data.get("debateTopicCandidates"):
        logger.info("[debate] TOPIC_SELECTION fallback 사용 (q=%s)", raw_question[:40])
        return fallback_topic_selection(raw_question, kl)
    try:
        return coerce_topic_selection(data, raw_question)
    except Exception as e:
        logger.warning("[debate] coerce_topic_selection 실패 → fallback: %s", e)
        return fallback_topic_selection(raw_question, kl)


def build_debate_round(req: Any) -> Dict[str, Any]:
    """후속 턴: 선택 논제 기준 찬반 토론. LLM 실패/JSON 깨짐 → deterministic fallback."""
    raw_question = (_get(req, "message") or "").strip()
    selected_topic = selected_topic_of(req) or {"topicId": None, "title": raw_question}
    # debateState에 rawQuestion이 보존돼 있으면 그것을 원 질문으로 우선 사용한다.
    state = _get(req, "debateState") or {}
    if _get(state, "rawQuestion"):
        raw_question = str(_get(state, "rawQuestion")).strip() or raw_question
    kl = _get(req, "knowledgeLevel")
    data = _llm_json(_ROUND_SYSTEM, _round_user_prompt(raw_question, selected_topic),
                     temperature=DEBATE_ROUND_TEMPERATURE, max_tokens=DEBATE_ROUND_MAX_TOKENS,
                     top_p=DEBATE_ROUND_TOP_P, knowledge_level=kl)
    if not data or not (data.get("pro") or data.get("con")):
        logger.info("[debate] DEBATE_ROUND fallback 사용 (topic=%s)", str(selected_topic.get("title"))[:40])
        return fallback_debate_round(raw_question, selected_topic)
    try:
        return coerce_debate_round(data, raw_question, selected_topic)
    except Exception as e:
        logger.warning("[debate] coerce_debate_round 실패 → fallback: %s", e)
        return fallback_debate_round(raw_question, selected_topic)


# ─────────────────────────────────────────────────────────────────────────────
# debateStages 합성 (마인드맵/history 하위호환)
# ─────────────────────────────────────────────────────────────────────────────
def synthesize_debate_stages(round_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """DEBATE_ROUND 결과를 기존 구조화 토론 stage(논제/입론/반박/판정)로 펼쳐
    마인드맵·history 소비자가 기존과 동일하게 렌더링할 수 있게 한다."""
    topic = round_result.get("selectedTopic") or {}
    pro = round_result.get("pro") or {}
    con = round_result.get("con") or {}
    reb = round_result.get("rebuttal") or {}
    key_issues = round_result.get("keyIssues") or []
    takeaway = round_result.get("learningTakeaway") or ""

    def _stage(stage_type, title, side, role, idx, content):
        return {"stageType": stage_type, "stageTitle": title, "side": side,
                "role": role, "agentIndex": idx, "agentName": role, "content": content or ""}

    def _side_text(s):
        parts = [s.get("claim", "")]
        ev = s.get("evidence") or []
        if ev:
            parts.append("근거: " + " / ".join(ev))
        if s.get("example"):
            parts.append("예시: " + s["example"])
        return "\n".join(p for p in parts if p)

    issues_text = ("핵심 쟁점: " + ", ".join(key_issues) + "\n\n") if key_issues else ""
    return [
        _stage("TOPIC", "논제", "TOPIC", "논제", None, topic.get("title", "")),
        _stage("OPENING_STATEMENT", "반대측 입론", "CON", "반대측", 1, _side_text(con)),
        _stage("OPENING_STATEMENT", "찬성측 입론", "PRO", "찬성측", 2, _side_text(pro)),
        _stage("REBUTTAL", "반대측 반박", "CON", "반대측", 1, reb.get("conRebuttal", "")),
        _stage("REBUTTAL", "찬성측 반박", "PRO", "찬성측", 2, reb.get("proRebuttal", "")),
        _stage("JUDGEMENT", "중립 판정 / 학습 정리", "NEUTRAL", "중립", 3, issues_text + takeaway),
    ]
