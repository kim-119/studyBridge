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
# 등장인물 대사가 "한 줄 질문"으로 쪼그라드는 것을 막는 최소 길이(문자).
MIN_LINE_CHARS = int(os.getenv("SIMULATION_MIN_LINE_CHARS", "40"))


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
    import time as _time
    started = _time.time()
    last_issues = ["empty_response"]
    for attempt in range(MAX_STEP_RETRIES + 1):
        prompt = user if attempt == 0 else (
            f"{user}\n\n[재작성 지시 — 직전 출력이 계약을 어겼다: {', '.join(last_issues)}]\n{repair_hint}")
        raw = llm(system, prompt, max_tokens=CONTENT_MAX_TOKENS, temperature=temperature + 0.05 * attempt)
        obj = build(_parse(raw))
        issues = validate(obj)
        if not issues:
            obj.regenerated = attempt
            logger.info("[SIMULATION] llm_call role=%s agent=%s attempts=%d elapsed_ms=%d chars=%d",
                        role, getattr(obj, "agent_name", ""), attempt + 1,
                        int((_time.time() - started) * 1000), len(getattr(obj, "text", "") or ""))
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
    if count <= 0:
        return ("- choices: 빈 배열 []. 이 상황은 자유 답변 상황이라 선택지를 만들지 않는다.")
    return (f"- choices: 정확히 {count}개. 각 항목은 {{\"label\":\"사용자가 고를 행동/입장\"}} 형태다. "
            "각 label 은 30자 이내의 짧은 선택지다. 사용자의 답변을 대신 완성해 주면 실패다. "
            f"{count}개가 아니면 실패다.")


def choices_enabled(request: Any) -> bool:
    """선택지를 붙일 상황인가.

    기존 simulationConfig 계약(includeChoices / interactionStyle / scenarioType)만 읽는다.
      - includeChoices=False 또는 자유응답 스타일이면 붙이지 않는다.
      - 면접/발표(프로젝트) 상황은 자유 답변이 자연스럽다. 설정이 선택지를 명시하지 않았다면
        억지로 붙이지 않는다(설정이 명시했으면 그 개수를 정확히 지킨다).
    """
    cfg = getattr(request, "simulationConfig", None)
    if isinstance(cfg, dict):
        include = cfg.get("includeChoices", cfg.get("include_choices", None))
        style = cfg.get("interactionStyle") or cfg.get("interaction_style") or ""
        explicit_count = cfg.get("choiceCount", cfg.get("choice_count", None)) is not None
    elif cfg is not None:
        include = getattr(cfg, "includeChoices", None)
        style = getattr(cfg, "interactionStyle", "") or ""
        explicit_count = getattr(cfg, "choiceCount", None) is not None
    else:
        include, style, explicit_count = None, "", False

    if include is False:
        return False
    style_key = str(style).strip().lower()
    if style_key in _FREE_RESPONSE_STYLES:
        return False
    if include is True or explicit_count or style_key in _CHOICE_STYLES:
        return True
    stype, _diff, _count = resolve_config(request)
    return stype not in (INTERVIEW, PROJECT)


_FREE_RESPONSE_STYLES = {"free_response", "free", "freeform", "자유", "자유응답", "자유답변", "dialogue_only"}
_CHOICE_STYLES = {"choice_based", "choice", "선택지", "선택형"}


def effective_choice_count(request: Any, choice_count: int) -> int:
    return choice_count if choices_enabled(request) else 0


def _parse_choices(raw: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i, c in enumerate(raw or []):
        label = _s(c.get("label") if isinstance(c, dict) else c)
        if not label:
            continue
        out.append({"choiceId": chr(65 + i), "label": label, "text": label})
    return out


def _quote(line: str) -> str:
    """등장인물 대사는 따옴표로 감싼다(설명문과 대사를 눈으로 구분하기 위해)."""
    t = _s(line).strip('"“”')
    return f'"{t}"' if t else ""


# ── 1턴: 상황 짧게 + 즉시 대사 ──────────────────────────────────────────────

def generate_scene_setup(topic: str, stype: str, difficulty: str, choice_count: int,
                         agent_name: str, llm=None) -> SimSpeech:
    """진행/주질문자의 첫 발화. 설명문이 아니라 '장면 한 줄 + 실제 대사'다."""
    call = llm or _default_llm
    user = (
        f"[사용자가 연습하고 싶은 것]\n{topic}\n\n"
        f"{_TYPE_DIRECTIVE[stype]}\n{_DIFF_DIRECTIVE[difficulty]}\n\n"
        "너는 이 장면의 '주 질문자'다(교수/면접관/리뷰어 등 상황에 맞는 인물).\n"
        "상황 안내문을 길게 쓰지 마라. 지금 바로 그 인물로서 사용자에게 말을 건다.\n\n"
        "다음 JSON만 출력하라.\n"
        "- sceneBrief: 어디서 무슨 일이 벌어지는지 딱 한 문장(40자 내외).\n"
        "- userRole: 사용자가 맡는 역할(짧은 명사구).\n"
        "- goal: 사용자가 이 장면에서 해내야 할 것 한 줄.\n"
        "- speakerRole: 네가 맡은 인물의 호칭(예: 교수, 면접관, 팀장).\n"
        "- line: 그 인물이 사용자에게 직접 하는 실제 대사 2~4문장. 마지막은 질문이다. "
        "따옴표·지문·괄호 없이 대사 본문만 쓴다. '상황을 설명하겠습니다' 같은 진행 안내 문장 금지.\n"
        f"{_choice_spec(choice_count)}\n\n"
        '{"sceneBrief":"...","userRole":"...","goal":"...","speakerRole":"...","line":"...?","choices":[{"label":"..."}]}'
    )

    def build(o: Dict[str, Any]) -> SimSpeech:
        brief, role, goal = _s(o.get("sceneBrief")), _s(o.get("userRole")), _s(o.get("goal"))
        speaker, line = _s(o.get("speakerRole")) or "주 질문자", _s(o.get("line"))
        if brief and brief[-1] not in ".!?…":
            brief = brief + "."
        head = " ".join(p for p in [brief, f"당신은 {role}입니다." if role else ""] if p)
        text = "\n\n".join(p for p in [head, _quote(line)] if p)
        return SimSpeech(role=HOST, stage_type=SCENE_SETUP, stage_title="상황 시작", text=text,
                         agent_name=agent_name, choices=_parse_choices(o.get("choices")),
                         structured={"sceneBrief": brief, "userRole": role, "goal": goal,
                                     "speakerRole": speaker, "line": line})

    def validate(sp: SimSpeech) -> List[str]:
        from app.services.korean_text_match import is_question_like
        issues = validate_choices(sp.choices, choice_count)
        brief = _s(sp.structured.get("sceneBrief"))
        line = _s(sp.structured.get("line"))
        if len(brief) < 8:
            issues.append("scene_brief_missing")
        if len(brief) > 160:
            issues.append("scene_brief_too_long")
        if not _s(sp.structured.get("userRole")):
            issues.append("user_role_missing")
        if len(line) < MIN_LINE_CHARS:
            issues.append("line_too_short")
        if not is_question_like(line):
            issues.append("line_not_addressing_user")
        return issues

    return _generate(call, _SYSTEM, user, build, validate,
                     repair_hint=("sceneBrief 는 한 문장으로 줄이고, line 에는 그 인물이 사용자에게 하는 "
                                  "실제 대사(질문으로 끝남)를 써라."),
                     role=HOST)


def generate_opening_challenge(scene: Dict[str, Any], host_line: str, stype: str, difficulty: str,
                               agent_name: str, llm=None) -> SimSpeech:
    """1턴의 두 번째 인물(심화 검증자). 주 질문자의 대사를 이어받아 압박 질문을 던진다."""
    call = llm or _default_llm
    user = (
        f"{_scene_block(scene)}\n[주 질문자가 방금 한 말]\n{host_line}\n\n"
        f"{_TYPE_DIRECTIVE[stype]}\n{_DIFF_DIRECTIVE[difficulty]}\n\n"
        "너는 같은 자리에 있는 '심화 검증자'다(깐깐한 심사위원/시니어 개발자 등).\n"
        "주 질문자의 질문을 반복하지 말고, 그 질문이 건드리지 않은 비용·위험·트레이드오프를 파고든다.\n"
        "사용자는 아직 답하지 않았다. 사용자의 답을 네가 대신 만들어내지 마라.\n\n"
        "- speakerRole: 네가 맡은 인물의 호칭.\n"
        "- line: 사용자에게 직접 하는 실제 대사 2~4문장. 마지막은 질문이다.\n\n"
        '{"speakerRole":"...","line":"...?"}'
    )

    def build(o: Dict[str, Any]) -> SimSpeech:
        line = _s(o.get("line"))
        return SimSpeech(role=CHALLENGER, stage_type=CHALLENGE, stage_title="심화 검증",
                         text=_quote(line), agent_name=agent_name,
                         structured={"speakerRole": _s(o.get("speakerRole")) or "심화 검증자",
                                     "line": line})

    def validate(sp: SimSpeech) -> List[str]:
        from app.services.korean_text_match import is_question_like
        issues = []
        line = _s(sp.structured.get("line"))
        if len(line) < MIN_LINE_CHARS:
            issues.append("line_too_short")
        if not is_question_like(line):
            issues.append("challenge_question_missing")
        if host_line and is_repeat_of(line, host_line):
            issues.append("repeats_host_question")
        return issues

    return _generate(call, _SYSTEM, user, build, validate,
                     repair_hint="주 질문자와 다른 지점을 공격하는 실제 대사 2~4문장을 질문으로 끝내라.",
                     role=CHALLENGER)


def generate_answer_brief(scene: Dict[str, Any], host_line: str, challenge_line: str,
                          agent_name: str, llm=None) -> SimSpeech:
    """1턴의 세 번째 인물(답변 코치). 사용자가 답하기 전에 '무엇을 담아야 하는지'만 짚는다.

    사용자의 답을 대신 만들지 않는다. 답의 내용이 아니라 답의 구성 요소만 말한다.
    """
    call = llm or _default_llm
    user = (
        f"{_scene_block(scene)}\n[주 질문자의 질문]\n{host_line}\n[심화 검증자의 질문]\n{challenge_line}\n\n"
        "너는 사용자 편에 선 '답변 코치'다. 사용자는 지금부터 답해야 한다.\n"
        "★ 사용자의 답을 대신 작성하면 실패다. 정답 내용을 말하지 말고, 좋은 답이 갖춰야 할 "
        "구성 요소(무엇을 근거로, 어떤 순서로 말할지)만 짚어라.\n\n"
        "- focusPoints: 답변에 반드시 들어가야 할 요소 2~3개(내용이 아니라 요소).\n"
        "- line: 사용자에게 하는 짧은 코칭 대사 1~2문장.\n\n"
        '{"focusPoints":["...","..."],"line":"..."}'
    )

    def build(o: Dict[str, Any]) -> SimSpeech:
        points, line = _slist(o.get("focusPoints"), 3), _s(o.get("line"))
        body = _quote(line)
        if points:
            body = "\n".join([body, "답변에 담을 것"] + [f"- {p}" for p in points]).strip()
        return SimSpeech(role=COACH, stage_type=FEEDBACK, stage_title="답변 준비 코칭",
                         text=body, agent_name=agent_name,
                         structured={"focusPoints": points, "line": line})

    def validate(sp: SimSpeech) -> List[str]:
        issues = []
        if len(sp.structured.get("focusPoints") or []) < 2:
            issues.append("focus_points_missing")
        if len(_s(sp.structured.get("line"))) < 5:
            issues.append("coach_line_missing")
        return issues

    return _generate(call, _SYSTEM, user, build, validate,
                     repair_hint="focusPoints 2개 이상과 짧은 코칭 대사를 채워라. 정답 내용은 쓰지 마라.",
                     role=COACH)


# ── 2턴 이후 ────────────────────────────────────────────────────────────────

def _scene_block(session_data: Dict[str, Any]) -> str:
    return (f"[고정된 장면]\n{session_data.get('scenario', '')}\n"
            f"[사용자 역할] {session_data.get('userRole', '')}\n"
            f"[목표] {session_data.get('goal', '')}\n"
            f"[직전 발언/질문] {session_data.get('prompt', '')}\n")


def is_repeat_of(text: str, other: str, threshold: float = 0.8) -> bool:
    import difflib
    a, b = _s(text), _s(other)
    if not a or not b:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= threshold


def generate_follow_up(session_data: Dict[str, Any], user_answer: str, stype: str, difficulty: str,
                       choice_count: int, agent_name: str, llm=None) -> SimSpeech:
    """주 질문자의 꼬리질문. 사용자의 답 중 실제로 한 부분을 집어 이어간다."""
    call = llm or _default_llm
    user = (
        f"{_scene_block(session_data)}\n[사용자의 이번 답변/선택]\n{user_answer}\n\n"
        f"{_TYPE_DIRECTIVE[stype]}\n{_DIFF_DIRECTIVE[difficulty]}\n\n"
        "너는 이 장면의 '주 질문자'다. 같은 장면을 이어간다(장면을 처음부터 다시 설명하지 마라).\n"
        "- reaction: 사용자의 답을 들은 인물의 짧은 반응/장면 진행 1문장.\n"
        "- targetPart: 사용자의 답에서 네가 집어든 부분(사용자가 실제로 한 말).\n"
        "- line: 그 부분을 파고드는 꼬리질문 대사 2~4문장. 마지막은 질문이다.\n"
        f"{_choice_spec(choice_count)}\n\n"
        '{"reaction":"...","targetPart":"...","line":"...?","choices":[{"label":"..."}]}'
    )

    def build(o: Dict[str, Any]) -> SimSpeech:
        reaction, target, line = _s(o.get("reaction")), _s(o.get("targetPart")), _s(o.get("line"))
        text = "\n\n".join(p for p in [reaction, _quote(line)] if p)
        return SimSpeech(role=HOST, stage_type=NEXT_SCENE, stage_title="꼬리 질문", text=text,
                         agent_name=agent_name, choices=_parse_choices(o.get("choices")),
                         structured={"reaction": reaction, "targetPart": target, "line": line,
                                     "prompt": line})

    def validate(sp: SimSpeech) -> List[str]:
        from app.services.korean_text_match import is_question_like
        issues = validate_choices(sp.choices, choice_count)
        line = _s(sp.structured.get("line"))
        if len(line) < MIN_LINE_CHARS:
            issues.append("line_too_short")
        if not is_question_like(line):
            issues.append("prompt_missing")
        if not _s(sp.structured.get("targetPart")):
            issues.append("target_part_missing")
        if not references_user_answer(f"{sp.structured.get('targetPart', '')} {line}", user_answer):
            issues.append("not_referencing_user_answer")
        return issues

    return _generate(call, _SYSTEM, user, build, validate,
                     repair_hint=("사용자가 실제로 쓴 표현을 targetPart 로 집고, 그 부분을 파고드는 "
                                  "대사를 질문으로 끝내라."),
                     role=HOST)


def generate_challenge(session_data: Dict[str, Any], user_answer: str, stype: str, difficulty: str,
                       agent_name: str, llm=None, host_line: str = "") -> SimSpeech:
    """심화 검증자의 반박. 사용자의 답에서 기술적으로 약한 근거를 공격한다."""
    call = llm or _default_llm
    host_block = f"[주 질문자가 방금 한 꼬리질문]\n{host_line}\n" if host_line else ""
    user = (
        f"{_scene_block(session_data)}\n[사용자의 이번 답변/선택]\n{user_answer}\n{host_block}\n"
        f"{_TYPE_DIRECTIVE[stype]}\n{_DIFF_DIRECTIVE[difficulty]}\n\n"
        "너는 '심화 검증자'다. 주 질문자와 같은 질문을 반복하지 마라.\n"
        "사용자의 답에서 근거가 약한 지점 하나를 골라 실제 대사로 반박한다.\n"
        "사용자가 하지 않은 말을 지어내서 공격하지 마라.\n\n"
        "- targetPoint: 사용자의 답에서 실제로 짚을 지점.\n"
        "- line: 그 지점을 공격하는 대사 2~4문장. 마지막은 질문이다.\n\n"
        '{"targetPoint":"...","line":"...?"}'
    )

    def build(o: Dict[str, Any]) -> SimSpeech:
        target, line = _s(o.get("targetPoint")), _s(o.get("line"))
        return SimSpeech(role=CHALLENGER, stage_type=CHALLENGE, stage_title="심화 검증",
                         text=_quote(line), agent_name=agent_name,
                         structured={"targetPoint": target, "line": line,
                                     "challengeQuestion": line})

    def validate(sp: SimSpeech) -> List[str]:
        from app.services.korean_text_match import is_question_like
        issues = []
        line = _s(sp.structured.get("line"))
        if not is_question_like(line):
            issues.append("challenge_question_missing")
        if len(line) < MIN_LINE_CHARS:
            issues.append("line_too_short")
        if len(_s(sp.structured.get("targetPoint"))) < 5:
            issues.append("target_point_missing")
        if not references_user_answer(f"{sp.structured.get('targetPoint', '')} {line}", user_answer):
            issues.append("not_referencing_user_answer")
        if host_line and is_repeat_of(line, host_line):
            issues.append("repeats_host_question")
        return issues

    return _generate(call, _SYSTEM, user, build, validate,
                     repair_hint="사용자가 실제로 쓴 표현을 근거로 targetPoint 를 정하고 대사를 질문으로 끝내라.",
                     role=CHALLENGER)


def generate_feedback(session_data: Dict[str, Any], user_answer: str, difficulty: str,
                      agent_name: str, llm=None) -> SimSpeech:
    """답변 코치. 방금 답변의 강점/약점과 보완점을 짧게 피드백한다."""
    call = llm or _default_llm
    user = (
        f"{_scene_block(session_data)}\n[사용자의 이번 답변/선택]\n{user_answer}\n\n"
        f"{_DIFF_DIRECTIVE[difficulty]}\n\n"
        "너는 '답변 코치'다. 이번 답변만 평가한다. 사용자의 다음 답을 대신 쓰지 마라.\n"
        "- strengths: 잘한 점 1~2개(사용자가 실제로 말한 내용 기준).\n"
        "- weaknesses: 부족한 점 1~2개.\n"
        "- improvement: 다음 답변에서 바로 적용할 개선 방향 한 줄.\n\n"
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


# ── 턴 검증 ─────────────────────────────────────────────────────────────────

def validate_turn(speeches: List[SimSpeech], choice_count: int, first_turn: bool,
                  user_answer: str = "") -> List[str]:
    """3역할 전원 발화 / 대사 형태 / 선택지 수 / 사용자 응답 반영."""
    issues: List[str] = []
    roles = [sp.role for sp in speeches]
    for required in (HOST, CHALLENGER, COACH):
        if required not in roles:
            issues.append(f"missing_role_{required.lower()}")
    if not first_turn:
        for sp in speeches:
            if sp.role in (HOST, CHALLENGER) and not references_user_answer(sp.text, user_answer):
                issues.append(f"{sp.role.lower()}_not_referencing_user")
    host = next((s for s in speeches if s.role == HOST), None)
    if host is not None:
        issues.extend(validate_choices(host.choices, choice_count))
    return issues


def scene_choices(speeches: List[SimSpeech]) -> List[Dict[str, Any]]:
    """이번 턴에서 사용자가 고를 선택지(진행 역할이 낸 것)."""
    for sp in speeches:
        if sp.role == HOST:
            return sp.choices
    return []
