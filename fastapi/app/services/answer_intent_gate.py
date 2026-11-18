"""
사용자 메시지 의도 게이트 (결정론·LLM 비호출).

멀티에이전트 모드(특히 debate/simulation)에서 "일반 질문"과 "선택지 생성 요청",
"이전 선택지에 대한 짧은 응답"을 명확히 구분한다. 토론 모드가 모든 질문을 A~E
선택지로 강등하던 버그(직접 질문도 후보만 뜸)와, "A" 입력 시 이전 선택지가 아니라
새 랜덤 선택지를 생성하던 버그를 근본 차단하기 위한 SSOT 분류기다.

intent 종류:
  - DIRECT_QUESTION : 단일 일반 질문 ("gRPC가 뭐야")
  - MULTI_QUESTION  : 한 메시지에 여러 질문 ("SSH가 뭐고 gRPC가 뭐고 차이는?")
  - REQUEST_OPTIONS : 명시적 선택지/주제 추천 요청 ("토론 주제 추천해줘", "선택지 줘")
  - OPTION_SELECTION: 직전 선택지에 대한 짧은 단일 토큰 응답 ("A", "1번")
  - EXPANSION       : 직전 답변 이어가기/심화 ("더 자세히", "이어서")
  - GUARDRAIL_DIRECT: 인사/잡담/감사 등 직접 응답 축약 대상

핵심 불변조건:
  - 일반 질문은 절대 REQUEST_OPTIONS/OPTION_SELECTION으로 분류되지 않는다.
  - OPTION_SELECTION은 메시지 전체가 사실상 단일 옵션 토큰일 때만(긴 문장 금지).
  - OPTION_SELECTION의 "유효성"(이전 선택지 존재)은 호출자가 pending_choice_context로
    별도 판정한다. 이 모듈은 분류만 하고 새 선택지를 만들지 않는다.

신규 파일 — 기존 endpoint/스키마/계약 불변(additive).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ── intent 상수 ──────────────────────────────────────────────────────────────
DIRECT_QUESTION = "DIRECT_QUESTION"
MULTI_QUESTION = "MULTI_QUESTION"
REQUEST_OPTIONS = "REQUEST_OPTIONS"
OPTION_SELECTION = "OPTION_SELECTION"
EXPANSION = "EXPANSION"
GUARDRAIL_DIRECT = "GUARDRAIL_DIRECT"

# 선택지/옵션 토큰을 해석하는 모드(그 외 모드에서 "A"는 일반 질문으로 둔다)
CHOICE_MODES = {"debate", "토론", "simulation", "상황극", "roleplay"}

_DIGIT_TO_LETTER = {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"}
_KO_TO_LETTER = {"가": "A", "나": "B", "다": "C", "라": "D", "마": "E"}

# 메시지 전체가 단일 옵션 토큰일 때만 매치(긴 문장은 매치되지 않음).
#   "A" / "a" / "B 선택" / "1번" / "2" / "C로" / "가"
_OPTION_TOKEN_RE = re.compile(
    r"^\s*(?:선택\s*)?([A-Ea-e]|[1-5]|[가-마])\s*"
    r"(?:번|\.|\)|로|을|를|이요|요|선택|할게|할래|골라|골라줘)?\s*$"
)

# 인사/잡담(메시지 전체가 거의 인사일 때만). 1차 guardrail은 별도 _guard가 담당.
_GREETING_RE = re.compile(
    r"^\s*(안녕(하세요)?|반가워(요)?|하이|헬로|hi|hello|ㅎㅇ|"
    r"고마워(요)?|감사(합니다|해요)?|잘\s*가|수고(했어|하세요)?)\s*[!~.?]*\s*$",
    re.IGNORECASE,
)

# 이어가기/심화 신호(좁게 유지 — '설명해줘'는 신규 질문이므로 제외).
_EXPANSION_RE = re.compile(
    r"(더\s*자세히|더\s*알려|자세히\s*말|이어서|계속\s*(해|하)|추가\s*설명|"
    r"방금\s*답변|이전\s*답변|더\s*깊(이|게)|덧붙)"
)


@dataclass
class IntentResult:
    intent: str
    atomic_questions: List[str] = field(default_factory=list)
    option_token: Optional[str] = None
    reason: str = ""

    @property
    def primary_question(self) -> str:
        return self.atomic_questions[0] if self.atomic_questions else ""

    @property
    def is_multi(self) -> bool:
        return self.intent == MULTI_QUESTION


# ─────────────────────────────────────────────────────────────────────────────
# 옵션 토큰
# ─────────────────────────────────────────────────────────────────────────────
def parse_option_token(message: str) -> Optional[str]:
    """메시지 전체가 단일 옵션 토큰이면 정규화된 대문자(A~E)를 반환, 아니면 None."""
    m = _OPTION_TOKEN_RE.match(message or "")
    if not m:
        return None
    raw = m.group(1)
    if raw in _DIGIT_TO_LETTER:
        return _DIGIT_TO_LETTER[raw]
    if raw in _KO_TO_LETTER:
        return _KO_TO_LETTER[raw]
    return raw.upper()


# ─────────────────────────────────────────────────────────────────────────────
# 선택지 생성 요청 판정
# ─────────────────────────────────────────────────────────────────────────────
def is_request_options(message: str) -> bool:
    """명시적으로 '선택지/주제 추천/퀴즈 출제'를 요청했는지(일반 질문과 구분)."""
    t = (message or "").lower().replace(" ", "")
    if any(k in t for k in ["선택지", "옵션", "보기를", "보기좀", "후보", "a~e", "a-e", "a∼e"]):
        return True
    if "주제" in t and any(k in t for k in ["추천", "골라", "정해", "뽑아", "줘", "추려"]):
        return True
    if "논제" in t and any(k in t for k in ["추천", "골라", "정해", "뽑아"]):
        return True
    if ("퀴즈" in t or "문제" in t) and any(k in t for k in ["내", "만들", "줘", "출제", "내줘"]):
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# 멀티 질문 분해
# ─────────────────────────────────────────────────────────────────────────────
# 분리 신호: 종결부호 뒤 공백 / 줄바꿈·세미콜론 / "그리고" / "~뭐고|뭐며|무엇이고" / 쉼표
_SPLIT_RE = re.compile(
    r"(?<=[?？])\s+"            # 물음표 뒤
    r"|[\n;]+"                  # 줄바꿈/세미콜론
    r"|\s*그리고\s*"            # 접속 '그리고'
    r"|(?<=뭐)고\s+"           # "~뭐고 "
    r"|(?<=뭔지)\s+"
    r"|(?<=무엇)이고\s+"        # "~무엇이고 "
    r"|,\s*(?=\S)"             # 쉼표
)


def split_atomic_questions(message: str) -> List[str]:
    """메시지를 원자 질문 배열로 분해한다. 분리 신호가 없으면 [원문] 1개."""
    s = (message or "").strip()
    if not s:
        return []
    parts = _SPLIT_RE.split(s)
    cleaned = [p.strip(" ,.?？!·-\t") for p in parts if p and p.strip(" ,.?？!·-\t")]
    return cleaned or [s]


# ─────────────────────────────────────────────────────────────────────────────
# pending_choice_context (서버 무상태 → 클라이언트가 echo)
# ─────────────────────────────────────────────────────────────────────────────
def make_pending_choice_context(
    *, turn_id: str, mode: str, original_user_message: str,
    candidates: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """선택지 후보로부터 pending_choice_context를 만든다.

    프론트가 다음 턴에 그대로 echo하면, 사용자가 'A'만 입력해도 서버가 직전
    선택지를 복원해 확정할 수 있다(새 랜덤 후보 생성 금지)."""
    options = []
    for c in candidates or []:
        oid = c.get("topicId") or c.get("optionId") or c.get("id")
        otext = c.get("title") or c.get("optionText") or c.get("text") or ""
        if not oid:
            continue
        options.append({
            "optionId": str(oid),
            "optionText": str(otext),
            "axis": c.get("axis"),
            "proPosition": c.get("proPosition"),
            "conPosition": c.get("conPosition"),
        })
    return {
        "turnId": turn_id,
        "mode": mode,
        "originalUserMessage": original_user_message,
        "options": options,
    }


def resolve_option(option_token: Optional[str],
                   pending_choice_context: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """option_token('A')을 pending_choice_context의 옵션으로 해석한다.

    context가 없거나 토큰이 후보에 없으면 None(→ 호출자는 새 선택지를 만들지 말고 안내)."""
    if not option_token or not pending_choice_context:
        return None
    options = pending_choice_context.get("options") or []
    tok = option_token.strip().upper()
    for opt in options:
        if str(opt.get("optionId", "")).strip().upper() == tok:
            return opt
    return None


def extract_pending_choice_context(req: Any) -> Optional[Dict[str, Any]]:
    """요청에서 pending_choice_context를 추출한다(pendingChoiceContext 또는 debateState 내)."""
    def _get(obj, key):
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    ctx = _get(req, "pendingChoiceContext") or _get(req, "pending_choice_context")
    if ctx:
        return ctx
    state = _get(req, "debateState") or {}
    if isinstance(state, dict):
        return state.get("pendingChoiceContext") or state.get("pending_choice_context")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 분류
# ─────────────────────────────────────────────────────────────────────────────
def classify_intent(message: str, *, mode: str = "default",
                    has_pending_choice: bool = False) -> IntentResult:
    """메시지 의도를 결정론적으로 분류한다(LLM 비호출).

    우선순위:
      1) 단일 옵션 토큰 + 선택지 모드 → OPTION_SELECTION
      2) 인사/잡담 → GUARDRAIL_DIRECT
      3) 명시적 선택지 요청 → REQUEST_OPTIONS
      4) 여러 질문 → MULTI_QUESTION
      5) 이어가기/심화 → EXPANSION
      6) 그 외 → DIRECT_QUESTION
    """
    msg = (message or "").strip()
    mode_l = (mode or "default").strip().lower()

    # 1) 옵션 토큰(선택지 모드에서만). 유효성(이전 선택지 존재)은 호출자가 판정.
    if mode_l in CHOICE_MODES:
        tok = parse_option_token(msg)
        if tok:
            return IntentResult(intent=OPTION_SELECTION, option_token=tok,
                                atomic_questions=[msg], reason="single_option_token")

    # 2) 인사/잡담
    if _GREETING_RE.match(msg):
        return IntentResult(intent=GUARDRAIL_DIRECT, atomic_questions=[msg], reason="greeting")

    # 3) 명시적 선택지 요청
    if is_request_options(msg):
        return IntentResult(intent=REQUEST_OPTIONS, atomic_questions=[msg], reason="explicit_option_request")

    # 4) 멀티 질문
    atomic = split_atomic_questions(msg)
    if len(atomic) >= 2:
        return IntentResult(intent=MULTI_QUESTION, atomic_questions=atomic, reason="multiple_questions")

    # 5) 이어가기/심화
    if _EXPANSION_RE.search(msg):
        return IntentResult(intent=EXPANSION, atomic_questions=atomic or [msg], reason="expansion")

    # 6) 일반 단일 질문
    return IntentResult(intent=DIRECT_QUESTION, atomic_questions=atomic or [msg], reason="direct")
