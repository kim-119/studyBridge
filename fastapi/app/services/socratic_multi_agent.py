"""
소크라테스 모드 — 다중 에이전트 사이클 엔진.

기존 socratic_session_engine 은 '한 명의 러닝메이트'를 전제로 만들어졌다.
그 결과 방에 3명을 설정해도 agents[0] 한 명만 발화했고, 한 문장짜리 질문만 나갔다.

이 모듈은 그 전제를 바꾼다.
  - 선택된 에이전트는 '모두' 한 사이클에서 실제로 모델 호출을 받는다.
  - 다만 세 명이 동시에 짧은 질문만 던져 사용자를 혼란시키지 않도록 기능적 역할을 나눈다.

      PROBE       개념 유도   — 사용자의 현재 전제를 확인하고 사고 방향을 잡는다
      PERSPECTIVE 관점/반례   — 앞 발언과 다른 각도나 반례를 제시한다
      VERIFY      논리 검증   — 지금까지의 추론에서 빠진 고리를 짚는다

  - 각 발언의 출력 계약은 '맥락 인정 + 사고 방향 + 질문 1개'다.
    max_tokens 만 늘리는 방식이 아니라 계약 자체로 빈약한 한 문장 응답을 막는다.
  - 뒤 순서 에이전트는 같은 사이클의 앞 발언을 실제 입력으로 받는다(각자 독립 생성 금지).
  - 정답을 먼저 말하지 않는다(기존 leaks_answer 게이트 재사용).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services import socratic_session_engine as SE

logger = logging.getLogger(__name__)

# ── 기능적 역할 ─────────────────────────────────────────────────────────────
PROBE, PERSPECTIVE, VERIFY = "PROBE", "PERSPECTIVE", "VERIFY"
ROLE_CYCLE = (PROBE, PERSPECTIVE, VERIFY)

ROLE_LABEL = {PROBE: "개념 유도", PERSPECTIVE: "다른 관점", VERIFY: "논리 검증"}
# 기존 프론트 socraticSteps stageType 계약을 그대로 쓴다(새 UI 계약을 만들지 않는다).
ROLE_STAGE_TYPE = {PROBE: "DIAGNOSIS", PERSPECTIVE: "COUNTEREXAMPLE", VERIFY: "MISCONCEPTION_CHECK"}
ROLE_STAGE_TITLE = {PROBE: "생각 확인 질문", PERSPECTIVE: "다른 관점/반례", VERIFY: "논리 검증 질문"}

MIN_TURN_CHARS = int(os.getenv("SOCRATIC_MIN_TURN_CHARS", "80"))
MAX_TURN_CHARS = int(os.getenv("SOCRATIC_MULTI_MAX_CHARS", "700"))
MAX_STEP_RETRIES = int(os.getenv("SOCRATIC_MAX_STEP_RETRIES", "2"))


@dataclass
class AgentSpeech:
    """한 에이전트의 한 발언."""
    role: str
    agent_id: Any
    agent_name: str
    agent_index: int
    text: str
    question: str = ""
    acknowledge: str = ""
    direction: str = ""
    assessment: str = ""
    regenerated: int = 0
    repaired: bool = False
    issues: List[str] = field(default_factory=list)
    structured: Dict[str, Any] = field(default_factory=dict)


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _agent_id(agent: Any, fallback: str) -> Any:
    return getattr(agent, "agentId", None) or getattr(agent, "id", None) or fallback


def _agent_name(agent: Any, idx: int) -> str:
    return _s(getattr(agent, "name", None)) or f"러닝메이트 {idx}"


def assign_roles(agents: Sequence[Any]) -> List[Tuple[Any, str]]:
    """선택된 에이전트 '전원'에게 기능적 역할을 배정한다.

    3명을 넘으면 역할을 순환 배정한다. 아무도 없으면 가상 튜터 1명을 만든다.
    에이전트를 잘라내지 않는다 — 선택된 사람은 모두 말한다.
    """
    live = [a for a in (agents or []) if a is not None]
    if not live:
        from app.schemas.multi_chat_schema import AgentProfile
        live = [AgentProfile(agentId="socratic-tutor", id="socratic-tutor", name="러닝메이트")]
    return [(a, ROLE_CYCLE[i % len(ROLE_CYCLE)]) for i, a in enumerate(live)]


# ── 프롬프트 ────────────────────────────────────────────────────────────────

_SYSTEM = (
    "너는 StudyBridge 소크라테스 학습방의 한 참여자다. 정답을 알려주는 강사가 아니다.\n"
    "- 목적은 사용자가 스스로 답에 도달하게 하는 것이다. 결과가 아니라 사고 과정이 중요하다.\n"
    "- 너는 여러 참여자 중 한 명이다. 앞선 참여자가 한 말을 반복하지 마라.\n"
    "- 정답·정의·결론을 먼저 말하지 않는다. 강의체 요약 금지.\n"
    "- 네 발언에서 질문은 정확히 1개다. 질문 앞에는 맥락과 사고 방향을 먼저 말한다.\n"
    "- 출력은 지시된 JSON 하나만. 설명·머리말·코드펜스 금지. 값은 한국어."
)

_ROLE_DIRECTIVE = {
    PROBE: (
        "너의 역할은 '개념 유도'다.\n"
        "- 사용자가 지금 무엇을 이미 알고 있다고 말했는지 먼저 확인한다.\n"
        "- 그 전제에서 한 걸음 더 나아가려면 어디를 봐야 하는지 방향을 잡아준다.\n"
        "- 그 방향을 확인하는 질문 1개로 끝낸다."
    ),
    PERSPECTIVE: (
        "너의 역할은 '다른 관점/반례'다.\n"
        "- 앞선 참여자의 발언과 사용자의 말을 읽고, 같은 질문을 다시 하지 마라.\n"
        "- 다른 각도(예: 반대 방향의 상황, 조건이 바뀐 경우, 반례)를 제시한다.\n"
        "- 그 각도에서 사용자가 스스로 따져보게 만드는 질문 1개로 끝낸다."
    ),
    VERIFY: (
        "너의 역할은 '논리 검증'이다.\n"
        "- 지금까지 나온 사용자의 추론과 앞선 참여자들의 지적에서 '아직 연결되지 않은 고리'를 찾는다.\n"
        "- 무엇이 아직 근거 없이 넘어갔는지 짚는다(비난하지 않는다).\n"
        "- 그 고리를 잇게 하는 검증 질문 1개로 끝낸다."
    ),
}

_JSON_SPEC = (
    '{"acknowledge":"...","direction":"...","question":"...?"}'
)
_JSON_SPEC_WITH_ASSESSMENT = (
    '{"assessment":"partial","acknowledge":"...","direction":"...","question":"...?"}'
)


def _peer_block(peers: List[AgentSpeech]) -> str:
    if not peers:
        return "[이번 사이클에서 너보다 먼저 말한 참여자] 없음(네가 첫 번째다)\n"
    lines = ["[이번 사이클에서 너보다 먼저 말한 참여자 — 실제 발언 원문]"]
    for sp in peers:
        lines.append(f"- {sp.agent_name}({ROLE_LABEL.get(sp.role, sp.role)}): {sp.text}")
    lines.append("위 발언과 같은 질문을 반복하면 실패다.")
    return "\n".join(lines) + "\n"


def _transcript_block(transcript: List[Dict[str, str]], limit: int = 8) -> str:
    if not transcript:
        return ""
    lines = ["[이전 대화]"]
    for item in transcript[-limit:]:
        who = "사용자" if item.get("role") == "user" else _s(item.get("name")) or "참여자"
        lines.append(f"- {who}: {_s(item.get('text'))}")
    return "\n".join(lines) + "\n"


def _build_user_prompt(*, topic: str, user_message: str, role: str, agent: Any,
                       peers: List[AgentSpeech], transcript: List[Dict[str, str]],
                       intensity: str, hint_style: str, is_first_cycle: bool,
                       expected_idea: str) -> str:
    from app.services.debate_engine import build_style_directive

    head = f"[사용자가 지금 배우려는 주제]\n{topic}\n"
    if not is_first_cycle and user_message:
        head += f"\n[사용자의 이번 답변 — 최우선 입력]\n{user_message}\n"
    secret = (f"\n[내부 기록 — 사용자에게 절대 노출 금지] 사용자가 스스로 도달해야 할 결론: {expected_idea}\n"
              if expected_idea else "")
    # 사이클의 첫 발언자는 사용자의 답을 평가한다(힌트 단계/마무리 판단의 입력).
    assess = ("- assessment: 사용자의 이번 답변 평가. correct | partial | wrong | unknown 중 하나.\n"
              if (role == PROBE and not is_first_cycle) else "")
    spec = _JSON_SPEC_WITH_ASSESSMENT if assess else _JSON_SPEC
    return (
        f"{head}{_transcript_block(transcript)}\n{_peer_block(peers)}\n"
        f"{_ROLE_DIRECTIVE[role]}\n\n"
        f"{SE._intensity_directive(intensity, hint_style)}\n"
        f"{secret}\n"
        "다음 JSON만 출력하라.\n"
        f"{assess}"
        "- acknowledge: 사용자의 말이나 앞 참여자의 지적 중 실제로 있었던 것을 한 문장으로 받는다.\n"
        "- direction: 지금 어디를 봐야 하는지 사고 방향 1~2문장(정답을 말하지 않는다).\n"
        "- question: 사용자가 스스로 답하게 만드는 질문 정확히 1개(물음표로 끝난다).\n"
        f"★ acknowledge+direction 은 합쳐서 최소 {MIN_TURN_CHARS}자 이상이어야 한다. "
        "한 문장짜리 질문만 던지면 실패다.\n"
        "★ 정답 문장을 그대로 알려주면 실패다.\n\n"
        f"{build_style_directive(agent)}\n\n{spec}"
    )


# ── 검증 ────────────────────────────────────────────────────────────────────

def validate_speech(sp: AgentSpeech, *, expected_idea: str, known_text: str,
                    keywords: Optional[List[str]], used_questions: List[str]) -> List[str]:
    issues: List[str] = []
    if not sp.question or not sp.question.strip().endswith("?"):
        issues.append("question_missing")
    if SE.count_questions(sp.text) != 1:
        issues.append("not_single_question")
    body = f"{sp.acknowledge} {sp.direction}".strip()
    if len(body) < MIN_TURN_CHARS:
        issues.append("too_shallow")
    if len(sp.text) > MAX_TURN_CHARS:
        issues.append("too_long")
    if SE.leaks_answer(sp.text, expected_idea, known_text, keywords):
        issues.append("answer_leaked")
    for marker in SE._LECTURE_MARKERS:
        if marker in sp.text:
            issues.append("lecture_style")
            break
    if used_questions and sp.question:
        from app.services.korean_text_match import repeats_any
        if repeats_any(sp.question, used_questions, 0.85):
            issues.append("question_repeated")
    return issues


def _render(acknowledge: str, direction: str, question: str) -> str:
    body = " ".join(p for p in (acknowledge, direction) if p).strip()
    return SE.normalize_text("\n\n".join(p for p in (body, question) if p))


def _repair(sp: AgentSpeech, *, topic: str, expected_idea: str, known_text: str,
            keywords: Optional[List[str]], used_questions: List[str]) -> AgentSpeech:
    """재생성 상한을 넘겨도 계약 위반 텍스트를 사용자에게 내보내지 않는다.

    모델을 더 부르지 않고 구조만 고친다. 에이전트를 침묵시키지는 않는다
    (선택된 에이전트는 모두 발화한다는 계약이 우선이다).
    """
    from app.services.korean_text_match import repeats_any

    ack, direction = sp.acknowledge, sp.direction
    question = SE.first_question(sp.question or sp.text)

    if ack and SE.leaks_answer(ack, expected_idea, known_text, keywords):
        ack = ""
    if direction and SE.leaks_answer(direction, expected_idea, known_text, keywords):
        direction = ""
    if question and SE.leaks_answer(question, expected_idea, known_text, keywords):
        question = ""
    if not question.endswith("?") or (used_questions and repeats_any(question, used_questions, 0.9)):
        question = SE.topic_anchored_question(topic, used_questions)

    body = f"{ack} {direction}".strip()
    if len(body) < MIN_TURN_CHARS:
        # content-free 보강: 도메인 용어를 코드에 박지 않고 역할이 하는 일만 말한다.
        direction = (direction + " " + _ROLE_BRIDGE[sp.role]).strip()

    sp.acknowledge, sp.direction, sp.question = ack, direction, question
    sp.text = _render(ack, direction, question)
    sp.repaired = True
    return sp


# 마지막 수단으로 붙이는 역할별 다리 문장(주제어를 박지 않는다).
_ROLE_BRIDGE = {
    PROBE: "지금 확실하게 말할 수 있는 부분과 아직 확인되지 않은 부분을 나눠서 정리해보자.",
    PERSPECTIVE: "조건이 지금과 달랐다면 같은 결론이 유지되는지도 함께 따져보자.",
    VERIFY: "여기까지의 설명에서 근거 없이 넘어간 연결 고리가 있는지 확인해보자.",
}


# ── 생성 ────────────────────────────────────────────────────────────────────

def generate_speech(*, topic: str, user_message: str, agent: Any, role: str, agent_index: int,
                    peers: List[AgentSpeech], transcript: List[Dict[str, str]],
                    intensity: str, hint_style: str, is_first_cycle: bool,
                    expected_idea: str, keywords: Optional[List[str]],
                    used_questions: List[str], llm=None) -> AgentSpeech:
    """한 에이전트의 발언 1건을 실제 모델 호출로 만든다(에이전트당 1콜 + 재생성)."""
    call = llm or SE._default_llm
    user_prompt = _build_user_prompt(
        topic=topic, user_message=user_message, role=role, agent=agent, peers=peers,
        transcript=transcript, intensity=intensity, hint_style=hint_style,
        is_first_cycle=is_first_cycle, expected_idea=expected_idea)
    known_text = f"{topic}\n{user_message}"
    aid = _agent_id(agent, f"socratic-{agent_index}")
    name = _agent_name(agent, agent_index)

    last: Optional[AgentSpeech] = None
    last_issues: List[str] = ["empty_response"]
    for attempt in range(MAX_STEP_RETRIES + 1):
        prompt = user_prompt if attempt == 0 else (
            f"{user_prompt}\n\n[재작성 지시 — 직전 출력이 계약을 어겼다: {', '.join(last_issues)}]\n"
            f"질문은 1개만, 앞부분 설명은 {MIN_TURN_CHARS}자 이상, 정답은 말하지 마라.")
        raw = call(_SYSTEM, prompt, max_tokens=SE.CONTENT_MAX_TOKENS, temperature=0.45 + 0.05 * attempt)
        obj = SE._parse(raw)
        ack = _s(obj.get("acknowledge"))
        direction = _s(obj.get("direction")) or _s(obj.get("hint"))
        assessment = _s(obj.get("assessment")).lower()
        question = SE.first_question(_s(obj.get("question")))
        # acknowledge/direction 에 질문이 섞이면 '한 발언 한 질문' 계약이 깨진다.
        ack = ack.split("?")[0].strip() if "?" in ack else ack
        direction = direction.split("?")[0].strip() if "?" in direction else direction
        sp = AgentSpeech(
            role=role, agent_id=aid, agent_name=name, agent_index=agent_index,
            text=_render(ack, direction, question), question=question,
            acknowledge=ack, direction=direction, assessment=assessment, regenerated=attempt,
            structured={"acknowledge": ack, "direction": direction, "question": question,
                        "assessment": assessment, "role": role,
                        "roleLabel": ROLE_LABEL.get(role, role)},
        )
        issues = validate_speech(sp, expected_idea=expected_idea, known_text=known_text,
                                 keywords=keywords, used_questions=used_questions)
        if not issues:
            return sp
        last, last_issues = sp, issues
        logger.warning("[SOCRATIC-MULTI] %s(%s) 계약 위반(attempt=%d) issues=%s",
                       name, role, attempt + 1, issues)

    sp = last or AgentSpeech(role=role, agent_id=aid, agent_name=name,
                             agent_index=agent_index, text="")
    sp.issues = last_issues
    return _repair(sp, topic=topic, expected_idea=expected_idea, known_text=known_text,
                   keywords=keywords, used_questions=used_questions)


def run_cycle(*, topic: str, user_message: str, roles: List[Tuple[Any, str]],
              transcript: List[Dict[str, str]], intensity: str, hint_style: str,
              is_first_cycle: bool, expected_idea: str, keywords: Optional[List[str]],
              used_questions: List[str], llm=None,
              on_speech=None) -> List[AgentSpeech]:
    """한 사이클 = 선택된 에이전트 전원이 순서대로 한 번씩 발화한다.

    뒤 순서 에이전트는 앞 발언 원문을 입력으로 받는다(각자 독립 생성 금지).
    on_speech 가 있으면 발언이 만들어지는 즉시 흘려보낸다(SSE 선출력).
    """
    speeches: List[AgentSpeech] = []
    asked = list(used_questions)
    for idx, (agent, role) in enumerate(roles, start=1):
        sp = generate_speech(
            topic=topic, user_message=user_message, agent=agent, role=role, agent_index=idx,
            peers=list(speeches), transcript=transcript, intensity=intensity,
            hint_style=hint_style, is_first_cycle=is_first_cycle, expected_idea=expected_idea,
            keywords=keywords, used_questions=asked, llm=llm)
        speeches.append(sp)
        if sp.question:
            asked.append(sp.question)
        if on_speech:
            on_speech(sp)
    return speeches


def validate_cycle(speeches: List[AgentSpeech], expected_count: int) -> List[str]:
    """사이클 전체 계약: 전원 발화 / 역할 분리 / 질문 1개씩 / 빈약하지 않음."""
    issues: List[str] = []
    if len(speeches) != expected_count:
        issues.append(f"agent_count_{len(speeches)}_expected_{expected_count}")
    for sp in speeches:
        if not sp.question:
            issues.append(f"{sp.agent_name}_question_missing")
        if len(sp.text) < MIN_TURN_CHARS:
            issues.append(f"{sp.agent_name}_too_shallow")
    if expected_count >= 2:
        roles = [sp.role for sp in speeches[:len(ROLE_CYCLE)]]
        if len(set(roles)) != len(roles):
            issues.append("roles_not_distinct")
    return issues


def derive_expected_idea(topic: str, llm=None) -> Tuple[str, List[str]]:
    """사이클 시작 전 '사용자가 스스로 도달해야 할 결론'을 내부 기록으로 확보한다.

    사용자에게 보여주지 않는다. 정답 노출 게이트(leaks_answer)의 기준으로만 쓴다.
    실패해도 사이클을 막지 않는다(게이트가 느슨해질 뿐이다).
    """
    call = llm or SE._default_llm
    user = (
        f"[주제]\n{topic}\n\n"
        "이 주제에서 학습자가 스스로 도달해야 할 핵심 결론을 정리하라. 사용자에게 보여주지 않는 내부 기록이다.\n"
        "- expectedIdea: 핵심 결론 1~2문장.\n"
        "- answerKeywords: 그 결론을 결정적으로 드러내는 표현 1~3개.\n\n"
        '{"expectedIdea":"...","answerKeywords":["..."]}'
    )
    try:
        obj = SE._parse(call(_SYSTEM, user, max_tokens=300, temperature=0.3))
        idea = _s(obj.get("expectedIdea"))
        kws = [_s(k) for k in (obj.get("answerKeywords") or []) if _s(k)][:3]
        return idea, kws
    except Exception as exc:  # pragma: no cover - 방어
        logger.warning("[SOCRATIC-MULTI] expectedIdea 확보 실패: %s", type(exc).__name__)
        return "", []
