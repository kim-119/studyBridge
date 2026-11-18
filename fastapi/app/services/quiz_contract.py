"""Quiz contract for AI07 -> Spring (quiz.v2, additive over the existing camelCase DTO).

Existing Spring contract (GroupStudyQuizDTO.AIQuizResponse) is kept byte-compatible:
    quizTitle, questions[{question, options: List<String>, correctAnswer: 0-based int, timeLimitSeconds}]
Additive fields (Spring's Jackson ignores unknown properties today):
    quiz:     schemaVersion, quizId, status, degraded, degradedReason, answerKeyFields
    question: questionId, answerType, optionIds, correctOptionIds

questionId is content-derived (sha1 of normalized question + options), so the same
question keeps the same id across retries/serialisation; option ids are positional
letters aligned with the `options` list, i.e. optionIds[correctAnswer] == correctOptionIds[0].

Answer-key boundary: AI07 may send the answer key to Spring, never to a browser.
ANSWER_KEY_FIELDS lists exactly which per-question fields Spring must strip before it
sends a question to users; to_public_quiz() is the reference implementation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "quiz.v2"
OPTION_LETTERS = "ABCDEFGH"
ANSWER_KEY_FIELDS = ("correctAnswer", "answer", "correctOptionIds", "explanation", "sourceSnippet")
# POST /api/ai/quiz (material archive quiz): legacy `answer`/`answerIndex` are 0-based ints,
# explanations reveal the key, sourceTrace.evidence can quote the correct sentence.
MATERIAL_ANSWER_KEY_FIELDS = (
    "correctAnswer", "answer", "answerIndex", "correctOptionIds", "explanation", "wrongExplanations", "sourceTrace",
)

ANSWER_TYPE_BY_QUESTION_TYPE = {
    "multiple_choice": "SINGLE_CHOICE",
    "true_false": "TRUE_FALSE",
    "short_answer": "SHORT_ANSWER",
}


def _norm(text: Any) -> str:
    return re.sub(r"[\s\W_]+", "", str(text or ""), flags=re.UNICODE).casefold()


def option_integrity_error(options: Sequence[Any]) -> Optional[str]:
    """None if options are usable; else a reason code."""
    texts = [str(o if o is not None else "").strip() for o in options]
    if any(not t for t in texts):
        return "EMPTY_OPTION"
    keys = [_norm(t) for t in texts]
    if any(not k for k in keys):
        return "EMPTY_OPTION"
    if len(set(keys)) != len(keys):
        return "DUPLICATE_OPTION"
    return None


def resolve_single_answer_index(correct: Any, answer: Any, options: Sequence[str]) -> Any:
    """Resolve a SINGLE_CHOICE answer to a 0-based index.

    Returns int index, or a str reason code on failure:
      MULTIPLE_ANSWERS_FOR_SINGLE_CHOICE, ANSWER_NOT_IN_OPTIONS, ANSWER_INDEX_TEXT_MISMATCH,
      ANSWER_MISSING.
    """
    n = len(options)
    if isinstance(correct, list):
        if len(correct) > 1:
            return "MULTIPLE_ANSWERS_FOR_SINGLE_CHOICE"
        correct = correct[0] if correct else None
    if isinstance(correct, bool):            # int(True) == 1 would silently pick option B
        correct = None
    idx: Optional[int] = None
    if isinstance(correct, int):
        idx = correct
    elif isinstance(correct, str) and correct.strip():
        c = correct.strip()
        if re.fullmatch(r"\d+", c):
            idx = int(c)
        elif len(c) == 1 and c.upper() in OPTION_LETTERS[:n]:
            idx = OPTION_LETTERS.index(c.upper())
        elif re.search(r"[,/]| and |및", c):
            return "MULTIPLE_ANSWERS_FOR_SINGLE_CHOICE"
    answer_idx: Optional[int] = None
    if isinstance(answer, str) and answer.strip():
        a = answer.strip()
        if len(a) == 1 and a.upper() in OPTION_LETTERS[:n]:
            answer_idx = OPTION_LETTERS.index(a.upper())
        else:
            matches = [i for i, o in enumerate(options) if _norm(o) == _norm(a)]
            if matches:
                answer_idx = matches[0]
            elif idx is None:
                return "ANSWER_NOT_IN_OPTIONS"
    if idx is None:
        idx = answer_idx
    if idx is None:
        return "ANSWER_MISSING"
    if not (0 <= idx < n):
        return "ANSWER_NOT_IN_OPTIONS"
    if answer_idx is not None and answer_idx != idx:
        # e.g. 1-based index from the model: index says B, answer text says A -> ambiguous key
        return "ANSWER_INDEX_TEXT_MISMATCH"
    return idx


def stable_question_id(question: str, options: Sequence[str]) -> str:
    basis = _norm(question) + "\x1f" + "\x1f".join(_norm(o) for o in options)
    return "q_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def stable_quiz_id(material_id: Any, question_ids: Sequence[str]) -> str:
    basis = f"{material_id}|" + "|".join(question_ids)
    return "quiz_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def attach_contract_fields(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add questionId/answerType/optionIds/correctOptionIds in place (legacy fields untouched)."""
    for q in questions:
        options = list(q.get("options") or [])
        q["questionId"] = stable_question_id(q.get("question", ""), options)
        q["answerType"] = ANSWER_TYPE_BY_QUESTION_TYPE.get(q.get("questionType") or "multiple_choice", "SINGLE_CHOICE")
        q["optionIds"] = list(OPTION_LETTERS[: len(options)])
        ca = q.get("correctAnswer")
        q["correctOptionIds"] = [OPTION_LETTERS[ca]] if isinstance(ca, int) and not isinstance(ca, bool) and 0 <= ca < len(options) else []
    return questions


def validate_quiz_contract(questions: Sequence[Dict[str, Any]]) -> List[str]:
    """Whole-quiz post-condition. Empty list == valid. Deterministic."""
    errors: List[str] = []
    if not questions:
        return ["NO_QUESTIONS"]
    seen_ids, seen_q = set(), set()
    for i, q in enumerate(questions):
        tag = f"q{i}"
        text = str(q.get("question") or "").strip()
        if not text:
            errors.append(f"{tag}:EMPTY_QUESTION")
        qid = q.get("questionId")
        if not qid:
            errors.append(f"{tag}:MISSING_QUESTION_ID")
        elif qid in seen_ids:
            errors.append(f"{tag}:DUPLICATE_QUESTION_ID")
        seen_ids.add(qid)
        if _norm(text) in seen_q:
            errors.append(f"{tag}:DUPLICATE_QUESTION")
        seen_q.add(_norm(text))
        atype = q.get("answerType")
        options = q.get("options") or []
        if atype in ("SINGLE_CHOICE", "TRUE_FALSE"):
            err = option_integrity_error(options)
            if err:
                errors.append(f"{tag}:{err}")
            ca = q.get("correctAnswer")
            if isinstance(ca, bool) or not isinstance(ca, int) or not (0 <= ca < len(options)):
                errors.append(f"{tag}:ANSWER_NOT_IN_OPTIONS")
            cids = q.get("correctOptionIds") or []
            if len(cids) != 1:
                errors.append(f"{tag}:SINGLE_CHOICE_ANSWER_COUNT_{len(cids)}")
            elif cids[0] not in (q.get("optionIds") or []):
                errors.append(f"{tag}:ANSWER_NOT_IN_OPTIONS")
        elif atype == "SHORT_ANSWER":
            if not str(q.get("answer") or "").strip():
                errors.append(f"{tag}:ANSWER_MISSING")
        else:
            errors.append(f"{tag}:UNKNOWN_ANSWER_TYPE")
    return errors


def harden_material_questions(items: Sequence[Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """pdf_quiz_service items {question, choices, correct_answer(text), answerIndex?, ...}
    -> (valid SINGLE_CHOICE questions in the /api/ai/quiz legacy+quiz.v2 shape, rejects).

    Integrity is enforced per question, never repaired by guessing: an unresolvable or
    ambiguous answer key drops the question (no silent index 0), duplicates are dropped
    (never re-emitted to pad the count).
    """
    valid: List[Dict[str, Any]] = []
    rejects: List[Dict[str, str]] = []
    seen: set = set()
    for i, q in enumerate(items or []):
        if not isinstance(q, dict):
            rejects.append({"index": str(i), "reason": "NOT_AN_OBJECT"})
            continue
        text = str(q.get("question") or "").strip()
        if not text:
            rejects.append({"index": str(i), "reason": "EMPTY_QUESTION"})
            continue
        if _norm(text) in seen:
            rejects.append({"index": str(i), "reason": "DUPLICATE_QUESTION"})
            continue
        raw_options = q.get("choices") if q.get("choices") is not None else q.get("options")
        if not isinstance(raw_options, list) or len(raw_options) < 2:
            rejects.append({"index": str(i), "reason": "OPTIONS_MISSING"})
            continue
        if not all(isinstance(o, str) for o in raw_options):
            rejects.append({"index": str(i), "reason": "OPTION_NOT_TEXT"})
            continue
        options = [o.strip() for o in raw_options]
        err = option_integrity_error(options)
        if err:
            rejects.append({"index": str(i), "reason": err})
            continue
        key = q.get("correct_answer")
        if isinstance(key, str):
            resolved = resolve_single_answer_index(q.get("answerIndex"), key, options)
        else:  # int / bool / list; bool is rejected inside resolve (True must not mean index 1)
            resolved = resolve_single_answer_index(key if q.get("answerIndex") is None else q.get("answerIndex"),
                                                   None, options)
        if not isinstance(resolved, int):
            rejects.append({"index": str(i), "reason": resolved})
            continue
        seen.add(_norm(text))
        valid.append({
            "question": text,
            "questionType": "multiple_choice",
            "options": options,
            "answer": resolved,          # legacy: frontend parseQuizQuestions expects a 0-based int
            "answerIndex": resolved,     # legacy
            "correctAnswer": resolved,   # legacy + quiz.v2
            "explanation": str(q.get("explanation") or "").strip(),
            "difficulty": q.get("difficulty"),
            "wrongExplanations": q.get("wrong_explanations") or q.get("wrongExplanations") or [],
            "sourceTrace": q.get("source_trace") or q.get("sourceTrace"),
        })
    return attach_contract_fields(valid), rejects


def to_public_quiz(quiz: Dict[str, Any]) -> Dict[str, Any]:
    """User-facing view: same quiz without the answer key (what Spring should send to browsers).

    Strips quiz["answerKeyFields"] (or ANSWER_KEY_FIELDS) from every question in `questions`
    and `quizzes`, from the JSON string `quizData`, and the top-level `source_trace` copy.
    """
    public = copy.deepcopy(quiz)
    fields = tuple(public.get("answerKeyFields") or ANSWER_KEY_FIELDS)

    def _strip(items: Any) -> None:
        for q in items or []:
            if isinstance(q, dict):
                for f in fields:
                    q.pop(f, None)

    _strip(public.get("questions"))
    _strip(public.get("quizzes"))
    if isinstance(public.get("quizData"), str):
        try:
            parsed = json.loads(public["quizData"])
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            _strip(parsed)
            public["quizData"] = json.dumps(parsed, ensure_ascii=False)
    public.pop("source_trace", None)
    public.pop("answerKeyFields", None)
    return public
