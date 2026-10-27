"""출발지 네트워크 가드 — 인증 없는 AI 엔드포인트를 신뢰 구간(loopback/사설망) 밖에서 못 쓰게 막는다.

배경(2026-10-28 점검): 같은 코드가 ai07(Primary, 127.0.0.1:8000 + EC2 SSH 터널)과 EC2 Secondary(0.0.0.0:8000)에
배포된다. 라우트 75개 중 내부 토큰 검사가 있는 것은 25개뿐이고, Spring 의 fastApiWebClient 는 Authorization 을
기본으로 붙이지 않는다. EC2 Secondary 는 인터넷에서 접근 가능했고 Ollama 터널(ai07 GPU)·OpenAI 키를 쓴다.
7일 접근 기록: 정상 호출자는 172.18.0.x(Spring 컨테이너)·127.0.0.1 뿐, 외부 IP 는 스캐너뿐이었다.

정책(AI_NETWORK_GUARD):
  enforce(기본) 출발지가 신뢰 구간이면 통과. 아니면 Authorization: Bearer AI_SERVER_API_KEY 가 맞을 때만 통과,
                그 외 403 AI_NETWORK_FORBIDDEN(본문을 읽기 전에 차단). GET /health, /api/health 만 예외.
  strict        출발지와 무관하게 Bearer 필수(예외 경로 제외). Spring 이 모든 AI 호출에 키를 붙인 뒤 전환용.
  log           차단 대상이어도 통과시키고 경고만 남긴다(롤아웃 확인용).
  off           비활성.
신뢰 구간: AI_TRUSTED_NETWORKS(쉼표 구분 CIDR). 기본은 loopback + RFC1918 + IPv6 ULA.
보안 장치이므로 판정 중 예외가 나면 '신뢰하지 않음'으로 처리한다(fail-closed). AI Gateway 의 fail-open(스케줄러
내부 오류 시 슬롯 없이 통과)은 이 가드 뒤에서만 일어나므로 인증·출발지 검사를 우회하지 않는다.
uvicorn 은 기본적으로 127.0.0.1 에서 온 요청의 X-Forwarded-For 만 반영하므로 외부 클라이언트는 출발지를 위조할 수 없다.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import logging
import os
import time
from typing import Iterable, List, Optional

logger = logging.getLogger("studybridge.network_guard")

_DEFAULT_TRUSTED = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"
_EXEMPT_GET = ("/health", "/api/health")
_LOG_INTERVAL_S = 10.0


def _parse_networks(spec: str) -> List[ipaddress._BaseNetwork]:
    nets = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            logger.error("[NET_GUARD] invalid network in AI_TRUSTED_NETWORKS ignored: %r", part)
    return nets


def is_trusted_host(host: Optional[str], networks: Iterable[ipaddress._BaseNetwork]) -> bool:
    if host is None:
        return True                       # unix socket 등 네트워크 출발지가 없는 연결(로컬)
    if host == "testclient":
        return True                       # Starlette TestClient(테스트 전송 계층에서만 생김)
    try:
        ip = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return any(ip in n for n in networks if n.version == ip.version)


def _bearer_ok(headers: dict) -> bool:
    key = os.getenv("AI_SERVER_API_KEY") or ""
    if not key:
        return False
    scheme, _, token = (headers.get("authorization") or "").partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(token.encode(), key.encode())


class NetworkGuardMiddleware:
    def __init__(self, app) -> None:
        self.app = app
        self._last_log = 0.0
        self.blocked = 0

    def _mode(self) -> str:
        return (os.getenv("AI_NETWORK_GUARD") or "enforce").strip().lower()

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        mode = self._mode()
        if mode == "off":
            return await self.app(scope, receive, send)
        path = scope.get("path") or ""
        method = scope.get("method") or "GET"
        try:
            if method in ("GET", "HEAD") and path in _EXEMPT_GET:
                return await self.app(scope, receive, send)
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
            client = scope.get("client")
            host = client[0] if client else None
            if _bearer_ok(headers):
                allowed = True
            elif mode == "strict":
                allowed = False
            else:
                allowed = is_trusted_host(host, _parse_networks(os.getenv("AI_TRUSTED_NETWORKS", _DEFAULT_TRUSTED)))
        except Exception as e:  # noqa: BLE001 — 보안 장치는 fail-closed
            logger.error("[NET_GUARD] evaluation error (%s) — denying", type(e).__name__)
            allowed, host = False, None
        if allowed:
            return await self.app(scope, receive, send)
        self.blocked += 1
        now = time.monotonic()
        if now - self._last_log >= _LOG_INTERVAL_S:
            self._last_log = now
            logger.warning("[NET_GUARD] %s client=%s %s %s (blocked_total=%s)",
                           "would block" if mode == "log" else "blocked", host, method, path, self.blocked)
        if mode == "log":
            return await self.app(scope, receive, send)
        if scope.get("type") == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps({"error": {"code": "AI_NETWORK_FORBIDDEN",
                                     "message": "이 네트워크에서는 AI 서버를 직접 호출할 수 없습니다.",
                                     "retryable": False}}, ensure_ascii=False).encode()
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
