"""ASGI middleware: 요청 경로로 작업 유형을, 사용자/그룹 식별자로 공정성 키를 정한다.

순수 ASGI 로 작성했다(BaseHTTPMiddleware 는 StreamingResponse/SSE 취소 전파를 망가뜨린다).

식별자 신뢰 수준(2026-10-27 점검: ai07 은 127.0.0.1 바인딩 + EC2 SSH 터널로만 도달, nginx 는 /api/ 를 Spring 으로만
보낸다. 그러나 Spring 의 fastApiWebClient 는 Authorization 을 기본으로 붙이지 않고, 그룹스터디 멀티챗 payload 에는
사용자 id 가 없다):
  * 검증(verified)  — 내부 서비스 인증(Authorization: Bearer AI_SERVER_API_KEY)이 맞는 요청의
                      X-AI-User-Id / X-AI-Group-Id 헤더. Spring 이 JWT 에서 꺼낸 값을 넣는다는 계약. 키: u:/g:
  * 주장(claimed)   — JSON 본문의 userId/roomId 등. Spring 이 클라이언트 값을 그대로 옮겼을 수 있다. 키: cu:/cg:
  * 없음            — anon (사용자별 대기 상한 적용 제외)
주장 키는 공정성 정렬에만 쓴다. 우선순위 클래스는 경로로만 정해지고, 클래스 단위 상한(max_queue/max_concurrency/
전체 대기열)은 키와 무관하게 적용되므로 키를 조작해도 우선순위를 올리거나 클래스 상한을 넘을 수 없다.
본문은 application/json 이고 Content-Length ≤ 64KB 일 때만 읽어 재생(replay)한다 — 이미지/PDF 업로드나
스트리밍 업로드는 건드리지 않는다. 본문·헤더 값은 로그에 남기지 않는다.
"""
from __future__ import annotations

import hmac
import json
import os
import re
from typing import Any, Optional, Tuple

from app.ai_gateway.context import reset_context, set_context
from app.ai_gateway.policy import class_for_path

_MAX_SNIFF = 64 * 1024
_USER_KEYS = ("userId", "user_id", "memberId", "member_id", "askerUserId")
_GROUP_KEYS = ("roomId", "room_id", "groupId", "group_id", "studyRoomId", "sessionId")
_ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")


def _clean(v: Any) -> Optional[str]:
    if v is None or isinstance(v, (bool, dict, list)):
        return None
    s = str(v).strip()
    return s if s and _ID_RE.match(s) else None


def _ids_from_body(obj: Any) -> Tuple[Optional[str], Optional[str]]:
    if not isinstance(obj, dict):
        return None, None
    user = next((c for c in (_clean(obj.get(k)) for k in _USER_KEYS) if c), None)
    group = next((c for c in (_clean(obj.get(k)) for k in _GROUP_KEYS) if c), None)
    return user, group


def _internal_auth_ok(headers: dict) -> bool:
    key = os.getenv("AI_SERVER_API_KEY") or ""
    if not key:
        return False
    scheme, _, token = (headers.get("authorization") or "").partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(token.encode(), key.encode())


class AIGatewayContextMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path") or ""
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        user_key = group_key = None
        if _internal_auth_ok(headers):
            u, g = _clean(headers.get("x-ai-user-id")), _clean(headers.get("x-ai-group-id"))
            user_key = f"u:{u}" if u else None
            group_key = f"g:{g}" if g else None
        replay_receive = receive
        ctype = headers.get("content-type", "")
        try:
            clen = int(headers.get("content-length") or -1)
        except ValueError:
            clen = -1
        if user_key is None and scope.get("method") in ("POST", "PUT", "PATCH") \
                and "application/json" in ctype and 0 < clen <= _MAX_SNIFF:
            chunks = []
            early_msg = None
            more = True
            while more:
                msg = await receive()
                if msg["type"] != "http.request":
                    early_msg = msg          # disconnect 등: 그대로 앱에 넘긴다.
                    break
                chunks.append(msg.get("body", b""))
                more = msg.get("more_body", False)
            body = b"".join(chunks)
            try:
                bu, bg = _ids_from_body(json.loads(body or b"{}"))
            except (ValueError, UnicodeDecodeError):
                bu = bg = None
            user_key = f"cu:{bu}" if bu else None
            group_key = group_key or (f"cg:{bg}" if bg else None)
            sent = False

            async def replay_receive():  # type: ignore[no-redef]
                nonlocal sent
                if not sent:
                    sent = True
                    if early_msg is not None:
                        return early_msg
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()
        fair = user_key or group_key or "anon"
        tokens = set_context(class_for_path(path), fair, headers.get("x-request-id"), group_key or fair)
        try:
            return await self.app(scope, replay_receive, send)
        finally:
            reset_context(tokens)
