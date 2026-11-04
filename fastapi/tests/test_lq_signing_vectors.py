"""교차 언어 서명 벡터(app/contracts/fixtures/signing-vectors.v1.json) 검증.

1) ai07 Python 검증기가 벡터의 기대 결과(VALID/오류 코드)를 정확히 낸다.
2) 독립 구현(openssl)이 같은 HMAC 값을 만든다 — 언어/라이브러리 차이로 바이트가 달라지지 않음을 확인.
   (JVM javax.crypto.Mac 검증은 scripts/verify_signing_vectors.java — CI 밖에서 docker 로 1회 실행, 결과는 PR 본문에 기록)
"""
import base64
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.contracts import signing as S

FX = Path(__file__).resolve().parents[1] / "app" / "contracts" / "fixtures"
VEC = json.loads((FX / "signing-vectors.v1.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    for k, v in VEC["keys"].items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AI_SERVER_API_KEY", raising=False)


def _code(fn):
    try:
        fn()
        return "VALID"
    except S.SignatureError as e:
        return e.code


@pytest.mark.parametrize("v", VEC["bodySignature"], ids=lambda v: v["name"])
def test_body_signature_vectors(v):
    body = base64.b64decode(v["bodyBase64"])
    assert _code(lambda: S.verify_body(body, v["signature"], str(v["timestamp"]), now=v["verifyAt"])) == v["expect"]


@pytest.mark.parametrize("v", VEC["scopeToken"], ids=lambda v: v["name"])
def test_scope_token_vectors(v):
    assert _code(lambda: S.verify_request_scope(v["token"], v["requestId"], now=v["verifyAt"])) == v["expect"]


@pytest.mark.parametrize("v", VEC["consentToken"], ids=lambda v: v["name"])
def test_consent_token_vectors(v):
    assert _code(lambda: S.verify_consent_token(v["token"], expected_request_id=v["requestId"],
                                                now=v["verifyAt"])) == v["expect"]


def test_python_issuer_reproduces_vector_bytes():
    sv = VEC["scopeToken"][0]
    p = sv["payload"]
    tok = S.issue_scope_token(p["sub"], p["materialIds"], p["documentIds"], request_id=p["rid"], ttl=p["exp"] - p["iat"],
                              now=p["iat"])
    assert tok == sv["token"]


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl 없음")
def test_openssl_independent_hmac_matches():
    for line in (FX / "signing-vectors.v1.tsv").read_text(encoding="utf-8").splitlines():
        kind, env, msg_b64, expected = line.split("\t")
        key = VEC["keys"][env]
        raw = subprocess.run(["openssl", "dgst", "-sha256", "-mac", "HMAC", "-macopt", f"key:{key}", "-binary"],
                             input=base64.b64decode(msg_b64), capture_output=True, check=True).stdout
        got = raw.hex() if kind == "HEX" else base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
        assert got == expected, (kind, env)
