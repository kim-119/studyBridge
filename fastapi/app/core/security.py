"""
내부 API 인증 모듈.
Spring Boot가 FastAPI를 호출할 때 Authorization: Bearer {AI_SERVER_API_KEY} 헤더를 검사한다.
AI_SERVER_API_KEY가 설정되지 않은 경우 인증을 건너뛴다 (개발 편의).
"""
from fastapi import Header, HTTPException, status

from app.core.config import AI_SERVER_API_KEY


async def verify_internal_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    """
    FastAPI Depends로 사용하는 내부 토큰 검증 함수.

    AI_SERVER_API_KEY 환경변수가 설정된 경우에만 검사한다.
    미설정이면 개발/테스트 편의를 위해 인증을 통과시킨다.

    Args:
        authorization: 'Authorization' 헤더 값 (예: 'Bearer secret-key')

    Raises:
        HTTPException 401: 토큰이 없거나 일치하지 않을 때
    """
    if not AI_SERVER_API_KEY:
        # 환경변수 미설정 → 개발 모드, 인증 스킵
        return

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AI 서버 인증에 실패했습니다. Authorization 헤더가 없습니다.",
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != AI_SERVER_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AI 서버 인증에 실패했습니다. 토큰이 올바르지 않습니다.",
        )
