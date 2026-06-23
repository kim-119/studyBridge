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

    # 3. 최외곽 여는 괄호({ 또는 [) 기준으로 마지막 닫는 괄호까지 추출.
    #    (객체-우선 JSON에서 중첩 배열을 잘못 잡아채지 않도록 '바깥 구조'만 본다.)
    first_obj = text.find('{')
    first_arr = text.find('[')
    if first_obj != -1 and (first_arr == -1 or first_obj < first_arr):
        pairs = [('{', '}')]
    elif first_arr != -1:
        pairs = [('[', ']')]
    else:
        pairs = []
    for start_char, end_char in pairs:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

    # 4. 잘린(truncated) JSON 복구 — max_tokens 초과로 응답이 중간에 끊긴 경우,
    #    열린 문자열/객체/배열을 닫아 가능한 만큼 파싱한다(부분 결과라도 살린다).
    repaired = _repair_truncated_json(text)
    if repaired is not None:
        logger.info("JSON 복구 성공(truncated). 원본 길이: %d", len(text))
        return repaired

    logger.warning("JSON 추출 실패. 원본 텍스트 길이: %d", len(text))
    return None


def _repair_truncated_json(text: str) -> Optional[Any]:
    """가장 바깥 '{'(또는 '[')부터 시작해, 잘린 JSON의 열린 구조를 닫아 파싱을 시도한다.

    - 문자열 안/밖을 추적하며 열린 따옴표를 닫고, 마지막 미완성 토큰(콜론 뒤 값 없음,
      트레일링 콤마)을 제거한 뒤 남은 '{'/'[' 를 역순으로 닫는다.
    - 완벽한 복구가 아니라 'best-effort'다. 실패하면 None.
    """
    start = text.find('{')
    if start == -1:
        start = text.find('[')
    if start == -1:
        return None
    s = text[start:]

    out = []
    stack = []
    in_str = False
    escaped = False
    for ch in s:
        if in_str:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
        elif ch in '{[':
            stack.append(ch)
            out.append(ch)
        elif ch in '}]':
            if stack:
                stack.pop()
            out.append(ch)
        else:
            out.append(ch)

    buf = "".join(out)
    if in_str:               # 열린 문자열 닫기
        buf += '"'
    # 트레일링 콤마/콜론 정리: 마지막 의미 없는 꼬리 제거
    buf = re.sub(r'[\s,]*$', '', buf)
    buf = re.sub(r':\s*$', ': null', buf)   # "key": <끊김> → null
    buf = re.sub(r',\s*$', '', buf)
    # 남은 열린 괄호를 역순으로 닫기
    for opener in reversed(stack):
        buf += '}' if opener == '{' else ']'
    try:
        return json.loads(buf)
    except json.JSONDecodeError:
        # 마지막 콤마 이후 미완성 항목까지 잘라내고 한 번 더 시도
        cut = max(buf.rfind('},'), buf.rfind('],'))
        if cut != -1:
            trimmed = buf[:cut + 1]
            depth_close = []
            in_str2 = escaped2 = False
            st2 = []
            for ch in trimmed:
                if in_str2:
                    if escaped2: escaped2 = False
                    elif ch == '\\': escaped2 = True
                    elif ch == '"': in_str2 = False
                    continue
                if ch == '"': in_str2 = True
                elif ch in '{[': st2.append(ch)
                elif ch in '}]':
                    if st2: st2.pop()
            for opener in reversed(st2):
                trimmed += '}' if opener == '{' else ']'
            try:
                return json.loads(trimmed)
            except json.JSONDecodeError:
                return None
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
