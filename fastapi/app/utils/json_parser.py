"""
LLM 응답에서 JSON을 안전하게 파싱하는 유틸리티.
LLM은 마크다운 코드 블록, 불필요한 텍스트 등을 포함할 수 있으므로 정제 후 파싱한다.
"""
import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


def extract_json(text: str) -> Optional[Any]:
    """
    LLM 출력에서 JSON을 추출하여 파싱한다.

    시도 순서:
    1. 전체 텍스트 직접 파싱
    2. ```json ... ``` 코드 블록 추출
    3. { 또는 [ 로 시작하는 부분 탐색
    """
    if not text or not text.strip():
        return None

    # 1. 직접 파싱
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # 2. 마크다운 코드 블록 추출
    code_block = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if code_block:
        try:
            return json.loads(code_block.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. 첫 번째 { 또는 [ 에서 마지막 } 또는 ] 까지 추출
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

    logger.warning("JSON 추출 실패. 원본 텍스트 길이: %d", len(text))
    return None


def safe_parse_quiz_json(text: str) -> Optional[list]:
    """
    LLM 출력에서 퀴즈 JSON 배열을 파싱한다.
    result가 dict이면 questions 키에서 배열을 추출한다.
    """
    parsed = extract_json(text)
    if parsed is None:
        return None

    if isinstance(parsed, list):
        return parsed

    if isinstance(parsed, dict):
        for key in ("questions", "quiz", "items", "data"):
            if key in parsed and isinstance(parsed[key], list):
                return parsed[key]

    return None
