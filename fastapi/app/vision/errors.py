"""구조화된 Vision API 오류. 메시지에는 사용자 입력(질문/이미지)을 절대 넣지 않는다."""
from __future__ import annotations


class VisionError(Exception):
    """status/code/retryable 를 가진 클라이언트 구별 가능한 오류."""

    def __init__(self, status: int, code: str, message: str, *, retryable: bool = False,
                 retry_after: int | None = None) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable
        self.retry_after = retry_after


# 코드 → (HTTP status, retryable). 계약 문서와 테스트가 이 표를 기준으로 한다.
ERROR_CODES: dict[str, tuple[int, bool]] = {
    "VISION_DISABLED": (503, False),
    "VISION_AUTH_NOT_CONFIGURED": (503, False),
    "VISION_UNAUTHORIZED": (401, False),
    "VISION_BODY_TOO_LARGE": (413, False),
    "VISION_INVALID_JSON": (400, False),
    "VISION_INVALID_FIELD": (422, False),
    "VISION_QUESTION_EMPTY": (422, False),
    "VISION_QUESTION_TOO_LONG": (422, False),
    "VISION_IMAGE_MISSING": (422, False),
    "VISION_UNSUPPORTED_MIME": (415, False),
    "VISION_INVALID_BASE64": (422, False),
    "VISION_IMAGE_TOO_LARGE": (413, False),
    "VISION_MIME_MISMATCH": (415, False),
    "VISION_IMAGE_CORRUPT": (422, False),
    "VISION_IMAGE_DIMENSIONS": (422, False),
    "VISION_DUPLICATE_REQUEST": (409, False),
    "VISION_GROUP_LIMIT": (429, True),
    "VISION_QUEUE_FULL": (429, True),
    "VISION_QUEUE_TIMEOUT": (503, True),
    "VISION_SHUTTING_DOWN": (503, True),
    "VISION_INFERENCE_TIMEOUT": (504, True),
    "VISION_RESOURCE_EXHAUSTED": (503, True),
    "VISION_MODEL_UNAVAILABLE": (503, False),
    "VISION_BACKEND_UNAVAILABLE": (503, True),
    "VISION_EMPTY_RESPONSE": (502, True),
    "VISION_BACKEND_ERROR": (502, True),
    "VISION_CLIENT_CANCELLED": (499, False),
    "VISION_INTERNAL_ERROR": (500, True),
}


def vision_error(code: str, message: str, *, retry_after: int | None = None) -> VisionError:
    status, retryable = ERROR_CODES[code]
    return VisionError(status, code, message, retryable=retryable, retry_after=retry_after)
