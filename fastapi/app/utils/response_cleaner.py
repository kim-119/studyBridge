"""
LLM 응답 텍스트 정제 유틸리티.
마크다운, 특수문자, 과도한 개행 등을 제거한다.
"""
import re


def strip_markdown(text: str) -> str:
    """마크다운 헤더, 강조, 코드 블록을 제거하여 순수 텍스트로 반환한다."""
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"#{1,6}\s+", "", text)
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
    return text.strip()


def normalize_whitespace(text: str) -> str:
    """연속된 공백/개행을 정리한다."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def clean_llm_response(text: str) -> str:
    """LLM 응답에서 마크다운과 불필요한 공백을 제거한다."""
    return normalize_whitespace(strip_markdown(text))


def truncate_context(text: str, max_chars: int = 3000) -> str:
    """프롬프트 컨텍스트를 최대 길이로 잘라낸다."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...(이하 생략)"
