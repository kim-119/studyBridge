"""
상황극(simulation) 모드 — 세션형 3역할 시뮬레이션 엔진.

일반 1:1 Q&A 가 아니다. 한 세션에 세 기능적 역할이 살아 있어야 한다.
  HOST       진행/질의   — 상황을 만들고 사건·질문을 진행한다
  CHALLENGER 심화 검증   — 사용자의 논리 허점·근거를 꼬리질문으로 검증한다
  COACH      피드백 코치 — 답변의 강점/약점과 개선 방향을 정리한다

흐름:
  1턴  상황 제시(+선택지)
  2턴~ 사용자 답/선택 → 심화 검증 → 코치 피드백 → 결과/다음 장면(+선택지)

설정(simulationConfig)은 기존 DTO를 재사용한다.
  scenarioType 현실|면접|프로젝트, difficulty 쉬움|보통|어려움, choiceCount 2~4.
선택지 개수는 설정값과 '정확히' 일치해야 한다.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

HOST, CHALLENGER, COACH = "HOST", "CHALLENGER", "COACH"
ROLE_LABEL = {HOST: "진행", CHALLENGER: "심화 검증", COACH: "피드백 코치"}

SCENE_SETUP, CHALLENGE, FEEDBACK, NEXT_SCENE = "SCENE_SETUP", "CHALLENGE", "FEEDBACK", "NEXT_SCENE"

REALISTIC, INTERVIEW, PROJECT = "realistic", "interview", "project"
EASY, NORMAL, HARD = "easy", "normal", "hard"

_TYPE_ALIASES = {
    "realistic": REALISTIC, "현실": REALISTIC, "현실형": REALISTIC, "real": REALISTIC, "auto": REALISTIC,
    "interview": INTERVIEW, "면접": INTERVIEW, "job": INTERVIEW,
    "project": PROJECT, "프로젝트": PROJECT, "발표": PROJECT, "capstone": PROJECT,
}
_DIFF_ALIASES = {
    "easy": EASY, "쉬움": EASY, "low": EASY, "beginner": EASY,
    "normal": NORMAL, "보통": NORMAL, "medium": NORMAL,
    "hard": HARD, "어려움": HARD, "high": HARD, "difficult": HARD,
}

MAX_STEP_RETRIES = int(os.getenv("SIMULATION_MAX_STEP_RETRIES", "2"))
CONTENT_MAX_TOKENS = int(os.getenv("SIMULATION_MAX_TOKENS", "900"))
MIN_CHOICES, MAX_CHOICES = 2, 4


def resolve_config(request: Any) -> Tuple[str, str, int]:
    cfg = getattr(request, "simulationConfig", None)
    if isinstance(cfg, dict):
        raw_type = cfg.get("scenarioType") or cfg.get("scenario_type") or cfg.get("domain")
        raw_diff = cfg.get("difficulty")
        raw_count = cfg.get("choiceCount") or cfg.get("choice_count")
    else:
        raw_type = getattr(cfg, "scenarioType", None) or getattr(cfg, "domain", None)
        raw_diff = getattr(cfg, "difficulty", None)
        raw_count = getattr(cfg, "choiceCount", None)
    stype = _TYPE_ALIASES.get(str(raw_type or "").strip().lower(), REALISTIC)
    diff = _DIFF_ALIASES.get(str(raw_diff or "").strip().lower(), NORMAL)
    try:
        count = int(raw_count)
    except (TypeError, ValueError):
        count = 3
    count = max(MIN_CHOICES, min(MAX_CHOICES, count))
    return stype, diff, count


# ── 데이터 ──────────────────────────────────────────────────────────────────

@dataclass
class SimSpeech:
    role: str
    stage_type: str
    stage_title: str
    text: str
    agent_id: Any = None
    agent_name: str = ""
    choices: List[Dict[str, Any]] = field(default_factory=list)
    structured: Dict[str, Any] = field(default_factory=dict)
    regenerated: int = 0
    issues: List[str] = field(default_factory=list)


# ── LLM ─────────────────────────────────────────────────────────────────────

def _default_llm(system_prompt: str, user_prompt: str, *, max_tokens: int, temperature: float) -> str:
    from app.services.ollama_client import ask_ollama
    return ask_ollama(system_prompt=system_prompt, user_prompt=user_prompt,
                      max_tokens=max_tokens, temperature=temperature, think=False)


def _parse(raw: str) -> Dict[str, Any]:
    from app.services.debate_engine import parse_json_object
    return parse_json_object(raw)


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _slist(v: Any, limit: int = 4) -> List[str]:
    if isinstance(v, (list, tuple)):
        return [_s(x) for x in v if _s(x)][:limit]
    return [_s(v)] if _s(v) else []


class SimulationStageError(RuntimeError):
    """역할 단계 생성 실패. 다른 모드로 폴백하지 않고 모드 전용 오류로 올린다."""

    def __init__(self, role: str, issues: List[str]):
        self.role = role
        self.issues = issues
        super().__init__(f"{role} 단계 생성 실패: {', '.join(issues)}")


def _generate(llm, system: str, user: str, build, validate, repair_hint: str, role: str,
              temperature: float = 0.5):
    last_issues = ["empty_response"]
    for attempt in range(MAX_STEP_RETRIES + 1):
        prompt = user if attempt == 0 else (
            f"{user}\n\n[재작성 지시 — 직전 출력이 계약을 어겼다: {', '.join(last_issues)}]\n{repair_hint}")
        raw = llm(system, prompt, max_tokens=CONTENT_MAX_TOKENS, temperature=temperature + 0.05 * attempt)
        obj = build(_parse(raw))
        issues = validate(obj)
        if not issues:
            obj.regenerated = attempt
            return obj
        last_issues = issues
        logger.warning("[SIMULATION] %s 단계 검증 실패(attempt=%d) issues=%s", role, attempt + 1, issues)
    raise SimulationStageError(role, last_issues)


# ── 검증 ────────────────────────────────────────────────────────────────────

def _tokens(text: str) -> set:
    from app.services.korean_text_match import tokens
    return tokens(text)


def references_user_answer(text: str, user_answer: str, min_overlap: int = 1) -> bool:
    """검증 질문이 '사용자가 실제로 한 말'을 대상으로 하는지(지어낸 공격 방지)."""
    from app.services.korean_text_match import overlap_count
    a, b = _tokens(text), _tokens(user_answer)
    if not b:
        return True
    return overlap_count(a, b) >= min_overlap


# 사용자가 선택지를 '2번', 'B', '두 번째'처럼 짧게 가리킬 때 세션에 저장된 선택지로 되돌린다.
# (프론트가 selectedChoice 를 보내지 않는 경로에서도 사용자의 선택이 실제 내용으로 전달돼야 한다.)
_ORDINAL_WORDS = ("첫", "두", "세", "네", "다섯")
_CHOICE_NUM_RE = re.compile(r"^\s*([1-9])\s*(번|번째|째)?\s*$")
_CHOICE_LETTER_RE = re.compile(r"^\s*([A-Ea-e])\s*[.)]?\s*$")


def resolve_choice_reference(message: str, choices: List[Dict[str, Any]]) -> str:
    """선택지 지시어 → 해당 선택지 문구. 지시어가 아니면 빈 문자열."""
    text = _s(message)
    if not text or not choices:
        return ""
    idx = None
    m = _CHOICE_NUM_RE.match(text)
    if m:
        idx = int(m.group(1)) - 1
    if idx is None:
        m = _CHOICE_LETTER_RE.match(text)
        if m:
            idx = ord(m.group(1).upper()) - 65
    if idx is None:
        for i, word in enumerate(_ORDINAL_WORDS):
            if text.replace(" ", "").startswith(f"{word}번째"):
                idx = i
                break
    if idx is None or idx < 0 or idx >= len(choices):
        return ""
    choice = choices[idx]
    if isinstance(choice, dict):
        return _s(choice.get("label") or choice.get("text"))
    return _s(choice)


def validate_choices(choices: List[Dict[str, Any]], expected: int) -> List[str]:
    if len(choices) != expected:
        return [f"choice_count_{len(choices)}_expected_{expected}"]
    if any(not _s(c.get("label")) for c in choices):
        return ["choice_label_missing"]
    return []


# ── 프롬프트 ────────────────────────────────────────────────────────────────

_SYSTEM = (
    "너는 StudyBridge 상황극(시뮬레이션) 학습 엔진의 한 역할을 맡는다.\n"
    "- 일반 개념 설명문을 쓰지 마라. 지금은 사용자가 '그 상황 안에 있는' 훈련이다.\n"
    "- 사용자를 관찰자가 아니라 당사자로 다룬다.\n"
    "- 출력은 지시된 JSON 하나만. 설명·머리말·코드펜스 금지. 값은 한국어."
)

_TYPE_DIRECTIVE = {
    INTERVIEW: "면접 상황이다. 면접관의 질문과 꼬리질문이 이어져야 한다.",
    PROJECT: "프로젝트/발표 상황이다. 원인·근거·대안을 압박하는 질문이 이어져야 한다.",
    REALISTIC: "현실 업무 상황이다. 선택에 따른 결과와 개념 연결이 드러나야 한다.",
}
_DIFF_DIRECTIVE = {
    EASY: "난이도 쉬움: 상황을 명확히 설명하고, 선택지 간 차이를 뚜렷하게 만든다.",
    NORMAL: "난이도 보통: 현실적인 제약을 한두 개 넣는다.",
    HARD: "난이도 어려움: 상충하는 제약과 불완전한 정보를 넣고, 근거 없는 답은 바로 파고든다.",
}


def _choice_spec(count: int) -> str:
    return (f"- choices: 정확히 {count}개. 각 항목은 {{\"label\":\"사용자가 고를 행동/답변\"}} 형태다. "
            f"{count}개가 아니면 실패다.")


def generate_scene_setup(topic: str, stype: str, difficulty: str, choice_count: int,
                         agent_name: str, llm=None) -> SimSpeech:
    call = llm or _default_llm
    user = (
        f"[사용자가 연습하고 싶은 것]\n{topic}\n\n"
        f"{_TYPE_DIRECTIVE[stype]}\n{_DIFF_DIRECTIVE[difficulty]}\n\n"
        "너는 '진행/질의' 역할이다. 세션의 첫 장면을 만든다. 다음 JSON만 출력하라.\n"
        "- scenario: 상황 한 문단(어디서, 누가, 무엇이 걸려 있는지).\n"
        "- userRole: 이 상황에서 사용자가 맡는 역할.\n"
        "- goal: 사용자가 이 장면에서 달성해야 할 목표 한 줄.\n"
        "- prompt: 사용자에게 던지는 질문 또는 사건(1~2문장, 물음표로 끝난다).\n"
        f"{_choice_spec(choice_count)}\n\n"
        '{"scenario":"...","userRole":"...","goal":"...","prompt":"...?","choices":[{"label":"..."}]}'
    )

    def build(o: Dict[str, Any]) -> SimSpeech:
        choices = [{"choiceId": chr(65 + i), "label": _s(c.get("label") if isinstance(c, dict) else c),
                    "text": _s(c.get("label") if isinstance(c, dict) else c)}
                   for i, c in enumerate(o.get("choices") or [])]
        scenario, role, goal, prompt = (_s(o.get("scenario")), _s(o.get("userRole")),
                                        _s(o.get("goal")), _s(o.get("prompt")))
        text = "\n\n".join(p for p in [scenario, f"당신의 역할: {role}" if role else "",
                                       f"목표: {goal}" if goal else "", prompt] if p)
        return SimSpeech(role=HOST, stage_type=SCENE_SETUP, stage_title="상황 제시", text=text,
                         agent_name=agent_name, choices=choices,
                         structured={"scenario": scenario, "userRole": role, "goal": goal, "prompt": prompt})

    def validate(sp: SimSpeech) -> List[str]:
        issues = validate_choices(sp.choices, choice_count)
        if len(_s(sp.structured.get("scenario"))) < 20:
            issues.append("scenario_missing")
        if not _s(sp.structured.get("userRole")):
            issues.append("user_role_missing")
        from app.services.korean_text_match import is_question_like
        if not is_question_like(_s(sp.structured.get("prompt"))):
            issues.append("prompt_missing")
        return issues

    return _generate(call, _SYSTEM, user, build, validate,
                     repair_hint=f"choices 를 정확히 {choice_count}개로 맞추고 scenario/userRole/prompt 를 채워라.",
                     role=HOST)


def _scene_block(session_data: Dict[str, Any]) -> str:
    return (f"[고정된 상황]\n{session_data.get('scenario', '')}\n"
            f"[사용자 역할] {session_data.get('userRole', '')}\n"
            f"[목표] {session_data.get('goal', '')}\n"
            f"[직전 질문/사건] {session_data.get('prompt', '')}\n")


def generate_challenge(session_data: Dict[str, Any], user_answer: str, stype: str, difficulty: str,
                       agent_name: str, llm=None) -> SimSpeech:
    call = llm or _default_llm
    user = (
        f"{_scene_block(session_data)}\n[사용자의 이번 답변/선택]\n{user_answer}\n\n"
        f"{_TYPE_DIRECTIVE[stype]}\n{_DIFF_DIRECTIVE[difficulty]}\n\n"
        "너는 '심화 검증' 역할이다. 사용자의 답에서 근거가 약하거나 빠진 지점을 하나 골라 꼬리질문을 던진다.\n"
        "- targetPoint: 사용자의 답에서 실제로 짚을 지점(사용자가 한 말을 근거로).\n"
        "- challengeQuestion: 그 지점을 검증하는 질문 1개(물음표로 끝난다).\n"
        "사용자가 하지 않은 말을 지어내서 공격하지 마라.\n\n"
        '{"targetPoint":"...","challengeQuestion":"...?"}'
    )

    def build(o: Dict[str, Any]) -> SimSpeech:
        target, q = _s(o.get("targetPoint")), _s(o.get("challengeQuestion"))
        text = "\n\n".join(p for p in [target, q] if p)
        return SimSpeech(role=CHALLENGER, stage_type=CHALLENGE, stage_title="심화 검증",
                         text=text, agent_name=agent_name,
                         structured={"targetPoint": target, "challengeQuestion": q})

    def validate(sp: SimSpeech) -> List[str]:
        issues = []
        from app.services.korean_text_match import is_question_like
        if not is_question_like(_s(sp.structured.get("challengeQuestion"))):
            issues.append("challenge_question_missing")
        if len(_s(sp.structured.get("targetPoint"))) < 5:
            issues.append("target_point_missing")
        if not references_user_answer(sp.text, user_answer):
            issues.append("not_referencing_user_answer")
        return issues

    return _generate(call, _SYSTEM, user, build, validate,
                     repair_hint="사용자가 실제로 쓴 표현을 근거로 targetPoint 를 정하고 질문 1개로 끝내라.",
                     role=CHALLENGER)


def generate_feedback(session_data: Dict[str, Any], user_answer: str, difficulty: str,
                      agent_name: str, llm=None) -> SimSpeech:
    call = llm or _default_llm
    user = (
        f"{_scene_block(session_data)}\n[사용자의 이번 답변/선택]\n{user_answer}\n\n"
        f"{_DIFF_DIRECTIVE[difficulty]}\n\n"
        "너는 '피드백 코치' 역할이다. 이번 답변만 평가한다. 다음 JSON만 출력하라.\n"
        "- strengths: 잘한 점 1~2개(사용자가 실제로 말한 내용 기준).\n"
        "- weaknesses: 부족한 점 1~2개.\n"
        "- improvement: 다음 번에 바로 적용할 개선 방향 한 줄.\n\n"
        '{"strengths":["..."],"weaknesses":["..."],"improvement":"..."}'
    )

    def build(o: Dict[str, Any]) -> SimSpeech:
        st, wk, imp = _slist(o.get("strengths"), 2), _slist(o.get("weaknesses"), 2), _s(o.get("improvement"))
        lines = []
        if st:
            lines.append("잘한 점\n" + "\n".join(f"- {x}" for x in st))
        if wk:
            lines.append("보완할 점\n" + "\n".join(f"- {x}" for x in wk))
        if imp:
            lines.append(f"다음 시도에서는: {imp}")
        return SimSpeech(role=COACH, stage_type=FEEDBACK, stage_title="피드백", text="\n\n".join(lines),
                         agent_name=agent_name,
                         structured={"strengths": st, "weaknesses": wk, "improvement": imp})

    def validate(sp: SimSpeech) -> List[str]:
        issues = []
        if not sp.structured.get("strengths") and not sp.structured.get("weaknesses"):
            issues.append("feedback_empty")
        if not _s(sp.structured.get("improvement")):
            issues.append("improvement_missing")
        return issues

    return _generate(call, _SYSTEM, user, build, validate,
                     repair_hint="strengths/weaknesses/improvement 를 모두 채워라.", role=COACH)


def generate_next_scene(session_data: Dict[str, Any], user_answer: str, stype: str, difficulty: str,
                        choice_count: int, agent_name: str, llm=None) -> SimSpeech:
    call = llm or _default_llm
    user = (
        f"{_scene_block(session_data)}\n[사용자의 이번 답변/선택]\n{user_answer}\n\n"
        f"{_TYPE_DIRECTIVE[stype]}\n{_DIFF_DIRECTIVE[difficulty]}\n\n"
        "너는 '진행/질의' 역할이다. 같은 상황을 이어간다(장면을 처음부터 새로 만들지 마라).\n"
        "- consequence: 사용자의 답/선택이 이 상황에서 만든 결과 1~2문장.\n"
        "- conceptLink: 이 장면이 연결되는 학습 개념 한 줄.\n"
        "- prompt: 이어지는 질문 또는 사건 1개(물음표로 끝난다).\n"
        f"{_choice_spec(choice_count)}\n\n"
        '{"consequence":"...","conceptLink":"...","prompt":"...?","choices":[{"label":"..."}]}'
    )

    def build(o: Dict[str, Any]) -> SimSpeech:
        choices = [{"choiceId": chr(65 + i), "label": _s(c.get("label") if isinstance(c, dict) else c),
                    "text": _s(c.get("label") if isinstance(c, dict) else c)}
                   for i, c in enumerate(o.get("choices") or [])]
        cons, link, prompt = _s(o.get("consequence")), _s(o.get("conceptLink")), _s(o.get("prompt"))
        text = "\n\n".join(p for p in [cons, f"연결 개념: {link}" if link else "", prompt] if p)
        return SimSpeech(role=HOST, stage_type=NEXT_SCENE, stage_title="다음 장면", text=text,
                         agent_name=agent_name, choices=choices,
                         structured={"consequence": cons, "conceptLink": link, "prompt": prompt})

    def validate(sp: SimSpeech) -> List[str]:
        issues = validate_choices(sp.choices, choice_count)
        if len(_s(sp.structured.get("consequence"))) < 10:
            issues.append("consequence_missing")
        from app.services.korean_text_match import is_question_like
        if not is_question_like(_s(sp.structured.get("prompt"))):
            issues.append("prompt_missing")
        return issues

    return _generate(call, _SYSTEM, user, build, validate,
                     repair_hint=f"consequence/prompt 를 채우고 choices 를 정확히 {choice_count}개로 맞춰라.",
                     role=HOST)


# ── 턴 검증 ─────────────────────────────────────────────────────────────────

def validate_turn(speeches: List[SimSpeech], choice_count: int, first_turn: bool,
                  user_answer: str = "") -> List[str]:
    """세션 유지 / 3역할 / 선택지 수 / 사용자 응답 반영 / 검증질문 / 피드백 / 다음 상태."""
    issues: List[str] = []
    roles = [sp.role for sp in speeches]
    if first_turn:
        if roles != [HOST]:
            issues.append("scene_setup_role_invalid")
    else:
        for required in (CHALLENGER, COACH, HOST):
            if required not in roles:
                issues.append(f"missing_role_{required.lower()}")
        challenge = next((s for s in speeches if s.role == CHALLENGER), None)
        if challenge and not references_user_answer(challenge.text, user_answer):
            issues.append("challenge_not_referencing_user")
    last = speeches[-1] if speeches else None
    if last is not None and last.role == HOST:
        issues.extend(validate_choices(last.choices, choice_count))
    return issues
