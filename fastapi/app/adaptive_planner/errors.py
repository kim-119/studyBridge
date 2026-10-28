"""구조화 오류. 인증·입력 무결성 오류는 규칙 추천으로 우회하지 않고 그대로 4xx 로 돌려준다.

message 에는 입력값 원문을 넣지 않는다(필드 경로만). 사용자 데이터가 오류 응답·로그로 새지 않게 한다.
"""
from __future__ import annotations

from typing import Optional

_STATUS = {
    "ADAPTIVE_DISABLED": 503,
    "ADAPTIVE_AUTH_NOT_CONFIGURED": 503,
    "ADAPTIVE_UNAUTHORIZED": 401,
    "ADAPTIVE_BODY_TOO_LARGE": 413,
    "ADAPTIVE_TOO_MANY_ITEMS": 413,
    "ADAPTIVE_INVALID_JSON": 400,
    "ADAPTIVE_INVALID_REQUEST": 400,
    "ADAPTIVE_INVALID_MODE": 400,
    "ADAPTIVE_INVALID_MINUTES": 400,
    "ADAPTIVE_INVALID_TIMEZONE": 400,
    "ADAPTIVE_INVALID_DATE": 400,
    "ADAPTIVE_INVALID_STATUS": 400,
    "ADAPTIVE_FIELD_NOT_ALLOWED": 400,
    "ADAPTIVE_DUPLICATE_ITEM_ID": 422,
    "ADAPTIVE_DUPLICATE_ORDER": 422,
    "ADAPTIVE_CURRENT_STEP_REQUIRED": 422,
    "ADAPTIVE_CURRENT_STEP_NOT_FOUND": 422,
    "ADAPTIVE_UNKNOWN_ITEM_REFERENCE": 422,
    "ADAPTIVE_TOO_MANY_REQUESTS": 429,
    "ADAPTIVE_OVERLOADED": 503,
    "ADAPTIVE_TIMEOUT": 504,
    "ADAPTIVE_CLIENT_CANCELLED": 499,
    "ADAPTIVE_INTERNAL_ERROR": 500,
}
_RETRYABLE = {"ADAPTIVE_TOO_MANY_REQUESTS", "ADAPTIVE_OVERLOADED", "ADAPTIVE_TIMEOUT", "ADAPTIVE_INTERNAL_ERROR"}


class AdaptiveError(Exception):
    def __init__(self, code: str, message: str, *, field: Optional[str] = None,
                 retry_after: Optional[int] = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.field = field
        self.status = _STATUS.get(code, 400)
        self.retryable = code in _RETRYABLE
        self.retry_after = retry_after if retry_after is not None else (3 if self.retryable else None)


def bad(code: str, message: str, field: Optional[str] = None) -> AdaptiveError:
    return AdaptiveError(code, message, field=field)
