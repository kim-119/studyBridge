"""
StudyBridge DEBATE(토론) 모드 실행 엔진.

기존 토론은 '토론 형식으로 답하라'는 system prompt 한 줄이었고, 실제 구조는
기본 모드와 동일한 per-agent 1회 호출이었다. 즉 두 에이전트가 각자 자기 말만 하고
끝났다(상대 발언을 읽지 않으므로 반박이 아니라 병렬 의견 나열).

이 모듈은 토론을 코드 레벨 orchestration으로 재구현한다.

  사용자 메시지 = 안건(1단계). 별도의 논제 생성/논제 입력을 하지 않는다.
  각 에이전트는 6단 논법 중 2~6단계를 실제로 수행한다.
    2. 결론  3. 이유  4. 설명  5. 반론 꺾기  6. 예외 정리

  A 입론 → B 입론 → (A→B 반박 → B→A 반박) × N라운드
    → 예외 정리 → (입장 수정) → 수렴 → 최종 결론

  ★ 반박은 반드시 '상대의 실제 출력값(transcript)'을 입력으로 받는다(strawman 방지).
  ★ 사회자/판정자 에이전트를 만들지 않는다. 최종 결론은 마지막 발언 에이전트가
    양측의 수정된 결론을 근거로 작성한다.
  ★ 승패를 정하지 않는다. 조건이 붙은 하나의 판단(decision/conditions/reason/recommendation)을 낸다.

레이어 분리:
  Content layer  — 논리(JSON: conclusion/reasons/explanation/rebuttal/exception)를 만든다.
  Style layer    — 성격/지식수준/customInstruction을 '표현'에만 적용한다.
  우선순위: Debate Contract > Assigned Stance > Knowledge Level > Persona/Tone
"""
from __future__ import annotations

import difflib
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

from app.schemas.multi_chat_schema import AgentProfile, MultiChatRequest

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 0) 토론 강도 (light | normal | deep) — 라운드 수로 반영한다(토큰 길이가 아니다)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LIGHT, NORMAL, DEEP = "light", "normal", "deep"
STRENGTHS = (LIGHT, NORMAL, DEEP)

_STRENGTH_ALIASES: Dict[str, str] = {
    "light": LIGHT, "낮음": LIGHT, "약": LIGHT, "약함": LIGHT, "가볍게": LIGHT, "간단": LIGHT, "shallow": LIGHT,
    "normal": NORMAL, "보통": NORMAL, "중간": NORMAL, "기본": NORMAL, "standard": NORMAL, "medium": NORMAL,
    "deep": DEEP, "깊음": DEEP, "깊게": DEEP, "심화": DEEP, "high": DEEP, "강함": DEEP,
}

# 강도 → 상호 반박 라운드 수. (라운드마다 A→B, B→A 각 1회 = 2발언)
_REBUTTAL_ROUNDS: Dict[str, int] = {LIGHT: 1, NORMAL: 2, DEEP: 3}

# 발언 1건의 토큰 예산은 강도와 무관하게 동일하다.
# (강도 차이를 '길이 차이'로 처리하지 않기 위한 명시적 상수)
CONTENT_MAX_TOKENS = int(os.getenv("DEBATE_CONTENT_MAX_TOKENS", "900"))
CONTENT_TEMPERATURE = float(os.getenv("DEBATE_CONTENT_TEMPERATURE", "0.45"))
MAX_STEP_RETRIES = int(os.getenv("DEBATE_MAX_STEP_RETRIES", "2"))


def normalize_strength(value: Any) -> Optional[str]:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    return _STRENGTH_ALIASES.get(raw)


def _config_depth(cfg: Any) -> Optional[str]:
    """debateConfig 가 pydantic 모델이든 dict 든 debateDepth 를 읽는다."""
    if cfg is None:
        return None
    if isinstance(cfg, dict):
        return cfg.get("debateDepth") or cfg.get("debate_depth")
    return getattr(cfg, "debateDepth", None) or getattr(cfg, "debate_depth", None)


def resolve_strength(request: MultiChatRequest) -> str:
    """요청에서 토론 강도를 뽑는다. debateStrength > debateConfig.debateDepth > normal."""
    for candidate in (
        getattr(request, "debateStrength", None),
        getattr(request, "debateDepth", None),
        _config_depth(getattr(request, "debateConfig", None)),
        getattr(request, "answerDepth", None) if str(getattr(request, "answerDepth", "") or "").lower() in _STRENGTH_ALIASES else None,
    ):
        norm = normalize_strength(candidate)
        if norm:
            return norm
    return NORMAL


def rebuttal_rounds(strength: str) -> int:
    return _REBUTTAL_ROUNDS.get(normalize_strength(strength) or NORMAL, 2)


def uses_position_revision(strength: str) -> bool:
    """normal/deep 은 '예외 정리' 다음에 별도의 '입장 수정' 발언을 낸다."""
    return (normalize_strength(strength) or NORMAL) in (NORMAL, DEEP)


def uses_convergence_step(strength: str) -> bool:
    """deep 은 최종 결론 전에 '공통 판단 기준 수렴' 단계를 한 번 더 거친다."""
    return (normalize_strength(strength) or NORMAL) == DEEP


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1) 데이터 구조
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class DebateAgentFailure(RuntimeError):
    """한 참여자가 실제로 발언을 만들어내지 못했다.

    남은 참여자로 일반 답변을 만들어 성공 처리하면 안 된다(토론이 아니라 설명문이 된다).
    호출부는 이 예외를 DEBATE_AGENT_FAILURE 로 사용자에게 전달한다.
    """

    def __init__(self, agent_name: str, agent_id, stage: str, issues: List[str]):
        self.agent_name = agent_name
        self.agent_id = agent_id
        self.stage = stage
        self.issues = list(issues or [])
        super().__init__(f"{agent_name} 의 {stage} 단계 생성 실패: {', '.join(self.issues)}")


@dataclass
class DebatePosition:
    """에이전트에게 배정된 관점(대립축의 한쪽)."""
    agent_id: Any
    agent_name: str
    slot: str            # "A" | "B"
    label: str           # 관점 이름 (예: 운영 단순성 우선 관점)
    stance: str          # 이 관점이 무엇을 우선하는지 1~2문장
    axis: str = ""       # 두 관점을 가르는 판단 기준


@dataclass
class InitialArgument:
    conclusion: str = ""
    reasons: List[str] = field(default_factory=list)
    explanation: str = ""


@dataclass
class Rebuttal:
    target_claim: str = ""
    acknowledged_point: str = ""
    counter_argument: str = ""
    evidence_or_reasoning: str = ""


@dataclass
class ExceptionNote:
    acknowledged_from_opponent: str = ""
    exceptions: List[str] = field(default_factory=list)
    flip_conditions: List[str] = field(default_factory=list)
    revised_conclusion: str = ""


@dataclass
class FinalConclusion:
    decision: str = ""
    conditions: List[str] = field(default_factory=list)
    reason: str = ""
    recommendation: str = ""


@dataclass
class Speech:
    """사용자에게 보이는 발언 1건 + 그 근거가 된 구조화 데이터."""
    slot: str
    agent_id: Any
    agent_name: str
    speech_type: str        # OPENING | REBUTTAL | EXCEPTION | REVISION | CONVERGENCE | FINAL_CONCLUSION
    stage_type: str         # SSE fingerprint 분리용 고유 stage 키
    stage_title: str
    round_no: int
    text: str
    target_agent_id: Any = None
    target_agent_name: Optional[str] = None
    structured: Dict[str, Any] = field(default_factory=dict)
    regenerated: int = 0


@dataclass
class DebateTranscript:
    topic: str = ""
    strength: str = NORMAL
    request_id: str = ""
    positions: List[DebatePosition] = field(default_factory=list)
    speeches: List[Speech] = field(default_factory=list)
    openings: Dict[str, InitialArgument] = field(default_factory=dict)
    rebuttals: Dict[str, List[Rebuttal]] = field(default_factory=dict)
    exceptions: Dict[str, ExceptionNote] = field(default_factory=dict)
    convergence: List[str] = field(default_factory=list)
    final: Optional[FinalConclusion] = None
    consensus: Optional["ConsensusOutcome"] = None

    def position(self, slot: str) -> Optional[DebatePosition]:
        for p in self.positions:
            if p.slot == slot:
                return p
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2) LLM 어댑터 (테스트에서 주입 가능)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LLMCall = Callable[..., str]


def _default_llm(system_prompt: str, user_prompt: str, *, max_tokens: int, temperature: float) -> str:
    from app.services.ollama_client import ask_ollama
    return ask_ollama(
        system_prompt=system_prompt, user_prompt=user_prompt,
        max_tokens=max_tokens, temperature=temperature, think=False,
    )


_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")


def _strip_fences(text: str) -> str:
    return _FENCE.sub("", (text or "").strip()).strip()


def parse_json_object(raw: str) -> Dict[str, Any]:
    """LLM 출력에서 첫 JSON object를 뽑는다. 실패하면 빈 dict."""
    s = _strip_fences(raw)
    if not s:
        return {}
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass
    start = s.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
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
                    try:
                        obj = json.loads(s[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except Exception:
                        break
        start = s.find("{", start + 1)
    return {}


# 성격/말투 계층이 붙이는 '내용 없는' 격려·칭찬 문장. 논거 본문에 남으면
# 반박의 '인정할 부분'이 격려 문구로 채워지는 등 토론 계약이 무너진다.
# 주제어가 아니라 대화 상투구 패턴만 본다(도메인 단어를 하드코딩하지 않는다).
_FILLER_SENTENCE = re.compile(
    r"[^.!?\n]*(좋은\s*질문|훌륭한\s*질문|멋진\s*질문|힘내|화이팅|파이팅|응원할게|"
    r"함께\s*알아봐요|같이\s*알아봐요|궁금한\s*점이?\s*있으면|언제든\s*물어봐)[^.!?\n]*[.!?]?",
)


def strip_filler(text: str) -> str:
    """격려/칭찬만 담긴 문장을 제거한다. 내용이 있는 문장은 건드리지 않는다."""
    if not text:
        return text
    cleaned = _FILLER_SENTENCE.sub(" ", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _s(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(_s(v) for v in value)
    return strip_filler(str(value).strip())


def _slist(value: Any, limit: int = 4) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [p.strip() for p in re.split(r"[\n·•]|(?<=[.。])\s", value) if p.strip()]
    elif isinstance(value, (list, tuple)):
        items = [_s(v) for v in value]
    else:
        items = [_s(value)]
    return [i for i in items if i][:limit]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3) 검증기 (LLM이 계약을 어기면 SSE로 내보내지 않는다)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_TOKEN = re.compile(r"[가-힣A-Za-z0-9]{2,}")
# 조사/접속어처럼 어느 문장에나 나오는 토큰은 '상대 발언 참조' 근거로 쓰지 않는다.
_STOP = {
    "그리고", "하지만", "그러나", "따라서", "때문", "때문에", "그것", "이것", "우리", "너는", "나는",
    "있다", "없다", "한다", "된다", "이다", "합니다", "입니다", "때문이다", "경우", "가능", "필요",
    "생각", "주장", "의견", "설명", "정리", "결론", "이유", "반박", "인정", "그러므로", "또한",
}


def content_tokens(text: str) -> set:
    return {t for t in _TOKEN.findall(_s(text)) if t not in _STOP}


def references_opponent(rebuttal_text: str, opponent_text: str, *, min_overlap: int = 2) -> bool:
    """반박이 '상대가 실제로 한 말'을 대상으로 하는지 확인한다(strawman 최소화).

    상대 발언의 내용어와 반박의 지목 문장 사이 겹치는 토큰이 min_overlap개 이상이어야 한다.
    """
    r, o = content_tokens(rebuttal_text), content_tokens(opponent_text)
    if not r or not o:
        return False
    return len(r & o) >= min_overlap


def is_repeat(text: str, previous: List[str], threshold: float = 0.82) -> bool:
    """직전 라운드와 같은 말을 반복하는지(토큰만 늘리는지) 확인한다."""
    a = re.sub(r"\s+", " ", _s(text))
    if not a:
        return True
    for prev in previous:
        b = re.sub(r"\s+", " ", _s(prev))
        if not b:
            continue
        if difflib.SequenceMatcher(None, a, b).ratio() >= threshold:
            return True
    return False


def validate_initial_argument(arg: InitialArgument) -> List[str]:
    issues = []
    if len(_s(arg.conclusion)) < 8:
        issues.append("conclusion_missing")
    if len([r for r in arg.reasons if len(_s(r)) >= 5]) < 2:
        issues.append("reasons_missing")
    if len(_s(arg.explanation)) < 30:
        issues.append("explanation_missing")
    return issues


def validate_rebuttal(reb: Rebuttal, opponent_text: str) -> List[str]:
    issues = []
    if len(_s(reb.target_claim)) < 5:
        issues.append("target_claim_missing")
    if len(_s(reb.counter_argument)) < 20:
        issues.append("counter_argument_missing")
    if len(_s(reb.evidence_or_reasoning)) < 15:
        issues.append("evidence_missing")
    if not references_opponent(reb.target_claim + " " + reb.counter_argument, opponent_text):
        issues.append("not_targeting_opponent")
    return issues


def validate_exception(note: ExceptionNote) -> List[str]:
    issues = []
    if not [e for e in note.exceptions if len(_s(e)) >= 5]:
        issues.append("exceptions_missing")
    if len(_s(note.revised_conclusion)) < 8:
        issues.append("revised_conclusion_missing")
    return issues


_WINNER_PAT = re.compile(r"(승리|승자|이겼|패배|패자|우승|판정승|A\s*승|B\s*승)")


def validate_final(final: FinalConclusion) -> List[str]:
    issues = []
    if len(_s(final.decision)) < 10:
        issues.append("decision_missing")
    if not [c for c in final.conditions if len(_s(c)) >= 5]:
        issues.append("conditions_missing")
    if len(_s(final.reason)) < 15:
        issues.append("reason_missing")
    if len(_s(final.recommendation)) < 10:
        issues.append("recommendation_missing")
    if _WINNER_PAT.search(_s(final.decision) + _s(final.reason)):
        issues.append("winner_declaration")
    return issues


def validate_transcript(t: DebateTranscript) -> Tuple[bool, List[str]]:
    """토론 전체 구조 검증. 사용자에게 나가기 전 마지막 게이트."""
    issues: List[str] = []
    if not _s(t.topic):
        issues.append("topic_missing")
    if len(t.positions) < 2:
        issues.append("positions_missing")
    elif _s(t.positions[0].label).lower() == _s(t.positions[1].label).lower():
        issues.append("positions_not_opposed")

    # 참여자 전원이 실제로 입론/반박/예외 정리를 했는가(2명이든 3명이든 동일하게 본다).
    slots = [p.slot for p in t.positions] or ["A", "B"]
    for slot in slots:
        opening = t.openings.get(slot)
        if opening is None:
            issues.append(f"{slot}_opening_missing")
            continue
        issues.extend(f"{slot}_{i}" for i in validate_initial_argument(opening))

        rebs = t.rebuttals.get(slot) or []
        if not rebs:
            issues.append(f"{slot}_rebuttal_missing")
        note = t.exceptions.get(slot)
        if note is None or validate_exception(note):
            issues.append(f"{slot}_exception_missing")

    # 반박이 실제 상대 발언을 겨냥했는지(교차 검증)
    opponent_of = {slots[i]: slots[(i + 1) % len(slots)] for i in range(len(slots))}
    for slot in slots:
        other = opponent_of[slot]
        other_text = _opponent_corpus(t, other)
        for idx, reb in enumerate(t.rebuttals.get(slot) or [], start=1):
            if not references_opponent(reb.target_claim + " " + reb.counter_argument, other_text):
                issues.append(f"{slot}_rebuttal{idx}_not_targeting_{other}")

    # 최종 결론이 한 참여자의 단독 저작이면 실패다(합의 절차를 거쳐야 한다).
    finals = [s for s in t.speeches if s.speech_type == "FINAL_CONCLUSION"]
    if finals and any(s.slot != CONSENSUS_SLOT for s in finals):
        issues.append("final_owned_by_single_agent")
    if len(slots) >= 2 and not [s for s in t.speeches if s.speech_type == "CONSENSUS_REVIEW"]:
        issues.append("consensus_review_missing")

    if t.final is None:
        issues.append("final_conclusion_missing")
    else:
        issues.extend(f"final_{i}" for i in validate_final(t.final))
    return (not issues), issues


def _opponent_corpus(t: DebateTranscript, slot: str) -> str:
    parts: List[str] = []
    opening = t.openings.get(slot)
    if opening:
        parts.append(opening.conclusion)
        parts.extend(opening.reasons)
        parts.append(opening.explanation)
    for reb in t.rebuttals.get(slot) or []:
        parts.extend([reb.counter_argument, reb.evidence_or_reasoning])
    return "\n".join(p for p in parts if p)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4) Style layer — 논리는 건드리지 않고 '표현'만 담당
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_CONTRACT_PRIORITY = (
    "[우선순위] ① 토론 계약(형식/JSON/역할) ② 배정된 입장 ③ 지식수준 ④ 성격·말투.\n"
    "성격이나 말투 때문에 배정된 입장이 바뀌면 실패다. 성격은 '표현'에만 적용하라."
)


def _agent_level(agent: AgentProfile) -> str:
    from app.services import level_policy
    return level_policy.normalize(
        getattr(agent, "knowledgeLevel", None) or getattr(agent, "knowledgeLevelLabel", None)
    )


def build_style_directive(agent: AgentProfile) -> str:
    """성격/지식수준/customInstruction → 표현 지시. 입장·논리에는 개입하지 않는다."""
    from app.services import level_policy
    from app.services.personality_prompt_builder import build_persona_directive

    lvl = _agent_level(agent)
    persona = build_persona_directive(
        getattr(agent, "personalityLabel", None) or getattr(agent, "personality", None),
        getattr(agent, "customInstruction", None),
    )
    return (
        f"[표현 계층 — 논리가 아니라 '말투'에만 적용]\n"
        f"- 학습자 수준: {level_policy.korean_label(lvl)} 눈높이의 어휘와 설명 밀도를 쓴다.\n"
        f"{persona}\n{_CONTRACT_PRIORITY}"
    )


def _bullet(items: List[str], marker: str = "-") -> str:
    return "\n".join(f"{marker} {i}" for i in items if _s(i))


def render_opening(arg: InitialArgument, pos: DebatePosition) -> str:
    """Style Renderer: 구조화된 논리 → 사용자에게 보이는 입론 텍스트."""
    lines = [f"[{pos.label}] 결론: {arg.conclusion}", "", "이유"]
    lines.append(_bullet(arg.reasons))
    lines.extend(["", "설명", arg.explanation])
    return "\n".join(l for l in lines if l is not None).strip()


def render_rebuttal(reb: Rebuttal, pos: DebatePosition, target_name: str) -> str:
    lines = [
        f"[{pos.label} → {target_name} 반박]",
        f"지목한 주장: {reb.target_claim}",
    ]
    if _s(reb.acknowledged_point):
        lines.append(f"인정할 부분: {reb.acknowledged_point}")
    lines.extend(["", f"반박: {reb.counter_argument}", "", f"근거: {reb.evidence_or_reasoning}"])
    return "\n".join(lines).strip()


def render_exception(note: ExceptionNote, pos: DebatePosition) -> str:
    lines = [f"[{pos.label} 예외 정리]"]
    if _s(note.acknowledged_from_opponent):
        lines.append(f"상대 주장 중 인정할 부분: {note.acknowledged_from_opponent}")
    lines.extend(["", "내 주장에 적용되는 예외", _bullet(note.exceptions)])
    if note.flip_conditions:
        lines.extend(["", "결론이 뒤집히는 조건", _bullet(note.flip_conditions)])
    return "\n".join(lines).strip()


def render_revision(note: ExceptionNote, pos: DebatePosition) -> str:
    return f"[{pos.label} 입장 수정]\n수정된 결론: {note.revised_conclusion}".strip()


def render_final(final: FinalConclusion, pos: DebatePosition) -> str:
    lines = [
        "[최종 결론]",
        final.decision,
        "",
        "적용 조건",
        _bullet(final.conditions),
        "",
        f"이유: {final.reason}",
        "",
        f"권고: {final.recommendation}",
    ]
    return "\n".join(lines).strip()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5) Content layer — 단계별 생성 + 단계별 재생성(전체 재생성 금지)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_DEBATE_SYSTEM = (
    "너는 StudyBridge 토론 참여자다. 사회자도 심판도 아니다.\n"
    "- 안건은 사용자의 질문 그 자체다. 새 논제를 만들지 마라.\n"
    "- 너는 배정된 관점을 유지한 채 근거로 주장하고, 상대의 '실제 발언'만 반박한다.\n"
    "- 상대가 하지 않은 말을 지어내서 공격하지 마라(허수아비 논증 금지).\n"
    "- 승패·판정·총평을 말하지 마라.\n"
    "- 상대나 사용자 발언의 문장을 그대로 복사하지 마라(지목할 때만 짧게 인용).\n"
    "- 칭찬·격려 인사말로 발언을 끝내지 마라.\n"
    "- 출력은 지시된 JSON 하나만. 설명·머리말·코드펜스 금지. 값은 한국어로 쓴다."
)


def _generate_structured(
    llm: LLMCall,
    *,
    system: str,
    user: str,
    build: Callable[[Dict[str, Any]], Any],
    validate: Callable[[Any], List[str]],
    repair_hint: str,
    max_retries: int = MAX_STEP_RETRIES,
    temperature: float = CONTENT_TEMPERATURE,
) -> Tuple[Any, List[str], int]:
    """한 단계만 생성/검증/재생성한다. 실패해도 다른 단계는 다시 만들지 않는다."""
    last_obj, last_issues = None, ["empty_response"]
    for attempt in range(max_retries + 1):
        prompt = user if attempt == 0 else (
            f"{user}\n\n[재작성 지시 — 직전 출력이 계약을 어겼다: {', '.join(last_issues)}]\n{repair_hint}"
        )
        raw = llm(system, prompt, max_tokens=CONTENT_MAX_TOKENS,
                  temperature=temperature + (0.05 * attempt))
        obj = build(parse_json_object(raw))
        issues = validate(obj)
        if not issues:
            return obj, [], attempt
        last_obj, last_issues = obj, issues
        logger.warning("[DEBATE] 단계 검증 실패(attempt=%d) issues=%s", attempt + 1, issues)
    return last_obj, last_issues, max_retries


def _build_positions(obj: Dict[str, Any]) -> Dict[str, Any]:
    a, b = obj.get("a") or {}, obj.get("b") or {}
    return {
        "axis": _s(obj.get("axis")),
        "a": {"label": _s(a.get("label")), "stance": _s(a.get("stance"))},
        "b": {"label": _s(b.get("label")), "stance": _s(b.get("stance"))},
    }


def _validate_positions(obj: Dict[str, Any]) -> List[str]:
    issues = []
    a, b = obj.get("a") or {}, obj.get("b") or {}
    for slot, side in (("a", a), ("b", b)):
        if len(_s(side.get("label"))) < 2:
            issues.append(f"{slot}_label_missing")
        if len(_s(side.get("stance"))) < 10:
            issues.append(f"{slot}_stance_missing")
    if not issues and _s(a.get("label")).lower() == _s(b.get("label")).lower():
        issues.append("labels_identical")
    if not issues and difflib.SequenceMatcher(None, _s(a.get("stance")), _s(b.get("stance"))).ratio() > 0.85:
        issues.append("stances_identical")
    if len(_s(obj.get("axis"))) < 4:
        issues.append("axis_missing")
    return issues


def assign_positions(topic: str, agent_a: AgentProfile, agent_b: AgentProfile,
                     llm: Optional[LLMCall] = None) -> Tuple[DebatePosition, DebatePosition]:
    """안건에서 '실제로 대립 가능한 두 판단 기준'을 만들어 두 에이전트에게 배정한다.

    억지 찬반이 아니라, 질문이 두 선택지 비교가 아니면 서로 다른 우선순위(판단 기준)를 축으로 잡는다.
    """
    call = llm or _default_llm
    user = (
        f"[안건(사용자 질문 원문)]\n{topic}\n\n"
        "이 안건에서 실제로 논리적으로 대립 가능한 관점 2개를 잡아라.\n"
        "- 안건이 두 선택지 비교면 각 선택지를 지지하는 관점으로 나눈다.\n"
        "- 두 선택지 비교가 아니면 서로 다른 '판단 기준'(무엇을 우선하는가)으로 나눈다.\n"
        "- 억지로 찬성/반대를 만들지 말고, 실제 실무에서 갈리는 지점을 축으로 삼아라.\n"
        "- 두 관점은 같은 말을 다르게 쓴 것이면 안 된다.\n\n"
        '{"axis":"두 관점을 가르는 판단 기준 한 줄",'
        '"a":{"label":"관점 이름(10자 내외)","stance":"이 관점이 무엇을 우선하는지 1~2문장"},'
        '"b":{"label":"...","stance":"..."}}'
    )
    obj, issues, _ = _generate_structured(
        call, system=_DEBATE_SYSTEM, user=user, build=_build_positions,
        validate=_validate_positions,
        repair_hint="두 관점의 label과 stance를 확실히 다르게, 안건에 실제로 존재하는 대립축으로 다시 써라.",
        temperature=0.5,
    )
    if issues or not obj:
        # content-free 폴백: 도메인 용어를 코드에 박지 않는다(안건 문구만 사용).
        obj = {
            "axis": "이 안건에서 무엇을 먼저 지킬 것인가",
            "a": {"label": "관점 A", "stance": "안건에서 제시된 조건을 유지했을 때의 이점을 우선한다."},
            "b": {"label": "관점 B", "stance": "안건에서 제시된 조건을 바꿨을 때의 이점을 우선한다."},
        }
        logger.warning("[DEBATE] 관점 배정 폴백 사용 issues=%s", issues)

    pos_a = DebatePosition(
        agent_id=_agent_id(agent_a), agent_name=_agent_name(agent_a, 1), slot="A",
        label=obj["a"]["label"], stance=obj["a"]["stance"], axis=obj["axis"],
    )
    pos_b = DebatePosition(
        agent_id=_agent_id(agent_b), agent_name=_agent_name(agent_b, 2), slot="B",
        label=obj["b"]["label"], stance=obj["b"]["stance"], axis=obj["axis"],
    )
    return pos_a, pos_b


def _position_block(pos: DebatePosition, opponent: DebatePosition) -> str:
    return (
        f"[너의 관점 — 반드시 유지] {pos.label}\n{pos.stance}\n"
        f"[상대 관점] {opponent.label} — {opponent.stance}\n"
        f"[대립축] {pos.axis}"
    )


def generate_opening(topic: str, pos: DebatePosition, opponent: DebatePosition,
                     agent: AgentProfile, llm: Optional[LLMCall] = None) -> Tuple[InitialArgument, List[str], int]:
    """2단계 결론 + 3단계 이유 + 4단계 설명을 하나의 입론으로 만든다."""
    call = llm or _default_llm
    user = (
        f"[안건(사용자 질문 원문)]\n{topic}\n\n{_position_block(pos, opponent)}\n\n"
        "너의 입론을 만들어라. 6단 논법의 2~4단계다.\n"
        "- conclusion: 안건에 대한 네 결론 한 문장(모호한 양비론 금지).\n"
        "- reasons: 서로 다른 근거 2~3개(같은 말 반복 금지).\n"
        "- explanation: 그 근거가 왜 성립하는지 3~5문장.\n\n"
        f"{build_style_directive(agent)}\n\n"
        '{"conclusion":"...","reasons":["...","..."],"explanation":"..."}'
    )
    def build(o: Dict[str, Any]) -> InitialArgument:
        return InitialArgument(
            conclusion=_s(o.get("conclusion")),
            reasons=_slist(o.get("reasons"), 3),
            explanation=_s(o.get("explanation")),
        )
    return _generate_structured(
        call, system=_DEBATE_SYSTEM, user=user, build=build, validate=validate_initial_argument,
        repair_hint="conclusion 한 문장, reasons 2개 이상, explanation 3문장 이상을 반드시 채워라.",
    )


def generate_rebuttal(topic: str, pos: DebatePosition, opponent: DebatePosition, agent: AgentProfile,
                      opponent_transcript: str, own_previous: List[str], round_no: int,
                      llm: Optional[LLMCall] = None,
                      opponent_latest: str = "",
                      target_candidates: Optional[List[str]] = None,
                      own_previous_counters: Optional[List[str]] = None) -> Tuple[Rebuttal, List[str], int]:
    """5단계 반론 꺾기. 상대의 '실제 발언 원문'만 입력으로 준다.

    2차 이후 라운드는 '상대의 직전 발언에서 새로 나온 주장'을 주 대상으로 삼는다
    (같은 논점을 다시 때리며 토큰만 늘리는 것을 막는다).
    """
    call = llm or _default_llm
    prev_block = ""
    if own_previous:
        prev_block = (
            "\n[네가 이미 반박한 지점 — 다시 고르면 실패다]\n"
            + "\n---\n".join(p[:600] for p in own_previous[-3:]) + "\n"
        )
    latest_block = ""
    if opponent_latest and opponent_latest.strip():
        latest_block = (
            f"\n[★ 상대의 직전 발언 — 이번 라운드의 주 반박 대상]\n{opponent_latest}\n"
        )
    candidate_block = ""
    if target_candidates:
        listed = "\n".join(f"{i}) {c}" for i, c in enumerate(target_candidates[:5], start=1))
        candidate_block = (
            "\n[아직 네가 반박하지 않은 상대 주장 — 반드시 이 중 하나를 targetClaim 으로 골라라(원문 그대로)]\n"
            f"{listed}\n"
        )
    user = (
        f"[안건(사용자 질문 원문)]\n{topic}\n\n{_position_block(pos, opponent)}\n\n"
        f"[상대({opponent.agent_name})가 실제로 한 발언 원문 — 이 안에 있는 문장만 반박 대상이다]\n"
        f"{opponent_transcript}\n{latest_block}{candidate_block}{prev_block}\n"
        f"이번은 {round_no}차 반박이다. 상대의 직전 발언에서 '새로 나온' 주장 하나를 골라 반박하라.\n"
        "- targetClaim: 상대 발언에서 그대로 가져온 주장(원문 표현을 유지해서 지목).\n"
        "- acknowledgedPoint: 그 주장에서 인정할 부분(없으면 어디까지는 맞는지).\n"
        "- counterArgument: 핵심 반박(상대가 말하지 않은 주장을 지어내지 마라).\n"
        "- evidenceOrReasoning: 왜 그런지(메커니즘/조건/반례).\n\n"
        f"{build_style_directive(agent)}\n\n"
        '{"targetClaim":"...","acknowledgedPoint":"...","counterArgument":"...","evidenceOrReasoning":"..."}'
    )
    def build(o: Dict[str, Any]) -> Rebuttal:
        return Rebuttal(
            target_claim=_s(o.get("targetClaim") or o.get("target_claim")),
            acknowledged_point=_s(o.get("acknowledgedPoint") or o.get("acknowledged_point")),
            counter_argument=_s(o.get("counterArgument") or o.get("counter_argument")),
            evidence_or_reasoning=_s(o.get("evidenceOrReasoning") or o.get("evidence_or_reasoning")),
        )

    def validate(reb: Rebuttal) -> List[str]:
        issues = validate_rebuttal(reb, opponent_transcript)
        body = reb.target_claim + " " + reb.counter_argument
        if own_previous and is_repeat(body, own_previous):
            issues.append("repeats_previous_round")
        # 지목 대상만 바꾸고 반박 본문을 그대로 재사용하는 경우도 반복이다.
        elif own_previous_counters and is_repeat(reb.counter_argument, own_previous_counters, threshold=0.85):
            issues.append("reuses_previous_counter_argument")
        return issues

    return _generate_structured(
        call, system=_DEBATE_SYSTEM, user=user, build=build, validate=validate,
        repair_hint=("targetClaim은 상대 발언 원문에서 그대로 인용하고, 이전 라운드와 다른 지점을 골라라. "
                     "상대가 하지 않은 말을 만들어내면 실패다."),
    )


def claim_candidates(t: "DebateTranscript", slot: str) -> List[str]:
    """상대가 실제로 내놓은 '주장 문장' 목록(입론 결론/이유 + 각 라운드 반박)."""
    out: List[str] = []
    opening = t.openings.get(slot)
    if opening:
        if _s(opening.conclusion):
            out.append(_s(opening.conclusion))
        out.extend(_s(r) for r in opening.reasons if _s(r))
    for reb in t.rebuttals.get(slot) or []:
        if _s(reb.counter_argument):
            out.append(_s(reb.counter_argument))
    return out


def untargeted_claims(candidates: List[str], already_targeted: List[str], threshold: float = 0.7) -> List[str]:
    """아직 반박하지 않은 주장만 남긴다(같은 논점 재탕 방지)."""
    remaining = []
    for c in candidates:
        if any(difflib.SequenceMatcher(None, c, prev).ratio() >= threshold for prev in already_targeted if prev):
            continue
        remaining.append(c)
    return remaining

def generate_exception(topic: str, pos: DebatePosition, opponent: DebatePosition, agent: AgentProfile,
                       own_transcript: str, opponent_transcript: str,
                       llm: Optional[LLMCall] = None,
                       opponent_note: Optional[ExceptionNote] = None) -> Tuple[ExceptionNote, List[str], int]:
    """6단계 예외 정리 + 수정된 결론."""
    call = llm or _default_llm
    user = (
        f"[안건(사용자 질문 원문)]\n{topic}\n\n{_position_block(pos, opponent)}\n\n"
        f"[너의 발언 기록]\n{own_transcript}\n\n"
        f"[상대의 발언 기록]\n{opponent_transcript}\n\n"
        "이제 토론을 마무리하기 위해 네 주장을 스스로 재검토하라.\n"
        "- acknowledgedFromOpponent: 상대 주장 중 실제로 인정할 부분.\n"
        "- exceptions: 네 결론이 그대로 적용되지 않는 예외 상황 2개 이상.\n"
        "- flipConditions: 어떤 조건이 충족되면 네 결론이 뒤집히는지 1개 이상.\n"
        "- revisedConclusion: 예외를 반영해 다듬은 결론 한 문장(입장을 버리지는 말고 조건을 붙여라).\n\n"
        f"{build_style_directive(agent)}\n\n"
        '{"acknowledgedFromOpponent":"...","exceptions":["...","..."],'
        '"flipConditions":["..."],"revisedConclusion":"..."}'
    )
    def build(o: Dict[str, Any]) -> ExceptionNote:
        return ExceptionNote(
            acknowledged_from_opponent=_s(o.get("acknowledgedFromOpponent") or o.get("acknowledged_from_opponent")),
            exceptions=_slist(o.get("exceptions"), 4),
            flip_conditions=_slist(o.get("flipConditions") or o.get("flip_conditions"), 3),
            revised_conclusion=_s(o.get("revisedConclusion") or o.get("revised_conclusion")),
        )
    def validate(note: ExceptionNote) -> List[str]:
        issues = validate_exception(note)
        # 상대가 먼저 낸 예외 정리를 그대로 베끼면(같은 문장 복사) 실패다.
        if opponent_note is not None and _is_copy_of(note, opponent_note):
            issues.append("copies_opponent_exception")
        return issues

    return _generate_structured(
        call, system=_DEBATE_SYSTEM, user=user, build=build, validate=validate,
        repair_hint=("exceptions를 2개 이상, revisedConclusion을 한 문장으로 채워라. "
                     "상대가 쓴 문장을 복사하지 말고 '네 관점'에서 다시 써라."),
    )


def _is_copy_of(note: ExceptionNote, other: ExceptionNote, threshold: float = 0.8) -> bool:
    """상대의 예외 정리를 사실상 그대로 옮겨 적었는지."""
    mine = " ".join(note.exceptions + [note.revised_conclusion])
    theirs = " ".join(other.exceptions + [other.revised_conclusion])
    if not mine or not theirs:
        return False
    return difflib.SequenceMatcher(None, re.sub(r"\s+", " ", mine), re.sub(r"\s+", " ", theirs)).ratio() >= threshold

def generate_convergence(topic: str, pos_a: DebatePosition, pos_b: DebatePosition,
                         note_a: ExceptionNote, note_b: ExceptionNote, agent: AgentProfile,
                         llm: Optional[LLMCall] = None) -> Tuple[List[str], List[str], int]:
    """deep 전용: 두 수정 결론에서 '공통 판단 기준'을 뽑는다(사회자 아님, 마지막 발언자가 수행)."""
    call = llm or _default_llm
    user = (
        f"[안건]\n{topic}\n\n"
        f"[{pos_a.label} 수정 결론] {note_a.revised_conclusion}\n"
        f"[{pos_a.label} 예외] {'; '.join(note_a.exceptions)}\n"
        f"[{pos_b.label} 수정 결론] {note_b.revised_conclusion}\n"
        f"[{pos_b.label} 예외] {'; '.join(note_b.exceptions)}\n\n"
        "두 수정 결론이 실제로 합의하는 '판단 기준'을 2~3개 뽑아라. 승패를 말하지 마라.\n"
        '{"criteria":["...","..."]}'
    )
    def build(o: Dict[str, Any]) -> List[str]:
        return _slist(o.get("criteria"), 3)

    def validate(items: List[str]) -> List[str]:
        return [] if len([i for i in items if len(_s(i)) >= 5]) >= 2 else ["criteria_missing"]

    return _generate_structured(
        call, system=_DEBATE_SYSTEM, user=user, build=build, validate=validate,
        repair_hint="두 입장이 모두 받아들일 수 있는 판단 기준 문장을 2개 이상 써라.",
    )


def generate_final(topic: str, pos_a: DebatePosition, pos_b: DebatePosition,
                   note_a: ExceptionNote, note_b: ExceptionNote, agent: AgentProfile,
                   criteria: List[str], llm: Optional[LLMCall] = None) -> Tuple[FinalConclusion, List[str], int]:
    """최종 결론 — 승패가 아니라 조건이 붙은 하나의 답."""
    call = llm or _default_llm
    criteria_block = ("\n[양측이 합의한 판단 기준]\n" + _bullet(criteria)) if criteria else ""
    user = (
        f"[안건(사용자 질문 원문)]\n{topic}\n\n"
        f"[{pos_a.label} 수정 결론] {note_a.revised_conclusion}\n"
        f"[{pos_a.label}이 인정한 부분] {note_a.acknowledged_from_opponent}\n"
        f"[{pos_a.label} 예외] {'; '.join(note_a.exceptions)}\n\n"
        f"[{pos_b.label} 수정 결론] {note_b.revised_conclusion}\n"
        f"[{pos_b.label}이 인정한 부분] {note_b.acknowledged_from_opponent}\n"
        f"[{pos_b.label} 예외] {'; '.join(note_b.exceptions)}\n"
        f"{criteria_block}\n\n"
        "이제 사용자의 질문에 대한 '하나의 최종 답'을 써라.\n"
        "- 어느 쪽이 이겼는지 말하지 마라. 승자/패자/판정은 금지다.\n"
        "- '양쪽 다 장단점이 있다'로 끝내지 마라. 조건을 명시한 하나의 판단을 내려야 한다.\n"
        "- decision: 사용자가 실제로 무엇을 택해야 하는지 한두 문장.\n"
        "- conditions: 그 판단이 성립하는 조건 2개 이상.\n"
        "- reason: 왜 그 판단이 가장 타당한지(양측 반박을 통과한 근거).\n"
        "- recommendation: 지금 당장 취할 수 있는 실행 권고.\n\n"
        '{"decision":"...","conditions":["...","..."],"reason":"...","recommendation":"..."}'
    )
    def build(o: Dict[str, Any]) -> FinalConclusion:
        return FinalConclusion(
            decision=_s(o.get("decision")),
            conditions=_slist(o.get("conditions"), 4),
            reason=_s(o.get("reason")),
            recommendation=_s(o.get("recommendation")),
        )
    return _generate_structured(
        call, system=_DEBATE_SYSTEM, user=user, build=build, validate=validate_final,
        repair_hint="승패 표현을 빼고, decision/conditions/reason/recommendation을 모두 채워라.",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5-b) 다중 참여자 관점 배정 + 합의(consensus) 프로토콜
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MAX_CONSENSUS_ROUNDS = int(os.getenv("DEBATE_MAX_CONSENSUS_ROUNDS", "2"))


@dataclass
class ConsensusReview:
    """다른 참여자가 초안 결론을 읽고 낸 동의 여부와 수정 요구."""
    slot: str
    agent_id: Any
    agent_name: str
    agree: bool = False
    corrections: List[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class ConsensusOutcome:
    final: FinalConclusion
    agreed: bool = False
    rounds: int = 0
    reviews: List[ConsensusReview] = field(default_factory=list)
    open_points: List[str] = field(default_factory=list)


def _perspectives_fallback(n: int) -> Dict[str, Any]:
    # content-free 폴백: 도메인 용어를 코드에 박지 않는다(안건 문구만 사용).
    base = [
        "안건에서 제시된 조건을 유지했을 때의 이점을 우선한다.",
        "안건에서 제시된 조건을 바꿨을 때의 이점을 우선한다.",
        "안건이 성립하는 범위 자체를 먼저 따져야 한다고 본다.",
        "안건의 비용을 누가 부담하는지를 먼저 본다.",
    ]
    return {"axis": "이 안건에서 무엇을 먼저 지킬 것인가",
            "perspectives": [{"label": f"관점 {SLOT_LETTERS[i]}", "stance": base[i % len(base)]}
                             for i in range(n)]}


def assign_positions_multi(topic: str, agents: List[AgentProfile],
                           llm: Optional[LLMCall] = None) -> List[DebatePosition]:
    """참여자 수만큼 서로 다른 관점을 만들어 '전원'에게 배정한다.

    2명이면 대립하는 두 관점, 3명 이상이면 서로 겹치지 않는 판단 기준 N개를 만든다.
    억지 찬반이 아니라 실제로 갈리는 지점을 축으로 삼는다.
    """
    n = len(agents)
    call = llm or _default_llm
    user = (
        f"[안건(사용자 질문 원문)]\n{topic}\n\n"
        f"이 안건에서 실제로 논리적으로 갈리는 관점 {n}개를 잡아라.\n"
        "- 안건이 선택지 비교면 각 선택지를 지지하는 관점으로 나눈다.\n"
        "- 아니면 서로 다른 '판단 기준'(무엇을 우선하는가)으로 나눈다.\n"
        "- 관점끼리 같은 말을 다르게 쓴 것이면 실패다.\n\n"
        '{"axis":"관점들을 가르는 판단 기준 한 줄","perspectives":['
        '{"label":"관점 이름(10자 내외)","stance":"이 관점이 무엇을 우선하는지 1~2문장"}]}'
    )

    def build(o: Dict[str, Any]) -> Dict[str, Any]:
        items = []
        for p in (o.get("perspectives") or [])[:n]:
            if isinstance(p, dict):
                items.append({"label": _s(p.get("label")), "stance": _s(p.get("stance"))})
        return {"axis": _s(o.get("axis")), "perspectives": items}

    def validate(o: Dict[str, Any]) -> List[str]:
        items = o.get("perspectives") or []
        issues: List[str] = []
        if len(items) != n:
            issues.append(f"perspective_count_{len(items)}_expected_{n}")
            return issues
        for i, p in enumerate(items):
            if len(_s(p.get("label"))) < 2:
                issues.append(f"{i}_label_missing")
            if len(_s(p.get("stance"))) < 10:
                issues.append(f"{i}_stance_missing")
        labels = [_s(p.get("label")).lower() for p in items]
        if len(set(labels)) != len(labels):
            issues.append("labels_identical")
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if difflib.SequenceMatcher(None, _s(items[i].get("stance")),
                                           _s(items[j].get("stance"))).ratio() > 0.85:
                    issues.append("stances_identical")
                    break
        if len(_s(o.get("axis"))) < 4:
            issues.append("axis_missing")
        return issues

    obj, issues, _ = _generate_structured(
        call, system=_DEBATE_SYSTEM, user=user, build=build, validate=validate,
        repair_hint=f"관점을 정확히 {n}개, 서로 확실히 다른 label/stance 로 다시 써라.",
        temperature=0.5,
    )
    if issues or not obj or not obj.get("perspectives"):
        obj = _perspectives_fallback(n)
        logger.warning("[DEBATE] 관점 배정 폴백 사용 n=%d issues=%s", n, issues)

    axis = obj["axis"]
    return [
        DebatePosition(agent_id=_agent_id(agent), agent_name=_agent_name(agent, i + 1),
                       slot=SLOT_LETTERS[i], label=obj["perspectives"][i]["label"],
                       stance=obj["perspectives"][i]["stance"], axis=axis)
        for i, agent in enumerate(agents)
    ]


def _notes_block(positions: List[DebatePosition], notes: Dict[str, ExceptionNote]) -> str:
    lines = []
    for pos in positions:
        note = notes.get(pos.slot)
        if note is None:
            continue
        lines.append(
            f"[{pos.label}({pos.agent_name}) 수정 결론] {note.revised_conclusion}\n"
            f"[{pos.label}이 인정한 부분] {note.acknowledged_from_opponent}\n"
            f"[{pos.label} 예외] {'; '.join(note.exceptions)}"
        )
    return "\n\n".join(lines)


def generate_conclusion_draft(topic: str, drafter: DebatePosition, positions: List[DebatePosition],
                              notes: Dict[str, ExceptionNote], agent: AgentProfile,
                              criteria: List[str], corrections: Optional[List[str]] = None,
                              llm: Optional[LLMCall] = None) -> Tuple[FinalConclusion, List[str], int]:
    """합의 초안. 자기 승리 선언이 아니라 '토론 전체를 통과한 하나의 답' 초안이다."""
    call = llm or _default_llm
    criteria_block = ("\n[참여자들이 합의한 판단 기준]\n" + _bullet(criteria)) if criteria else ""
    fix_block = ("\n[다른 참여자가 요구한 수정 사항 — 반드시 반영하라]\n" + _bullet(corrections)
                 if corrections else "")
    user = (
        f"[안건(사용자 질문 원문)]\n{topic}\n\n{_notes_block(positions, notes)}\n{criteria_block}{fix_block}\n\n"
        "너는 토론 참여자로서 '합의 초안'을 쓴다. 사회자도 심판도 아니다.\n"
        "- 어느 쪽이 이겼는지 말하지 마라. 승자/패자/판정은 금지다.\n"
        "- '양쪽 다 장단점이 있다'로 끝내지 마라. 조건을 명시한 하나의 판단을 내려야 한다.\n"
        "- 네 관점만 담지 마라. 다른 참여자의 예외와 수정 결론이 조건 안에 실제로 반영돼야 한다.\n"
        "- decision: 사용자가 실제로 무엇을 택해야 하는지 한두 문장.\n"
        "- conditions: 그 판단이 성립하는 조건 2개 이상.\n"
        "- reason: 왜 그 판단이 타당한지(반박을 통과한 근거).\n"
        "- recommendation: 지금 당장 취할 수 있는 실행 권고.\n\n"
        '{"decision":"...","conditions":["...","..."],"reason":"...","recommendation":"..."}'
    )

    def build(o: Dict[str, Any]) -> FinalConclusion:
        return FinalConclusion(
            decision=_s(o.get("decision")), conditions=_slist(o.get("conditions"), 4),
            reason=_s(o.get("reason")), recommendation=_s(o.get("recommendation")),
        )

    return _generate_structured(
        call, system=_DEBATE_SYSTEM, user=user, build=build, validate=validate_final,
        repair_hint="승패 표현을 빼고 decision/conditions/reason/recommendation 을 모두 채워라.",
    )


def generate_conclusion_review(topic: str, reviewer: DebatePosition, draft: FinalConclusion,
                               agent: AgentProfile, note: Optional[ExceptionNote] = None,
                               llm: Optional[LLMCall] = None) -> Tuple[ConsensusReview, List[str], int]:
    """다른 참여자가 초안을 읽고 동의/수정 요구를 낸다(최종 결론의 단독 소유를 막는다)."""
    call = llm or _default_llm
    own = f"\n[네 수정 결론] {note.revised_conclusion}\n[네가 든 예외] {'; '.join(note.exceptions)}\n" if note else ""
    user = (
        f"[안건]\n{topic}\n\n"
        f"[다른 참여자가 낸 합의 초안]\n결론: {draft.decision}\n"
        f"조건:\n{_bullet(draft.conditions)}\n이유: {draft.reason}\n권고: {draft.recommendation}\n"
        f"{own}\n"
        f"{_position_block_solo(reviewer)}\n\n"
        "지금은 토론이 끝나고 '합의' 단계다. 초안을 다시 쓰지 말고 판정만 하라.\n"
        "★ 합의 판정 기준은 '내 입장이 이겼는가'가 아니다. 초안이 조건을 명확히 달고 있고,\n"
        "  네가 든 예외가 그 조건 안에 반영돼 있으면 네 관점과 결론이 달라도 동의해야 한다.\n"
        "  네 주장이 그대로 채택되지 않았다는 이유로 false 를 내면 실패다.\n"
        "- agree: 이 초안을 최종 결론으로 받아들일 수 있으면 true, 아니면 false.\n"
        "- corrections: false 라면 반드시 고쳐야 할 점 1~2개(무엇을 조건에 추가해야 하는지 구체적으로).\n"
        "  true 면 빈 배열.\n"
        "- reason: 그렇게 판단한 이유 한두 문장.\n\n"
        '{"agree":true,"corrections":[],"reason":"..."}'
    )

    def build(o: Dict[str, Any]) -> ConsensusReview:
        agree = o.get("agree")
        if isinstance(agree, str):
            agree = agree.strip().lower() in ("true", "yes", "y", "1", "동의", "예")
        return ConsensusReview(
            slot=reviewer.slot, agent_id=reviewer.agent_id, agent_name=reviewer.agent_name,
            agree=bool(agree), corrections=_slist(o.get("corrections"), 3), reason=_s(o.get("reason")),
        )

    def validate(rv: ConsensusReview) -> List[str]:
        issues = []
        if len(_s(rv.reason)) < 5:
            issues.append("review_reason_missing")
        if not rv.agree and not rv.corrections:
            issues.append("corrections_missing")
        return issues

    return _generate_structured(
        call, system=_DEBATE_SYSTEM, user=user, build=build, validate=validate,
        repair_hint="agree 를 true/false 로 명확히 내고, false 면 corrections 를 1개 이상 써라.",
        temperature=0.35,
    )


def _position_block_solo(pos: DebatePosition) -> str:
    return f"[너의 관점 — 반드시 유지] {pos.label}\n{pos.stance}\n[판단 기준 축] {pos.axis}"


def render_consensus_draft(draft: FinalConclusion, pos: DebatePosition, round_no: int) -> str:
    lines = [f"[{pos.label} 합의 초안{f' (수정 {round_no - 1}차)' if round_no > 1 else ''}]",
             draft.decision, "", "적용 조건", _bullet(draft.conditions), "", f"이유: {draft.reason}"]
    return "\n".join(l for l in lines if l is not None).strip()


def render_consensus_review(review: ConsensusReview, pos: DebatePosition) -> str:
    head = f"[{pos.label} 검토] {'초안에 동의한다' if review.agree else '아직 동의할 수 없다'}"
    lines = [head, review.reason]
    if review.corrections:
        lines.extend(["", "수정 요구", _bullet(review.corrections)])
    return "\n".join(l for l in lines if l).strip()


def render_consensus_final(final: FinalConclusion, outcome: "ConsensusOutcome",
                           positions: List[DebatePosition]) -> str:
    names = ", ".join(p.agent_name for p in positions)
    head = ("[최종 결론 — 참여자 합의]" if outcome.agreed
            else "[최종 결론 — 합의된 부분까지]")
    lines = [head, final.decision, "", "적용 조건", _bullet(final.conditions), "",
             f"이유: {final.reason}", "", f"권고: {final.recommendation}"]
    if outcome.open_points:
        lines.extend(["", "합의되지 않아 남겨둔 쟁점", _bullet(outcome.open_points)])
    lines.extend(["", f"이 결론은 {names} 의 토론과 상호 검토를 거쳐 수렴한 것이다."])
    return "\n".join(l for l in lines if l is not None).strip()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6) 에이전트 선택 / 안건 추출
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _agent_id(agent: AgentProfile) -> Any:
    return getattr(agent, "agentId", None) or getattr(agent, "id", None)


def _agent_name(agent: AgentProfile, idx: int) -> str:
    return _s(getattr(agent, "name", None)) or f"토론자 {idx}"


def extract_topic(request: MultiChatRequest) -> str:
    """1단계 안건 = 사용자 메시지 원문. 별도 논제 생성을 하지 않는다."""
    return _s(getattr(request, "message", ""))


SLOT_LETTERS = "ABCDEFGH"


def select_debate_participants(agents: List[AgentProfile]) -> List[AgentProfile]:
    """토론 참여자 = 선택된 에이전트 '전원'. 사회자/심판을 따로 만들지 않는다.

    선택된 사람을 2명으로 잘라내면 나머지는 화면에 아예 등장하지 못한다(관측된 버그).
    1명뿐이면 토론이 성립하지 않으므로 대립 관점 1명을 복제해 최소 2명을 만든다.
    """
    live = [a for a in (agents or []) if a is not None]
    if len(live) >= 2:
        return live[:len(SLOT_LETTERS)]
    if len(live) == 1:
        base = live[0]
        clone = base.model_copy(deep=True)
        clone.agentId = f"{_agent_id(base) or 'agent'}-b"
        clone.id = clone.agentId
        clone.name = "대립 관점 토론자"
        return [base, clone]
    return [AgentProfile(agentId="debate-a", id="debate-a", name="토론자 1"),
            AgentProfile(agentId="debate-b", id="debate-b", name="토론자 2")]


def select_debate_agents(agents: List[AgentProfile]) -> Tuple[AgentProfile, AgentProfile]:
    """하위 호환: 앞의 2명만 필요한 호출부용."""
    parts = select_debate_participants(agents)
    return parts[0], parts[1]


_ARGUMENT_TYPES = ("OPENING", "REBUTTAL")


def _speech_corpus(t: DebateTranscript, slot: str, *, last_only: bool = False,
                   types: Optional[Tuple[str, ...]] = None) -> str:
    """상대에게 넘길 '실제 발언 원문'. transcript에 쌓인 텍스트만 사용한다.

    types 를 주면 그 발언 유형만 넘긴다(예외 정리 단계에서 상대의 예외 정리를 베끼는 것 방지).
    """
    texts = [s.text for s in t.speeches
             if s.slot == slot and (types is None or s.speech_type in types)]
    if not texts:
        return ""
    if last_only:
        return texts[-1]
    return "\n\n---\n\n".join(texts)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7) 오케스트레이션 — 실제 토론 진행
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _log(request_id: str, strength: str, round_no: Any, speaker: str, target: str, stage: str) -> None:
    # 사용자 메시지/프롬프트 원문은 남기지 않는다(발화 메타데이터만).
    logger.info("[DEBATE] request_id=%s mode=debate debate_strength=%s round=%s speaker=%s target=%s stage=%s",
                request_id, strength, round_no, speaker, target, stage)


def run_debate(request: MultiChatRequest, agents: List[AgentProfile],
               llm: Optional[LLMCall] = None,
               on_speech: Optional[Callable[[Speech], None]] = None,
               on_stage: Optional[Callable[[str, str], None]] = None) -> DebateTranscript:
    """토론 전체를 실행하고 transcript를 반환한다. 발언마다 on_speech 콜백을 호출한다.

    선택된 에이전트는 '전원' 입론 → 상호 반박 → 예외 정리에 실제로 참여한다.
    최종 결론은 한 명이 독단으로 쓰지 않는다. 초안 → 상호 검토 → 수정의 합의 절차를 거친다.
    """
    call = llm or _default_llm
    topic = extract_topic(request)
    strength = resolve_strength(request)
    rounds = rebuttal_rounds(strength)
    request_id = f"dbt_{uuid.uuid4().hex[:12]}"

    participants = select_debate_participants(agents)
    t = DebateTranscript(topic=topic, strength=strength, request_id=request_id)

    def emit(speech: Speech) -> None:
        t.speeches.append(speech)
        _log(request_id, strength, speech.round_no, f"agent_{speech.slot.lower()}",
             (speech.target_agent_name or "-"), speech.stage_type)
        if on_speech:
            on_speech(speech)

    def stage(key: str, title: str) -> None:
        if on_stage:
            on_stage(key, title)

    # ── 관점 배정 ────────────────────────────────────────────────────────────
    stage("POSITION_ASSIGNMENT", "관점 배정")
    positions = assign_positions_multi(topic, participants, llm=call)
    t.positions = positions
    _log(request_id, strength, 0, "system", "-", "POSITION_ASSIGNMENT")

    slots = [p.slot for p in positions]
    agent_of = {p.slot: participants[i] for i, p in enumerate(positions)}
    pos_of = {p.slot: p for p in positions}
    # 반박 상대는 다음 순번(순환). 2명이면 A↔B, 3명이면 A→B→C→A 로 전원이 때리고 전원이 맞는다.
    opponent_of = {slots[i]: slots[(i + 1) % len(slots)] for i in range(len(slots))}

    logger.info("[DEBATE] request_id=%s participants=%d slots=%s", request_id, len(slots), slots)

    # ── 입론 ─────────────────────────────────────────────────────────────────
    stage("OPENING", "입론")
    for slot in slots:
        me, other = pos_of[slot], pos_of[opponent_of[slot]]
        try:
            arg, issues, retries = generate_opening(topic, me, other, agent_of[slot], llm=call)
        except Exception as exc:
            raise DebateAgentFailure(me.agent_name, me.agent_id, "OPENING",
                                     [type(exc).__name__]) from exc
        # 한 명이 실제로 주장하지 못했는데 나머지로 진행하면 토론이 아니라 설명문이 된다.
        if arg is None or not _s(arg.conclusion) or (not arg.reasons and not _s(arg.explanation)):
            raise DebateAgentFailure(me.agent_name, me.agent_id, "OPENING", issues or ["empty_opening"])
        t.openings[slot] = arg
        emit(Speech(
            slot=slot, agent_id=me.agent_id, agent_name=me.agent_name,
            speech_type="OPENING", stage_type="DEBATE_OPENING", stage_title=f"{me.label} 입론",
            round_no=0, text=render_opening(arg, me), regenerated=retries,
            structured={"conclusion": arg.conclusion, "reasons": arg.reasons,
                        "explanation": arg.explanation, "issues": issues, "position": me.label},
        ))

    # ── 상호 반박 — 강도만큼 라운드 반복 ─────────────────────────────────────
    for rnd in range(1, rounds + 1):
        stage(f"REBUTTAL_R{rnd}", f"{rnd}차 상호 반박")
        for slot in slots:
            other_slot = opponent_of[slot]
            me, other = pos_of[slot], pos_of[other_slot]
            # ★ 상대의 '실제 발언'만 컨텍스트로 넘긴다.
            opponent_text = _speech_corpus(t, other_slot)
            own_previous = [r.target_claim + " " + r.counter_argument for r in t.rebuttals.get(slot, [])]
            already = [r.target_claim for r in t.rebuttals.get(slot, [])]
            candidates = untargeted_claims(claim_candidates(t, other_slot), already)
            try:
                reb, issues, retries = generate_rebuttal(
                    topic, me, other, agent_of[slot], opponent_text, own_previous, rnd, llm=call,
                    opponent_latest=_speech_corpus(t, other_slot, last_only=True),
                    target_candidates=candidates,
                    own_previous_counters=[r.counter_argument for r in t.rebuttals.get(slot, [])])
            except Exception as exc:
                raise DebateAgentFailure(me.agent_name, me.agent_id, f"REBUTTAL_R{rnd}",
                                         [type(exc).__name__]) from exc
            if reb is None or not _s(reb.counter_argument):
                raise DebateAgentFailure(me.agent_name, me.agent_id, f"REBUTTAL_R{rnd}",
                                         issues or ["empty_rebuttal"])
            t.rebuttals.setdefault(slot, []).append(reb)
            emit(Speech(
                slot=slot, agent_id=me.agent_id, agent_name=me.agent_name,
                speech_type="REBUTTAL", stage_type=f"DEBATE_REBUTTAL_R{rnd}",
                stage_title=f"{me.label} {rnd}차 반박", round_no=rnd,
                text=render_rebuttal(reb, me, other.agent_name),
                target_agent_id=other.agent_id, target_agent_name=other.agent_name,
                regenerated=retries,
                structured={"targetClaim": reb.target_claim, "acknowledgedPoint": reb.acknowledged_point,
                            "counterArgument": reb.counter_argument,
                            "evidenceOrReasoning": reb.evidence_or_reasoning,
                            "issues": issues, "position": me.label},
            ))

    # ── 예외 정리 + 입장 수정 ────────────────────────────────────────────────
    stage("EXCEPTION", "예외 정리")
    for slot in slots:
        other_slot = opponent_of[slot]
        me, other = pos_of[slot], pos_of[other_slot]
        note, issues, retries = generate_exception(
            topic, me, other, agent_of[slot],
            _speech_corpus(t, slot, types=_ARGUMENT_TYPES),
            _speech_corpus(t, other_slot, types=_ARGUMENT_TYPES),
            llm=call, opponent_note=t.exceptions.get(other_slot))
        if note is None:
            note = ExceptionNote()
        if not _s(note.revised_conclusion):
            opening = t.openings.get(slot)
            note.revised_conclusion = opening.conclusion if opening else ""
        t.exceptions[slot] = note
        emit(Speech(
            slot=slot, agent_id=me.agent_id, agent_name=me.agent_name,
            speech_type="EXCEPTION", stage_type="DEBATE_EXCEPTION",
            stage_title=f"{me.label} 예외 정리", round_no=rounds + 1,
            text=render_exception(note, me), target_agent_id=other.agent_id,
            target_agent_name=other.agent_name, regenerated=retries,
            structured={"acknowledgedFromOpponent": note.acknowledged_from_opponent,
                        "exceptions": note.exceptions, "flipConditions": note.flip_conditions,
                        "issues": issues, "position": me.label},
        ))

    if uses_position_revision(strength):
        stage("REVISION", "입장 수정")
        for slot in slots:
            me, note = pos_of[slot], t.exceptions[slot]
            emit(Speech(
                slot=slot, agent_id=me.agent_id, agent_name=me.agent_name,
                speech_type="REVISION", stage_type="DEBATE_REVISION",
                stage_title=f"{me.label} 입장 수정", round_no=rounds + 2,
                text=render_revision(note, me),
                structured={"revisedConclusion": note.revised_conclusion, "position": me.label},
            ))

    # ── 수렴 (deep 전용) ─────────────────────────────────────────────────────
    if uses_convergence_step(strength) and len(slots) >= 2:
        stage("CONVERGENCE", "판단 기준 수렴")
        criteria, _issues, _r = generate_convergence(
            topic, pos_of[slots[0]], pos_of[slots[1]], t.exceptions[slots[0]],
            t.exceptions[slots[1]], agent_of[slots[-1]], llm=call)
        t.convergence = criteria or []
        _log(request_id, strength, rounds + 3, f"agent_{slots[-1].lower()}", "-", "DEBATE_CONVERGENCE")

    # ── 최종 결론 — 합의 프로토콜 (특정 에이전트의 단독 저작 금지) ────────────
    stage("CONSENSUS", "합의 절차")
    outcome = run_consensus(topic, positions, t.exceptions, agent_of, t.convergence,
                            llm=call, emit=emit, rounds_base=rounds + 3)
    t.final = outcome.final
    t.consensus = outcome

    stage("FINAL_CONCLUSION", "최종 결론")
    emit(Speech(
        slot=CONSENSUS_SLOT, agent_id=CONSENSUS_AGENT_ID, agent_name=CONSENSUS_AGENT_NAME,
        speech_type="FINAL_CONCLUSION", stage_type="DEBATE_FINAL_CONCLUSION",
        stage_title="최종 결론", round_no=rounds + 6,
        text=render_consensus_final(outcome.final, outcome, positions),
        structured={"decision": outcome.final.decision, "conditions": outcome.final.conditions,
                    "reason": outcome.final.reason, "recommendation": outcome.final.recommendation,
                    "convergenceCriteria": t.convergence,
                    "consensusAgreed": outcome.agreed, "consensusRounds": outcome.rounds,
                    "openPoints": outcome.open_points,
                    "authoredBy": [p.agent_name for p in positions],
                    "agreement": {f"agent{p.slot}Agree": _slot_agreed(outcome, p.slot)
                                  for p in positions}},
    ))
    return t


CONSENSUS_SLOT = "*"
CONSENSUS_AGENT_ID = "debate-consensus"
CONSENSUS_AGENT_NAME = "최종 결론 (합의)"


def _slot_agreed(outcome: "ConsensusOutcome", slot: str) -> bool:
    """마지막 라운드에서 그 슬롯이 동의했는가. 초안 작성자는 자기 초안에 동의한 것으로 본다."""
    for rv in reversed(outcome.reviews):
        if rv.slot == slot:
            return bool(rv.agree)
    return True


def run_consensus(topic: str, positions: List[DebatePosition], notes: Dict[str, ExceptionNote],
                  agent_of: Dict[str, AgentProfile], criteria: List[str],
                  llm: Optional[LLMCall] = None,
                  emit: Optional[Callable[[Speech], None]] = None,
                  rounds_base: int = 0) -> ConsensusOutcome:
    """합의 절차.

      1) 첫 참여자가 토론 결과로 결론 초안을 쓴다.
      2) 나머지 참여자가 각자 읽고 agree / corrections 를 낸다.
      3) 동의하지 않으면 초안 작성자가 corrections 를 반영해 다시 쓴다.
      4) 다시 검토한다. (최대 MAX_CONSENSUS_ROUNDS 회)
      5) 모두 agree 면 합의 확정, 아니면 남은 쟁점을 open_points 로 명시한다.

    최종 결론이 특정 에이전트 소유가 되지 않게 하는 것이 이 절차의 목적이다.
    """
    call = llm or _default_llm
    drafter = positions[0]
    reviewers = positions[1:]
    draft = FinalConclusion()
    all_reviews: List[ConsensusReview] = []
    last_round_reviews: List[ConsensusReview] = []
    corrections: List[str] = []
    agreed = False
    rnd = 0

    for rnd in range(1, MAX_CONSENSUS_ROUNDS + 1):
        new_draft, issues, retries = generate_conclusion_draft(
            topic, drafter, positions, notes, agent_of[drafter.slot], criteria,
            corrections=corrections or None, llm=call)
        if new_draft is not None and _s(new_draft.decision):
            draft = new_draft
        elif rnd == 1:
            raise DebateAgentFailure(drafter.agent_name, drafter.agent_id, "CONSENSUS_DRAFT",
                                     issues or ["empty_draft"])
        if emit:
            emit(Speech(
                slot=drafter.slot, agent_id=drafter.agent_id, agent_name=drafter.agent_name,
                speech_type="CONSENSUS_DRAFT", stage_type=f"DEBATE_CONSENSUS_DRAFT_R{rnd}",
                stage_title=f"{drafter.label} 합의 초안" + (f" (수정 {rnd - 1}차)" if rnd > 1 else ""),
                round_no=rounds_base + rnd, text=render_consensus_draft(draft, drafter, rnd),
                regenerated=retries,
                structured={"decision": draft.decision, "conditions": draft.conditions,
                            "reason": draft.reason, "recommendation": draft.recommendation,
                            "consensusRound": rnd, "issues": issues, "position": drafter.label},
            ))

        last_round_reviews = []
        for rev_pos in reviewers:
            review, r_issues, r_retries = generate_conclusion_review(
                topic, rev_pos, draft, agent_of[rev_pos.slot], notes.get(rev_pos.slot), llm=call)
            if review is None:
                review = ConsensusReview(slot=rev_pos.slot, agent_id=rev_pos.agent_id,
                                         agent_name=rev_pos.agent_name, agree=False,
                                         corrections=["초안 검토 응답을 만들지 못했다."],
                                         reason="검토 응답 생성 실패")
            last_round_reviews.append(review)
            all_reviews.append(review)
            if emit:
                emit(Speech(
                    slot=rev_pos.slot, agent_id=rev_pos.agent_id, agent_name=rev_pos.agent_name,
                    speech_type="CONSENSUS_REVIEW", stage_type=f"DEBATE_CONSENSUS_REVIEW_R{rnd}",
                    stage_title=f"{rev_pos.label} 초안 검토", round_no=rounds_base + rnd,
                    text=render_consensus_review(review, rev_pos),
                    target_agent_id=drafter.agent_id, target_agent_name=drafter.agent_name,
                    regenerated=r_retries,
                    structured={"agree": review.agree, "corrections": review.corrections,
                                "reason": review.reason, "consensusRound": rnd,
                                "issues": r_issues, "position": rev_pos.label},
                ))

        agreed = all(rv.agree for rv in last_round_reviews) if last_round_reviews else True
        if agreed:
            break
        corrections = [c for rv in last_round_reviews for c in rv.corrections][:4]

    open_points = ([c for rv in last_round_reviews if not rv.agree for c in rv.corrections][:4]
                   if not agreed else [])
    return ConsensusOutcome(final=draft, agreed=agreed, rounds=rnd,
                            reviews=all_reviews, open_points=open_points)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 8) 직렬화 (SSE / 동기 JSON 공통)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def position_payload(pos: DebatePosition) -> Dict[str, Any]:
    return {"slot": pos.slot, "agentId": pos.agent_id, "agentName": pos.agent_name,
            "label": pos.label, "stance": pos.stance, "axis": pos.axis}


def speech_answer(speech: Speech, order: int, identity: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = {
        "agentId": speech.agent_id,
        "agentName": speech.agent_name,
        "answer": speech.text,
        "content": speech.text,
        "mode": "debate",
        "round": speech.round_no,
        "displayOrder": order,
        "sequence": order,
        "status": "SUCCESS",
        "speechType": speech.speech_type,
        "stageType": speech.stage_type,
        "stageTitle": speech.stage_title,
        "debateSlot": speech.slot,
        "debateRound": speech.round_no,
        "targetAgentId": speech.target_agent_id,
        "targetAgentName": speech.target_agent_name,
        "debateStructured": speech.structured,
    }
    if identity:
        data.update(identity)
    return data


def transcript_payload(t: DebateTranscript) -> Dict[str, Any]:
    ok, issues = validate_transcript(t)
    return {
        "topic": t.topic,
        "debateStrength": t.strength,
        "rebuttalRounds": rebuttal_rounds(t.strength),
        "debateRequestId": t.request_id,
        "debatePositions": [position_payload(p) for p in t.positions],
        "debateStages": [
            {"stageType": s.stage_type, "stageTitle": s.stage_title, "speechType": s.speech_type,
             # side/agentIndex 는 기존 프론트 토론 렌더러(색상/마인드맵 노드) 호환 필드다.
             # 찬반 프레임이 아니라 '두 관점'이므로 슬롯 A/B를 색상 축으로만 매핑한다.
             "side": "NEUTRAL" if s.slot == CONSENSUS_SLOT else ("PRO" if s.slot == "A" else "CON"),
             "agentIndex": (0 if s.slot == CONSENSUS_SLOT
                            else (SLOT_LETTERS.index(s.slot) + 1 if s.slot in SLOT_LETTERS else 1)),
             "agentId": s.agent_id, "agentName": s.agent_name, "round": s.round_no,
             "targetAgentName": s.target_agent_name, "content": s.text}
            for s in t.speeches
        ],
        "debateResult": ({
            "decision": t.final.decision, "conditions": t.final.conditions,
            "reason": t.final.reason, "recommendation": t.final.recommendation,
            # 최종 결론은 특정 에이전트 소유가 아니다. 누가 무엇에 동의했는지만 남긴다.
            "consensus": ({
                "agreed": t.consensus.agreed,
                "rounds": t.consensus.rounds,
                "openPoints": t.consensus.open_points,
                "authoredBy": [p.agent_name for p in t.positions],
                "agreement": [{"agentId": p.agent_id, "agentName": p.agent_name,
                               "slot": p.slot, "agree": _slot_agreed(t.consensus, p.slot)}
                              for p in t.positions],
            } if t.consensus else None),
        } if t.final else None),
        "debateParticipants": [
            {"slot": p.slot, "agentId": p.agent_id, "agentName": p.agent_name, "label": p.label}
            for p in t.positions
        ],
        "debateConvergenceCriteria": t.convergence,
        "debateValidation": {"passed": ok, "issues": issues},
    }
