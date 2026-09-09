"""
소크라테스 모드 — 세션형 상태 머신.

정의: 정답을 주입하는 답변 모드가 아니라, 사용자가 스스로 답에 도달하도록
사고 과정을 설계하는 러닝 메이트 모드. 결과가 아니라 과정이 목적이다.

상태:
  ASSESS → ASK → EVALUATE → HINT/DEEPEN → VERIFY → SUMMARY

턴 계약:
  - 첫 턴은 '질문 1개'다. 정의/정답/결론을 먼저 주지 않는다.
  - 다음 턴부터는 사용자의 답을 평가(correct/partial/wrong/unknown)하고
    평가에 따라 다음 행동을 다르게 한다.
  - 연속 실패가 쌓이면 힌트를 단계적으로 강화하고, 마지막에는 부분 해법을 준 뒤
    사용자가 자기 말로 결론을 재구성하게 한다(VERIFY) → SUMMARY.

이 모듈은 LLM 호출을 주입 가능한 콜러블로 받아 테스트에서 격리한다.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 상태 ────────────────────────────────────────────────────────────────────
ASSESS, ASK, EVALUATE, HINT, DEEPEN, VERIFY, SUMMARY = (
    "ASSESS", "ASK", "EVALUATE", "HINT", "DEEPEN", "VERIFY", "SUMMARY")

# ── 평가 결과 ───────────────────────────────────────────────────────────────
CORRECT, PARTIAL, WRONG, UNKNOWN = "correct", "partial", "wrong", "unknown"

# ── 질문 강도 / 힌트 방식 (canonical) ───────────────────────────────────────
GENTLE, NORMAL, INTENSIVE = "gentle", "normal", "intensive"
HINT_CONCEPT, HINT_EXAMPLE, HINT_CHOICE, HINT_COUNTER, HINT_STEP = (
    "concept", "example", "choice", "counterexample", "step")

_INTENSITY_ALIASES = {
    "gentle": GENTLE, "low": GENTLE, "soft": GENTLE, "easy": GENTLE, "부드럽게": GENTLE, "약하게": GENTLE, "낮음": GENTLE,
    "normal": NORMAL, "medium": NORMAL, "보통": NORMAL, "중간": NORMAL,
    "intensive": INTENSIVE, "high": INTENSIVE, "hard": INTENSIVE, "strong": INTENSIVE, "강하게": INTENSIVE, "높음": INTENSIVE,
}
_HINT_ALIASES = {
    "concept": HINT_CONCEPT, "conceptual": HINT_CONCEPT, "minimal": HINT_CONCEPT, "개념": HINT_CONCEPT,
    "example": HINT_EXAMPLE, "예시": HINT_EXAMPLE,
    "choice": HINT_CHOICE, "options": HINT_CHOICE, "선택지": HINT_CHOICE,
    "counterexample": HINT_COUNTER, "반례": HINT_COUNTER,
    "step": HINT_STEP, "step_by_step": HINT_STEP, "단계": HINT_STEP, "단계별": HINT_STEP,
}

MAX_STEP_RETRIES = int(os.getenv("SOCRATIC_MAX_STEP_RETRIES", "2"))
MAX_TURNS = int(os.getenv("SOCRATIC_MAX_TURNS", "8"))
FAIL_ESCALATION = int(os.getenv("SOCRATIC_FAIL_ESCALATION", "3"))
CONTENT_MAX_TOKENS = int(os.getenv("SOCRATIC_MAX_TOKENS", "600"))


def normalize_intensity(value: Any) -> str:
    return _INTENSITY_ALIASES.get(str(value or "").strip().lower(), NORMAL)


def normalize_hint_style(value: Any) -> str:
    return _HINT_ALIASES.get(str(value or "").strip().lower(), HINT_CONCEPT)


def resolve_config(request: Any) -> Tuple[str, str]:
    """socraticConfig(기존 DTO) → (질문 강도, 힌트 방식). 새 중복 필드를 만들지 않는다."""
    cfg = getattr(request, "socraticConfig", None)
    if isinstance(cfg, dict):
        intensity = cfg.get("questionIntensity") or cfg.get("question_intensity")
        hint = cfg.get("hintPolicy") or cfg.get("hint_policy")
    else:
        intensity = getattr(cfg, "questionIntensity", None)
        hint = getattr(cfg, "hintPolicy", None)
    return normalize_intensity(intensity), normalize_hint_style(hint)


# ── 데이터 ──────────────────────────────────────────────────────────────────

@dataclass
class SocraticTurn:
    state: str
    text: str
    question: str = ""
    hint: str = ""
    assessment: str = ""
    hint_level: int = 0
    regenerated: int = 0
    issues: List[str] = field(default_factory=list)
    structured: Dict[str, Any] = field(default_factory=dict)


# ── LLM 어댑터 ──────────────────────────────────────────────────────────────

def _default_llm(system_prompt: str, user_prompt: str, *, max_tokens: int, temperature: float) -> str:
    from app.services.ollama_client import ask_ollama
    return ask_ollama(system_prompt=system_prompt, user_prompt=user_prompt,
                      max_tokens=max_tokens, temperature=temperature, think=False)


def _parse(raw: str) -> Dict[str, Any]:
    from app.services.debate_engine import parse_json_object
    return parse_json_object(raw)


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


# ── 검증기 ──────────────────────────────────────────────────────────────────


# 첫 턴에 나오면 안 되는 '강의/정답' 신호(도메인 용어가 아니라 형식 신호만 본다).
_LECTURE_MARKERS = ("정리하면", "핵심 개념", "핵심개념", "정의하면", "정답은", "답은 ", "결론적으로",
                    "요약하면", "다음과 같습니다", "즉,")


def _tokens(text: str) -> set:
    from app.services.korean_text_match import tokens
    return tokens(text)


def leaks_answer(rendered: str, expected_idea: str, known_text: str = "",
                 keywords: Optional[List[str]] = None, threshold: float = 0.6) -> bool:
    """모델이 스스로 적어둔 '기대 정답'이 사용자에게 그대로 드러났는가.

    주제/사용자가 이미 쓴 어휘는 제외한다. 질문은 원래 주제 어휘를 공유하므로
    그대로 비교하면 정상 질문까지 정답 노출로 오판한다(첫 턴이 폴백 질문으로 무너짐).
    판정은 '정답에만 있는 어휘'가 노출됐는지로 한다.
    """
    from app.services.korean_text_match import covered_ratio, overlap_count, subtract, tokens

    shown = _tokens(rendered)
    known = _tokens(known_text)

    # (1) 모델이 스스로 지목한 '정답을 결정짓는 표현'이 있으면 그것만 본다(가장 정확).
    #     단, 사용자가 이미 쓴 말은 노출로 보지 않는다(되돌려 말하기 허용).
    if keywords:
        for kw in keywords:
            kw_tokens = subtract(tokens(kw), known)
            if not kw_tokens:
                continue
            # 잔여 토큰이 1개뿐이고 짧으면(일반어) 노출 근거로 쓰지 않는다.
            if len(kw_tokens) == 1 and len(next(iter(kw_tokens))) < 3:
                continue
            if overlap_count(kw_tokens, shown) == len(kw_tokens):
                return True
        return False

    # (2) 키워드가 없으면 정답에만 있는 어휘 비율로 판단한다(보수적 폴백).
    exp = subtract(_tokens(expected_idea), known)
    if len(exp) < 2:
        return False
    return covered_ratio(exp, shown) >= threshold


def count_questions(text: str) -> int:
    return len(re.findall(r"\?", text or ""))


def validate_first_turn(turn: SocraticTurn, expected_idea: str, topic: str = "",
                        keywords: Optional[List[str]] = None) -> List[str]:
    issues: List[str] = []
    if not turn.question or not turn.question.strip().endswith("?"):
        issues.append("question_missing")
    if count_questions(turn.text) != 1:
        issues.append("not_single_question")
    if leaks_answer(turn.text, expected_idea, topic, keywords):
        issues.append("answer_leaked")
    for marker in _LECTURE_MARKERS:
        if marker in turn.text:
            issues.append("lecture_style")
            break
    if len(turn.text) > int(os.getenv("SOCRATIC_FIRST_TURN_MAX_CHARS", "400")):
        issues.append("too_long")
    return issues


def validate_followup(turn: SocraticTurn) -> List[str]:
    issues: List[str] = []
    if turn.state != SUMMARY:
        if count_questions(turn.text) != 1:
            issues.append("not_single_question")
        if not turn.question:
            issues.append("question_missing")
    if turn.state in (HINT, DEEPEN, ASK, VERIFY) and len(turn.text) > 700:
        issues.append("too_long")
    return issues


# ── 생성 ────────────────────────────────────────────────────────────────────

_SYSTEM = (
    "너는 StudyBridge 소크라테스 러닝메이트다. 정답을 알려주는 강사가 아니다.\n"
    "- 목적은 사용자가 스스로 답에 도달하게 하는 것이다. 결과가 아니라 사고 과정이 중요하다.\n"
    "- 한 턴에 질문은 정확히 1개만 한다.\n"
    "- 정답·정의·결론을 먼저 말하지 않는다. 개념 요약/강의체 서술 금지.\n"
    "- 사용자를 평가절하하지 않는다. 짧고 구체적으로 묻는다.\n"
    "- 출력은 지시된 JSON 하나만. 설명·머리말·코드펜스 금지. 값은 한국어."
)


def _generate(llm, system: str, user: str, build, validate, repair_hint: str,
              max_retries: int = MAX_STEP_RETRIES, temperature: float = 0.4):
    last, last_issues = None, ["empty_response"]
    for attempt in range(max_retries + 1):
        prompt = user if attempt == 0 else (
            f"{user}\n\n[재작성 지시 — 직전 출력이 계약을 어겼다: {', '.join(last_issues)}]\n{repair_hint}")
        raw = llm(system, prompt, max_tokens=CONTENT_MAX_TOKENS, temperature=temperature + 0.05 * attempt)
        obj = build(_parse(raw))
        issues = validate(obj)
        if not issues:
            obj.regenerated = attempt
            return obj, []
        last, last_issues = obj, issues
        logger.warning("[SOCRATIC] 턴 검증 실패(attempt=%d) issues=%s", attempt + 1, issues)
    if last is not None:
        last.regenerated = max_retries
        last.issues = last_issues
    return last, last_issues


_MULTI_Q = re.compile(r"\?{2,}")
# 마지막 수단으로 쓰는 content-free 되묻기(도메인 용어를 넣지 않는다).
_FALLBACK_QUESTION = "지금 말한 근거를 한 단계만 더 밀어보면, 어떤 결론이 남을까?"


def normalize_text(text: str) -> str:
    return _MULTI_Q.sub("?", (text or "").strip())


_ASSERTIVE_TAIL = re.compile(
    r"(입니다|습니다|됩니다|합니다|이다|한다|된다|이에요|예요|해요|야|지|다)\s*[.!]?\s*$")


def is_assertive(text: str) -> bool:
    """'~이다/~됩니다'처럼 사실을 단정하는 서술문인가(힌트가 정답 문장이 되는 것을 막는다)."""
    t = (text or "").strip()
    return bool(t) and bool(_ASSERTIVE_TAIL.search(t))


def hint_states_the_answer(hint: str, expected_idea: str, known_text: str = "") -> bool:
    """힌트가 '정답을 단정하는 서술문'인지. 유도형 힌트는 통과시킨다."""
    from app.services.korean_text_match import overlap_count, subtract
    if not hint or not is_assertive(hint):
        return False
    novel = subtract(_tokens(expected_idea), _tokens(known_text))
    if not novel:
        return False
    return overlap_count(novel, _tokens(hint)) >= 1


def first_question(text: str) -> str:
    """질문이 여러 개면 첫 번째 질문만 남긴다(한 턴 한 질문 계약)."""
    t = normalize_text(text)
    if "?" not in t:
        return t
    head = t.split("?", 1)[0].strip()
    return f"{head}?" if head else ""


# 마지막 수단으로 쓰는 되묻기 — 주제(사용자 원문)만 인용하고 정답 어휘는 쓰지 않는다.
# 같은 문장이 반복되지 않도록 이미 쓴 것을 피해 고른다.
_TOPIC_PROBES = (
    "'{t}' 이 질문에서, 지금 확실하다고 말할 수 있는 건 무엇이고 아직 모르는 건 무엇일까?",
    "'{t}' 를 네 말로 다시 설명한다면 어디부터 시작하겠어?",
    "'{t}' 에서 결과를 결정하는 조건은 무엇이라고 생각해?",
)


def topic_anchored_question(topic: str, used: Optional[List[str]] = None) -> str:
    t = (topic or "").strip().rstrip("?")
    if not t:
        return _FALLBACK_QUESTION
    from app.services.korean_text_match import repeats_any
    candidates = [tmpl.format(t=t[:60]) for tmpl in _TOPIC_PROBES]
    for cand in candidates:
        if not used or not repeats_any(cand, used, 0.9):
            return cand
    return candidates[0]


def repair_turn(turn: SocraticTurn, expected_idea: str, known_text: str = "",
                keywords: Optional[List[str]] = None, topic: str = "",
                used_questions: Optional[List[str]] = None) -> SocraticTurn:
    """재생성 상한을 넘겨도 사용자에게 계약 위반 텍스트를 내보내지 않는다.

    모델을 더 부르지 않고 구조만 고친다(정답 노출 조각 제거 + 질문 1개로 축소).
    """
    ack = turn.structured.get("acknowledge", "")
    hint = turn.hint
    question = first_question(turn.question)

    if hint and (leaks_answer(hint, expected_idea, known_text, keywords) or "?" in hint):
        hint = ""
    if ack and leaks_answer(ack, expected_idea, known_text, keywords):
        ack = ""
    if question and leaks_answer(question, expected_idea, known_text, keywords):
        question = topic_anchored_question(topic, used_questions) if topic else _FALLBACK_QUESTION
    if not question.endswith("?"):
        question = topic_anchored_question(topic, used_questions) if topic else _FALLBACK_QUESTION
    # 계약(질문 1개·정답 미노출)을 지켜도 '이미 한 질문'이면 사용자에겐 턴 낭비다.
    # 모델이 직전 질문을 그대로 되풀이한 경우 여기서 다른 질문으로 바꾼다.
    if question and used_questions:
        from app.services.korean_text_match import repeats_any
        if repeats_any(question, used_questions, 0.9):
            question = topic_anchored_question(topic, used_questions) if topic else _FALLBACK_QUESTION

    turn.hint = hint
    turn.question = question
    turn.structured["acknowledge"] = ack
    turn.structured["repaired"] = True
    turn.text = normalize_text("\n\n".join(p for p in (ack, hint, question) if p))
    return turn


def _intensity_directive(intensity: str, hint_style: str) -> str:
    if intensity == GENTLE:
        body = ("- 질문 강도: 부드럽게. 큰 질문을 작은 단계로 쪼개고, 한 걸음만 앞서 묻는다.\n"
                "- 막힐 것 같으면 짧은 힌트를 함께 준다(정답은 절대 말하지 않는다).")
    elif intensity == INTENSIVE:
        body = ("- 질문 강도: 강하게. 힌트를 최소화하고 '왜 그런가/근거가 무엇인가/반례는 없는가'를 파고든다.\n"
                "- 사용자가 근거 없이 단정하면 그 근거를 되묻는다.")
    else:
        body = "- 질문 강도: 보통. 한 번에 한 걸음씩, 필요한 최소한의 힌트만 준다."
    styles = {
        HINT_CONCEPT: "개념의 핵심 성질을 짚는 한 줄 힌트",
        HINT_EXAMPLE: "구체적인 예시 상황 하나로 주는 힌트",
        HINT_CHOICE: "두세 개의 선택지를 제시해 고르게 하는 힌트",
        HINT_COUNTER: "반례를 던져 스스로 모순을 발견하게 하는 힌트",
        HINT_STEP: "다음 한 단계만 짚어주는 단계형 힌트",
    }
    return body + f"\n- 힌트가 필요할 때의 방식: {styles.get(hint_style, styles[HINT_CONCEPT])}."


def generate_first_turn(topic: str, intensity: str, hint_style: str, agent_name: str,
                        llm=None) -> Tuple[SocraticTurn, List[str]]:
    """ASSESS + ASK — 사용자의 현재 이해를 확인하거나 핵심 추론 지점을 찌르는 질문 1개."""
    call = llm or _default_llm
    user = (
        f"[사용자가 지금 배우려는 주제]\n{topic}\n\n"
        f"{_intensity_directive(intensity, hint_style)}\n\n"
        "첫 턴이다. 다음 JSON만 출력하라.\n"
        "- expectedIdea: 이 주제에서 사용자가 스스로 도달해야 할 핵심 결론(내부 기록용, 사용자에게 보여주지 않는다).\n"
        "- answerKeywords: 그 결론을 결정적으로 드러내는 표현 1~3개(이 표현이 질문에 들어가면 정답을 준 것이다).\n"
        "- probe: 사용자의 현재 이해를 확인하는 짧은 한 문장(정답·정의 금지, 평서문, 생략 가능하면 빈 문자열).\n"
        "- question: 사용자가 스스로 추론하게 만드는 질문 정확히 1개(물음표로 끝난다).\n"
        "★ probe 와 question 어디에도 expectedIdea 의 내용을 쓰지 마라. 쓰면 실패다.\n\n"
        '{"expectedIdea":"...","answerKeywords":["..."],"probe":"...","question":"...?"}'
    )

    def build(o: Dict[str, Any]) -> SocraticTurn:
        probe, question = _s(o.get("probe")), _s(o.get("question"))
        # probe 는 '현재 이해 확인' 평서문이다. 질문이 섞이면 한 턴 한 질문 계약이 깨지므로 버린다.
        if "?" in probe:
            probe = ""
        question = first_question(question)
        text = (probe + "\n\n" + question).strip() if probe else question
        keywords = [k for k in (o.get("answerKeywords") or []) if _s(k)][:3]
        return SocraticTurn(state=ASK, text=text, question=question,
                            structured={"expectedIdea": _s(o.get("expectedIdea")),
                                        "answerKeywords": [_s(k) for k in keywords], "probe": probe})

    def validate(t: SocraticTurn) -> List[str]:
        return validate_first_turn(t, t.structured.get("expectedIdea", ""), topic,
                                   t.structured.get("answerKeywords"))

    turn, issues = _generate(
        call, _SYSTEM, user, build, validate,
        repair_hint=("질문 1개만 남기고, 정답/정의/요약 문장을 모두 지워라. "
                     "expectedIdea 의 내용이 사용자에게 보이면 실패다."))
    if turn is not None and issues:
        expected = turn.structured.get("expectedIdea", "")
        probe = turn.structured.get("probe", "")
        keywords = turn.structured.get("answerKeywords")
        if probe and (leaks_answer(probe, expected, topic, keywords) or "?" in probe
                      or any(m in probe for m in _LECTURE_MARKERS)):
            turn.structured["probe"] = ""
            probe = ""
        turn.question = first_question(turn.question)
        if not turn.question.endswith("?") or leaks_answer(turn.question, expected, topic, keywords):
            turn.question = topic_anchored_question(topic)
        turn.text = normalize_text("\n\n".join(p for p in (probe, turn.question) if p))
        turn.structured["repaired"] = True
        issues = validate_first_turn(turn, expected, topic, keywords)
    return turn, issues


def _evaluation_directive(assessment: str, intensity: str, hint_style: str, hint_level: int) -> str:
    if assessment == CORRECT:
        return ("사용자의 답이 정확하다. 정답을 반복해 설명하지 말고, 더 깊은 '왜' 또는 '적용' 질문 1개를 던져라. "
                "힌트는 주지 않는다.")
    if assessment == PARTIAL:
        return ("사용자의 답이 부분적으로 맞다. 맞은 부분을 한 구절로 인정하고, '빠진 한 요소'만 묻는 보완 질문 1개를 던져라. "
                "빠진 요소가 무엇인지 직접 말하지 마라.")
    if assessment == WRONG:
        base = ("사용자의 답이 틀렸다. 정답을 공개하지 말고, 스스로 오류를 발견하게 만드는 '가장 작은 교정 힌트' 1개와 "
                "다시 생각해보게 하는 질문 1개를 줘라.")
        return base + (" 힌트는 최소한으로." if intensity == INTENSIVE else "")
    # UNKNOWN — 힌트 사다리
    ladder = {
        0: "개념의 핵심 성질을 짚는 힌트",
        1: "구체적인 예시 또는 선택지를 주는 힌트",
        2: "부분 스캐폴딩(문제를 반으로 쪼개 앞부분만 같이 정리)",
    }
    step = ladder.get(min(hint_level, 2), ladder[2])
    return (f"사용자가 모른다고 했다. 정답을 주지 말고 {step}를 준 뒤, 한 걸음만 앞선 질문 1개를 던져라.")


def generate_followup(topic: str, user_answer: str, transcript: List[Dict[str, str]],
                      intensity: str, hint_style: str, hint_level: int, consecutive_fail: int,
                      expected_idea: str, llm=None,
                      answer_keywords: Optional[List[str]] = None,
                      previous_questions: Optional[List[str]] = None) -> Tuple[SocraticTurn, List[str]]:
    """EVALUATE → (DEEPEN | ASK | HINT | VERIFY)."""
    call = llm or _default_llm
    history = "\n".join(f"- {t['role']}: {t['text'][:300]}" for t in transcript[-6:])
    escalate = consecutive_fail + 1 >= FAIL_ESCALATION
    escalate_note = (
        "\n★ 사용자가 연속으로 막혀 있다. 이번에는 부분 해법(핵심 절반)을 먼저 보여준 뒤, "
        "'네 말로 다시 정리해볼래?'처럼 사용자가 스스로 결론을 재구성하게 하는 질문 1개로 끝내라.\n"
        if escalate else "")
    user = (
        f"[주제]\n{topic}\n\n[지금까지의 대화]\n{history}\n\n"
        f"[사용자의 이번 답변]\n{user_answer}\n\n"
        f"[사용자가 도달해야 할 핵심(내부용, 그대로 노출 금지)]\n{expected_idea}\n\n"
        f"{_intensity_directive(intensity, hint_style)}\n{escalate_note}\n"
        "다음 JSON만 출력하라.\n"
        "- assessment: correct | partial | wrong | unknown 중 하나(사용자 답변에 대한 판정).\n"
        "- acknowledge: 사용자의 답에서 인정하거나 짚어줄 부분 한 문장(평가 문구, 정답 공개 금지).\n"
        "- hint: 필요할 때만 주는 한 줄 힌트(불필요하면 빈 문자열). 정답 문장 자체는 금지.\n"
        "- question: 다음 사고를 끌어내는 질문 정확히 1개(물음표로 끝난다).\n\n"
        '{"assessment":"...","acknowledge":"...","hint":"...","question":"...?"}'
    )

    def build(o: Dict[str, Any]) -> SocraticTurn:
        assessment = _s(o.get("assessment")).lower()
        if assessment not in (CORRECT, PARTIAL, WRONG, UNKNOWN):
            assessment = UNKNOWN
        ack, hint, question = _s(o.get("acknowledge")), _s(o.get("hint")), _s(o.get("question"))
        # 강도 정책: intensive 는 첫 실패까지 힌트를 주지 않는다(정책이 실제 출력에 영향).
        if intensity == INTENSIVE and consecutive_fail == 0 and assessment in (WRONG, UNKNOWN):
            hint = ""
        # ★ 힌트가 정답을 단정하는 서술문이면 버린다(질문 끝에 정답을 붙이는 동작 차단).
        if hint and not escalate and hint_states_the_answer(hint, expected_idea, f"{topic}\n{user_answer}"):
            hint = ""
        if intensity == GENTLE and assessment in (WRONG, UNKNOWN) and not hint:
            hint = "지금 아는 것과 모르는 것을 한 줄씩 나눠서 적어보자."
        parts = [p for p in (ack, hint, question) if p]
        state = {CORRECT: DEEPEN, PARTIAL: ASK, WRONG: HINT, UNKNOWN: HINT}[assessment]
        if escalate:
            state = VERIFY
        return SocraticTurn(state=state, text="\n\n".join(parts), question=question, hint=hint,
                            assessment=assessment, hint_level=hint_level,
                            structured={"acknowledge": ack, "assessment": assessment})

    def validate(t: SocraticTurn) -> List[str]:
        issues = validate_followup(t)
        # 정답 노출은 평가 결과와 무관하게 금지한다(질문 끝에 정답을 붙이는 동작 차단).
        # 단, 연속 실패로 부분 해법을 주기로 한 턴(escalate)은 예외다.
        known = f"{topic}\n{user_answer}"
        if not escalate and leaks_answer(t.text, expected_idea, known, answer_keywords):
            issues.append("answer_leaked")
        # 같은 질문을 다시 던지며 턴만 소모하지 않는다.
        from app.services.korean_text_match import repeats_any
        if previous_questions and t.question and repeats_any(t.question, previous_questions, 0.9):
            issues.append("repeats_previous_question")
        return issues

    turn, issues = _generate(
        call, _SYSTEM, user, build, validate,
        repair_hint=("질문은 정확히 1개, 정답 문장은 쓰지 마라. 직전 턴과 같은 질문을 반복하지 말고 "
                     "한 걸음 더 나아간 질문을 해라. acknowledge/hint/question 을 채워라."))
    if turn is not None and issues and not escalate:
        # 재생성 상한을 넘겼다 → 모델을 더 부르지 않고 구조만 고쳐서 계약을 지킨다.
        turn = repair_turn(turn, expected_idea, known_text=f"{topic}\n{user_answer}",
                           keywords=answer_keywords, topic=topic,
                           used_questions=previous_questions)
        issues = validate_followup(turn)
    return turn, issues


def generate_summary(topic: str, transcript: List[Dict[str, str]], expected_idea: str,
                     llm=None) -> Tuple[SocraticTurn, List[str]]:
    """SUMMARY — 사용자가 도출한 답을 검증하고 오개념만 교정한다."""
    call = llm or _default_llm
    history = "\n".join(f"- {t['role']}: {t['text'][:300]}" for t in transcript[-10:])
    user = (
        f"[주제]\n{topic}\n\n[대화 기록]\n{history}\n\n"
        f"[핵심(내부용)]\n{expected_idea}\n\n"
        "마무리 턴이다. 새 강의를 하지 마라. 다음 JSON만 출력하라.\n"
        "- userConclusion: 사용자가 대화에서 실제로 도달한 결론을 사용자의 말로 요약(1~2문장).\n"
        "- verified: 그 결론이 맞는지 true/false.\n"
        "- correction: 남아 있는 오개념만 짧게 교정(없으면 빈 문자열).\n"
        "- nextStep: 다음에 스스로 확인해볼 것 한 줄.\n\n"
        '{"userConclusion":"...","verified":true,"correction":"...","nextStep":"..."}'
    )

    def build(o: Dict[str, Any]) -> SocraticTurn:
        parts = [f"네가 정리한 결론: {_s(o.get('userConclusion'))}"]
        if _s(o.get("correction")):
            parts.append(f"한 가지만 바로잡으면: {_s(o.get('correction'))}")
        if _s(o.get("nextStep")):
            parts.append(f"다음 확인 포인트: {_s(o.get('nextStep'))}")
        return SocraticTurn(state=SUMMARY, text="\n\n".join(parts),
                            structured={"userConclusion": _s(o.get("userConclusion")),
                                        "verified": bool(o.get("verified")),
                                        "correction": _s(o.get("correction")),
                                        "nextStep": _s(o.get("nextStep"))})

    def validate(t: SocraticTurn) -> List[str]:
        return [] if _s(t.structured.get("userConclusion")) else ["conclusion_missing"]

    return _generate(call, _SYSTEM, user, build, validate,
                     repair_hint="userConclusion 을 반드시 채워라. 새 강의를 하지 마라.")


# ── 상태 전이 ───────────────────────────────────────────────────────────────

def next_state_after(turn: SocraticTurn, turn_index: int) -> str:
    """다음 턴이 시작할 상태."""
    if turn.state == SUMMARY:
        return SUMMARY
    if turn_index + 1 >= MAX_TURNS:
        return VERIFY
    return turn.state


def should_summarize(session_data: Dict[str, Any], turn_index: int, last_assessment: str) -> bool:
    """DEEPEN 을 통과했거나 턴 상한에 도달하면 마무리한다."""
    if turn_index + 1 >= MAX_TURNS:
        return True
    if session_data.get("state") == VERIFY and last_assessment in (CORRECT, PARTIAL):
        return True
    if session_data.get("deepen_passed"):
        return True
    return False
