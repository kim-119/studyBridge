"""
사용자 표시 텍스트에서 마크다운/HTML 잔여물을 제거하는 공통 유틸.

플래너 assist, 오답노트 피드백, 변형 문제 등 "사용자에게 그대로 보이는" 필드와
pdf_plain_text(=PDF에 바로 넣는 일반 텍스트)에 적용한다.

제거 대상:
  - **굵게** / __굵게__  → 일반 텍스트
  - ###/##/# 제목         → 일반 텍스트
  - `백틱`/```코드블록```  → 백틱 제거
  - <태그>HTML</태그>     → 태그 제거
  - 줄머리 -, *, • 불릿    → 불릿만 제거(내용 유지)
"""
import re
from typing import Any, Dict, List

_TAG_RE = re.compile(r"<[^>]+>")
_CODE_FENCE_RE = re.compile(r"```[a-zA-Z0-9_-]*")
_HEADING_RE = re.compile(r"(?m)^\s*#{1,6}\s*")
_BOLD_RE = re.compile(r"\*\*|__")
# 줄머리 -, *, • 불릿만 제거(내용은 유지). 일반 텍스트 번호(1. 1))는 보존한다.
_BULLET_RE = re.compile(r"(?m)^\s*[-*•]\s+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def sanitize_markdown_text(value: Any) -> str:
    """마크다운/HTML 문법을 제거한 평문을 반환한다. None/숫자도 안전하게 처리."""
    if value is None:
        return ""
    text = str(value)
    text = _CODE_FENCE_RE.sub("", text)   # 코드펜스 ```lang
    text = _HEADING_RE.sub("", text)      # #/##/### 제목
    text = _BOLD_RE.sub("", text)         # **/__ 강조
    text = _TAG_RE.sub("", text)          # <html> 태그
    text = text.replace("`", "")          # 인라인 백틱
    text = _BULLET_RE.sub("", text)       # 줄머리 불릿
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


def sanitize_list(values: Any) -> List[str]:
    """리스트의 각 항목을 sanitize. 빈 값은 제거."""
    if not isinstance(values, list):
        if values in (None, ""):
            return []
        values = [values]
    out: List[str] = []
    for v in values:
        cleaned = sanitize_markdown_text(v)
        if cleaned:
            out.append(cleaned)
    return out


def sanitize_obj(obj: Any) -> Any:
    """dict/list/str을 재귀적으로 sanitize. 사용자 표시 구조 전체에 일괄 적용용."""
    if isinstance(obj, dict):
        return {k: sanitize_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_obj(v) for v in obj]
    if isinstance(obj, str):
        return sanitize_markdown_text(obj)
    return obj
