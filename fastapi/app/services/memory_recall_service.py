"""
previousAnswers 기반 결정론적 기억 회상(memory recall) 서비스.

배경/계약:
- ai07 FastAPI는 Redis에 직접 붙지 않는다. 이전 대화 기억은 Spring ChatService →
  redisChatService.getRecentPersonalHistory(roomId) → previousAnswers → FastAPI 로 전달된다.
- 따라서 이 모듈은 "FastAPI가 받은 previousAnswers 범위 안에서만" deterministic하게 회상한다.
  범위 밖(예: 첫 질문 원문이 안 넘어옴)이면 지어내지 말고 "찾지 못했다"고 답한다.
- LLM을 호출하지 않는다(회상은 코드가 직접 처리). 일반 질문은 여기서 NORMAL로 분류돼 기존 LLM 경로로 간다.

이 파일은 (autodeploy reset 생존을 위해) 신규 untracked 모듈로 작성된다. 순수 함수 위주라 테스트가 쉽다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class MemoryIntent(str, Enum):
    EXACT_FIRST_MESSAGE = "EXACT_FIRST_MESSAGE"
    EXACT_LAST_MESSAGE = "EXACT_LAST_MESSAGE"
    EXACT_NTH_MESSAGE = "EXACT_NTH_MESSAGE"
    TOPIC_RECALL = "TOPIC_RECALL"
    CONTEXTUAL_FOLLOWUP = "CONTEXTUAL_FOLLOWUP"
    NORMAL = "NORMAL"


# 회상 의도(LLM 우회 대상). FOLLOWUP/NORMAL은 기존 LLM 경로.
_RECALL_INTENTS = {
    MemoryIntent.EXACT_FIRST_MESSAGE,
    MemoryIntent.EXACT_LAST_MESSAGE,
    MemoryIntent.EXACT_NTH_MESSAGE,
    MemoryIntent.TOPIC_RECALL,
}


@dataclass
class NormalizedTurn:
    role: str  # "user" | "assistant" | "unknown"
    content: str
    agentName: Optional[str] = None
    createdAt: Optional[Any] = None
    index: int = 0


# ── 분류 패턴 ────────────────────────────────────────────────────────────────
# "회상을 뜻하는 말"(질문/채팅/메시지/뭐라/물어 …). 시간/순서 앵커와 함께 있어야 EXACT로 본다.
_RECALL_WORD = r"(질문|채팅|메시지|뭐라|뭐라고|물어|물었|물어봤|물어본|뭐\s*물|무엇을\s*물)"
# 첫 질문 앵커.
_FIRST_ANCHOR = r"(맨\s*처음|제일\s*처음|처음|첫번째|첫\s*번째|첫\s*질문|첫\s*채팅|첫\s*메시지|첫\b)"
# 마지막/최근 질문 앵커.
_LAST_ANCHOR = r"(방금|마지막|최근|직전|바로\s*전)"
# n번째 앵커(한글 서수 + 숫자).
_NTH_RE = re.compile(r"(\d+|두|둘|세|셋|네|넷|다섯|여섯|일곱|여덟|아홉|열)\s*번째")
_KO_ORD = {
    "두": 2, "둘": 2, "세": 3, "셋": 3, "네": 4, "넷": 4, "다섯": 5,
    "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10,
}
# 후속(맥락 의존) 표현.
_FOLLOWUP_RE = re.compile(
    r"(그거|이거|그것|저거|아까\s*말한|아까\s*그|아까\s*설명|방금\s*말한|방금\s*설명|"
    r"위\s*내용|위에서\s*말한|위에서|앞서\s*말한|이어서|이어|계속해서\s*설명|"
    r"더\s*쉽게|쉽게\s*다시|다시\s*설명|예시\s*들어|표로\s*정리)"
)
# 주제 회상 마커.
_TOPIC_MARKER_RE = re.compile(
    r"([\w가-힣A-Za-z0-9.\+\#\-]+)\s*(?:에\s*대해서|에\s*대해|에\s*대한|에\s*관해서|에\s*관해|관련해서|관련해|관련된|관련|관한)"
)
_TOPIC_VERB_RE = re.compile(r"([\w가-힣A-Za-z0-9.\+\#\-]+)\s*(?:질문한|질문했|물어본|물어봤|물었)")
_TOPIC_RECALL_CONTEXT = re.compile(r"(질문|물어|물었|물어봤|물어본|뭐\s*물|기록\s*있|한\s*적\s*있|물어본\s*거)")
_PARTICLES = ("으로", "로", "에서", "에게", "에", "을", "를", "이", "가", "은", "는", "도", "랑", "와", "과")


def _strip_particle(tok: str) -> str:
    t = (tok or "").strip().strip("\"'“”‘’.,!?")
    if t in ("내", "내가", "제", "제가"):
        return ""
    for p in _PARTICLES:
        if len(t) > len(p) + 1 and t.endswith(p):
            return t[: -len(p)]
    return t


def _extract_topic(msg: str) -> str:
    m = _TOPIC_MARKER_RE.search(msg)
    if m:
        topic = _strip_particle(m.group(1))
        if topic:
            return topic
    m = _TOPIC_VERB_RE.search(msg)
    if m:
        topic = _strip_particle(m.group(1))
        if topic:
            return topic
    return ""


def _parse_nth(msg: str) -> Optional[int]:
    m = _NTH_RE.search(msg)
    if not m:
        return None
    tok = m.group(1)
    if tok.isdigit():
        return int(tok)
    return _KO_ORD.get(tok)


def classify_memory_intent(message: str) -> Tuple[MemoryIntent, Dict[str, Any]]:
    """사용자 메시지의 기억 관련 의도를 분류한다. (intent, extra) 반환.
    extra: TOPIC_RECALL이면 {"topic": ...}, EXACT_NTH_MESSAGE면 {"n": ...}.

    설계 원칙:
    - "TCP가 뭐야"처럼 시간/순서 앵커가 없는 개념 질문은 절대 회상으로 오판하지 않는다(→ NORMAL).
    - EXACT(첫/마지막/n번째)는 '앵커 + 회상어'가 함께 있어야 성립한다.
    """
    msg = (message or "").strip()
    if not msg:
        return MemoryIntent.NORMAL, {}

    has_recall_word = re.search(_RECALL_WORD, msg) is not None

    # 1) n번째 (가장 구체적인 순서 앵커)
    n = _parse_nth(msg)
    if n is not None and has_recall_word:
        return MemoryIntent.EXACT_NTH_MESSAGE, {"n": n}

    # 2) 첫 질문
    if re.search(_FIRST_ANCHOR, msg) and has_recall_word:
        return MemoryIntent.EXACT_FIRST_MESSAGE, {}

    # 3) 마지막/방금 질문
    if re.search(_LAST_ANCHOR, msg) and has_recall_word:
        return MemoryIntent.EXACT_LAST_MESSAGE, {}

    # 4) 주제 회상 ("내가 TCP에 대해 질문한 것 같은데?")
    if _TOPIC_RECALL_CONTEXT.search(msg):
        topic = _extract_topic(msg)
        if topic:
            return MemoryIntent.TOPIC_RECALL, {"topic": topic}

    # 5) 후속(맥락 의존)
    if _FOLLOWUP_RE.search(msg):
        return MemoryIntent.CONTEXTUAL_FOLLOWUP, {}

    # 6) 일반
    return MemoryIntent.NORMAL, {}


def is_recall_intent(intent: MemoryIntent) -> bool:
    return intent in _RECALL_INTENTS


# ── previousAnswers 정규화 ───────────────────────────────────────────────────
_USER_ROLES = {"user", "사용자", "human", "me"}
_ASSISTANT_ROLES = {"assistant", "ai", "bot", "agent", "system"}
# 저장돼선 안 되는(또는 의미 없는) 콘텐츠 패턴.
_SKIP_CONTENT = (
    "(응답을 생성하지 못했어요",
    "(이 에이전트의 응답 생성 중 오류",
    "스트리밍 중 오류",
)


def _norm_role(raw: Any, agent_name: Any = None) -> str:
    r = str(raw or "").strip().lower()
    if r in _USER_ROLES:
        return "user"
    if r in _ASSISTANT_ROLES:
        return "assistant"
    # role이 없을 때 agentName으로 보강: "사용자"면 user.
    an = str(agent_name or "").strip().lower()
    if an in _USER_ROLES:
        return "user"
    if an and an not in _USER_ROLES:
        return "assistant"
    return "unknown"


def _content_ok(content: str) -> bool:
    c = (content or "").strip()
    if not c:
        return False
    for bad in _SKIP_CONTENT:
        if c.startswith(bad) or bad in c:
            return False
    return True


def _get(obj: Any, *names: str) -> Any:
    for name in names:
        if isinstance(obj, dict):
            if name in obj and obj[name] is not None:
                return obj[name]
        else:
            v = getattr(obj, name, None)
            if v is not None:
                return v
    return None


def _split_role_string(s: str) -> List[Tuple[str, str]]:
    """'Q: .. A: ..' 또는 'user: .. assistant: ..' 형태 문자열을 (role, content) 목록으로 분해."""
    out: List[Tuple[str, str]] = []
    text = s.strip()
    # Q:/A: 패턴
    mq = re.search(r"\bQ\s*[:：]\s*(.+?)(?:\s*\bA\s*[:：]\s*(.+))?$", text, re.IGNORECASE | re.DOTALL)
    if mq and ("A:" in text.upper() or "A：" in text):
        q = (mq.group(1) or "").strip()
        a = (mq.group(2) or "").strip()
        if q:
            out.append(("user", q))
        if a:
            out.append(("assistant", a))
        if out:
            return out
    # user:/assistant: 패턴
    parts = re.split(r"(?i)\b(user|assistant)\s*[:：]\s*", text)
    if len(parts) >= 3:
        i = 1
        while i < len(parts) - 1:
            role = _norm_role(parts[i])
            content = parts[i + 1].strip()
            if content:
                out.append((role, content))
            i += 2
        if out:
            return out
    return out


def normalize_previous_answers(previous_answers: Any) -> List[NormalizedTurn]:
    """다양한 형태의 previousAnswers를 NormalizedTurn 목록으로 방어적 정규화한다.

    지원: pydantic 객체 list / dict list / string list / 'Q:..A:..' / 'user:..assistant:..'.
    빈 콘텐츠·오류 트레이스·빈 assistant 답변은 제외한다.
    """
    turns: List[NormalizedTurn] = []
    if not previous_answers:
        return turns

    items = previous_answers if isinstance(previous_answers, (list, tuple)) else [previous_answers]
    idx = 0
    for item in items:
        # 1) 문자열
        if isinstance(item, str):
            pairs = _split_role_string(item)
            if pairs:
                for role, content in pairs:
                    if _content_ok(content):
                        turns.append(NormalizedTurn(role=role, content=content.strip(), index=idx))
                        idx += 1
            elif _content_ok(item):
                turns.append(NormalizedTurn(role="unknown", content=item.strip(), index=idx))
                idx += 1
            continue

        # 2) dict / pydantic
        content = _get(item, "content", "answer", "message", "text")
        agent_name = _get(item, "agentName", "agent_name", "name")
        role = _norm_role(_get(item, "role", "senderType", "type"), agent_name)
        created = _get(item, "createdAt", "created_at", "ts")
        content = "" if content is None else str(content)
        if _content_ok(content):
            turns.append(NormalizedTurn(
                role=role, content=content.strip(),
                agentName=str(agent_name) if agent_name is not None else None,
                createdAt=created, index=idx,
            ))
            idx += 1
    return turns


def _user_turns(turns: List[NormalizedTurn]) -> List[NormalizedTurn]:
    return [t for t in turns if t.role == "user"]


# ── 회상 답변 생성(결정론적) ─────────────────────────────────────────────────
_NOT_FOUND_FIRST = (
    "현재 전달된 이전 대화 범위에서는 첫 질문 원문을 찾지 못했어. "
    "Spring에서 Redis 전체 원문 기록을 FastAPI로 넘기거나, Spring에서 직접 처리해야 정확히 답할 수 있어."
)


@dataclass
class RecallResult:
    text: str
    matched_count: int


def build_recall_answer(intent: MemoryIntent, extra: Dict[str, Any], turns: List[NormalizedTurn]) -> RecallResult:
    """회상 의도에 대한 결정론적 답변 텍스트를 만든다. 못 찾으면 지어내지 않고 안내문을 반환."""
    users = _user_turns(turns)

    if intent == MemoryIntent.EXACT_FIRST_MESSAGE:
        if users:
            return RecallResult(f'처음 질문은 다음이었어.\n\n"{users[0].content}"', 1)
        return RecallResult(_NOT_FOUND_FIRST, 0)

    if intent == MemoryIntent.EXACT_LAST_MESSAGE:
        if users:
            return RecallResult(f'마지막 질문은 다음이었어.\n\n"{users[-1].content}"', 1)
        return RecallResult(
            "현재 전달된 이전 대화 범위에서는 마지막 질문을 찾지 못했어.", 0)

    if intent == MemoryIntent.EXACT_NTH_MESSAGE:
        n = int(extra.get("n") or 0)
        if 1 <= n <= len(users):
            return RecallResult(f'{n}번째 질문은 다음이었어.\n\n"{users[n - 1].content}"', 1)
        return RecallResult(
            f"현재 전달된 이전 대화 범위에서는 {n}번째 질문을 찾지 못했어. "
            f"(전달된 이전 사용자 질문은 {len(users)}개야.)", 0)

    if intent == MemoryIntent.TOPIC_RECALL:
        topic = str(extra.get("topic") or "").strip()
        if not topic:
            return RecallResult("어떤 주제의 질문을 찾을지 분명하지 않아. 주제를 한 단어로 알려줘.", 0)
        low = topic.lower()
        matched = [t.content for t in users if low in t.content.lower()]
        if matched:
            lines = [f'이 방의 전달된 이전 대화 범위에서 "{topic}" 관련 질문을 찾았어.', ""]
            for i, q in enumerate(matched[:5], start=1):
                lines.append(f'{i}. "{q}"')
            return RecallResult("\n".join(lines), len(matched[:5]))
        return RecallResult(
            f'현재 전달된 이전 대화 범위에서는 "{topic}" 관련 질문을 찾지 못했어.', 0)

    # 회상 의도가 아니면 호출되지 않아야 한다(방어).
    return RecallResult("", 0)
