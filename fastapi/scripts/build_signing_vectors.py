"""EC2(Spring) ↔ ai07 서명 계약 교차 언어 테스트 벡터 생성기(PROPOSED_BY_AI07).

키는 '테스트 전용' 고정값이다(운영 키 아님). 벡터는 raw 바이트 기준:
- 본문 서명: X-AI-Contract-Signature = "v1=" + hex(HMAC-SHA256(sampleKey, ascii(timestamp) + "." + rawBodyBytes))
  rawBodyBytes 는 '전송한 바이트 그대로'(재직렬화 금지). X-AI-Contract-Timestamp = unix seconds, 허용 오차 ±300s.
- scope/consent 토큰: base64url(payloadJsonBytes) + "." + base64url(HMAC-SHA256(key, ascii(payloadB64))) (패딩 없음).
  검증자는 payload 를 재직렬화하지 않고 받은 payloadB64 문자열 그대로 HMAC 한다 → 언어 간 JSON 정규화 차이 무관.
  scope: typ=ai-scope, rid=X-Request-Id 와 같아야 함, iat<=now+30, exp>=now, exp-iat<=600.
  consent: typ=training-consent, rid 필수.
    cd fastapi && python -m scripts.build_signing_vectors
"""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app" / "contracts" / "fixtures" / "signing-vectors.v1.json"
KEYS = {"AI_SCOPE_SIGNING_KEY": "TEST-ONLY-scope-key-0123456789abcdefABCDEF",
        "AI_TRAINING_CONSENT_SIGNING_KEY": "TEST-ONLY-consent-key-0123456789abcdefABCDEF",
        "AI_TRAINING_SAMPLE_SIGNING_KEY": "TEST-ONLY-sample-key-0123456789abcdefABCDEF"}
NOW = 1793750400          # 2026-11-04T00:00:00Z


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def body_sig(key: str, ts: int, body: bytes) -> str:
    return "v1=" + hmac.new(key.encode(), str(ts).encode() + b"." + body, hashlib.sha256).hexdigest()


def token(key: str, payload: dict) -> str:
    p = b64u(json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode())
    return p + "." + b64u(hmac.new(key.encode(), p.encode(), hashlib.sha256).digest())


def main():
    sk, ck, bk = KEYS["AI_SCOPE_SIGNING_KEY"], KEYS["AI_TRAINING_CONSENT_SIGNING_KEY"], KEYS["AI_TRAINING_SAMPLE_SIGNING_KEY"]
    body_ko = json.dumps({"schemaVersion": "training-sample.v1", "eventId": "evt-vec-000001",
                          "question": "TCP 3-way handshake 란?\n줄바꿈 포함"}, ensure_ascii=False).encode()
    body_ascii = b'{"a":1,"b":"x"}'
    scope_p = {"v": 1, "typ": "ai-scope", "sub": "pk_vector_user_000001", "materialIds": [7, 42], "documentIds": [],
               "iat": NOW, "exp": NOW + 120, "rid": "req-vector-000001"}
    consent_p = {"v": 1, "typ": "training-consent", "sub": "pk_vector_user_000001", "cv": "tc-2026-10",
                 "ct": "2026-10-30T00:00:00Z", "scope": ["MODEL_TRAINING"], "rights": {"42": "USER_OWNED_VERIFIED"},
                 "dtid": "del-vector-000001", "rid": "req-vector-000001", "iat": NOW, "exp": NOW + 120}
    good_scope, good_consent = token(sk, scope_p), token(ck, consent_p)
    vec = {
        "status": "CANONICAL_EC2_V1", "algorithm": "HMAC-SHA256", "keys": KEYS,
        "note": "TEST-ONLY keys. raw-bytes signing; verifier must not re-serialize JSON.",
        "bodySignature": [
            {"name": "utf8_korean_newline", "timestamp": NOW, "bodyBase64": base64.b64encode(body_ko).decode(),
             "signature": body_sig(bk, NOW, body_ko), "verifyAt": NOW + 10, "expect": "VALID"},
            {"name": "ascii", "timestamp": NOW, "bodyBase64": base64.b64encode(body_ascii).decode(),
             "signature": body_sig(bk, NOW, body_ascii), "verifyAt": NOW, "expect": "VALID"},
            {"name": "reserialized_body_rejected", "timestamp": NOW,
             "bodyBase64": base64.b64encode(json.dumps(json.loads(body_ko)).encode()).decode(),   # 같은 JSON, 다른 바이트
             "signature": body_sig(bk, NOW, body_ko), "verifyAt": NOW, "expect": "SIGNATURE_INVALID"},
            {"name": "stale_timestamp", "timestamp": NOW, "bodyBase64": base64.b64encode(body_ascii).decode(),
             "signature": body_sig(bk, NOW, body_ascii), "verifyAt": NOW + 301, "expect": "SIGNATURE_EXPIRED"},
            {"name": "huge_timestamp", "timestamp": "9" * 40, "bodyBase64": base64.b64encode(body_ascii).decode(),
             "signature": "v1=00", "verifyAt": NOW, "expect": "SIGNATURE_TIMESTAMP_INVALID"},
        ],
        "scopeToken": [
            {"name": "valid", "token": good_scope, "requestId": "req-vector-000001", "verifyAt": NOW + 5, "expect": "VALID",
             "payload": scope_p},
            {"name": "rid_mismatch", "token": good_scope, "requestId": "req-vector-000002", "verifyAt": NOW + 5,
             "expect": "SCOPE_REQUEST_MISMATCH"},
            {"name": "expired", "token": good_scope, "requestId": "req-vector-000001", "verifyAt": NOW + 121,
             "expect": "SCOPE_TOKEN_EXPIRED"},
            {"name": "tampered_payload", "token": b64u(json.dumps({**scope_p, "materialIds": [7, 42, 999]},
                                                                  separators=(",", ":"), sort_keys=True).encode())
             + "." + good_scope.split(".")[1], "requestId": "req-vector-000001", "verifyAt": NOW + 5,
             "expect": "SCOPE_TOKEN_INVALID"},
            {"name": "consent_token_as_scope", "token": token(sk, {**consent_p}), "requestId": "req-vector-000001",
             "verifyAt": NOW + 5, "expect": "SCOPE_TOKEN_TYPE_INVALID"},
            {"name": "future_iat", "token": token(sk, {**scope_p, "iat": NOW + 3600, "exp": NOW + 3700}),
             "requestId": "req-vector-000001", "verifyAt": NOW, "expect": "SCOPE_TOKEN_EXPIRED"},
        ],
        "consentToken": [
            {"name": "valid", "token": good_consent, "requestId": "req-vector-000001", "verifyAt": NOW + 5, "expect": "VALID",
             "payload": consent_p},
            {"name": "rid_mismatch", "token": good_consent, "requestId": "req-vector-000009", "verifyAt": NOW + 5,
             "expect": "CONSENT_REQUEST_MISMATCH"},
            {"name": "scope_token_as_consent", "token": token(ck, scope_p), "requestId": "req-vector-000001",
             "verifyAt": NOW + 5, "expect": "CONSENT_TOKEN_TYPE_INVALID"},
            {"name": "signed_with_scope_key", "token": token(sk, consent_p), "requestId": "req-vector-000001",
             "verifyAt": NOW + 5, "expect": "CONSENT_TOKEN_INVALID"},
        ],
    }
    OUT.write_text(json.dumps(vec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    # Java/openssl 교차 검증용 TSV(kind, keyEnv, messageBase64, expected)
    rows = []
    for v in vec["bodySignature"][:2]:
        msg = str(v["timestamp"]).encode() + b"." + base64.b64decode(v["bodyBase64"])
        rows.append(("HEX", "AI_TRAINING_SAMPLE_SIGNING_KEY", base64.b64encode(msg).decode(), v["signature"][3:]))
    for grp, env in (("scopeToken", "AI_SCOPE_SIGNING_KEY"), ("consentToken", "AI_TRAINING_CONSENT_SIGNING_KEY")):
        v = vec[grp][0]
        p, s = v["token"].split(".")
        rows.append(("B64URL", env, base64.b64encode(p.encode()).decode(), s))
    (OUT.parent / "signing-vectors.v1.tsv").write_text("\n".join("\t".join(r) for r in rows) + "\n", encoding="utf-8")
    print("vectors ->", OUT)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONHASHSEED", "0")
    main()
