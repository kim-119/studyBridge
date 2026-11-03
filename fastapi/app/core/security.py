"""
내부 API 인증 모듈 (fail-closed).

Spring Boot가 FastAPI를 호출할 때 Authorization: Bearer {AI_SERVER_API_KEY} 헤더를 검사한다.
- AI_SERVER_API_KEY 미설정/너무 짧음 → 503 INTERNAL_AUTH_NOT_CONFIGURED (예전: 인증 생략 = fail-open).
  운영 ai07 은 APP_ENV=local 로 돌기 때문에 환경 이름으로 '개발 모드'를 판별하지 않는다. 우회 스위치는 없다.
- 비교는 hmac.compare_digest(상수 시간). 키는 호출 시점에 읽는다(재설정/테스트 반영).
- IP/loopback 은 인증을 대체하지 않는다: reverse SSH(EC2 127.0.0.1:18000 → ai07 127.0.0.1:8000)와
  EC2 docker bridge socat 경유 요청도 ai07 에서는 127.0.0.1 로 보이기 때문이다.

학습 후보 관리(승인/거절/내보내기/통계)는 일반 내부 키만으로 수행할 수 없다:
verify_training_admin = 내부 Bearer + X-Training-Admin-Token(TRAINING_ADMIN_TOKEN, 내부 키와 달라야 함)
                        + X-Actor-Id + X-Actor-Role(training_reviewer|training_admin) + X-Request-Id.
"""
from __future__ import annotations

import hmac
import os
import re
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, status

import app.core.config  # noqa: F401 — .env 로드(load_dotenv) 부작용 보장

MIN_INTERNAL_KEY_LEN = 24
MIN_ADMIN_TOKEN_LEN = 32
_ACTOR_RE = re.compile(r"^[A-Za-z0-9._:@\-]{3,64}$")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:\-]{8,128}$")
ADMIN_ROLES = ("training_reviewer", "training_admin")


def _deny(code: int, error_code: str, message: str) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"} if code == status.HTTP_401_UNAUTHORIZED else None
    return HTTPException(status_code=code, detail={"errorCode": error_code, "message": message}, headers=headers)


def internal_key() -> str:
    return (os.getenv("AI_SERVER_API_KEY") or "").strip()


def check_bearer(authorization: Optional[str]) -> None:
    key = internal_key()
    if len(key) < MIN_INTERNAL_KEY_LEN:
        raise _deny(status.HTTP_503_SERVICE_UNAVAILABLE, "INTERNAL_AUTH_NOT_CONFIGURED",
                    "AI 서버 내부 인증이 구성되지 않아 요청을 처리할 수 없습니다.")
    if not authorization:
        raise _deny(status.HTTP_401_UNAUTHORIZED, "AUTH_HEADER_MISSING",
                    "AI 서버 인증에 실패했습니다. Authorization 헤더가 없습니다.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip().encode(), key.encode()):
        raise _deny(status.HTTP_401_UNAUTHORIZED, "AUTH_TOKEN_INVALID",
                    "AI 서버 인증에 실패했습니다. 토큰이 올바르지 않습니다.")


async def verify_internal_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    """FastAPI Depends 용 내부 토큰 검증(fail-closed).

    Raises:
        HTTPException 503: 서버에 내부 키가 구성되지 않음
        HTTPException 401: 토큰이 없거나 일치하지 않음
    """
    check_bearer(authorization)


@dataclass(frozen=True)
class AdminPrincipal:
    actor_id: str
    role: str
    request_id: str


async def verify_training_admin(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_training_admin_token: str | None = Header(default=None, alias="X-Training-Admin-Token"),
    x_actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
    x_actor_role: str | None = Header(default=None, alias="X-Actor-Role"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> AdminPrincipal:
    check_bearer(authorization)
    admin = (os.getenv("TRAINING_ADMIN_TOKEN") or "").strip()
    if len(admin) < MIN_ADMIN_TOKEN_LEN or hmac.compare_digest(admin.encode(), internal_key().encode()):
        # 관리자 토큰이 없거나 일반 내부 키와 같으면 권한 분리가 성립하지 않는다 → 관리 API 전체 차단.
        raise _deny(status.HTTP_503_SERVICE_UNAVAILABLE, "ADMIN_AUTH_NOT_CONFIGURED",
                    "학습 후보 관리 권한이 구성되지 않았습니다.")
    if not x_training_admin_token or not hmac.compare_digest(x_training_admin_token.strip().encode(), admin.encode()):
        raise _deny(status.HTTP_403_FORBIDDEN, "ADMIN_TOKEN_INVALID", "학습 후보 관리 권한이 없습니다.")
    if not x_actor_id or not _ACTOR_RE.match(x_actor_id):
        raise _deny(status.HTTP_400_BAD_REQUEST, "ACTOR_ID_INVALID", "X-Actor-Id 가 필요합니다.")
    if x_actor_role not in ADMIN_ROLES:
        raise _deny(status.HTTP_403_FORBIDDEN, "ACTOR_ROLE_INVALID", "허용되지 않은 역할입니다.")
    if not x_request_id or not _REQUEST_ID_RE.match(x_request_id):
        raise _deny(status.HTTP_400_BAD_REQUEST, "REQUEST_ID_INVALID", "X-Request-Id 가 필요합니다.")
    return AdminPrincipal(actor_id=x_actor_id, role=x_actor_role, request_id=x_request_id)


def require_role(principal: AdminPrincipal, *roles: str) -> None:
    if principal.role not in roles:
        raise _deny(status.HTTP_403_FORBIDDEN, "ACTOR_ROLE_INSUFFICIENT", "이 작업에 필요한 역할이 아닙니다.")
