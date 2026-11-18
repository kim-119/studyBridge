"""
Ollama 응답 정제(sanitize) + 빈 응답 판정 유틸 — qwen3 thinking 대응.

목적:
- qwen3 등 thinking 계열 모델이 <think>...</think> 추론 블록만 반환하거나,
  추론 블록 뒤 본문이 비는 경우를 '빈 응답(blank)'으로 정확히 판정한다.
- 사용자에게 chain-of-thought(추론 과정)를 노출하지 않도록 본문만 추출한다.

설계 원칙:
- 순수 함수 모음(네트워크/LLM/DB 호출·부작용 없음). ollama_client 등이 호출한다.
- 본문이 정상이면 원문을 최대한 보존하고 추론 블록만 제거한다.
- 미닫힌 <think>(토큰 소진으로 잘린 경우) 같은 비정상 케이스도 안전하게 처리한다.
- secret/prompt 원문을 다루지 않는다(텍스트 변환만 수행).
"""
from __future__ import annotations

import re
from typing import Tuple

# 정상 닫힘: <think ...> ... </think>
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
# 대체 추론 마커: <thinking>...</thinking>, <reasoning>...</reasoning>, <|thinking|>... 등
_ALT_REASONING_RE = re.compile(
    r"<\|?\s*(?:thinking|reasoning|thought)\s*\|?>.*?</\|?\s*(?:thinking|reasoning|thought)\s*\|?>",
    re.IGNORECASE | re.DOTALL,
)
# 열림 태그 존재 여부
_THINK_OPEN_RE = re.compile(r"<think\b", re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r"</think", re.IGNORECASE)
# 미닫힌 <think> ~ 끝까지(추론 도중 잘림)
_THINK_OPEN_TO_END_RE = re.compile(r"<think\b[^>]*>.*\Z", re.IGNORECASE | re.DOTALL)
# 열림 없이 떠다니는 선두 </think> 제거
_THINK_DANGLING_CLOSE_RE = re.compile(r"^\s*</think\s*>", re.IGNORECASE)


def strip_think_tags(text: str) -> str:
    """추론(<think>/<reasoning>) 블록을 제거하고 사용자에게 보일 본문만 남긴다.

    - 정상 닫힌 블록은 통째로 제거.
    - 닫힘 없이 열린 think는 (토큰 소진 절단으로 보고) 끝까지 제거.
    - 본문이 없으면 빈 문자열을 반환한다(빈 응답 판정은 is_blank_response가 담당).
    """
    if not text:
        return ""
    t = str(text)
    t = _THINK_BLOCK_RE.sub(" ", t)
    t = _ALT_REASONING_RE.sub(" ", t)
    # 닫힘 없이 열린 think만 남았으면 끝까지 추론으로 간주하고 제거
    if _THINK_OPEN_RE.search(t) and not _THINK_CLOSE_RE.search(t):
        t = _THINK_OPEN_TO_END_RE.sub(" ", t)
    t = _THINK_DANGLING_CLOSE_RE.sub(" ", t)
    # 남은 깨진 think 토큰 흔적 정리
    t = re.sub(r"</?think\s*>", " ", t, flags=re.IGNORECASE)
    return t.strip()


def is_blank_response(text: str) -> bool:
    """think 제거 후 사용자에게 보일 본문이 사실상 비었는지 판정한다.

    blank 조건: None / "" / 공백만 / 추론 블록만 있고 본문이 없는 경우.
    """
    if text is None:
        return True
    if not str(text).strip():
        return True
    return not strip_think_tags(text)


def sanitize_and_check(text: str) -> Tuple[str, bool]:
    """(정제된 본문, is_blank) 튜플을 반환한다. ollama_client 호출용 단축 함수."""
    cleaned = strip_think_tags(text or "")
    return cleaned, (not cleaned)
