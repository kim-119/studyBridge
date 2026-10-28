"""외부(OpenAI) 전송 전 개인정보·비밀값 마스킹. 원본 이미지는 보내지 않고, 판독 텍스트와 질문만 이 단계를 거친다.

가리는 것: 이메일, 전화번호, 주민등록번호, 카드번호, API 키·토큰·JWT·개인키, password/secret/token 대입값,
URL 의 토큰성 쿼리값. 코드·오류 설명에 필요한 식별자·URL 경로·IP 는 남긴다.
"""
from __future__ import annotations

import re
from typing import Any

_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"), "[비밀키]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[토큰]"),
    (re.compile(r"\b(?:sk|pk|rk)-(?:proj-|live-|test-)?[A-Za-z0-9_-]{16,}"), "[API키]"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[API키]"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}"), "[API키]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "[API키]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), "[API키]"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{16,}"), r"\1 [토큰]"),
    (re.compile(r"(?i)((?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|auth[_-]?token|token|비밀번호)"
                r"[\"']?\s*[:=]\s*[\"']?)([^\s\"',;()\[\].]{6,})(?![\w(.\[])"), r"\1[비밀값]"),
    (re.compile(r"(?i)([?&](?:token|access_token|key|api_key|sig|signature|code|session)=)[^&\s]+"), r"\1[비밀값]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[이메일]"),
    (re.compile(r"\b\d{6}\s?-\s?[1-8]\d{6}\b"), "[주민등록번호]"),
    (re.compile(r"\b(?:\d{4}[ -]){3}\d{4}\b"), "[카드번호]"),
    (re.compile(r"(?<!\d)(?:\+82[ -]?1[016789]|01[016789])[ -]?\d{3,4}[ -]?\d{4}(?!\d)"), "[전화번호]"),
    (re.compile(r"(?<!\d)0(?:2|[3-6][1-5])[ -]\d{3,4}[ -]\d{4}(?!\d)"), "[전화번호]"),
]


def mask_text(text: str) -> tuple[str, int]:
    if not text:
        return text, 0
    n = 0
    for pat, rep in _RULES:
        text, k = pat.subn(rep, text)
        n += k
    return text, n


def mask_obj(obj: Any) -> tuple[Any, int]:
    """dict/list/str 를 재귀로 마스킹한다. 반환: (마스킹된 사본, 가린 개수)."""
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, list):
        out, n = [], 0
        for v in obj:
            m, k = mask_obj(v)
            out.append(m)
            n += k
        return out, n
    if isinstance(obj, dict):
        out_d, n = {}, 0
        for key, v in obj.items():
            m, k = mask_obj(v)
            out_d[key] = m
            n += k
        return out_d, n
    return obj, 0
