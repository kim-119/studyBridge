"""경로 단위 내부 인증(deny-by-default) — Phase B2.

모든 HTTP 요청을 라우팅 전에 분류한다. IP/loopback/reverse SSH 출발지는 인증 판단에 쓰지 않는다
(ai07 에서는 EC2 터널·docker bridge 경유 요청이 전부 127.0.0.1 로 보인다).

분류(경로는 ASGI scope["path"] = 라우팅과 같은 디코딩 결과로 판정 — %인코딩 우회 불가):
  PUBLIC        GET/HEAD /health, /api/health, /api/ai/health, /api/native-engine/health  → 항상 통과(liveness)
  DOCS          /docs, /redoc, /docs/oauth2-redirect → AI_DOCS_ENABLED=true 가 아니면 404(운영 비공개).
                켜도 Bearer 필요.
  SPRING_COMPAT 현재 운영 Spring 이 Bearer 없이 부르는 21개 경로 + GET /openapi.json(Spring 프로브·ops 헬스체크)
  PROTECTED     그 밖의 전부(미등록 경로 포함) → 모드와 무관하게 Bearer 필수.

모드(AI_INTERNAL_AUTH_MODE):
  report(기본)  SPRING_COMPAT 은 토큰이 없거나 틀려도 통과시키고 사유를 집계·기록한다(운영 호환: EC2 PR #117 배포 전
                Spring 은 28곳 중 3곳만 Bearer 를 보내고, Secondary 는 Spring 과 키가 다르다). PROTECTED 는 강제.
  enforce       SPRING_COMPAT 도 Bearer 필수. 단 AI_INTERNAL_AUTH_UNAUTH_ALLOWLIST(기본 POST /api/extract,
                POST /api/ai/intent/route — EC2 RestTemplate/intentRouterWebClient 가 아직 Bearer 를 안 보냄)는
                '토큰 없음'만 허용(틀린 토큰은 401). EC2 수정 후 이 env 를 비우면 예외 0.
공통 fail-closed: 서버에 AI_SERVER_API_KEY 가 없거나 짧으면 보호 경로는 503(모드 무관). 키 회전용 AI_SERVER_API_KEY_PREVIOUS 허용.
로그에는 경로 분류·방법·사유 코드만 남긴다(토큰·본문 원문 금지).
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
import threading
import time
from collections import Counter
from typing import Dict, Optional, Tuple

logger = logging.getLogger("studybridge.internal_auth")

MIN_KEY_LEN = 24
PUBLIC_PATHS = frozenset({"/health", "/api/health", "/api/ai/health", "/api/native-engine/health"})
DOCS_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect"})
OPENAPI_PATH = "/openapi.json"

# EC2 정적 분석(LEARNING_LOOP_EC2_CANONICAL_V1 §6)과 ai07 라우트 덤프를 대조한 SPRING_INTERNAL 무인증 21개.
SPRING_COMPAT_POST = frozenset({
    "/api/ai/multi-chat", "/api/ai/multi-chat/stream", "/api/ai/predict-study-time", "/api/ai/feedback",
    "/api/ai/summary", "/api/ai/quiz", "/api/ai/question", "/api/ai/quiz/generate", "/api/ai/roadmap/generate",
    "/api/ai/keyword/define", "/api/ai/material/classify", "/api/ai/major-analysis/note", "/api/ai/intent/route",
    "/api/ai/study-journal/validate", "/api/ai/planner/analyze", "/api/ai/planner/analyze-semantic",
    "/api/ai/planner/assist", "/api/ai/review/wrong-note-feedback", "/api/ai/review/variant-question",
    "/api/ai/review-needed", "/api/extract",
})
_DEFAULT_UNAUTH_ALLOWLIST = "POST /api/extract,POST /api/ai/intent/route"

PUBLIC, DOCS, COMPAT, PROTECTED = "PUBLIC", "DOCS", "SPRING_COMPAT", "PROTECTED"

_stats_lock = threading.Lock()
_stats: Counter = Counter()
_last_log = {"t": 0.0}


def _truthy(v: Optional[str]) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def mode() -> str:
    m = (os.getenv("AI_INTERNAL_AUTH_MODE") or "report").strip().lower()
    return m if m in ("report", "enforce") else "enforce"   # 알 수 없는 값 = 더 엄격한 쪽


def _unauth_allowlist() -> frozenset:
    raw = os.getenv("AI_INTERNAL_AUTH_UNAUTH_ALLOWLIST")
    raw = _DEFAULT_UNAUTH_ALLOWLIST if raw is None else raw
    out = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        method, _, path = part.partition(" ")
        method, path = method.strip().upper(), path.strip()
        # 허용 목록은 SPRING_COMPAT 범위 안의 정확한 경로만 — 오타/와일드카드로 보호 경로를 열 수 없다.
        if method == "POST" and path in SPRING_COMPAT_POST:
            out.add((method, path))
        else:
            logger.error("[INTERNAL_AUTH] ignored invalid AI_INTERNAL_AUTH_UNAUTH_ALLOWLIST entry")
    return frozenset(out)


def classify(method: str, path: str) -> str:
    m = method.upper()
    if m in ("GET", "HEAD") and path in PUBLIC_PATHS:
        return PUBLIC
    if path in DOCS_PATHS:
        return DOCS
    if (m in ("GET", "HEAD") and path == OPENAPI_PATH) or (m == "POST" and path in SPRING_COMPAT_POST):
        return COMPAT
    return PROTECTED


def _keys() -> Tuple[str, ...]:
    keys = []
    for n in ("AI_SERVER_API_KEY", "AI_SERVER_API_KEY_PREVIOUS"):
        k = (os.getenv(n) or "").strip()
        if len(k) >= MIN_KEY_LEN:
            keys.append(k)
    return tuple(keys)


def token_status(authorization: Optional[str]) -> str:
    """OK | MISSING | MALFORMED | INVALID | NOT_CONFIGURED (상수 시간 비교)."""
    keys = _keys()
    if not keys or len((os.getenv("AI_SERVER_API_KEY") or "").strip()) < MIN_KEY_LEN:
        return "NOT_CONFIGURED"
    if not authorization:
        return "MISSING"
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return "MALFORMED"
    t = token.strip().encode()
    ok = False
    for k in keys:
        ok |= hmac.compare_digest(t, k.encode())
    return "OK" if ok else "INVALID"


def decide(method: str, path: str, authorization: Optional[str]) -> Tuple[bool, int, str, str]:
    """(허용, 거부 시 HTTP 코드, 사유 코드, 분류)."""
    cls = classify(method, path)
    if cls == PUBLIC:
        return True, 200, "PUBLIC", cls
    if cls == DOCS and not _truthy(os.getenv("AI_DOCS_ENABLED")):
        return False, 404, "DOCS_DISABLED", cls
    st = token_status(authorization)
    if st == "OK":
        return True, 200, "AUTH_OK", cls
    if st == "NOT_CONFIGURED":
        return False, 503, "INTERNAL_AUTH_NOT_CONFIGURED", cls
    if cls == COMPAT:
        if mode() == "report":
            return True, 200, f"COMPAT_TOLERATED_{st}", cls
        if st == "MISSING" and (method.upper(), path) in _unauth_allowlist():
            return True, 200, "LEGACY_UNAUTH_ALLOWLISTED", cls
    code = {"MISSING": "AUTH_HEADER_MISSING", "MALFORMED": "AUTH_TOKEN_INVALID", "INVALID": "AUTH_TOKEN_INVALID"}[st]
    return False, 401, code, cls


def _record(cls: str, reason: str, path: str) -> None:
    if reason in ("PUBLIC", "AUTH_OK"):
        return
    with _stats_lock:
        _stats[(cls, reason, path)] += 1
        now = time.time()
        if now - _last_log["t"] < 60:
            return
        _last_log["t"] = now
        top = _stats.most_common(12)
    logger.warning("[INTERNAL_AUTH] mode=%s summary=%s", mode(),
                   ";".join(f"{c}:{r}:{p}={n}" for (c, r, p), n in top))


def stats_snapshot() -> Dict[str, int]:
    with _stats_lock:
        return {f"{c}|{r}|{p}": n for (c, r, p), n in _stats.items()}


_MESSAGES = {
    401: "AI 서버 인증에 실패했습니다.",
    404: "Not Found",
    503: "AI 서버 내부 인증이 구성되지 않아 요청을 처리할 수 없습니다.",
}


class InternalAuthMiddleware:
    """순수 ASGI 미들웨어(스트리밍 응답을 버퍼링하지 않는다). 거부 시 본문을 읽기 전에 응답한다."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        method = scope.get("method", "GET")
        path = scope.get("path", "") or ""
        auth = None
        for k, v in scope.get("headers") or ():
            if k == b"authorization":
                auth = v.decode("latin-1")
                break
        try:
            allowed, status, reason, cls = decide(method, path, auth)
        except Exception:  # noqa: BLE001 — 보안 판정 오류는 거부(fail-closed)
            allowed, status, reason, cls = False, 503, "INTERNAL_AUTH_ERROR", PROTECTED
        _record(cls, reason, path)
        if allowed:
            return await self.app(scope, receive, send)
        if status == 404:
            body = json.dumps({"detail": "Not Found"}).encode()
        else:
            body = json.dumps({"detail": {"errorCode": reason, "message": _MESSAGES.get(status, "")}},
                              ensure_ascii=False).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
        if status == 401:
            headers.append((b"www-authenticate", b"Bearer"))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
