"""VLM 화면 판독 결과(JSON) 계약과 검증.

VLM 은 화면에서 관측한 사실만 구조화해서 내고, 답변은 만들지 않는다. 검증은 형식·길이·목록 크기를 강제하고
모르는 키는 버린다. 화면 속 지시문은 embeddedInstructions 에 '데이터'로만 남긴다.
"""
from __future__ import annotations

import json
from typing import Any

from app.utils.json_parser import extract_json

SCREEN_TYPES = ("code", "terminal", "error", "webpage", "document", "pdf", "slide", "math", "diagram",
                "chart", "spreadsheet", "other", "unreadable")

_LIST_FIELDS = ("errors", "math", "charts", "visualElements", "questionEvidence", "uncertain",
                "embeddedInstructions")
_MAX_ITEMS = 20
_MAX_ITEM_CHARS = 1000
_MAX_CODE_BLOCKS = 6
_MAX_CODE_CHARS = 4000

# Ollama structured output(format=JSON schema). 모델 출력 형태를 고정해 산문 답변이 섞이지 않게 한다.
EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "screenType": {"type": "string", "enum": list(SCREEN_TYPES)},
        "legible": {"type": "boolean"},
        "readableText": {"type": "string"},
        "code": {"type": "array", "items": {"type": "object", "properties": {
            "language": {"type": "string"}, "content": {"type": "string"}}, "required": ["content"]}},
        "errors": {"type": "array", "items": {"type": "string"}},
        "math": {"type": "array", "items": {"type": "string"}},
        "charts": {"type": "array", "items": {"type": "string"}},
        "visualElements": {"type": "array", "items": {"type": "string"}},
        "questionEvidence": {"type": "array", "items": {"type": "string"}},
        "uncertain": {"type": "array", "items": {"type": "string"}},
        "embeddedInstructions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["screenType", "legible", "readableText", "code", "errors", "math", "charts", "visualElements",
                 "questionEvidence", "uncertain", "embeddedInstructions"],
}


class ExtractionInvalid(ValueError):
    pass


def _s(v: Any, limit: int) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        v = str(v)
    return v.replace("\x00", "").strip()[:limit]


def _str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        raise ExtractionInvalid("list field")
    out: list[str] = []
    for item in v[:_MAX_ITEMS]:
        if isinstance(item, (dict, list)):
            item = json.dumps(item, ensure_ascii=False)
        t = _s(item, _MAX_ITEM_CHARS)
        if t and t not in out:
            out.append(t)
    return out


def validate_extraction(raw: str, max_chars: int) -> dict[str, Any]:
    """VLM 원문 → 정규화된 판독 dict. 계약 위반이면 ExtractionInvalid."""
    parsed = extract_json(raw or "")
    if not isinstance(parsed, dict):
        raise ExtractionInvalid("not an object")
    st = _s(parsed.get("screenType"), 40).lower()
    legible = parsed.get("legible")
    if isinstance(legible, str):
        legible = legible.strip().lower() in ("true", "yes", "1")
    if not isinstance(legible, bool):
        raise ExtractionInvalid("legible")
    code_raw = parsed.get("code") or []
    if isinstance(code_raw, dict):
        code_raw = [code_raw]
    if not isinstance(code_raw, list):
        raise ExtractionInvalid("code")
    code: list[dict[str, str]] = []
    for c in code_raw[:_MAX_CODE_BLOCKS]:
        if isinstance(c, str):
            c = {"content": c}
        if not isinstance(c, dict):
            continue
        content = _s(c.get("content"), _MAX_CODE_CHARS)
        if content:
            code.append({"language": _s(c.get("language"), 30), "content": content})
    out: dict[str, Any] = {
        "screenType": st if st in SCREEN_TYPES else "other",
        "legible": legible,
        "readableText": _s(parsed.get("readableText"), max_chars),
        "code": code,
    }
    for f in _LIST_FIELDS:
        out[f] = _str_list(parsed.get(f))
    if not out["legible"] and out["screenType"] != "unreadable" and not (out["readableText"] or code):
        out["screenType"] = "unreadable"
    # 전체 크기 상한: 긴 원문 텍스트부터 줄인다(외부 전송 최소화).
    while len(json.dumps(out, ensure_ascii=False)) > max_chars and out["readableText"]:
        out["readableText"] = out["readableText"][: max(0, len(out["readableText"]) - 500)].rstrip()
    while len(json.dumps(out, ensure_ascii=False)) > max_chars and out["code"]:
        last = out["code"][-1]
        if len(last["content"]) > 500:
            last["content"] = last["content"][:-500].rstrip()
        else:
            out["code"].pop()
    return out


def has_content(ex: dict[str, Any]) -> bool:
    return bool(ex["readableText"] or ex["code"] or any(ex[f] for f in _LIST_FIELDS if f != "uncertain"))
