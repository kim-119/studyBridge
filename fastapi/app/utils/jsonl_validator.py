"""
JSONL 파일 검증 유틸리티.
학습 데이터 내보내기 파일의 구조와 품질을 검증한다.

검증 항목:
- messages 배열 구조 (system/user/assistant 3개 role)
- 빈 content 없음
- 금지 필드 없음 (id, user_id, quality_score, metadata)
- PII 패턴 없음 (이메일, 전화번호)
"""
import json
import re
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FORBIDDEN_FIELDS = {"id", "user_id", "quality_score", "metadata", "session_id"}
_REQUIRED_ROLES = {"system", "user", "assistant"}
_PII_PATTERNS = [
    re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),  # email
    re.compile(r"01[016789]-?\d{3,4}-?\d{4}"),                         # KR mobile
    re.compile(r"\d{6}-[1-4]\d{6}"),                                   # KR resident number
]


class JsonlValidationResult:
    def __init__(self):
        self.total = 0
        self.valid = 0
        self.errors: list[str] = []

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, line_num: int, reason: str) -> None:
        self.errors.append(f"line {line_num}: {reason}")


def validate_jsonl_file(file_path: str) -> JsonlValidationResult:
    """
    JSONL 파일을 읽어 각 라인을 검증한다.

    Args:
        file_path: 검증할 JSONL 파일 경로

    Returns:
        JsonlValidationResult (total, valid, errors)
    """
    result = JsonlValidationResult()
    path = Path(file_path)

    if not path.exists():
        result.add_error(0, f"파일을 찾을 수 없습니다: {file_path}")
        return result

    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            result.total += 1
            errors = _validate_line(line, line_num)
            if errors:
                for e in errors:
                    result.add_error(line_num, e)
            else:
                result.valid += 1

    return result


def validate_jsonl_record(record: dict) -> list[str]:
    """단일 레코드를 검증하고 오류 목록을 반환한다."""
    errors = []

    messages = record.get("messages")
    if not isinstance(messages, list) or len(messages) < 2:
        errors.append("messages 배열이 없거나 2개 미만입니다.")
        return errors

    roles = {m.get("role") for m in messages}
    if not roles.issuperset({"user", "assistant"}):
        errors.append("messages에 user/assistant role이 모두 있어야 합니다.")

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if not content or not content.strip():
            errors.append(f"role={role}의 content가 비어 있습니다.")
        if _has_pii(content):
            errors.append(f"role={role}의 content에 PII가 포함될 수 있습니다.")

    forbidden = set(record.keys()) & _FORBIDDEN_FIELDS
    if forbidden:
        errors.append(f"금지 필드가 포함되어 있습니다: {forbidden}")

    return errors


def _validate_line(line: str, line_num: int) -> list[str]:
    try:
        record = json.loads(line)
    except json.JSONDecodeError as e:
        return [f"JSON 파싱 실패: {e}"]
    return validate_jsonl_record(record)


def _has_pii(text: str) -> bool:
    return any(p.search(text) for p in _PII_PATTERNS)
