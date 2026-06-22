"""
대화 행위 분류기 (Dialogue Act Classifier).

기본(basic) 모드에서 들어온 사용자 메시지가
  - 새 학습 질문(NEW_STUDY_QUERY)인지,
  - 직전 답변에 대한 후속 발화(FOLLOWUP_*)인지,
  - 호응/인사/감사 같은 사회적 발화인지
를 직전 대화 맥락(previous_context)과 함께 판별한다.

문제 배경:
  기본 모드에서 "아니왜?", "왜?", "그게 맞아?", "예시로", "더 쉽게", "ㅇㅇ" 같은
  짧은 후속 발화가 "새 학습 질문"으로 처리되어 3명의 에이전트가 직전 답변을 통째로
  다시 반복하던 버그가 있었다. 이 모듈은 그 분기점의 SSOT 분류기다.

설계 원칙(이 저장소의 message_intent_classifier / answer_intent_gate 와 동일 계열):
  - 결정론(패턴 + 맥락) 우선 → 빠르고 재현 가능(테스트가 Ollama에 의존하지 않음).
  - 애매한 경우에만 LLM 보조(think=False, env DIALOGUE_ACT_USE_LLM 로 게이팅, 실패 시 결정론 폴백).
  - 금지 안티패턴(`if msg == "아니왜"` 단일 하드코딩)이 아니라, 전체 dialogue act 분류 체계.
  - "왜" 키워드만 보고 무조건 FOLLOWUP 으로 강등하지 않는다. previous_context 가 없거나
    문장이 길고 새 주제어를 담으면 NEW_STUDY_QUERY 로 둔다.

신규 파일 — 기존 endpoint/스키마/계약 불변(additive).
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional, Sequence

logger = logging.getLogger(__name__)

# ── dialogue act 상수 ────────────────────────────────────────────────────────
DialogueAct = Literal[
    "NEW_STUDY_QUERY",
    "FOLLOWUP_WHY",
    "FOLLOWUP_CHALLENGE",
    "FOLLOWUP_CLARIFY",
    "FOLLOWUP_EXAMPLE",
    "FOLLOWUP_SIMPLIFY",
    "FOLLOWUP_CONTINUE",
    "AGREEMENT",
    "DISAGREEMENT",
    "BACKCHANNEL",
    "CASUAL_CHAT",
    "GREETING",
    "THANKS",
    "UNKNOWN",
]

NEW_STUDY_QUERY = "NEW_STUDY_QUERY"
FOLLOWUP_WHY = "FOLLOWUP_WHY"
FOLLOWUP_CHALLENGE = "FOLLOWUP_CHALLENGE"
FOLLOWUP_CLARIFY = "FOLLOWUP_CLARIFY"
FOLLOWUP_EXAMPLE = "FOLLOWUP_EXAMPLE"
FOLLOWUP_SIMPLIFY = "FOLLOWUP_SIMPLIFY"
FOLLOWUP_CONTINUE = "FOLLOWUP_CONTINUE"
AGREEMENT = "AGREEMENT"
DISAGREEMENT = "DISAGREEMENT"
BACKCHANNEL = "BACKCHANNEL"
CASUAL_CHAT = "CASUAL_CHAT"
GREETING = "GREETING"
THANKS = "THANKS"
UNKNOWN = "UNKNOWN"

# 풀답변(3명 full)을 허용하는 유일한 act. 그 외에는 basic 컨텍스트 턴으로 처리.
_FULL_ACTS = {NEW_STUDY_QUERY}
_SHORT_ACTS = {
    FOLLOWUP_WHY, FOLLOWUP_CHALLENGE, FOLLOWUP_CLARIFY,
    FOLLOWUP_EXAMPLE, FOLLOWUP_SIMPLIFY, FOLLOWUP_CONTINUE, DISAGREEMENT,
}
_MICRO_ACTS = {AGREEMENT, BACKCHANNEL, GREETING, THANKS, CASUAL_CHAT}
_ANTI_REPEAT_ACTS = _SHORT_ACTS  # 직전 답변 반복을 막아야 하는 act


# ── 데이터 구조 ──────────────────────────────────────────────────────────────
@dataclass
class PreviousTurnContext:
    """직전 대화 맥락. request.previousAnswers 로부터 구성한다(Redis 불필요)."""
    last_user_message: str = ""
    last_agent_answers: List[str] = field(default_factory=list)
    last_topic: Optional[str] = None
    last_claims: List[str] = field(default_factory=list)
    last_mode: Optional[str] = None

    @property
    def has_context(self) -> bool:
        return bool(self.last_agent_answers)

    @property
    def previous_answer_summary(self) -> str:
        if not self.last_agent_answers:
            return ""
        last = self.last_agent_answers[-1]
        return last[:280] + ("…" if len(last) > 280 else "")


@dataclass
class DialogueActDecision:
    act: str = NEW_STUDY_QUERY
    confidence: float = 0.0
    is_new_question: bool = True
    requires_three_agents: bool = True
    answer_depth: str = "full"            # full | short | micro | ask_clarification
    suppress_validation: bool = False
    suppress_peer_feedback: bool = False
    anti_repeat: bool = False
    target_previous_claim: Optional[str] = None
    reason: str = ""
    source: str = "deterministic"         # deterministic | llm

    def to_event(self) -> dict:
        return {
            "dialogueAct": self.act,
            "answerDepth": self.answer_depth,
            "confidence": round(self.confidence, 3),
        }


# ── 텍스트 정규화 헬퍼 ───────────────────────────────────────────────────────
_PUNCT_RE = re.compile(r"[\s?!.~,·…ㅡ\-–—\"'`()\[\]{}。、，！？:;]+")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+|\n+")


def _compact(s: Optional[str]) -> str:
    return _PUNCT_RE.sub("", s or "")


def _extract_claims(text: str, max_claims: int = 2) -> List[str]:
    """직전 답변에서 핵심 주장 1~2개(첫 문장 위주)를 뽑는다."""
    if not text:
        return []
    parts = [p.strip() for p in _SENT_SPLIT_RE.split(text) if p.strip()]
    claims: List[str] = []
    for p in parts:
        if len(_compact(p)) >= 6:
            claims.append(p[:160])
        if len(claims) >= max_claims:
            break
    return claims or ([text.strip()[:160]] if text.strip() else [])


def build_previous_context(
    previous_answers: Optional[Sequence[Any]],
    mode: Optional[str] = None,
) -> PreviousTurnContext:
    """request.previousAnswers(PreviousAnswer | dict 혼용)에서 맥락을 구성한다."""
    last_user = ""
    agent_answers: List[str] = []
    for pa in previous_answers or []:
        if isinstance(pa, dict):
            role = (pa.get("role") or "ASSISTANT")
            text = pa.get("answer") or pa.get("content") or ""
        else:
            role = getattr(pa, "role", None) or "ASSISTANT"
            text = getattr(pa, "answer", None) or getattr(pa, "content", None) or ""
        role = str(role).strip().upper()
        text = str(text).strip()
        if not text:
            continue
        if role == "USER":
            last_user = text
        else:
            agent_answers.append(text)
    claims = _extract_claims(agent_answers[-1]) if agent_answers else []
    return PreviousTurnContext(
        last_user_message=last_user,
        last_agent_answers=agent_answers[-3:],
        last_topic=(last_user or None),
        last_claims=claims,
        last_mode=mode,
    )


# ── 결정론 패턴 ──────────────────────────────────────────────────────────────
_GREETING = {
    "안녕", "안녕하세요", "하이", "헬로", "hello", "hi", "ㅎㅇ", "반가워", "반가워요",
    "반갑습니다", "좋은아침", "굿모닝", "굿이브닝",
}
_THANKS = {
    "고마워", "고마워요", "고맙습니다", "감사", "감사해", "감사해요", "감사합니다",
    "수고", "수고했어", "수고하세요", "ㄳ", "ㄱㅅ", "thx", "thanks", "thankyou",
}
_BACKCHANNEL = {
    "ㅇㅇ", "ㅇㅋ", "ㅇㅎ", "오", "오오", "오오오", "우와", "와", "아하", "아하그렇구나",
    "그렇구나", "그렇군", "그렇군요", "음", "흠", "흐음", "넵", "넹", "웅", "웅웅",
    "ok", "okay", "ㅎㅎ", "ㅋㅋ", "ㅋㅋㅋ", "ㄱㄱ", "오케", "오케이",
}
_AGREEMENT = {
    "맞아", "맞아맞아", "맞네", "맞다", "그렇지", "그치", "그러네", "인정", "ㅇㅈ",
    "동의", "동의해", "그래그래", "맞는말", "맞말",
}
_DISAGREEMENT = {
    "아닌데", "아니야", "아냐", "아니지", "아니거든", "틀렸어", "틀림", "틀린데",
    "노노", "ㄴㄴ", "그건아니지", "아닌것같은데", "에이아니야",
}
_WHY = {
    "왜", "왜그래", "왜그럼", "왜그렇게", "왜그런데", "왜그렇게됨", "왜냐", "왜요",
    "왜죠", "왜이렇게", "대체왜", "왜그러는데", "아니왜", "근데왜", "그게왜", "그래서왜",
    "왜그러지", "왜인데", "왜임",
}
_CHALLENGE = {
    "그게맞아", "그게맞나", "맞나", "맞나요", "정말", "진짜", "진짜로", "확실해",
    "확실", "그런가", "그런가요", "틀린거아냐", "틀린거아님", "틀린거아니야",
    "말이안되는데", "말이안돼", "말이안됨", "이상한데", "이게맞나", "이게맞아",
    "설마", "그게진짜야", "맞는말이야", "맞는거야",
}
# 부분일치(토큰 in compact) 카테고리 — 다소 긴 문장 허용
_SIMPLIFY = (
    "더쉽게", "쉽게", "간단히", "간략", "요약해", "요약", "초딩", "쉬운말",
    "쉽게말", "쉽게설명", "이해하기쉽게", "알아듣게", "쉬운예", "풀어서",
)
_EXAMPLE = ("예시", "예를", "예로", "사례", "코드예", "예제", "실제예", "예좀", "비유로")
_CONTINUE = (
    "계속", "다음", "이어서", "이어줘", "마저", "더알려", "더말해", "더설명",
    "더해줘", "더자세", "자세히", "덧붙", "추가설명",
)
_CLARIFY = (
    "무슨말", "무슨소리", "뭔소리", "뭔말", "이해안", "이해가안", "다시설명",
    "다시말", "무슨뜻", "뭔뜻", "뭐라는", "어떤뜻", "다시한번",
)
# 새 질문 신호(이게 있으면 후속 발화가 아니라 새 학습 질문일 가능성↑)
_NEW_MARKERS = (
    "뭐야", "뭔데", "뭐임", "뭐죠", "무엇", "설명해줘", "설명좀", "알려줘", "알려줄래",
    "가르쳐", "차이", "비교", "어떻게", "정의가", "개념", "원리", "구조", "장단점",
    "방법", "이란", "대해서", "에대해", "란무엇", "어떤거", "무슨차이",
)

# 후속 발화로 인정하는 최대 compact 길이(터스함 기준)
_TERSE_MAX = 12           # why/challenge/agreement/backchannel
_REQUEST_MAX = 26         # simplify/example/continue/clarify (조금 더 긴 요청)


def _is_substantive_new(compact: str) -> bool:
    """길거나 새 주제어를 담은 메시지는 새 질문으로 본다."""
    return len(compact) > 18 or any(m in compact for m in _NEW_MARKERS)


def _decision(
    act: str, confidence: float, *, ctx: Optional[PreviousTurnContext], reason: str,
) -> DialogueActDecision:
    is_new = act in _FULL_ACTS
    if act in _MICRO_ACTS:
        depth = "micro"
    elif act in _SHORT_ACTS:
        depth = "short"
    elif act == UNKNOWN:
        depth = "ask_clarification"
    else:
        depth = "full"
    target = None
    if act in (FOLLOWUP_WHY, FOLLOWUP_CHALLENGE, FOLLOWUP_CLARIFY, FOLLOWUP_CONTINUE):
        if ctx and ctx.last_claims:
            target = ctx.last_claims[0]
    return DialogueActDecision(
        act=act,
        confidence=confidence,
        is_new_question=is_new,
        requires_three_agents=True,
        answer_depth=depth,
        suppress_validation=not is_new,
        suppress_peer_feedback=not is_new,
        anti_repeat=act in _ANTI_REPEAT_ACTS,
        target_previous_claim=target,
        reason=reason,
        source="deterministic",
    )


def classify_deterministic(
    message: str,
    *,
    previous_context: Optional[PreviousTurnContext] = None,
    mode: Optional[str] = None,
    learning_mode: Optional[str] = None,
) -> DialogueActDecision:
    raw = (message or "").strip()
    compact = _compact(raw)
    clen = len(compact)
    ctx = previous_context if isinstance(previous_context, PreviousTurnContext) else None
    has_ctx = bool(ctx and ctx.has_context)
    ends_q = raw.endswith("?") or raw.endswith("？")

    if not compact:
        return _decision(UNKNOWN, 0.3, ctx=ctx, reason="empty message")

    # 1) 순수 인사/감사(맥락 무관) ────────────────────────────────────────────
    if compact in _GREETING:
        return _decision(GREETING, 0.9, ctx=ctx, reason="greeting token")
    if compact in _THANKS:
        return _decision(THANKS, 0.9, ctx=ctx, reason="thanks token")

    # 2) 맥락이 있을 때의 후속 발화 ───────────────────────────────────────────
    if has_ctx:
        # 2a) 명시적 요청류(예시/더 쉽게/계속/다시설명) — 새 질문 마커보다 우선.
        if clen <= _REQUEST_MAX:
            if any(t in compact for t in _SIMPLIFY):
                return _decision(FOLLOWUP_SIMPLIFY, 0.85, ctx=ctx, reason="simplify request")
            if any(t in compact for t in _EXAMPLE):
                return _decision(FOLLOWUP_EXAMPLE, 0.85, ctx=ctx, reason="example request")
            if any(t in compact for t in _CLARIFY):
                return _decision(FOLLOWUP_CLARIFY, 0.82, ctx=ctx, reason="clarify request")
            if any(t in compact for t in _CONTINUE):
                return _decision(FOLLOWUP_CONTINUE, 0.82, ctx=ctx, reason="continue request")

        # 2b) 터스한 호응/반박/추궁/왜.
        if clen <= _TERSE_MAX:
            if compact in _BACKCHANNEL:
                return _decision(BACKCHANNEL, 0.9, ctx=ctx, reason="backchannel token")
            if compact in _AGREEMENT and not ends_q:
                return _decision(AGREEMENT, 0.88, ctx=ctx, reason="agreement token")
            if compact in _WHY or ("왜" in compact and clen <= 8):
                return _decision(FOLLOWUP_WHY, 0.9, ctx=ctx, reason="why-challenge after answer")
            if compact in _CHALLENGE or (ends_q and ("맞" in compact or compact in {"정말", "진짜", "그래", "그런가"})):
                return _decision(FOLLOWUP_CHALLENGE, 0.85, ctx=ctx, reason="doubt/challenge after answer")
            if compact in _DISAGREEMENT:
                # 근거 없는 단순 반박: 무엇이 문제인지 되물어야 함.
                d = _decision(DISAGREEMENT, 0.8, ctx=ctx, reason="bare disagreement")
                if not (ctx and ctx.last_claims):
                    d.answer_depth = "ask_clarification"
                return d

        # 2c) 그 외: 새 질문 신호가 있으면 새 질문, 아니면 보수적으로 새 질문(기존 동작 유지).
        if _is_substantive_new(compact):
            return _decision(NEW_STUDY_QUERY, 0.7, ctx=ctx, reason="substantive new question w/ context")
        return _decision(NEW_STUDY_QUERY, 0.55, ctx=ctx, reason="unmatched-with-context → default full")

    # 3) 맥락이 없을 때 ───────────────────────────────────────────────────────
    if compact in _BACKCHANNEL or compact in _AGREEMENT:
        return _decision(BACKCHANNEL, 0.7, ctx=ctx, reason="interjection, no context")
    if compact in _WHY or (clen <= _TERSE_MAX and compact in _CHALLENGE):
        # 직전 답변이 없으면 "왜?"는 애매 → 명확화 요청.
        return _decision(UNKNOWN, 0.45, ctx=ctx, reason="why/challenge without previous context")
    if _is_substantive_new(compact) or clen >= 6:
        return _decision(NEW_STUDY_QUERY, 0.72, ctx=ctx, reason="new study question, no context")
    return _decision(CASUAL_CHAT, 0.5, ctx=ctx, reason="short social, no context")


# ── 선택적 LLM 보조(애매한 경우에만, think=False, env 게이팅) ──────────────────
_LLM_TRIGGER_CONFIDENCE = 0.7

_LLM_SYSTEM_PROMPT = (
    "You classify a Korean user message in a multi-agent study chat. Decide whether the "
    "current message is a new study question, a follow-up/challenge to the previous answer, "
    "a request for simplification/example/continuation, or a casual/backchannel message. "
    "Return JSON only. Do not answer the user. Do not repeat the previous answer.\n"
    "Available acts: NEW_STUDY_QUERY, FOLLOWUP_WHY, FOLLOWUP_CHALLENGE, FOLLOWUP_CLARIFY, "
    "FOLLOWUP_EXAMPLE, FOLLOWUP_SIMPLIFY, FOLLOWUP_CONTINUE, AGREEMENT, DISAGREEMENT, "
    "BACKCHANNEL, CASUAL_CHAT, GREETING, THANKS, UNKNOWN.\n"
    "Rules: '아니왜?','왜?','근데 왜?','그게 왜?' after an assistant answer are FOLLOWUP_WHY, "
    "not NEW_STUDY_QUERY. '아닌데','그게 맞아?','틀린 거 아님?' are FOLLOWUP_CHALLENGE or "
    "DISAGREEMENT. '예시로','예를 들어' are FOLLOWUP_EXAMPLE. '더 쉽게','초딩도 알게' are "
    "FOLLOWUP_SIMPLIFY. '계속','이어줘' are FOLLOWUP_CONTINUE. answer_depth: 'full' only for "
    "NEW_STUDY_QUERY; 'short' for FOLLOWUP_*; 'micro' for AGREEMENT/BACKCHANNEL/GREETING/THANKS/"
    "CASUAL_CHAT; 'ask_clarification' when disagreement is ambiguous.\n"
    'Return JSON: {"act":"...","confidence":0.0,"answer_depth":"full|short|micro|ask_clarification",'
    '"target_previous_claim":"... or null","reason":"..."}'
)

_VALID_ACTS = {
    NEW_STUDY_QUERY, FOLLOWUP_WHY, FOLLOWUP_CHALLENGE, FOLLOWUP_CLARIFY, FOLLOWUP_EXAMPLE,
    FOLLOWUP_SIMPLIFY, FOLLOWUP_CONTINUE, AGREEMENT, DISAGREEMENT, BACKCHANNEL,
    CASUAL_CHAT, GREETING, THANKS, UNKNOWN,
}


def _llm_enabled(use_llm: Optional[bool]) -> bool:
    if use_llm is not None:
        return bool(use_llm)
    return os.getenv("DIALOGUE_ACT_USE_LLM", "0").strip().lower() in ("1", "true", "yes", "on")


def _parse_llm_json(text: str) -> Optional[dict]:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return None


def classify_with_llm(
    message: str,
    *,
    previous_context: Optional[PreviousTurnContext] = None,
    mode: Optional[str] = None,
    learning_mode: Optional[str] = None,
) -> Optional[DialogueActDecision]:
    """애매한 경우의 LLM 보조 분류. 실패하면 None(호출자가 결정론 폴백)."""
    try:
        from app.services.ollama_client import ask_ollama
    except Exception:  # pragma: no cover - 방어
        return None

    ctx = previous_context if isinstance(previous_context, PreviousTurnContext) else None
    user = (
        f"이전 사용자 질문: {ctx.last_user_message if ctx else ''}\n"
        f"직전 에이전트 답변 요약: {ctx.previous_answer_summary if ctx else ''}\n"
        f"현재 사용자 메시지: {message}\n"
        "JSON only."
    )
    try:
        out = ask_ollama(_LLM_SYSTEM_PROMPT, user, max_tokens=160, temperature=0.0, think=False)
    except Exception as e:  # pragma: no cover - 네트워크/모델 오류
        logger.warning("[DialogueAct] LLM 분류 실패: %s", e)
        return None

    data = _parse_llm_json(out)
    if not data:
        return None
    act = str(data.get("act", "")).strip().upper()
    if act not in _VALID_ACTS:
        return None
    base = _decision(act, float(data.get("confidence", 0.7) or 0.7), ctx=ctx,
                     reason=str(data.get("reason", "llm"))[:200])
    base.source = "llm"
    depth = str(data.get("answer_depth", "") or "").strip().lower()
    if depth in ("full", "short", "micro", "ask_clarification"):
        base.answer_depth = depth
    tgt = data.get("target_previous_claim")
    if isinstance(tgt, str) and tgt.strip() and tgt.strip().lower() != "null":
        base.target_previous_claim = tgt.strip()[:200]
    return base


def classify_dialogue_act(
    message: str,
    *,
    previous_context: Optional[PreviousTurnContext] = None,
    mode: Optional[str] = None,
    learning_mode: Optional[str] = None,
    use_llm: Optional[bool] = None,
) -> DialogueActDecision:
    """
    공개 진입점. 결정론 우선 + (애매하고 LLM 활성 시) LLM 보조.

    Returns: DialogueActDecision (항상 비-None).
    """
    det = classify_deterministic(
        message, previous_context=previous_context, mode=mode, learning_mode=learning_mode,
    )
    if _llm_enabled(use_llm) and det.confidence < _LLM_TRIGGER_CONFIDENCE:
        llm = classify_with_llm(
            message, previous_context=previous_context, mode=mode, learning_mode=learning_mode,
        )
        if llm is not None:
            return llm
    return det
