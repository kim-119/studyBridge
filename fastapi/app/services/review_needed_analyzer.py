"""
오답노트 '복습 필요' 분석 엔진.

StudyBridge 현재 구조 전제(존재하지 않는 데이터를 가정하지 않는다):
  - 힌트 기능이 없다. 힌트 횟수/강도/단계 같은 필드를 만들지 않는다.
  - 다시풀기는 문제당 정확히 1회다. 최초 풀이 → (오답/미응답) → 다시풀기 1회 → 종료.
  - 따라서 판단 입력은 '최초 결과'와 '재풀이 1회 결과' 두 개뿐이다.

케이스:
  A 최초 오답  + 재풀이 오답   → 개념 이해 부족
  B 최초 미응답 + 재풀이 오답   → 개념 회상/접근 자체가 부족
  C 최초 오답  + 재풀이 정답   → 기계적으로 '복습 불필요' 처리하지 않는다(회복 여부를 함께 판단)
  D 최초 정답               → 복습 대상 아님(불필요한 AI 호출을 만들지 않는다)
  N 재풀이 기록 없음         → 최초 결과만으로 판단

이 모듈은 텍스트 생성만 담당한다. 대화 기억/이전 문제 컨텍스트는 절대 쓰지 않는다.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 케이스 코드
FIRST_CORRECT = "FIRST_CORRECT"
WRONG_THEN_WRONG = "WRONG_THEN_WRONG"
UNANSWERED_THEN_WRONG = "UNANSWERED_THEN_WRONG"
WRONG_THEN_CORRECT = "WRONG_THEN_CORRECT"
UNANSWERED_THEN_CORRECT = "UNANSWERED_THEN_CORRECT"
WRONG_NO_RETRY = "WRONG_NO_RETRY"
UNANSWERED_NO_RETRY = "UNANSWERED_NO_RETRY"

RECOVERED_CASES = {WRONG_THEN_CORRECT, UNANSWERED_THEN_CORRECT}
UNRESOLVED_CASES = {WRONG_THEN_WRONG, UNANSWERED_THEN_WRONG, WRONG_NO_RETRY, UNANSWERED_NO_RETRY}

CASE_LABEL = {
    FIRST_CORRECT: "최초 풀이에서 정답",
    WRONG_THEN_WRONG: "최초 오답, 다시풀기에서도 오답",
    UNANSWERED_THEN_WRONG: "최초 미응답, 다시풀기에서 오답",
    WRONG_THEN_CORRECT: "최초 오답, 다시풀기에서 정답",
    UNANSWERED_THEN_CORRECT: "최초 미응답, 다시풀기에서 정답",
    WRONG_NO_RETRY: "최초 오답, 다시풀기 기록 없음",
    UNANSWERED_NO_RETRY: "최초 미응답, 다시풀기 기록 없음",
}

# 미응답 표기(프론트/Spring 이 실제로 넣는 값). 값이 비어 있는 것도 미응답으로 본다.
_UNANSWERED_MARKS = ("미응답", "무응답", "미제출", "unanswered", "no_answer", "none", "-")

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+|[가-힣]{2,}")
_STOPWORDS = {
    "개념", "문제", "보기", "정답", "오답", "해설", "복습", "필요", "내용", "다음",
    "경우", "사용", "처리", "설명", "이유", "방법", "과목", "자료", "노트",
    "무엇", "어떤", "위해", "있다", "한다", "된다", "이다", "그리고", "하지만",
}


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def is_unanswered(value: Any) -> bool:
    text = _s(value)
    if not text:
        return True
    low = text.lower()
    return any(mark in low for mark in _UNANSWERED_MARKS)


def _matches_answer(answer: Any, correct: Any, choices: Optional[List[Any]] = None) -> Optional[bool]:
    """정오를 명시하지 않은 레거시 payload 를 위한 보조 판정. 판단 불가면 None."""
    a, c = _s(answer), _s(correct)
    if not a or not c:
        return None
    if a == c:
        return True
    # 보기 인덱스(0-base/1-base)로 저장된 경우
    if choices:
        for idx, choice in enumerate(choices):
            if _s(choice) == c and (a == str(idx) or a == str(idx + 1)):
                return True
            if _s(choice) == a and (c == str(idx) or c == str(idx + 1)):
                return True
    return False


@dataclass
class ReviewQuestion:
    """복습 판단에 쓰는 문제 1개. 존재하는 필드만 담는다."""
    question: str = ""
    choices: List[str] = field(default_factory=list)
    correct_answer: str = ""
    explanation: str = ""
    concept: str = ""
    first_answer: str = ""
    first_correct: Optional[bool] = None
    retry_answer: str = ""
    retry_correct: Optional[bool] = None
    has_retry: bool = False

    @property
    def first_unanswered(self) -> bool:
        return is_unanswered(self.first_answer)

    @property
    def retry_unanswered(self) -> bool:
        return self.has_retry and is_unanswered(self.retry_answer)

    def case(self) -> str:
        first_ok = self.first_correct
        if first_ok is None:
            first_ok = _matches_answer(self.first_answer, self.correct_answer, self.choices)
        if first_ok is True:
            return FIRST_CORRECT

        started_unanswered = self.first_unanswered
        if not self.has_retry:
            return UNANSWERED_NO_RETRY if started_unanswered else WRONG_NO_RETRY

        retry_ok = self.retry_correct
        if retry_ok is None:
            retry_ok = _matches_answer(self.retry_answer, self.correct_answer, self.choices)
        if retry_ok is True:
            return UNANSWERED_THEN_CORRECT if started_unanswered else WRONG_THEN_CORRECT
        return UNANSWERED_THEN_WRONG if started_unanswered else WRONG_THEN_WRONG


def parse_questions(payload: Dict[str, Any]) -> List[ReviewQuestion]:
    """Spring/프론트가 보내는 형태를 모두 받아 ReviewQuestion 목록으로 정규화한다.

    - questions[] (권장: 최초 + 재풀이 결과 포함)
    - 단일 문제 flat payload (기존 계약, 재풀이 정보 없음)
    """
    raw_items = payload.get("questions") or payload.get("items") or payload.get("retryQuestions")
    if not isinstance(raw_items, list) or not raw_items:
        flat = {k: v for k, v in payload.items()}
        raw_items = [flat] if _s(flat.get("question")) else []

    out: List[ReviewQuestion] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        choices = raw.get("choices") or raw.get("options") or []
        if isinstance(choices, str):
            choices = [c.strip() for c in choices.split(",") if c.strip()]
        retry = raw.get("retry") if isinstance(raw.get("retry"), dict) else {}

        retry_answer = _first_present(raw, "retryAnswer", "retry_answer") or _s(retry.get("answer"))
        retry_correct = _first_bool(raw, "retryCorrect", "retry_correct", "retryIsCorrect")
        if retry_correct is None:
            retry_correct = _to_bool(retry.get("correct"))
        has_retry = bool(retry_answer) or retry_correct is not None or bool(retry)

        out.append(ReviewQuestion(
            question=_s(raw.get("question") or raw.get("prompt")),
            choices=[_s(c) for c in choices if _s(c)],
            correct_answer=_first_present(raw, "correctAnswer", "correct_answer", "answer"),
            explanation=_first_present(raw, "explanation", "rationale"),
            concept=_first_present(raw, "concept", "conceptName", "keyConcept"),
            first_answer=_first_present(raw, "firstAnswer", "first_answer", "userAnswer", "user_answer"),
            first_correct=_first_bool(raw, "firstCorrect", "first_correct", "isCorrect", "correct"),
            retry_answer=retry_answer,
            retry_correct=retry_correct,
            has_retry=has_retry,
        ))
    return out


def _first_present(raw: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        if _s(raw.get(k)):
            return _s(raw.get(k))
    return ""


def _to_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    text = _s(value).lower()
    if text in ("true", "1", "y", "yes", "correct", "정답", "o"):
        return True
    if text in ("false", "0", "n", "no", "wrong", "오답", "x"):
        return False
    return None


def _first_bool(raw: Dict[str, Any], *keys: str) -> Optional[bool]:
    for k in keys:
        if k in raw:
            b = _to_bool(raw.get(k))
            if b is not None:
                return b
    return None


# ── 개념 추출 ───────────────────────────────────────────────────────────────

def extract_concept(questions: List[ReviewQuestion], subject: str = "") -> str:
    """명시 concept 우선. 없으면 현재 문제/해설에서만 뽑는다(다른 문제 오염 금지)."""
    for q in questions:
        if q.concept:
            return q.concept[:40]
    subject_tokens = set(_TOKEN_RE.findall(subject or ""))
    freq: Dict[str, int] = {}
    for q in questions:
        for tok in _TOKEN_RE.findall(f"{q.explanation} {q.question}"):
            if tok in _STOPWORDS or tok in subject_tokens or len(tok) < 2:
                continue
            freq[tok] = freq.get(tok, 0) + 1
    if freq:
        ranked = sorted(freq.items(), key=lambda kv: (-kv[1], -len(kv[0])))
        return " ".join(w for w, _ in ranked[:2])
    return _s(subject) or "핵심 개념"


# ── 판단 ────────────────────────────────────────────────────────────────────

@dataclass
class ReviewDecision:
    review_needed: bool
    cases: List[str]
    concept: str
    reason: str
    questions: List[ReviewQuestion] = field(default_factory=list)


def decide(questions: List[ReviewQuestion], subject: str = "") -> ReviewDecision:
    """LLM 호출 전에 '복습 대상인지'부터 결정한다(CASE D 는 호출하지 않는다)."""
    cases = [q.case() for q in questions]
    concept = extract_concept(questions, subject)
    if not questions:
        return ReviewDecision(False, [], concept, "분석할 문제 데이터가 없다", [])
    if all(c == FIRST_CORRECT for c in cases):
        return ReviewDecision(False, cases, concept, "모든 문제를 최초 풀이에서 맞혔다", questions)
    return ReviewDecision(True, cases, concept, "미해결 또는 회복 확인이 필요한 문제가 있다", questions)


# ── 프롬프트 ────────────────────────────────────────────────────────────────

FIRST_SENTENCE_SUFFIX = "에 대한 개념이 부족하여 복습이 필요합니다."

SYSTEM = (
    "너는 대학생 학습자의 오답노트를 분석하는 학습 코치다.\n"
    "- 지금 주어진 문제 데이터만 사용한다. 다른 문제나 이전 대화 내용을 끌어오지 않는다.\n"
    "- '문제를 틀렸으므로 복습이 필요합니다', '학습을 더 해보세요' 같은 의미 없는 문장은 금지한다.\n"
    "- 어떤 개념이 부족한지, 왜 그렇게 판단했는지, 무엇을 복습해야 하는지가 반드시 들어가야 한다.\n"
    "- 마크다운·제목·인사말 없이 하나의 완성된 설명문만 쓴다."
)


def _question_block(q: ReviewQuestion, idx: int, case: str) -> str:
    lines = [f"[문제 {idx}] 판정: {CASE_LABEL.get(case, case)}",
             f"문제: {q.question[:300]}"]
    if q.choices:
        lines.append("보기: " + " / ".join(q.choices)[:300])
    if q.correct_answer:
        lines.append(f"정답: {q.correct_answer[:120]}")
    lines.append(f"최초 답: {'(응답 없음)' if q.first_unanswered else q.first_answer[:120]}")
    if q.has_retry:
        lines.append(f"재풀이 답: {'(응답 없음)' if q.retry_unanswered else q.retry_answer[:120]}")
    if q.explanation:
        lines.append(f"기존 해설: {q.explanation[:400]}")
    if q.concept:
        lines.append(f"관련 개념: {q.concept[:120]}")
    return "\n".join(lines)


def build_prompt(decision: ReviewDecision, subject: str, material_title: str,
                 difficulty: str = "") -> str:
    blocks = "\n\n".join(_question_block(q, i + 1, c)
                         for i, (q, c) in enumerate(zip(decision.questions, decision.cases)))
    recovered = [c for c in decision.cases if c in RECOVERED_CASES]
    unresolved = [c for c in decision.cases if c in UNRESOLVED_CASES]

    guide = []
    if unresolved:
        guide.append("- 최초와 재풀이에서 모두 해결하지 못한 문제가 있다. 어떤 개념이 왜 부족한지 구체적으로 지목하라.")
    if recovered:
        guide.append("- 재풀이에서 맞힌 문제가 있다. 회복된 부분은 인정하되, 최초 오답 원인이 실제로 해소됐는지 "
                     "해설과 답변을 근거로 판단하고 남은 확인 포인트를 제시하라.")
    if any(c in (UNANSWERED_THEN_WRONG, UNANSWERED_THEN_CORRECT, UNANSWERED_NO_RETRY)
           for c in decision.cases):
        guide.append("- 최초에 '미응답'(답을 고르지 못함)이 있었다는 사실을 문장 안에 반드시 쓴다. "
                     "답을 고르지 못한 것과 틀린 것은 원인이 다르다.")

    return (
        "아래 오답노트 데이터를 바탕으로 학습자가 어떤 개념이 부족해서 복습이 필요한지 "
        "한국어로 500자 내외의 설명문 하나로 작성하라.\n\n"
        "반드시 첫 문장은 다음 형식을 따른다.\n"
        f'"{{구체 개념명}}{FIRST_SENTENCE_SUFFIX}"\n\n'
        "작성 규칙:\n"
        "1. {구체 개념명}은 과목명 전체가 아니라 문제에서 드러난 세부 개념으로 쓴다.\n"
        "2. 최초 풀이 결과와 재풀이 결과를 모두 반영한다(다시풀기는 문제당 1회뿐이다). "
        "재풀이 기록이 있으면 '다시풀기'라는 표현을 써서 그 결과를 문장 안에 명시한다.\n"
        "3. 정답을 그대로 반복하지 말고, 무엇을 몰라서 틀렸는지 설명한다.\n"
        "4. 마지막에 무엇을 어떤 순서로 복습할지 제시한다.\n"
        "5. 사용자를 비난하지 않는다. 500자 내외, 마크다운 금지.\n"
        + ("".join(f"{g}\n" for g in guide) if guide else "")
        + "\n[오답노트 정보]\n"
        f"과목/자료명: {subject or material_title}\n"
        f"난이도: {difficulty}\n\n{blocks}\n"
    )


# ── 결정론 폴백 (AI 실패/timeout 시에도 현재 문제 기반 문장) ─────────────────

def build_fallback(decision: ReviewDecision, material_title: str = "") -> str:
    concept = decision.concept or "핵심 개념"
    cases = decision.cases
    parts = [f"{concept}{FIRST_SENTENCE_SUFFIX}"]

    unresolved = [c for c in cases if c in UNRESOLVED_CASES]
    recovered = [c for c in cases if c in RECOVERED_CASES]

    if any(c in (UNANSWERED_THEN_WRONG, UNANSWERED_NO_RETRY) for c in cases):
        parts.append("최초 풀이에서 답을 고르지 못했고 다시풀기에서도 정답에 도달하지 못해, "
                     "개념을 떠올릴 단서 자체가 정리되지 않은 상태로 보입니다.")
    elif WRONG_THEN_WRONG in cases or WRONG_NO_RETRY in cases:
        parts.append("최초 풀이와 다시풀기에서 모두 같은 문제를 해결하지 못해, "
                     "해당 개념을 문제 상황에 적용하는 과정에서 이해가 끊기고 있습니다.")
    if recovered and not unresolved:
        parts.append("다시풀기에서는 정답을 골랐지만 최초 풀이에서 틀렸던 만큼, "
                     "정답의 근거를 스스로 설명할 수 있는지 한 번 더 확인할 필요가 있습니다.")
    elif recovered:
        parts.append("일부 문제는 다시풀기에서 회복했지만 아직 해결되지 않은 문제가 남아 있습니다.")

    source = _s(material_title)
    parts.append((f"{source} 자료에서 해당 개념이 설명된 부분을 다시 읽고, " if source
                  else "원본 자료에서 해당 개념이 설명된 부분을 다시 읽고, ")
                 + "정답과 내가 고른 답의 차이를 한 줄로 정리한 뒤, 기존 해설을 따라가며 "
                   "개념의 정의와 적용 조건을 구분해 보세요.")
    return " ".join(parts)


def build_no_review_text(decision: ReviewDecision) -> str:
    concept = decision.concept or "이 문제의 핵심 개념"
    return (f"{concept} 관련 문제를 최초 풀이에서 모두 맞혀 지금은 복습이 필요하지 않습니다. "
            "다음 학습에서는 같은 개념이 다른 형태로 나왔을 때도 같은 근거로 답할 수 있는지 확인해 보세요.")


# ── 출력 검증 ───────────────────────────────────────────────────────────────

_MEANINGLESS = (
    "문제를 틀렸으므로 복습이 필요합니다",
    "학습을 더 해보세요",
    "더 공부하세요",
    "복습이 필요합니다.",   # 이 문장만 단독으로 끝나는 경우
)


def validate_text(text: str, decision: ReviewDecision, min_chars: int = 120) -> List[str]:
    """의미 없는 문장/개념 누락/타 문제 오염을 걸러낸다."""
    issues: List[str] = []
    body = _s(text)
    if len(body) < min_chars:
        issues.append("too_short")
    if not body.startswith(decision.concept.split(" ")[0][:20]) and FIRST_SENTENCE_SUFFIX not in body[:120]:
        issues.append("first_sentence_contract")
    if len(body) <= 40 and any(m in body for m in _MEANINGLESS):
        issues.append("meaningless")
    # 재풀이 결과가 있는데 한 번도 언급이 없으면 반쪽 분석이다.
    if any(c != FIRST_CORRECT for c in decision.cases) and \
            any(q.has_retry for q in decision.questions) and \
            not re.search(r"(다시\s*풀|재풀이|다시 시도|두 번째)", body):
        issues.append("retry_not_reflected")
    # 미응답이 있었으면 그 사실이 드러나야 한다(틀린 것과 원인이 다르다).
    if any(c in (UNANSWERED_THEN_WRONG, UNANSWERED_THEN_CORRECT, UNANSWERED_NO_RETRY)
           for c in decision.cases) and \
            not re.search(r"(미응답|무응답|답을\s*(고르|쓰|적)지|응답하지\s*(않|못)|풀지\s*(않|못))", body):
        issues.append("unanswered_not_reflected")
    return issues
