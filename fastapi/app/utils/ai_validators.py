"""
플래너 assist / 오답노트 피드백 응답 검증기.

검증 실패 시 호출자는 OpenAI repair → Qwen repair → deterministic fallback 순으로 복구한다.
모든 사용자 표시 텍스트는 마크다운이 없어야 한다.
"""
import re
from typing import Any, Dict, List

# 사용자 표시 텍스트에 남으면 실패인 마크다운/HTML 흔적
_MD_PATTERNS = [
    re.compile(r"\*\*"),                  # **굵게**
    re.compile(r"__"),                    # __굵게__
    re.compile(r"(?m)^\s*#{1,6}\s"),      # # / ## / ### 제목
    re.compile(r"`"),                     # 백틱
    re.compile(r"<[^>]+>"),               # HTML 태그
    re.compile(r"(?m)^\s*[-*]\s"),        # 줄머리 - / * 불릿
]


def _collect_strings(obj: Any, out: List[str]) -> None:
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_strings(v, out)


def has_markdown(obj: Any) -> bool:
    """응답(문자열/구조) 어디든 마크다운/HTML 흔적이 있으면 True."""
    strings: List[str] = []
    _collect_strings(obj, strings)
    for s in strings:
        for pat in _MD_PATTERNS:
            if pat.search(s):
                return True
    return False


def _nonempty(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _nonempty_list(v: Any) -> bool:
    return isinstance(v, list) and len(v) > 0


def validate_planner_assist(d: Dict[str, Any]) -> bool:
    """플래너 assist 응답 검증."""
    if not isinstance(d, dict):
        return False
    if not _nonempty(d.get("refined_goal")):
        return False
    tasks = d.get("task_breakdown")
    if not isinstance(tasks, list) or len(tasks) < 3:
        return False
    fb = d.get("ai_feedback")
    if not isinstance(fb, dict):
        return False
    if not (_nonempty_list(fb.get("strengths")) and _nonempty_list(fb.get("concerns"))
            and _nonempty_list(fb.get("recommendations"))):
        return False
    if not _nonempty_list(d.get("next_actions")):
        return False
    if has_markdown(d):
        return False
    return True


def validate_wrong_note_feedback(d: Dict[str, Any], expected_count: int) -> bool:
    """오답노트 피드백 응답 검증."""
    if not isinstance(d, dict):
        return False
    notes = d.get("wrong_notes")
    if not isinstance(notes, list) or len(notes) != expected_count:
        return False
    for n in notes:
        if not isinstance(n, dict):
            return False
        if "user_answer" not in n:
            return False
        for key in ("question", "correct_answer", "ai_explanation", "why_user_answer_is_wrong"):
            if not _nonempty(n.get(key)):
                return False
        rq = n.get("retry_question")
        if not isinstance(rq, dict) or not _nonempty(rq.get("question")):
            return False
    if not _nonempty(d.get("pdf_plain_text")):
        return False
    if has_markdown(d):
        return False
    return True
