"""
학습 세션 상태 저장소 (socratic / simulation / debate 공통).

왜 필요한가:
  - 소크라테스/상황극은 '한 번의 답변'이 아니라 여러 턴에 걸친 상태 머신이다.
    상태가 없으면 "모르겠어", "2번" 같은 짧은 답이 매번 새 질문으로 재판정되고,
    장면이 매 턴 처음부터 다시 생성된다.
  - 새 세션 첫 입력에만 학습 의도 가드를 적용하려면 '지금이 새 세션인가'를 알아야 한다.

저장 방식(2단):
  1) 프로세스 메모리(TTL). 같은 워커로 이어지는 대화에서 가장 빠르다.
  2) 클라이언트 에코(state 필드). 프로세스 재시작/다중 워커로 1)이 비어도
     프론트가 되돌려준 state 로 세션을 복원한다(상황극 simulationState 와 동일 방식).
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SOCRATIC = "socratic"
DEBATE = "debate"
SIMULATION = "simulation"

_LOCK = threading.RLock()
_STORE: Dict[str, "LearningSession"] = {}
_MAX_SESSIONS = int(os.getenv("LEARNING_SESSION_MAX", "500"))


def ttl_seconds() -> int:
    try:
        return max(60, int(os.getenv("LEARNING_SESSION_TTL_SECONDS", "1800")))
    except (TypeError, ValueError):
        return 1800


@dataclass
class LearningSession:
    session_id: str
    mode: str
    topic: str
    state: str = ""
    turn_index: int = 0
    data: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def expired(self) -> bool:
        return (time.time() - self.updated_at) > ttl_seconds()

    def to_payload(self) -> Dict[str, Any]:
        """SSE/응답으로 클라이언트에 돌려줄 상태(다음 턴에 그대로 echo 받는다)."""
        return {
            "sessionId": self.session_id,
            "mode": self.mode,
            "topic": self.topic,
            "state": self.state,
            "turnIndex": self.turn_index,
            "data": self.data,
        }


# ── 세션 키 ─────────────────────────────────────────────────────────────────

def resolve_session_id(request: Any, mode: str) -> str:
    """요청에서 세션 식별자를 정한다. 명시 sessionId > 상태 echo > 방+모드."""
    for attr in ("sessionId", "session_id"):
        v = getattr(request, attr, None)
        if v:
            return f"{v}:{mode}"
    for attr in ("socraticState", "simulationState", "debateState"):
        st = getattr(request, attr, None)
        if isinstance(st, dict) and st.get("sessionId"):
            return f"{st['sessionId']}:{mode}"
    room = getattr(request, "roomId", None) or getattr(request, "room_id", None)
    group = getattr(request, "groupId", None) or getattr(request, "group_id", None)
    return f"room-{room or group or 'anon'}:{mode}"


def new_session_id(mode: str) -> str:
    return f"{mode}-{uuid.uuid4().hex[:12]}"


# ── 저장/조회 ───────────────────────────────────────────────────────────────

def _prune() -> None:
    if len(_STORE) <= _MAX_SESSIONS:
        return
    for key in sorted(_STORE, key=lambda k: _STORE[k].updated_at)[: len(_STORE) - _MAX_SESSIONS]:
        _STORE.pop(key, None)


def get(key: str) -> Optional[LearningSession]:
    with _LOCK:
        s = _STORE.get(key)
        if s is None:
            return None
        if s.expired():
            _STORE.pop(key, None)
            return None
        return s


def save(key: str, session: LearningSession) -> LearningSession:
    session.updated_at = time.time()
    with _LOCK:
        _STORE[key] = session
        _prune()
    return session


def end(key: str) -> None:
    with _LOCK:
        _STORE.pop(key, None)


def clear_all() -> None:
    """테스트 전용."""
    with _LOCK:
        _STORE.clear()


def hydrate_from_echo(key: str, mode: str, echo: Any) -> Optional[LearningSession]:
    """프로세스 메모리에 없을 때 클라이언트가 되돌려준 state 로 세션을 복원한다."""
    if not isinstance(echo, dict):
        return None
    sid = echo.get("sessionId")
    state = echo.get("state") or echo.get("phase")
    if not sid or not state:
        return None
    session = LearningSession(
        session_id=str(sid),
        mode=mode,
        topic=str(echo.get("topic") or ""),
        state=str(state),
        turn_index=int(echo.get("turnIndex") or 0),
        data=echo.get("data") if isinstance(echo.get("data"), dict) else {},
    )
    logger.info("[SESSION] echo 복원 mode=%s session_id=%s state=%s turn=%d",
                mode, sid, state, session.turn_index)
    return save(key, session)


# ── 새 질문 / 이어가기 판정 ─────────────────────────────────────────────────

_TOKEN = re.compile(r"[가-힣A-Za-z0-9]{2,}")
_STOP = {"그리고", "하지만", "그러면", "그럼", "이거", "그거", "저거", "무엇", "어떻게", "하는", "되는", "인가"}

# 진행 중 세션에서 '답변'으로 봐야 하는 짧은 발화(새 질문으로 재판정 금지).
_ANSWER_LIKE = re.compile(
    r"^\s*("
    r"모르|몰라|글쎄|음+|아니|응|네|넵|예|맞아|맞는|그런\s*것?\s*같|같아|같은데|"
    r"[0-9]+\s*번?|[abcdeABCDE]\s*$|[①②③④⑤]|"
    r"왜\??$|왜요\??$|그래서\??$|하나만|다시|계속|더|넘어가|모르겠"
    r")",
)

_LEARNING_MARK = re.compile(
    r"(뭐야|뭐죠|무엇|설명|이란|개념|정의|원리|구조|차이|작동|동작|방법|어떻게|왜|이유|"
    r"장단점|예시|특징|역할|비교|적합|나은|좋은\s*선택|연습|상황|면접|시나리오|알려)",
)


def _tokens(text: str) -> set:
    return {t for t in _TOKEN.findall(text or "") if t not in _STOP}


def matches_answer_pattern(message: str) -> bool:
    """진행 중 세션의 '답변 발화' 패턴인가('모르겠어', '2번', '아니', '왜?').

    길이만으로 판단하지 않는다(짧은 잡담까지 답변으로 오인하면 세션이 오염된다).
    """
    return bool(_ANSWER_LIKE.match((message or "").strip()))


def looks_like_new_question(message: str, session: Optional[LearningSession]) -> bool:
    """진행 중 세션에서 사용자가 '완전히 새로운 주제'를 물었는지.

    짧은 답('모르겠어', '2번', '아니')은 절대 새 질문이 아니다(요구사항: 재판정 금지).
    """
    msg = (message or "").strip()
    if session is None:
        return True
    if len(msg) <= 12 or _ANSWER_LIKE.match(msg):
        return False
    if not _LEARNING_MARK.search(msg):
        return False
    topic_tokens = _tokens(session.topic)
    msg_tokens = _tokens(msg)
    if not topic_tokens or not msg_tokens:
        return True
    overlap = len(topic_tokens & msg_tokens) / max(1, len(msg_tokens))
    return overlap < 0.2


def resolve_active_session(request: Any, mode: str, message: str, echo: Any = None):
    """(key, session, is_new) 를 돌려준다.

    is_new=True 면 '새 세션 첫 입력'이므로 학습 의도 가드를 적용해야 한다.
    """
    key = resolve_session_id(request, mode)
    session = get(key)
    if session is None and echo is not None:
        session = hydrate_from_echo(key, mode, echo)
    if session is not None and session.mode != mode:
        # 모드가 바뀌면 이전 모드 상태를 끊는다(이전 주제 오염 방지).
        end(key)
        session = None
    if session is not None and looks_like_new_question(message, session):
        logger.info("[SESSION] 새 주제 감지 → 이전 세션 종료 mode=%s session_id=%s", mode, session.session_id)
        end(key)
        session = None
    return key, session, session is None
