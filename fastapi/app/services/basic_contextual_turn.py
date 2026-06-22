"""
기본(basic) 모드 후속 발화용 컨텍스트 턴 스트림.

dialogue_act_classifier 가 현재 메시지를 NEW_STUDY_QUERY 가 아닌 후속 발화로
판정했을 때 호출된다. 직전 답변을 통째로 반복하지 않고, 3명의 에이전트가 각자
1~2문장 짧은 맥락 답변만 내도록 한다. validation/peer_feedback 은 내지 않는다
(basic 스트림은 원래도 그 이벤트를 내지 않으므로 계약 변화 없음).

이벤트 형식은 orchestrator_service.build_orchestrator_stream 과 동일:
    turn_start → agent_start(×N) → agent_answer(×N) → all_complete

신규 파일 — 기존 endpoint/스키마/계약 불변(additive).
"""
from __future__ import annotations

import logging
import os
import time
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, Generator, List, Optional

from app.services.dialogue_act_classifier import (
    DialogueActDecision,
    PreviousTurnContext,
    FOLLOWUP_WHY,
    FOLLOWUP_CHALLENGE,
    FOLLOWUP_CLARIFY,
    FOLLOWUP_EXAMPLE,
    FOLLOWUP_SIMPLIFY,
    FOLLOWUP_CONTINUE,
    DISAGREEMENT,
    AGREEMENT,
    BACKCHANNEL,
)

logger = logging.getLogger(__name__)

_REPEAT_THRESHOLD = 0.72   # SequenceMatcher 비율이 이 이상이면 "반복"으로 간주
ReplyFn = Callable[[str, Any, DialogueActDecision, Optional[PreviousTurnContext]], str]


# ── 유사도/반복 감지 ─────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    return "".join((s or "").split())


def is_repetitive_reply(new_reply: str, previous_answers: List[str], threshold: float = _REPEAT_THRESHOLD) -> bool:
    """새 답변이 직전 답변(들) 중 하나와 너무 유사하면 True."""
    a = _norm(new_reply)
    if not a:
        return True
    for prev in previous_answers or []:
        b = _norm(prev)
        if not b:
            continue
        if a in b or b in a:
            return True
        if SequenceMatcher(None, a, b).ratio() >= threshold:
            return True
    return False


# ── 에이전트 정체성 라벨(가능하면 SSOT 재사용) ───────────────────────────────
def _identity_payload(agent: Any) -> Dict[str, Any]:
    try:
        from app.services.multi_agent_service import _agent_identity_payload
        return _agent_identity_payload(agent) or {}
    except Exception:
        out: Dict[str, Any] = {}
        for k in ("personality", "personalityLabel", "knowledgeLevel", "knowledgeLevelLabel"):
            v = getattr(agent, k, None)
            if v:
                out[k] = v
        return out


def _agent_attr(agent: Any, *names: str, default: str = "") -> str:
    for n in names:
        v = getattr(agent, n, None)
        if v:
            return str(v)
    return default


# ── act별 짧은 사용자 지시(컨텍스트 reply prompt 보조) ────────────────────────
_ACT_DIRECTIVE = {
    FOLLOWUP_WHY: "사용자가 직전 답변의 이유를 묻고 있다. 직전 핵심 주장 1개의 '왜'만 한두 문장으로 설명하라.",
    FOLLOWUP_CHALLENGE: "사용자가 직전 답변을 의심/반박한다. 방어적으로 반복하지 말고, 어떤 전제/근거 때문인지 한두 문장으로 짚어라.",
    FOLLOWUP_CLARIFY: "사용자가 직전 답변을 이해하지 못했다. 핵심 1개만 다른 말로 짧게 풀어라.",
    FOLLOWUP_EXAMPLE: "사용자가 예시를 원한다. 설명을 반복하지 말고 구체적 예시 1개만 짧게 제시하라.",
    FOLLOWUP_SIMPLIFY: "사용자가 더 쉬운 설명을 원한다. 같은 내용을 더 낮은 난이도로 한두 문장으로 다시 표현하라.",
    FOLLOWUP_CONTINUE: "사용자가 이어가길 원한다. 직전 내용 다음 한 걸음만 짧게 덧붙여라.",
    DISAGREEMENT: "사용자가 근거 없이 반박했다. 같은 말을 반복하지 말고, 어느 지점이 걸리는지 한 문장으로 되물어라.",
    AGREEMENT: "사용자가 호응했다. 길게 설명하지 말고 한 문장으로 짧게 받아주고 다음을 가볍게 권하라.",
    BACKCHANNEL: "사용자가 짧게 반응했다. 긴 답변 금지. 한 문장으로 가볍게 이어가라.",
}


def _build_contextual_prompt(message: str, agent: Any, decision: DialogueActDecision,
                             ctx: Optional[PreviousTurnContext]) -> tuple[str, str]:
    name = _agent_attr(agent, "name", "agentName", default="교수")
    personality = _agent_attr(agent, "personality", "personalityLabel", "tone", "style", default="친절형")
    knowledge = _agent_attr(agent, "knowledgeLevel", "knowledgeLevelLabel", default="박사")
    last_user = ctx.last_user_message if ctx else ""
    prev_summary = ctx.previous_answer_summary if ctx else ""
    claims = "; ".join(ctx.last_claims) if (ctx and ctx.last_claims) else (decision.target_previous_claim or "")
    directive = _ACT_DIRECTIVE.get(decision.act, "직전 답변을 반복하지 말고 사용자의 후속 의도에만 짧게 답하라.")

    system = (
        f"너는 StudyBridge의 교수 에이전트 '{name}'다. 성격은 '{personality}', 지식수준은 '{knowledge}'다. "
        "지금 사용자 메시지는 새 질문이 아니라 직전 대화에 대한 후속 발화다. "
        "직전 답변 전체를 절대 반복하지 말고, 한국어로 1~2문장 이내로만 답하라. "
        "성격 차이는 드러내되 과장하지 말고, 다른 교수와 똑같은 문장을 쓰지 마라. "
        "validation/peer feedback/성격검증 점수/근거검증 문구는 출력하지 마라. 답변 문장만 출력하라."
    )
    user = (
        f"[현재 사용자 메시지] {message}\n"
        f"[분류] {decision.act} (answer_depth={decision.answer_depth})\n"
        f"[직전 사용자 질문] {last_user}\n"
        f"[직전 답변 요약] {prev_summary}\n"
        f"[직전 핵심 주장] {claims}\n"
        f"[이번 지시] {directive}\n"
        "1~2문장으로만, 직전 설명 반복 없이 답하라."
    )
    return system, user


# ── 기본 reply 함수: Ollama 호출(think=False, 짧게) ──────────────────────────
def _default_reply_fn(message: str, agent: Any, decision: DialogueActDecision,
                      ctx: Optional[PreviousTurnContext], *, regenerate: bool = False) -> str:
    from app.services.ollama_client import ask_ollama
    system, user = _build_contextual_prompt(message, agent, decision, ctx)
    if regenerate:
        user += ("\n[주의] 직전 생성이 이전 답변을 반복했다. 설명을 다시 풀지 말고, "
                 "사용자의 후속 의도만 새 문장으로 아주 짧게 답하라.")
    max_tokens = 90 if decision.answer_depth == "micro" else 160
    try:
        out = ask_ollama(system, user, max_tokens=max_tokens, temperature=0.6, think=False)
        return (out or "").strip()
    except Exception as e:
        logger.warning("[BasicContextual] reply 생성 실패(%s): %s", _agent_attr(agent, "name"), e)
        return ""


# act별 결정론 폴백 — 절대 직전 답변의 내용(주제어)을 그대로 되풀이하지 않는다.
# (주제어를 본문에 박으면 그 단어 때문에 답이 반복된다 → 의도적으로 content-free.)
# 직전 내용은 "방금 그 부분"처럼 추상적으로만 가리킨다. 에이전트마다 다른 변형을 쓴다.
_FALLBACK_VARIANTS = {
    FOLLOWUP_WHY: [
        "그 결론이 나오는 건 가장 기본이 되는 전제 때문인데, 어느 지점이 걸리는지 콕 짚어줄래?",
        "핵심 이유는 앞 단계가 그걸 강제하기 때문이야. 어떤 부분이 더 궁금해?",
        "왜냐면 그게 성립하지 않으면 앞 얘기가 무너지거든. 어디가 의심돼?",
    ],
    FOLLOWUP_CHALLENGE: [
        "어느 부분이 걸리는지 한 가지만 알려주면 그 지점만 다시 볼게.",
        "의심되는 대목을 콕 집어주면 거기만 근거를 다시 들어줄게.",
        "어떤 전제가 이상하게 느껴졌어? 그것만 다시 따져보자.",
    ],
    FOLLOWUP_CLARIFY: [
        "방금 설명에서 어떤 표현이 어려웠어? 그 부분만 다른 말로 바꿔줄게.",
        "어느 문장이 헷갈렸는지 알려주면 그것만 풀어서 말해줄게.",
        "막힌 지점 하나만 짚어주면 거기부터 다시 갈게.",
    ],
    FOLLOWUP_EXAMPLE: [
        "바로 떠오르는 사례 하나로 다시 보여줄게.",
        "구체적인 상황 하나를 들어 설명해줄게.",
        "실제로 마주치는 장면으로 바꿔 들려줄게.",
    ],
    FOLLOWUP_SIMPLIFY: [
        "한 줄로 줄이면 돼. 어느 부분이 어려웠는지 알려줄래?",
        "더 쉬운 말로 바꿔볼게. 막힌 단어가 있었어?",
        "비유로 풀어줄게. 어디가 무거웠는지 짚어줘.",
    ],
    FOLLOWUP_CONTINUE: [
        "다음 단계로 한 걸음만 더 가볼게.",
        "이어서 그다음 포인트를 짧게 덧붙일게.",
        "바로 다음 흐름으로 넘어가 볼게.",
    ],
    DISAGREEMENT: [
        "어느 지점이 틀렸다고 느꼈는지 한 가지만 짚어줄래?",
        "어떤 부분이 안 맞는다고 생각했어? 그것만 다시 보자.",
        "걸리는 대목 하나만 알려주면 거기부터 다시 볼게.",
    ],
}
_FALLBACK_MICRO = [
    "좋아, 더 궁금한 게 있으면 이어서 물어봐.",
    "응, 다음으로 넘어가도 되고 더 파봐도 돼.",
    "오케이, 이어서 뭐가 더 궁금한지 말해줘.",
]


def _compact_fallback(agent: Any, decision: DialogueActDecision,
                      ctx: Optional[PreviousTurnContext], idx: int = 0) -> str:
    """LLM 실패/반복 시 결정론 짧은 폴백. 비어있지 않고, 직전 답변 내용을 반복하지 않는다."""
    pick = idx % 3  # 에이전트 순번 기준 변형 → 세 답변이 서로 베끼지 않음(이름 해시 충돌 회피)
    act = decision.act
    if act in (AGREEMENT, BACKCHANNEL):
        return _FALLBACK_MICRO[pick]
    variants = _FALLBACK_VARIANTS.get(act)
    if variants:
        return variants[pick]
    return ("방금 그 부분에서 어디가 더 궁금한지 한 가지만 짚어줄래?",
            "어느 대목을 더 보고 싶은지 알려줘.",
            "다음에 뭘 더 파보면 좋을지 말해줘.")[pick]


def _produce_contextual_answer(
    message: str,
    agent: Any,
    decision: DialogueActDecision,
    ctx: Optional[PreviousTurnContext],
    reply_fn: ReplyFn,
    prev_texts: List[str],
    produced: List[str],
    idx: int,
) -> str:
    """한 에이전트의 짧은 맥락 답변 1개를 생성한다(반복 방지 가드 포함).
    스트림/논스트림 양쪽이 공유한다 — anti-repeat 정책을 한 곳에 둔다."""
    try:
        answer = (reply_fn(message, agent, decision, ctx) or "").strip()
    except Exception as e:  # pragma: no cover - 방어
        logger.warning("[BasicContextual] reply_fn 오류: %s", e)
        answer = ""

    # 반복 방지 가드: 직전 답변/이미 생성한 답변과 너무 유사하면 1회 재생성 → 폴백.
    if decision.anti_repeat and answer and is_repetitive_reply(answer, prev_texts + produced):
        regen = ""
        try:
            regen = (reply_fn(message, agent, decision, ctx, regenerate=True) or "").strip()  # type: ignore[call-arg]
        except TypeError:
            regen = ""  # reply_fn 이 regenerate 인자를 받지 않는 경우
        except Exception:
            regen = ""
        if regen and not is_repetitive_reply(regen, prev_texts + produced):
            answer = regen
        else:
            answer = _compact_fallback(agent, decision, ctx, idx)

    if not answer:
        answer = _compact_fallback(agent, decision, ctx, idx)
    return answer


def run_basic_contextual_turn(
    request: Any,
    agents: List[Any],
    decision: DialogueActDecision,
    previous_context: Optional[PreviousTurnContext],
    *,
    reply_fn: Optional[ReplyFn] = None,
) -> List[Dict[str, Any]]:
    """basic 후속 발화 비스트림 버전. 스트림과 동일한 정책(3명 짧은 답변·반복 방지·
    validation/peer_feedback 없음)으로 answer dict 리스트를 반환한다."""
    reply_fn = reply_fn or _default_reply_fn
    message = getattr(request, "message", "") or ""
    selected = list(agents or [])[:3]
    ctx = previous_context
    prev_texts = list(ctx.last_agent_answers) if (ctx and ctx.last_agent_answers) else []

    produced: List[str] = []
    all_answers: List[Dict[str, Any]] = []
    for idx, agent in enumerate(selected):
        agent_id = getattr(agent, "agentId", None) or f"agent-{getattr(agent, 'id', idx)}"
        agent_name = _agent_attr(agent, "name", "agentName", default="AI")
        identity = _identity_payload(agent)
        answer = _produce_contextual_answer(
            message, agent, decision, ctx, reply_fn, prev_texts, produced, idx
        )
        produced.append(answer)
        all_answers.append({
            "agentId": agent_id, "agentName": agent_name, "answer": answer,
            "displayOrder": idx + 1, "stage": 1, "status": "SUCCESS", **identity,
        })
    return all_answers


def run_basic_contextual_turn_stream(
    request: Any,
    agents: List[Any],
    decision: DialogueActDecision,
    previous_context: Optional[PreviousTurnContext],
    *,
    reply_fn: Optional[ReplyFn] = None,
    min_gap: float = 0.0,
) -> Generator[Dict[str, Any], None, None]:
    """basic 모드 후속 발화: 3명 짧은 맥락 답변. validation/peer_feedback 없음."""
    reply_fn = reply_fn or _default_reply_fn
    message = getattr(request, "message", "") or ""
    selected = list(agents or [])[:3]
    ctx = previous_context
    prev_texts = list(ctx.last_agent_answers) if (ctx and ctx.last_agent_answers) else []

    yield {
        "event": "turn_start",
        "data": {
            "type": "turn_start",
            "mode": "basic",
            "learningMode": "basic",
            "dialogueAct": decision.act,
            "answerDepth": decision.answer_depth,
            "phase": "CONTEXTUAL_FOLLOWUP",
            "message": "후속 질문에 대해 짧게 답하고 있습니다...",
            "visible": True,
        },
    }

    produced: List[str] = []
    all_answers: List[Dict[str, Any]] = []
    n = len(selected)
    for idx, agent in enumerate(selected):
        t0 = time.time()
        agent_id = getattr(agent, "agentId", None) or f"agent-{getattr(agent, 'id', idx)}"
        agent_name = _agent_attr(agent, "name", "agentName", default="AI")
        identity = _identity_payload(agent)

        yield {
            "event": "agent_start",
            "data": {
                "type": "agent_start",
                "agentIndex": idx + 1,
                "agentName": agent_name,
                "agentId": agent_id,
                "phase": "CONTEXTUAL_FOLLOWUP",
                "dialogueAct": decision.act,
                "visible": True,
                **identity,
            },
        }

        answer = _produce_contextual_answer(
            message, agent, decision, ctx, reply_fn, prev_texts, produced, idx
        )

        yield {
            "event": "agent_answer",
            "data": {
                "type": "agent_answer",
                "agentIndex": idx + 1,
                "agentName": agent_name,
                "agentId": agent_id,
                "answer": answer,
                "displayOrder": idx + 1,
                "stage": 1,
                "phase": "CONTEXTUAL_FOLLOWUP",
                "dialogueAct": decision.act,
                "answerDepth": decision.answer_depth,
                "visible": True,
                "status": "SUCCESS",
                **identity,
            },
        }
        produced.append(answer)
        all_answers.append({
            "agentId": agent_id, "agentName": agent_name, "answer": answer,
            "displayOrder": idx + 1, "stage": 1, "status": "SUCCESS", **identity,
        })

        if idx < n - 1 and min_gap > 0:
            remaining = min_gap - (time.time() - t0)
            if remaining > 0:
                time.sleep(remaining)

    yield {
        "event": "all_complete",
        "data": {
            "type": "all_complete",
            "mode": "basic",
            "learningMode": "basic",
            "dialogueAct": decision.act,
            "answerDepth": decision.answer_depth,
            "agentCount": len(all_answers),
            "answers": all_answers,
            "messages": all_answers,
            "suppressValidation": True,
            "suppressPeerFeedback": True,
            "status": "COMPLETED",
            "phase": "ALL_COMPLETE",
            "visible": True,
        },
    }
