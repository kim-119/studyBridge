"""서명된 내부 계약 검증(HMAC-SHA256) — EC2 canonical `AiContractSigning` 과 바이트·판정 단위로 같다.

키가 없으면 항상 실패한다(fail-closed). 검증 순서와 오류 코드는 Java 구현과 같다(차등 케이스로 고정:
app/contracts/fixtures/differential/, tests/test_lq_contract_differential.py).

1) 본문 서명: X-AI-Contract-Signature = "v1=" + hex(HMAC(key, ascii(timestamp) + "." + RAW_BODY))
   X-AI-Contract-Timestamp = unix seconds(ASCII 숫자 ≤12자리, 앞뒤 공백 허용), ±300s. 재전송 방지는 eventId/requestId DB 멱등.
2) scope 토큰: X-AI-Scope = b64url(json).b64url(HMAC(key, b64url(json)))
   payload = {"v":1,"typ":"ai-scope","sub","materialIds":[int↑],"documentIds":[str↑],"iat","exp","rid"}
3) consent 토큰: X-AI-Training-Consent = 같은 형식, {"v":1,"typ":"training-consent","sub","cv","ct","scope","rights","dtid","rid","iat","exp"}
   C-SIG-1: 다른 용도(typ) 토큰은 CONSENT_TOKEN_TYPE_INVALID(만료보다 먼저 판정).
토큰 수명 ≤600s, iat ≤ now+30s, 모든 비교는 상수 시간.

키 회전: <ENV> 가 현재 키, <ENV>_PREVIOUS 가 유예 중인 이전 키(선택). 검증은 둘 중 하나로 통과하면 된다(발급은 현재 키만).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Tuple

MIN_KEY_LEN = 32
MAX_SKEW_SECONDS = 300
MAX_SCOPE_TTL_SECONDS = 600
FUTURE_IAT_TOLERANCE_SECONDS = 30
SCOPE_TYP = "ai-scope"
CONSENT_TYP = "training-consent"
# 용도별 키는 서로, 그리고 내부 Bearer 키와 달라야 한다. 한 키를 돌려쓰면 한쪽 유출이 다른 용도의 위조로 이어진다.
_SIGNING_ENVS = ("AI_SCOPE_SIGNING_KEY", "AI_TRAINING_CONSENT_SIGNING_KEY", "AI_TRAINING_SAMPLE_SIGNING_KEY")
_INT64_MIN, _INT64_MAX = -(2 ** 63), 2 ** 63 - 1


class SignatureError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ── 키 ───────────────────────────────────────────────────────────────────────────
def _raw_env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _check_key(env_name: str, k: str) -> bytes:
    if len(k.encode("utf-8")) < MIN_KEY_LEN:
        raise SignatureError("SIGNING_KEY_NOT_CONFIGURED")
    others = [n for n in _SIGNING_ENVS if n != env_name] + ["AI_SERVER_API_KEY", "AI_SERVER_API_KEY_SECONDARY"]
    for n in others:
        for o in (_raw_env(n), _raw_env(n + "_PREVIOUS")):
            if o and hmac.compare_digest(o.encode("utf-8"), k.encode("utf-8")):
                raise SignatureError("SIGNING_KEY_REUSED")
    return k.encode("utf-8")


def _key(env_name: str) -> bytes:
    """발급/검증용 현재 키."""
    return _check_key(env_name, _raw_env(env_name))


def _verify_keys(env_name: str) -> List[bytes]:
    """검증용 키 목록: 현재 키(필수) + 이전 키(선택, 회전 유예)."""
    keys = [_key(env_name)]
    prev = _raw_env(env_name + "_PREVIOUS")
    if prev:
        keys.append(_check_key(env_name, prev))
    return keys


def _require_key(key: Optional[bytes]) -> None:
    if key is None or len(key) < MIN_KEY_LEN:
        raise SignatureError("SIGNING_KEY_NOT_CONFIGURED")


# ── Java 호환 보조 ───────────────────────────────────────────────────────────────
_JAVA_WS_CONTROLS = set("\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f")


def _java_ws(ch: str) -> bool:
    # Character.isWhitespace: 유니코드 공백 구분자(비분리 공백 제외) + 일부 제어 문자.
    if ch in _JAVA_WS_CONTROLS:
        return True
    if ch in (" ", " ", " "):
        return False
    return unicodedata.category(ch) in ("Zs", "Zl", "Zp")


def _java_strip(s: str) -> str:
    i, j = 0, len(s)
    while i < j and _java_ws(s[i]):
        i += 1
    while j > i and _java_ws(s[j - 1]):
        j -= 1
    return s[i:j]


def _java_blank(s: Optional[str]) -> bool:
    return s is None or _java_strip(s) == ""


def _jtext(v: Any) -> Optional[str]:
    """Jackson JsonNode.asText() 와 같은 문자열화(누락/null → None)."""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    return ""  # 객체/배열


def _jint_one(v: Any) -> bool:
    # p.path("v").isInt() && asInt()==1 — 불리언/실수/문자열은 거부.
    return type(v) is int and v == 1


def _jiter(v: Any) -> Iterable[Any]:
    # JsonNode 반복: 배열 → 원소, 객체 → 값, 그 밖(스칼라/누락) → 없음.
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return list(v.values())
    return []


def _const_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8", "surrogatepass"), b.encode("utf-8", "surrogatepass"))


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


_B64URL_RE = re.compile(r"[A-Za-z0-9_\-]*={0,2}")


def _b64d(s: str) -> bytes:
    if not _B64URL_RE.fullmatch(s):
        raise ValueError("invalid base64url")
    core = s.rstrip("=")
    return base64.urlsafe_b64decode(core + "=" * (-len(core) % 4))


def _canonical(payload: dict) -> str:
    # Java CanonicalJson == json.dumps(sort_keys, compact, ensure_ascii)
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _token(key: bytes, payload: dict) -> str:
    p = _b64e(_canonical(payload).encode())
    return f"{p}.{_b64e(hmac.new(key, p.encode(), hashlib.sha256).digest())}"


def _require_ttl(ttl: int) -> None:
    if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl <= 0 or ttl > MAX_SCOPE_TTL_SECONDS:
        raise ValueError(f"ttl must be 1..{MAX_SCOPE_TTL_SECONDS}")


def _verify_token_signature(keys: List[bytes], token: Optional[str], kind: str) -> dict:
    for k in keys:
        _require_key(k)
    if token is None or token.count(".") != 1:
        raise SignatureError(f"{kind}_TOKEN_MISSING")
    p, sig = token.split(".", 1)
    try:
        p_bytes = p.encode("ascii")
    except UnicodeEncodeError:
        raise SignatureError(f"{kind}_TOKEN_INVALID")
    if not any(_const_eq(_b64e(hmac.new(k, p_bytes, hashlib.sha256).digest()), sig) for k in keys):
        raise SignatureError(f"{kind}_TOKEN_INVALID")
    try:
        d = json.loads(_b64d(p))
    except (ValueError, binascii.Error, UnicodeDecodeError, RecursionError):
        raise SignatureError(f"{kind}_TOKEN_MALFORMED")
    if not isinstance(d, dict):
        raise SignatureError(f"{kind}_TOKEN_MALFORMED")
    return d


def _times(d: dict, kind: str) -> Tuple[int, int]:
    iat, exp = d.get("iat"), d.get("exp")
    if not (isinstance(iat, int) and not isinstance(iat, bool) and isinstance(exp, int) and not isinstance(exp, bool)):
        raise SignatureError(f"{kind}_TOKEN_MALFORMED")
    return iat, exp


def _times_valid(iat: int, exp: int, now: float) -> bool:
    return exp >= now and iat <= now + FUTURE_IAT_TOLERANCE_SECONDS and iat <= exp and exp - iat <= MAX_SCOPE_TTL_SECONDS


# ── 1) 본문 서명 ─────────────────────────────────────────────────────────────────
def sign_body(body: bytes, timestamp: int, *, env_name: str = "AI_TRAINING_SAMPLE_SIGNING_KEY") -> str:
    return sign_body_with_key(_key(env_name), body, timestamp)


def sign_body_with_key(key: bytes, body: bytes, timestamp: int) -> str:
    return "v1=" + hmac.new(key, str(timestamp).encode("ascii") + b"." + body, hashlib.sha256).hexdigest()


def verify_body(body: bytes, signature: Optional[str], timestamp: Optional[str], *,
                env_name: str = "AI_TRAINING_SAMPLE_SIGNING_KEY", now: Optional[float] = None) -> None:
    _verify_body(_verify_keys(env_name), body, signature, timestamp, now=now)


def verify_body_with_key(key: bytes, body: bytes, signature: Optional[str], timestamp: Optional[str], *,
                         now: Optional[float] = None) -> None:
    _verify_body([key], body, signature, timestamp, now=now)


def _verify_body(keys: List[bytes], body: bytes, signature: Optional[str], timestamp: Optional[str], *,
                 now: Optional[float]) -> None:
    for k in keys:
        _require_key(k)
    if _java_blank(signature) or _java_blank(timestamp):
        raise SignatureError("SIGNATURE_MISSING")
    ts_s = _java_strip(str(timestamp))
    if len(ts_s) > 12 or not all("0" <= ch <= "9" for ch in ts_s):  # ASCII 숫자만(유니코드 숫자 거부)
        raise SignatureError("SIGNATURE_TIMESTAMP_INVALID")
    ts = int(ts_s)
    if abs((time.time() if now is None else now) - ts) > MAX_SKEW_SECONDS:
        raise SignatureError("SIGNATURE_EXPIRED")
    got = _java_strip(str(signature))
    if not any(_const_eq(sign_body_with_key(k, body, ts), got) for k in keys):
        raise SignatureError("SIGNATURE_INVALID")


# ── 2) scope 토큰 ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Scope:
    sub: Optional[str]
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
    """테스트/계약 fixture 용 발급기(운영 발급은 EC2 Spring 책임). Java issueScopeToken 과 같은 바이트."""
    _require_ttl(ttl)
    iat = int(time.time() if now is None else now)
    payload = {"v": 1, "typ": SCOPE_TYP, "sub": sub, "materialIds": sorted({int(m) for m in material_ids}),
               "documentIds": sorted({str(d) for d in document_ids}), "iat": iat, "exp": iat + ttl, "rid": request_id}
    return _token(_key(env_name), payload)


def verify_scope_token(token: Optional[str], *, expected_sub: Optional[str] = None,
                       expected_request_id: Optional[str] = None,
                       env_name: str = "AI_SCOPE_SIGNING_KEY", now: Optional[float] = None) -> Scope:
    """Java verifyScopeToken 과 같다: expected_request_id 가 없으면 SCOPE_REQUEST_MISMATCH(요청 바인딩 필수)."""
    return _verify_scope(_verify_keys(env_name), token, expected_request_id, expected_sub, now)


def verify_scope_token_with_key(key: bytes, token: Optional[str], *, expected_request_id: Optional[str],
                                expected_sub: Optional[str] = None, now: Optional[float] = None) -> Scope:
    return _verify_scope([key], token, expected_request_id, expected_sub, now)


def _verify_scope(keys: List[bytes], token: Optional[str], expected_request_id: Optional[str],
                  expected_sub: Optional[str], now: Optional[float]) -> Scope:
    d = _verify_token_signature(keys, token, "SCOPE")
    iat, exp = _times(d, "SCOPE")
    if _jtext(d.get("typ")) != SCOPE_TYP:
        raise SignatureError("SCOPE_TOKEN_TYPE_INVALID")  # consent 등 다른 용도의 토큰을 scope 로 쓰지 못한다
    if not _jint_one(d.get("v")) or not _times_valid(iat, exp, time.time() if now is None else now):
        raise SignatureError("SCOPE_TOKEN_EXPIRED")
    sub = _jtext(d.get("sub"))
    if expected_sub is not None and expected_sub != sub:
        raise SignatureError("SCOPE_SUBJECT_MISMATCH")
    rid = _jtext(d.get("rid"))
    if expected_request_id is None or rid is None or not _const_eq(rid, expected_request_id):
        raise SignatureError("SCOPE_REQUEST_MISMATCH")
    mids = set()
    for n in _jiter(d.get("materialIds")):
        if not isinstance(n, int) or isinstance(n, bool) or not _INT64_MIN <= n <= _INT64_MAX:
            raise SignatureError("SCOPE_TOKEN_MALFORMED")
        mids.add(n)
    dids = {_jtext(n) if n is not None else "null" for n in _jiter(d.get("documentIds"))}
    return Scope(sub=sub, material_ids=frozenset(mids), document_ids=frozenset(dids), request_id=rid, exp=exp)


def verify_request_scope(token: Optional[str], request_id: Optional[str], *,
                         env_name: str = "AI_SCOPE_SIGNING_KEY", now: Optional[float] = None) -> Scope:
    """라우트 공용 scope 검증: 서명/만료/용도(typ) + 이 요청의 X-Request-Id 바인딩(없으면 SCOPE_REQUEST_MISMATCH).
    판정 순서는 Java verifyScopeToken 과 같다(토큰 누락/위조가 요청 바인딩보다 먼저)."""
    return verify_scope_token(token, expected_request_id=request_id or None, env_name=env_name, now=now)


# ── 3) 학습 데이터 활용 동의 claim (X-AI-Training-Consent) ─────────────────────────────
@dataclass(frozen=True)
class ConsentClaim:
    sub: Optional[str]
    consent_version: Optional[str]
    consent_timestamp: Optional[str]
    scope: frozenset
    rights: dict            # {"<materialId>": RightsStatus} — EC2 가 확인한 자료 권리
    deletion_tracking_id: Optional[str]
    request_id: Optional[str]


def issue_consent_token(sub: str, *, consent_version: str, consent_timestamp: str, scope: List[str],
                        rights: dict, deletion_tracking_id: str, request_id: str, ttl: int = 120,
                        env_name: str = "AI_TRAINING_CONSENT_SIGNING_KEY", now: Optional[float] = None) -> str:
    _require_ttl(ttl)
    iat = int(time.time() if now is None else now)
    payload = {"v": 1, "typ": CONSENT_TYP, "sub": sub, "cv": consent_version, "ct": consent_timestamp,
               "scope": sorted(set(scope)), "rights": dict(rights), "dtid": deletion_tracking_id, "rid": request_id,
               "iat": iat, "exp": iat + ttl}
    return _token(_key(env_name), payload)


def verify_consent_token(token: Optional[str], *, expected_request_id: Optional[str] = None,
                         expected_sub: Optional[str] = None,
                         env_name: str = "AI_TRAINING_CONSENT_SIGNING_KEY", now: Optional[float] = None) -> ConsentClaim:
    return _verify_consent(_verify_keys(env_name), token, expected_request_id, expected_sub, now)


def verify_consent_token_with_key(key: bytes, token: Optional[str], *, expected_request_id: Optional[str] = None,
                                  expected_sub: Optional[str] = None, now: Optional[float] = None) -> ConsentClaim:
    return _verify_consent([key], token, expected_request_id, expected_sub, now)


def _verify_consent(keys: List[bytes], token: Optional[str], expected_request_id: Optional[str],
                    expected_sub: Optional[str], now: Optional[float]) -> ConsentClaim:
    d = _verify_token_signature(keys, token, "CONSENT")
    iat, exp = _times(d, "CONSENT")
    if _jtext(d.get("typ")) != CONSENT_TYP:
        raise SignatureError("CONSENT_TOKEN_TYPE_INVALID")  # C-SIG-1
    if not _jint_one(d.get("v")) or not _times_valid(iat, exp, time.time() if now is None else now):
        raise SignatureError("CONSENT_TOKEN_EXPIRED")
    rid = _jtext(d.get("rid"))
    if _java_blank(rid):
        raise SignatureError("CONSENT_REQUEST_MISSING")
    if expected_request_id is not None and not _const_eq(rid, expected_request_id):
        raise SignatureError("CONSENT_REQUEST_MISMATCH")
    sub = _jtext(d.get("sub"))
    if expected_sub is not None and expected_sub != sub:
        raise SignatureError("CONSENT_SUBJECT_MISMATCH")
    rights_raw = d.get("rights")
    rights = {k: _jtext(v) if v is not None else "null" for k, v in rights_raw.items()} if isinstance(rights_raw, dict) else {}
    scope = frozenset(_jtext(n) if n is not None else "null" for n in _jiter(d.get("scope")))
    return ConsentClaim(sub=sub, consent_version=_jtext(d.get("cv")), consent_timestamp=_jtext(d.get("ct")),
                        scope=scope, rights=rights, deletion_tracking_id=_jtext(d.get("dtid")), request_id=rid)
