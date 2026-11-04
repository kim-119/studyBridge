"""서명된 내부 계약 검증(HMAC-SHA256). 키가 없으면 항상 실패한다(fail-closed).

1) 본문 서명: X-AI-Contract-Signature = "v1=" + hex(HMAC(key, timestamp + "." + body))
   X-AI-Contract-Timestamp = unix seconds (±300s), 재전송 방지는 eventId 멱등으로 처리.
2) 데이터 범위(scope) 토큰: X-AI-Scope = base64url(json) + "." + base64url(HMAC(key, payload_b64))
   payload = {"v":1,"sub":pseudonymousUserKey,"materialIds":[...],"documentIds":[...],"iat":..,"exp":..,"rid":requestId}
   ai07 은 Spring 이 권한을 확인했다는 '서명된 주장'만 받고, 주장 밖 materialId 의 pgvector 검색을 거부한다.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

MIN_KEY_LEN = 32
MAX_SKEW_SECONDS = 300
MAX_SCOPE_TTL_SECONDS = 600
SCOPE_TYP = "ai-scope"
CONSENT_TYP = "training-consent"
# 용도별 키는 서로, 그리고 내부 Bearer 키와 달라야 한다. 한 키를 돌려쓰면 한쪽 유출이 다른 용도의 위조로 이어진다.
_SIGNING_ENVS = ("AI_SCOPE_SIGNING_KEY", "AI_TRAINING_CONSENT_SIGNING_KEY", "AI_TRAINING_SAMPLE_SIGNING_KEY")


class SignatureError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _key(env_name: str) -> bytes:
    k = (os.getenv(env_name) or "").strip()
    if len(k) < MIN_KEY_LEN:
        raise SignatureError("SIGNING_KEY_NOT_CONFIGURED")
    others = [n for n in _SIGNING_ENVS if n != env_name] + ["AI_SERVER_API_KEY"]
    for n in others:
        o = (os.getenv(n) or "").strip()
        if o and hmac.compare_digest(o.encode("utf-8"), k.encode("utf-8")):
            raise SignatureError("SIGNING_KEY_REUSED")
    return k.encode("utf-8")


def sign_body(body: bytes, timestamp: int, *, env_name: str = "AI_TRAINING_SAMPLE_SIGNING_KEY") -> str:
    mac = hmac.new(_key(env_name), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    return "v1=" + mac


def verify_body(body: bytes, signature: Optional[str], timestamp: Optional[str], *,
                env_name: str = "AI_TRAINING_SAMPLE_SIGNING_KEY", now: Optional[float] = None) -> None:
    key = _key(env_name)
    if not signature or not timestamp:
        raise SignatureError("SIGNATURE_MISSING")
    ts_s = str(timestamp).strip()
    if not ts_s.isdigit() or len(ts_s) > 12:              # 예전: 401자리 값 → OverflowError → 500
        raise SignatureError("SIGNATURE_TIMESTAMP_INVALID")
    ts = int(ts_s)
    if abs((now or time.time()) - ts) > MAX_SKEW_SECONDS:
        raise SignatureError("SIGNATURE_EXPIRED")
    expected = "v1=" + hmac.new(key, str(ts).encode() + b"." + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected.encode(), signature.strip().encode()):
        raise SignatureError("SIGNATURE_INVALID")


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@dataclass(frozen=True)
class Scope:
    sub: str
    material_ids: frozenset = field(default_factory=frozenset)
    document_ids: frozenset = field(default_factory=frozenset)
    request_id: Optional[str] = None
    exp: int = 0

    def allows_material(self, material_id: Optional[int]) -> bool:
        return material_id is not None and int(material_id) in self.material_ids

    def allows_document(self, document_id: Optional[str]) -> bool:
        return document_id is not None and str(document_id) in self.document_ids


def issue_scope_token(sub: str, material_ids: List[int], document_ids: List[str], *, request_id: str,
                      ttl: int = 120, env_name: str = "AI_SCOPE_SIGNING_KEY", now: Optional[float] = None) -> str:
    """테스트/계약 fixture 용 발급기(운영 발급은 EC2 Spring 책임)."""
    iat = int(now or time.time())
    payload = {"v": 1, "typ": SCOPE_TYP, "sub": sub, "materialIds": sorted(int(m) for m in material_ids),
               "documentIds": sorted(str(d) for d in document_ids), "iat": iat, "exp": iat + ttl, "rid": request_id}
    p = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64e(hmac.new(_key(env_name), p.encode(), hashlib.sha256).digest())
    return f"{p}.{sig}"


def verify_scope_token(token: Optional[str], *, expected_sub: Optional[str] = None,
                       expected_request_id: Optional[str] = None,
                       env_name: str = "AI_SCOPE_SIGNING_KEY", now: Optional[float] = None) -> Scope:
    key = _key(env_name)
    if not token or token.count(".") != 1:
        raise SignatureError("SCOPE_TOKEN_MISSING")
    p, sig = token.split(".", 1)
    expected = _b64e(hmac.new(key, p.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected.encode(), sig.encode()):
        raise SignatureError("SCOPE_TOKEN_INVALID")
    try:
        payload = json.loads(_b64d(p))
    except (ValueError, json.JSONDecodeError):
        raise SignatureError("SCOPE_TOKEN_MALFORMED")
    t = now or time.time()
    if not isinstance(payload, dict) or not all(isinstance(payload.get(k), int) and not isinstance(payload.get(k), bool)
                                                for k in ("exp", "iat")):
        raise SignatureError("SCOPE_TOKEN_MALFORMED")
    exp, iat = payload["exp"], payload["iat"]
    if payload.get("typ") != SCOPE_TYP:
        raise SignatureError("SCOPE_TOKEN_TYPE_INVALID")       # consent 등 다른 용도의 토큰을 scope 로 쓰지 못한다
    if payload.get("v") != 1 or exp < t or iat > t + 30 or iat > exp or exp - iat > MAX_SCOPE_TTL_SECONDS:
        raise SignatureError("SCOPE_TOKEN_EXPIRED")
    if expected_sub is not None and payload.get("sub") != expected_sub:
        raise SignatureError("SCOPE_SUBJECT_MISMATCH")
    if expected_request_id is not None and payload.get("rid") != expected_request_id:
        raise SignatureError("SCOPE_REQUEST_MISMATCH")
    return Scope(sub=str(payload.get("sub")), material_ids=frozenset(int(m) for m in payload.get("materialIds", [])),
                 document_ids=frozenset(str(d) for d in payload.get("documentIds", [])),
                 request_id=payload.get("rid"), exp=exp)


def verify_request_scope(token: Optional[str], request_id: Optional[str], *,
                         env_name: str = "AI_SCOPE_SIGNING_KEY", now: Optional[float] = None) -> Scope:
    """라우트 공용 scope 검증: 서명/만료/용도(typ) + 이 요청의 X-Request-Id 바인딩.
    호출자가 X-Request-Id 를 보내지 않았거나(rid 없음) 토큰의 rid 와 다르면 거부한다(TTL 안 재사용 차단)."""
    sc = verify_scope_token(token, env_name=env_name, now=now)
    if not request_id or not sc.request_id or not hmac.compare_digest(str(sc.request_id).encode(), str(request_id).encode()):
        raise SignatureError("SCOPE_REQUEST_MISMATCH")
    return sc


# ── 학습 데이터 활용 동의 claim (X-AI-Training-Consent) ─────────────────────────────
@dataclass(frozen=True)
class ConsentClaim:
    sub: str
    consent_version: str
    consent_timestamp: str
    scope: frozenset
    rights: dict            # {"<materialId>": RightsStatus} — EC2 가 확인한 자료 권리
    deletion_tracking_id: str
    request_id: Optional[str]


def issue_consent_token(sub: str, *, consent_version: str, consent_timestamp: str, scope: List[str],
                        rights: dict, deletion_tracking_id: str, request_id: str, ttl: int = 120,
                        env_name: str = "AI_TRAINING_CONSENT_SIGNING_KEY", now: Optional[float] = None) -> str:
    iat = int(now or time.time())
    payload = {"v": 1, "typ": CONSENT_TYP, "sub": sub, "cv": consent_version, "ct": consent_timestamp,
               "scope": sorted(scope), "rights": rights, "dtid": deletion_tracking_id, "rid": request_id,
               "iat": iat, "exp": iat + ttl}
    p = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    return f"{p}.{_b64e(hmac.new(_key(env_name), p.encode(), hashlib.sha256).digest())}"


def verify_consent_token(token: Optional[str], *, expected_request_id: Optional[str] = None,
                         env_name: str = "AI_TRAINING_CONSENT_SIGNING_KEY", now: Optional[float] = None) -> ConsentClaim:
    key = _key(env_name)
    if not token or token.count(".") != 1:
        raise SignatureError("CONSENT_TOKEN_MISSING")
    p, sig = token.split(".", 1)
    if not hmac.compare_digest(_b64e(hmac.new(key, p.encode(), hashlib.sha256).digest()).encode(), sig.encode()):
        raise SignatureError("CONSENT_TOKEN_INVALID")
    try:
        d = json.loads(_b64d(p))
    except (ValueError, json.JSONDecodeError):
        raise SignatureError("CONSENT_TOKEN_MALFORMED")
    t = now or time.time()
    if not isinstance(d, dict) or not all(isinstance(d.get(k), int) and not isinstance(d.get(k), bool)
                                          for k in ("exp", "iat")):
        raise SignatureError("CONSENT_TOKEN_MALFORMED")
    exp, iat = d["exp"], d["iat"]
    if d.get("v") != 1 or d.get("typ") != CONSENT_TYP or exp < t or iat > t + 30 or iat > exp \
            or exp - iat > MAX_SCOPE_TTL_SECONDS:
        # iat 가 미래(ms 단위 실수 등)이면 TTL 검사가 무력화되므로 거부한다.
        raise SignatureError("CONSENT_TOKEN_EXPIRED")
    if not d.get("rid"):
        raise SignatureError("CONSENT_REQUEST_MISSING")
    if expected_request_id is not None and d.get("rid") != expected_request_id:
        raise SignatureError("CONSENT_REQUEST_MISMATCH")
    return ConsentClaim(sub=str(d["sub"]), consent_version=str(d["cv"]), consent_timestamp=str(d["ct"]),
                        scope=frozenset(d.get("scope") or []), rights=dict(d.get("rights") or {}),
                        deletion_tracking_id=str(d["dtid"]), request_id=d.get("rid"))
