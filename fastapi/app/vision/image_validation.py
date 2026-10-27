"""요청 필드·이미지 검증. 메타데이터를 먼저 보고, 디코딩/픽셀 로드는 마지막에 한다.

이미지는 메모리(BytesIO)에서만 다루고 임시 파일을 만들지 않는다. 통과한 이미지는
RGB JPEG 로 재인코딩해 EXIF 등 메타데이터를 제거한 바이트만 모델로 보낸다.
"""
from __future__ import annotations

import base64
import binascii
import io
import re
import warnings
from dataclasses import dataclass
from typing import Any

from PIL import Image, UnidentifiedImageError

from app.vision.config import VisionSettings
from app.vision.errors import vision_error

_ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")
_B64_CHARS_RE = re.compile(r"^[A-Za-z0-9+/]*={0,2}$")
_DATA_URI_RE = re.compile(r"^data:([a-zA-Z0-9/+.\-]+);base64,", re.IGNORECASE)

# MIME → Pillow format, magic bytes
_FORMATS: dict[str, tuple[str, tuple[bytes, ...]]] = {
    "image/jpeg": ("JPEG", (b"\xff\xd8\xff",)),
    "image/png": ("PNG", (b"\x89PNG\r\n\x1a\n",)),
    "image/webp": ("WEBP", (b"RIFF",)),
}


@dataclass
class VisionRequest:
    request_id: str
    group_id: str
    stream_id: str
    sharer_user_id: str
    asker_user_id: str
    question: str
    image_b64: str
    mime: str


@dataclass
class ValidatedImage:
    jpeg_bytes: bytes
    width: int
    height: int
    source_bytes: int


def _ident(payload: dict[str, Any], key: str, *, required: bool) -> str:
    """Spring 의 Long/String ID 둘 다 허용(문자열로 정규화). 값 자체는 오류 메시지에 넣지 않는다."""
    val = payload.get(key)
    if val is None or val == "":
        if required:
            raise vision_error("VISION_INVALID_FIELD", f"'{key}' 필드가 필요합니다.")
        return ""
    if isinstance(val, bool) or not isinstance(val, (int, str)):
        raise vision_error("VISION_INVALID_FIELD", f"'{key}' 는 정수 또는 문자열이어야 합니다.")
    s = str(val)
    if not _ID_RE.match(s):
        raise vision_error("VISION_INVALID_FIELD", f"'{key}' 형식이 올바르지 않습니다.")
    return s


def parse_request(payload: Any, settings: VisionSettings) -> VisionRequest:
    """JSON 객체 → VisionRequest. 이미지 디코딩 전 단계의 값싼 검증만 한다."""
    if not isinstance(payload, dict):
        raise vision_error("VISION_INVALID_JSON", "요청 바디는 JSON 객체여야 합니다.")

    request_id = _ident(payload, "requestId", required=True)
    group_id = _ident(payload, "groupId", required=True)
    stream_id = _ident(payload, "streamId", required=False)
    sharer = _ident(payload, "sharerUserId", required=False)
    asker = _ident(payload, "askerUserId", required=False)

    question = payload.get("question")
    if question is not None and not isinstance(question, str):
        raise vision_error("VISION_INVALID_FIELD", "'question' 은 문자열이어야 합니다.")
    question = (question or "").strip()
    if not question:
        raise vision_error("VISION_QUESTION_EMPTY", "질문이 비어 있습니다.")
    if len(question) > settings.max_question_chars:
        raise vision_error("VISION_QUESTION_TOO_LONG",
                           f"질문은 최대 {settings.max_question_chars}자까지 허용됩니다.")

    image = payload.get("image")
    if image is None or image == "":
        raise vision_error("VISION_IMAGE_MISSING", "이미지가 없습니다.")
    if not isinstance(image, str):
        raise vision_error("VISION_INVALID_FIELD", "'image' 는 Base64 문자열이어야 합니다.")

    mime = payload.get("mime")
    if not isinstance(mime, str) or not mime.strip():
        raise vision_error("VISION_UNSUPPORTED_MIME", "'mime' 필드가 필요합니다.")
    mime = mime.strip().lower()
    if mime == "image/jpg":
        mime = "image/jpeg"

    m = _DATA_URI_RE.match(image)
    if m:
        if m.group(1).lower().replace("image/jpg", "image/jpeg") != mime:
            raise vision_error("VISION_MIME_MISMATCH", "data URI 의 MIME 과 'mime' 이 다릅니다.")
        image = image[m.end():]

    if mime not in settings.allowed_mimes or mime not in _FORMATS:
        raise vision_error("VISION_UNSUPPORTED_MIME",
                           f"지원하지 않는 MIME 입니다. 허용: {', '.join(settings.allowed_mimes)}")

    # 디코딩 전에 길이로 상한 판단: base64 는 4글자당 3바이트
    if (len(image) // 4) * 3 > settings.max_image_bytes + 3:
        raise vision_error("VISION_IMAGE_TOO_LARGE",
                           f"이미지는 최대 {settings.max_image_bytes} 바이트까지 허용됩니다.")

    return VisionRequest(request_id, group_id, stream_id, sharer, asker, question, image, mime)


def decode_and_validate_image(image_b64: str, mime: str, settings: VisionSettings) -> ValidatedImage:
    """Base64 디코딩 → magic 확인 → 헤더로 해상도 확인(픽셀 로드 전) → 로드 → RGB JPEG 재인코딩."""
    compact = "".join(image_b64.split())
    if not compact or len(compact) % 4 != 0 or not _B64_CHARS_RE.match(compact):
        raise vision_error("VISION_INVALID_BASE64", "Base64 인코딩이 올바르지 않습니다.")
    try:
        raw = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        raise vision_error("VISION_INVALID_BASE64", "Base64 인코딩이 올바르지 않습니다.") from None
    if len(raw) > settings.max_image_bytes:
        raise vision_error("VISION_IMAGE_TOO_LARGE",
                           f"이미지는 최대 {settings.max_image_bytes} 바이트까지 허용됩니다.")

    fmt, magics = _FORMATS[mime]
    if not any(raw.startswith(mg) for mg in magics) or (fmt == "WEBP" and raw[8:12] != b"WEBP"):
        raise vision_error("VISION_MIME_MISMATCH", "선언된 MIME 과 실제 이미지 형식이 다릅니다.")

    try:
        with warnings.catch_warnings():
            # DecompressionBombWarning 을 오류로 승격(전역 Image.MAX_IMAGE_PIXELS 는 건드리지 않음)
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(raw))
            if img.format != fmt:
                raise vision_error("VISION_MIME_MISMATCH", "선언된 MIME 과 실제 이미지 형식이 다릅니다.")
            w, h = img.size  # 헤더만 읽은 상태
            if w < settings.min_side or h < settings.min_side:
                raise vision_error("VISION_IMAGE_DIMENSIONS", f"이미지가 너무 작습니다(최소 {settings.min_side}px).")
            if max(w, h) > settings.max_long_side or w * h > settings.max_pixels:
                raise vision_error("VISION_IMAGE_DIMENSIONS",
                                   f"이미지 긴 변은 최대 {settings.max_long_side}px 입니다.")
            if getattr(img, "n_frames", 1) > 1:
                raise vision_error("VISION_IMAGE_CORRUPT", "다중 프레임 이미지는 지원하지 않습니다.")
            img.load()  # 잘린/손상 데이터는 여기서 예외
            rgb = img.convert("RGB")
            out = io.BytesIO()
            rgb.save(out, format="JPEG", quality=90)  # EXIF/ICC 미포함 재인코딩
            jpeg = out.getvalue()
            img.close()
            rgb.close()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise vision_error("VISION_IMAGE_DIMENSIONS",
                           f"이미지 긴 변은 최대 {settings.max_long_side}px 입니다.") from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise vision_error("VISION_IMAGE_CORRUPT", "이미지를 해석할 수 없습니다(손상 또는 비정상).") from None
    finally:
        del raw
    return ValidatedImage(jpeg_bytes=jpeg, width=w, height=h, source_bytes=(len(compact) // 4) * 3)
