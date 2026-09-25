"""
오답노트 유사문제 / 그룹스터디 퀴즈 생성 — Ollama 기반 (하드코딩 문제 없음).

POST /api/ai/quiz/generate 에서 다음 경우에 호출된다.
  - source == "wrong_note" (오답노트 유사문제)
  - source == "group_study" (그룹스터디 퀴즈, 자료/주제/채팅 맥락 기반)
  - materialId/text 없이 원본 문제·정답·해설·자료 본문만 들어온 경우

설계 원칙(계약):
  - 반드시 Ollama 기반으로 생성한다. 하드코딩/정적 fallback 문제를 절대 만들지 않는다.
  - 입력 근거(원본 문제/정답/해설/자료 본문/주제)가 부족하면
      success=false + errorCode=QUIZ_SOURCE_INSUFFICIENT + questions=[]
  - Ollama 미응답/오류/타임아웃이면
      success=false + errorCode=OLLAMA_UNAVAILABLE + questions=[]   (서버 500/무한로딩 금지)
  - JSON parse 실패 시 1회 repair. 그래도 실패하면 success=false + questions=[].
  - 검증 통과 문제만 반환한다:
      choices 정확히 4개 / answerIndex 0~3 / answer == choices[answerIndex] /
      question 비어있지 않음 / explanation 비어있지 않음 / 원본 복붙 아님.
  - 유효 문제가 1개도 없으면 success=false (가짜 성공 금지).
"""
from __future__ import annotations

import difflib
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ask_ollama 는 실패 시 빈 문자열이 아니라 한국어 안내 prose 를 반환한다.
# 따라서 빈 문자열 검사로는 실패를 구분할 수 없어, 해당 sentinel marker 로 판별한다.
_OLLAMA_FAILURE_MARKERS = (
    "Ollama 서버", "연결할 수 없습니다", "[Ollama 오류]",
    "빈 응답을 반환", "초과했습니다", "num_predict",
)


def _looks_like_ollama_failure(text: Optional[str]) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    # JSON 으로 보이면 실패 prose 가 아니다.
    if t.startswith("{") or t.startswith("[") or "```" in t:
        return False
    return any(m in t for m in _OLLAMA_FAILURE_MARKERS)


def _fail(code: str, message: str) -> Dict[str, Any]:
    return {
        "success": False,
        "source": "ollama",
        "grounded": False,
        "errorCode": code,
        "message": message,
        "questions": [],
    }


def _coerce_count(raw: Any, default: int = 3) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, 5))


def _first_nonempty(payload: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = payload.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _resolve_answer_index(item: Dict[str, Any], choices: List[str]) -> Optional[int]:
    """다양한 key/형태(answerIndex/correctAnswer 정수·텍스트/answer 텍스트)에서 정답 인덱스 도출."""
    n = len(choices)

    # 1) 명시적 정수 인덱스 후보
    for key in ("answerIndex", "answer_index", "correctIndex", "correctAnswerIndex"):
        v = item.get(key)
        if isinstance(v, bool):
            continue
        if isinstance(v, int) and 0 <= v < n:
            return v
        if isinstance(v, str) and v.strip().isdigit() and 0 <= int(v.strip()) < n:
            return int(v.strip())

    # 2) correctAnswer 가 정수(인덱스)인 경우
    ca = item.get("correctAnswer")
    if isinstance(ca, int) and not isinstance(ca, bool) and 0 <= ca < n:
        return ca

    # 3) 정답 "텍스트"가 choices 중 하나와 일치하는 경우 (answer / correctAnswer / answerText)
    for key in ("answer", "correctAnswer", "answerText", "correct"):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            target = v.strip()
            for i, c in enumerate(choices):
                if c.strip() == target:
                    return i
    return None


def _normalize_question(item: Any, original_question: str) -> Optional[Dict[str, Any]]:
    """단일 문항을 계약 shape 로 정규화 + 검증. 실패 시 None."""
    if not isinstance(item, dict):
        return None

    question = str(item.get("question") or item.get("questionText") or "").strip()
    if not question:
        return None

    raw_choices = item.get("choices") or item.get("options") or []
    if not isinstance(raw_choices, list):
        return None
    choices = [str(c).strip() for c in raw_choices if str(c).strip()]
    # choices 정확히 4개 + 중복 없음
    if len(choices) != 4 or len(set(choices)) != 4:
        return None

    idx = _resolve_answer_index(item, choices)
    if idx is None or not (0 <= idx <= 3):
        return None

    explanation = str(item.get("explanation") or item.get("rationale") or "").strip()
    if not explanation:
        return None

    # 원본 문제 복붙 reject (같은 개념 다른 맥락이어야 함)
    if original_question:
        ratio = difflib.SequenceMatcher(None, question, original_question).ratio()
        if ratio >= 0.92:
            return None

    answer = choices[idx]
    source_hint = str(item.get("sourceHint") or item.get("source_hint") or "").strip()
    if not source_hint:
        source_hint = "원본 오답 문제·해설·자료 근거를 변형"

    return {
        "question": question,
        "choices": choices,
        "options": choices,            # 프론트 호환(quiz 카드가 options 를 읽는 경우)
        "answerIndex": idx,
        "correctAnswer": idx,          # 프론트 호환(인덱스 계약)
        "answer": answer,
        "explanation": explanation,
        "sourceHint": source_hint,
    }


def _parse_questions(raw: Optional[str], count: int, original_question: str) -> List[Dict[str, Any]]:
    """LLM 출력 → 유효 문항 배열. 검증 통과한 것만, 최대 count 개."""
    from app.utils.json_parser import safe_parse_quiz_json

    items = safe_parse_quiz_json(raw or "")
    if not isinstance(items, list):
        return []

    valid: List[Dict[str, Any]] = []
    seen_questions: List[str] = []
    for it in items:
        norm = _normalize_question(it, original_question)
        if not norm:
            continue
        # 생성된 문항끼리 중복 제거
        if any(difflib.SequenceMatcher(None, norm["question"], prev).ratio() >= 0.9
               for prev in seen_questions):
            continue
        seen_questions.append(norm["question"])
        valid.append(norm)
        if len(valid) >= count:
            break
    return valid


_SYSTEM_PROMPT = (
    "너는 StudyBridge 오답노트 유사 문제 생성기다.\n"
    "반드시 제공된 원문 문제, 정답, 오답, 해설, 자료 맥락에 근거해서만 유사 문제를 만든다.\n"
    "하드코딩 예시 문제를 사용하지 않는다.\n"
    "입력 근거가 부족하면 questions 를 비운다.\n"
    "반드시 JSON 만 출력한다. markdown code fence(```)를 쓰지 않는다.\n"
    "각 문제의 choices 는 정확히 4개다. answerIndex 는 0~3 정수다.\n"
    "answer 는 choices[answerIndex] 와 글자까지 정확히 일치해야 한다.\n"
    "explanation 은 왜 그 보기가 정답인지 설명한다.\n"
    "sourceHint 에는 원문 문제/해설/자료 중 어떤 부분을 변형했는지 짧게 적는다.\n"
    "원문과 완전히 같은 문제를 반복하지 말고, 같은 개념을 다른 상황/수치/표현으로 재구성한다.\n"
    "반드시 한국어로 작성한다."
)


def _build_user_prompt(payload: Dict[str, Any], topic: str, count: int, difficulty: str,
                       original_question: str, wrong_answer: str, correct_answer: str,
                       explanation: str, source_text: str) -> str:
    return (
        f"## 주제(topic)\n{topic or '(미지정)'}\n"
        f"## 원본 문제(originalQuestion)\n{original_question or '(없음)'}\n"
        f"## 사용자가 고른 오답(wrongAnswer)\n{wrong_answer or '(없음)'}\n"
        f"## 정답(correctAnswer)\n{correct_answer or '(없음)'}\n"
        f"## 해설(explanation)\n{explanation or '(없음)'}\n"
        f"## 자료 본문(sourceText)\n{(source_text or '(없음)')[:3000]}\n"
        f"## 요청 문항 수(requestedCount)\n{count}\n"
        f"## 난이도(difficulty)\n{difficulty or 'basic'}\n\n"
        f"위 근거에 기반해 같은 개념을 다른 맥락으로 묻는 4지선다 유사 문제 {count}개를 만들어라.\n"
        "아래 JSON 형식으로만 응답하라(설명/마크다운/코드펜스 금지):\n"
        '{ "questions": [ '
        '{ "question": "...", "choices": ["...","...","...","..."], '
        '"answerIndex": 0, "answer": "choices[answerIndex] 와 동일", '
        '"explanation": "왜 정답인지", "sourceHint": "어떤 부분을 변형했는지" } ] }'
    )


def generate_wrong_note_quiz(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    오답노트/그룹스터디 유사 퀴즈 생성. 항상 dict 를 반환(예외를 밖으로 던지지 않음).
    """
    payload = payload or {}

    topic = _first_nonempty(payload, "topic", "title", "subject")
    original_question = _first_nonempty(
        payload, "originalQuestion", "original_question", "questionText", "question")
    wrong_answer = _first_nonempty(payload, "wrongAnswer", "wrong_answer", "userAnswer", "user_answer")
    correct_answer = _first_nonempty(payload, "correctAnswer", "correct_answer", "answer")
    explanation = _first_nonempty(payload, "explanation", "rationale")
    source_text = _first_nonempty(payload, "sourceText", "source_text", "context", "materialContext", "text")
    difficulty = _first_nonempty(payload, "difficulty") or "basic"
    count = _coerce_count(payload.get("requestedCount") or payload.get("count")
                          or payload.get("numQuestions"), default=3)

    # ── 입력 근거 충분성 게이트 ────────────────────────────────────────────────
    # 문제를 변형할 "원본"(원본 문제 또는 자료 본문)과, 정답을 알 수 있는 근거
    # (정답/해설/자료 본문) 중 최소 하나는 있어야 한다.
    has_seed = bool(original_question) or len(source_text) >= 30
    has_basis = bool(correct_answer) or bool(explanation) or len(source_text) >= 30 or bool(topic)
    if not (has_seed and has_basis):
        logger.info("[wrong_note_quiz] 입력 근거 부족 → QUIZ_SOURCE_INSUFFICIENT")
        return _fail(
            "QUIZ_SOURCE_INSUFFICIENT",
            "유사 문제를 만들 수 있는 원문, 정답, 해설 정보가 부족합니다.",
        )

    # ── Ollama 가용성 확인 ────────────────────────────────────────────────────
    from app.services.ollama_client import ask_ollama, is_ollama_available

    if not is_ollama_available():
        logger.warning("[wrong_note_quiz] Ollama 미응답 → OLLAMA_UNAVAILABLE")
        return _fail(
            "OLLAMA_UNAVAILABLE",
            "현재 AI 문제 생성 모델 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
        )

    user_prompt = _build_user_prompt(
        payload, topic, count, difficulty, original_question,
        wrong_answer, correct_answer, explanation, source_text)

    try:
        raw = ask_ollama(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            top_p=0.85,
            max_tokens=1800,
            think=False,
        )
    except Exception as e:  # noqa: BLE001  — ask_ollama 는 보통 예외를 안 던지지만 방어.
        logger.error("[wrong_note_quiz] ask_ollama 예외: %s", e)
        return _fail(
            "OLLAMA_UNAVAILABLE",
            "현재 AI 문제 생성 모델 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
        )

    if _looks_like_ollama_failure(raw):
        logger.warning("[wrong_note_quiz] Ollama fallback prose 감지 → OLLAMA_UNAVAILABLE")
        return _fail(
            "OLLAMA_UNAVAILABLE",
            "현재 AI 문제 생성 모델 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
        )

    questions = _parse_questions(raw, count, original_question)

    # ── JSON parse/검증 실패 시 1회 repair ────────────────────────────────────
    if not questions:
        repair_user = (
            user_prompt
            + "\n\n[복구 지시] 직전 출력이 형식을 위반했다. 반드시 위 JSON 스키마만 출력하고, "
            "각 문제의 choices 는 정확히 4개, answerIndex 는 0~3, answer 는 choices[answerIndex] 와 "
            "글자까지 동일해야 한다. 코드펜스/설명 문장을 출력하지 마라."
        )
        try:
            raw2 = ask_ollama(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=repair_user,
                temperature=0.2,
                top_p=0.85,
                max_tokens=1800,
                think=False,
            )
        except Exception as e:  # noqa: BLE001
            logger.error("[wrong_note_quiz] repair ask_ollama 예외: %s", e)
            raw2 = None

        if _looks_like_ollama_failure(raw2):
            return _fail(
                "OLLAMA_UNAVAILABLE",
                "현재 AI 문제 생성 모델 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
            )
        questions = _parse_questions(raw2, count, original_question)

    if not questions:
        logger.warning("[wrong_note_quiz] 유효 문항 0개(파싱/검증 실패) → 생성 실패")
        return _fail(
            "QUIZ_GENERATION_FAILED",
            "유사 문제를 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        )

    return {
        "success": True,
        "source": "ollama",
        "grounded": bool(source_text or explanation or original_question),
        "topic": topic or original_question[:40] or "유사 문제",
        "difficulty": difficulty,
        "questions": questions,
    }
