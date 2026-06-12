"""
퀴즈 난이도 정책 강제 (easy / normal(=medium) / hard).

목표:
  - hard 퀴즈는 반드시 '시나리오형'이어야 한다. 오류 상황/설계 판단/책임 분리/테스트/
    유지보수/예외 처리/성능 관점 중 최소 1개를 포함하고, 단순 "주요 역할은 무엇인가요?"
    형태면 실패로 보고 repair 한다.
  - 생성 후 validate_quiz_difficulty(question, requested)로 검증하고, 실패 시
    (1) OpenAI repair → (2) Ollama repair → (3) deterministic hard template 순으로 복구한다.
  - 응답에 difficulty_requested/applied/policy/difficulty_validation 을 부착한다.

기존 generate_quiz_json/validate_quiz_result 계약은 깨지 않고, 이 모듈을 그 뒤에 얹는다.
모델/temperature/max_tokens/provider 사용 여부는 .env로 제어한다(하드코딩 금지).
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.material_summary_builder import sanitize_markdown_text

logger = logging.getLogger(__name__)

# ── 난이도 정규화 ─────────────────────────────────────────────────────────────
_DIFF_NORMALIZE = {
    "쉬움": "easy", "easy": "easy", "초급": "easy", "하": "easy",
    "보통": "normal", "normal": "normal", "medium": "normal", "중급": "normal", "중": "normal",
    "어려움": "hard", "hard": "hard", "advanced": "hard", "상급": "hard", "상": "hard",
}

_DIFFICULTY_POLICY_TEXT = {
    "easy": "문서에 직접 나온 정의/용어/기본 역할/설정값/기본 흐름 확인",
    "normal": "문서 기반 + 약간의 응용(역할 비교/흐름 이해/설정 이유/간단한 원인 추론)",
    "hard": "문서 기반 + 응용 + 고급 개념(시나리오/오류 상황/설계 판단/책임 분리/테스트/유지보수/예외/성능)",
}

# hard 가 반드시 포함해야 하는 신호어 (최소 1개)
_HARD_SIGNALS = [
    "시나리오", "상황", "발생", "구현했", "구현하니", "구현한", "오류", "에러", "예외",
    "설계", "아키텍처", "책임 분리", "책임 분배", "책임을", "테스트", "유지보수", "성능",
    "리팩토링", "리팩터링", "디버깅", "장애", "최적화", "확장성", "동시성", "중복 요청",
    "메모리 누수", "race", "병목", "트레이드오프", "결합도", "의존성", "회전 이후", "회전 후",
]

# hard 에서 금지되는 단순 패턴
_HARD_BANNED = [
    re.compile(r"주요\s*역할은\s*무엇"),
    re.compile(r"역할은\s*무엇(인가요|입니까|이라고)"),
    re.compile(r"정의(는|가)\s*무엇"),
    re.compile(r"무엇을\s*의미"),
    re.compile(r"무엇이라고\s*(하|부르)"),
]

_HARD_MIN_LEN = int(os.getenv("AI_QUIZ_HARD_MIN_LEN", "80"))


def normalize_difficulty(difficulty: Any) -> str:
    return _DIFF_NORMALIZE.get(str(difficulty or "").strip().lower(),
                               _DIFF_NORMALIZE.get(str(difficulty or "").strip(), "normal"))


def difficulty_policy_text(difficulty: str) -> str:
    return _DIFFICULTY_POLICY_TEXT.get(normalize_difficulty(difficulty),
                                       _DIFFICULTY_POLICY_TEXT["normal"])


def _qtext(q: Dict[str, Any]) -> str:
    return sanitize_markdown_text(q.get("question") or "")


def _choices(q: Dict[str, Any]) -> List[str]:
    opts = q.get("options") if isinstance(q.get("options"), list) else (q.get("choices") or [])
    return [sanitize_markdown_text(o) for o in opts if str(o).strip()]


# ── 검증 (스펙 C) ─────────────────────────────────────────────────────────────
def validate_quiz_difficulty(question: Dict[str, Any], requested_difficulty: str) -> Dict[str, Any]:
    """단일 문항이 요청 난이도 정책을 만족하는지 검증. {passed, reason}."""
    diff = normalize_difficulty(requested_difficulty)
    text = _qtext(question)
    explanation = sanitize_markdown_text(question.get("explanation") or "")
    choices = _choices(question)

    if not text:
        return {"passed": False, "reason": "문항(question)이 비어 있음"}

    if diff != "hard":
        # easy/normal: 최소한의 형식만 본다(문항/선택지 존재, 너무 짧지 않음)
        if len(choices) and len(choices) < 4:
            return {"passed": False, "reason": "선택지가 4개 미만"}
        if not explanation.strip():
            return {"passed": True, "reason": f"{diff} 정책 충족(해설 보강 권장)"}
        return {"passed": True, "reason": f"{diff} 정책 충족"}

    # hard 전용 강한 검증
    for pat in _HARD_BANNED:
        if pat.search(text):
            return {"passed": False, "reason": "단순 개념 확인형(금지 패턴) — 시나리오 필요"}
    if len(text) < _HARD_MIN_LEN:
        return {"passed": False, "reason": f"question 길이 {len(text)} < {_HARD_MIN_LEN}자"}
    if not any(sig.lower() in text.lower() for sig in _HARD_SIGNALS):
        return {"passed": False, "reason": "시나리오/설계/오류/테스트/성능 신호어 없음"}
    if not explanation.strip():
        return {"passed": False, "reason": "정답 해설(explanation)이 비어 있음"}
    if len(choices) and len(choices) < 4:
        return {"passed": False, "reason": "선택지가 4개 미만"}
    return {"passed": True, "reason": "시나리오 기반 설계 판단 문제로 생성됨"}


# ── 개념 추출 ─────────────────────────────────────────────────────────────────
def _concept_from(question: Dict[str, Any], context: str, fallback_keywords: List[str]) -> str:
    text = _qtext(question)
    # 영문/대문자 식별자(Retrofit2, ViewModel 등) 우선
    m = re.findall(r"[A-Z][A-Za-z0-9]{2,}", text) or re.findall(r"[A-Z][A-Za-z0-9]{2,}", context or "")
    if m:
        return m[0]
    for kw in fallback_keywords:
        if kw and len(kw) > 1:
            return kw
    # 한글 명사 후보
    h = re.findall(r"[가-힣]{2,}", text)
    return h[0] if h else "핵심 개념"


# ── deterministic hard 템플릿 (최후 보강) ─────────────────────────────────────
_HARD_SYMPTOMS = [
    ("화면 회전 이후 동일한 네트워크 요청이 중복 실행되고 테스트 코드 작성도 어려워졌다",
     "데이터 소스를 추상화하고 네트워크와 캐시, 예외 처리를 분리해 상위 계층의 책임을 줄이기 위해"),
    ("예외가 상위로 전파되지 않아 장애 원인 추적과 유지보수가 어려워졌다",
     "오류 처리와 데이터 접근 책임을 한 계층으로 모아 예외 흐름을 일관되게 관리하기 위해"),
    ("기능이 늘면서 한 클래스에 로직이 몰려 단위 테스트와 변경이 점점 힘들어졌다",
     "책임을 분리해 각 계층을 독립적으로 교체·테스트할 수 있도록 결합도를 낮추기 위해"),
]
_HARD_WRONG = [
    "UI 이벤트를 직접 처리해 화면 갱신 횟수를 줄이기 위해",
    "생명주기를 직접 관리해 메모리 누수를 막기 위해",
    "직렬화 포맷을 자동으로 변환해 주기 위해",
    "화면 애니메이션 성능을 높이기 위해",
    "로그 출력을 자동으로 비활성화하기 위해",
]


def build_hard_question(concept: str, seq: int = 0) -> Dict[str, Any]:
    """문서 개념을 시나리오형 hard 문항으로 결정적으로 생성(최후 fallback)."""
    concept = sanitize_markdown_text(concept) or "핵심 개념"
    symptom, correct = _HARD_SYMPTOMS[seq % len(_HARD_SYMPTOMS)]
    question = (
        f"{concept}을(를) 사용하는 모듈을 한 계층에서 직접 구현했더니 {symptom}. "
        f"이 구조를 책임에 따라 분리해야 하는 가장 타당한 이유는 무엇인가?"
    )
    wrongs = [_HARD_WRONG[(seq + i) % len(_HARD_WRONG)] for i in range(3)]
    options = [correct] + wrongs
    # 정답 위치를 seq로 회전(항상 0번이면 패턴 노출되므로)
    answer_index = seq % 4
    options[0], options[answer_index] = options[answer_index], options[0]
    explanation = (
        f"이 문항은 {concept}을(를) 단일 계층에 두었을 때 생기는 중복 실행, 예외 추적, "
        f"테스트 곤란 같은 유지보수 문제를 책임 분리로 해결하는 설계 판단을 묻는다. "
        f"정답은 데이터 접근과 예외 처리를 추상화해 상위 계층의 책임을 줄이는 선택지다. "
        f"나머지는 해당 계층의 책임이 아니거나 문제의 원인과 무관하다."
    )
    return {
        "question": question,
        "options": options,
        "answer": answer_index,
        "answerIndex": answer_index,
        "explanation": explanation,
        "difficulty": "hard",
    }


# ── LLM repair ────────────────────────────────────────────────────────────────
def _llm_repair_hard(concept: str, context: str, prev_question: str) -> Optional[Dict[str, Any]]:
    """OpenAI(refiner) 우선 → Ollama fallback 으로 시나리오형 hard 문항 1개 생성."""
    from app.services.study_action_router import refiner_llm  # OpenAI→Ollama fallback 내장
    from app.services.material_ai_manager import _extract_json

    system = (
        "너는 고난도 시험 출제 전문가다. 반드시 '시나리오형' 사지선다 한 문제를 한국어로 만든다. "
        "오류 상황/설계 판단/책임 분리/테스트/유지보수/예외/성능 중 최소 하나를 포함하고, "
        "단순 '무엇인가요?' 형태는 금지한다. 마크다운 없이 JSON 객체만 출력한다."
    )
    user = (
        f"## 핵심 개념\n{concept}\n\n## 문서 내용(근거)\n{(context or '')[:2500]}\n\n"
        f"## 너무 쉬웠던 기존 문항(개선 대상)\n{prev_question}\n\n"
        "아래 JSON 형식으로만 응답하라(설명/마크다운 금지):\n"
        '{"question":"80자 이상 시나리오 문항","options":["보기1","보기2","보기3","보기4"],'
        '"answerIndex":0,"answer":"정답 보기 텍스트","explanation":"정답/오답 근거 해설"}\n'
        "question은 상황 설명 + 설계 판단/오류 분석을 포함해야 한다."
    )
    try:
        raw = refiner_llm(system, user, max_tokens=900)
    except Exception as e:  # noqa: BLE001
        logger.warning("hard repair LLM 예외: %s", e)
        return None
    parsed = _extract_json(raw)
    if not isinstance(parsed, dict):
        return None
    opts = parsed.get("options") or parsed.get("choices") or []
    if not isinstance(opts, list) or len(opts) < 4:
        return None
    ans = parsed.get("answerIndex")
    if ans is None and isinstance(parsed.get("answer"), int):
        ans = parsed.get("answer")
    if ans is None and parsed.get("answer") in opts:
        ans = opts.index(parsed.get("answer"))
    try:
        ans = int(ans)
    except (TypeError, ValueError):
        ans = 0
    if not (0 <= ans < len(opts)):
        ans = 0
    q = {
        "question": sanitize_markdown_text(parsed.get("question")),
        "options": [sanitize_markdown_text(o) for o in opts[:4]],
        "answer": ans,
        "answerIndex": ans,
        "explanation": sanitize_markdown_text(parsed.get("explanation")),
        "difficulty": "hard",
    }
    return q


# ── 메인 진입점 ───────────────────────────────────────────────────────────────
def enforce_quiz_difficulty(
    questions: List[Dict[str, Any]],
    requested_difficulty: str,
    context: str = "",
    keywords: Optional[List[str]] = None,
    allow_llm_repair: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    각 문항을 요청 난이도 정책에 맞게 검증/복구한다.
    allow_llm_repair=False 면 LLM repair를 건너뛰고 결정적 hard 템플릿만 사용한다(타임아웃 복구용·즉시 반환).
    Returns: (questions, difficulty_meta)
      difficulty_meta = {difficulty_requested, difficulty_applied, difficulty_policy,
                         difficulty_validation:{passed, reason}, repaired_count}
    """
    diff = normalize_difficulty(requested_difficulty)
    keywords = keywords or []
    out: List[Dict[str, Any]] = []
    repaired = 0
    fail_reasons: List[str] = []

    for i, q in enumerate(questions or []):
        q = dict(q)
        # 모든 표시 텍스트 sanitize
        q["question"] = sanitize_markdown_text(q.get("question") or "")
        q["explanation"] = sanitize_markdown_text(q.get("explanation") or "")
        if isinstance(q.get("options"), list):
            q["options"] = [sanitize_markdown_text(o) for o in q["options"]]

        check = validate_quiz_difficulty(q, diff)
        if not check["passed"] and diff == "hard":
            concept = _concept_from(q, context, keywords)
            repaired_q = _llm_repair_hard(concept, context, q.get("question", "")) if allow_llm_repair else None
            if repaired_q is not None and validate_quiz_difficulty(repaired_q, "hard")["passed"]:
                q = repaired_q
                repaired += 1
            else:
                q = build_hard_question(concept, seq=i)  # 결정적 — 항상 hard 검증 통과
                repaired += 1
            check = validate_quiz_difficulty(q, "hard")

        q["difficulty_applied"] = diff
        q["difficulty_validation"] = check
        if not check["passed"]:
            fail_reasons.append(f"#{i + 1}: {check['reason']}")
        out.append(q)

    all_pass = all(qq.get("difficulty_validation", {}).get("passed") for qq in out) if out else False
    meta = {
        "difficulty_requested": requested_difficulty,
        "difficulty_applied": diff,
        "difficulty_policy": difficulty_policy_text(diff),
        "difficulty_validation": {
            "passed": all_pass,
            "reason": ("시나리오 기반 설계 판단 문제로 생성됨" if (all_pass and diff == "hard")
                       else ("정책 충족" if all_pass else "; ".join(fail_reasons)[:300])),
        },
        "repaired_count": repaired,
    }
    return out, meta
