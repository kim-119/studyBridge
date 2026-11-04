"""로그에 사용자 원문/LLM 출력/PDF 텍스트를 남기지 않기 위한 지문(fingerprint).

원문 대신 길이 + sha256 앞 12자만 남긴다. 같은 입력을 추적(상관)할 수는 있지만 내용은 복원할 수 없다.
"""
import hashlib
from typing import Any


def fp(text: Any) -> str:
    s = "" if text is None else str(text)
    return f"len={len(s)} sha={hashlib.sha256(s.encode('utf-8', 'replace')).hexdigest()[:12]}"
