"""차등 케이스(cases.v1.jsonl)에 대한 ai07 Python 판정 — Java 하네스(ContractDiffHarness)와 같은 출력 형식.

사용: python -m scripts.contract_crosscheck.python_verdicts <cases.jsonl>  (fastapi 디렉터리에서)
"""
from __future__ import annotations

import base64
import json
import sys
from typing import Any, Dict

from pydantic import ValidationError

from app.contracts import signing as S
from app.contracts.jtypes import ContractJsonError
from app.contracts.learning_context_v1 import parse_context_json
from app.contracts.response_quality_v1 import is_displayable, parse_input_json, parse_output_json
from app.contracts.training_sample_v1 import parse_sample_json

_PARSERS = {"lc": parse_context_json, "ts": parse_sample_json, "rqi": parse_input_json, "rqo": parse_output_json}


def _raw(c: Dict[str, Any]) -> bytes:
    if c.get("rawBase64") is not None:
        return base64.b64decode(c["rawBase64"])
    return c["raw"].encode("utf-8")


def verdict(c: Dict[str, Any]) -> Dict[str, Any]:
    m = c["model"]
    out: Dict[str, Any] = {"id": c["id"]}
    if m.startswith("sig-"):
        out["outcome"] = _signing(m, c)
        return out
    try:
        obj = _PARSERS[m](_raw(c))
        out["verdict"] = "VALID"
        if m == "rqo":
            out["displayable"] = is_displayable(obj, c.get("expectedRequestId"))
    except (ValidationError, ContractJsonError, ValueError) as e:
        out["verdict"] = "INVALID"
        out["error"] = type(e).__name__
        if m == "rqo":
            out["displayable"] = False
    return out


def _signing(m: str, c: Dict[str, Any]) -> str:
    key = c["key"].encode("utf-8")
    try:
        if m == "sig-body":
            S.verify_body_with_key(key, base64.b64decode(c["bodyBase64"]), c.get("signature"), c.get("timestamp"),
                                   now=c["now"])
        elif m == "sig-scope":
            S.verify_scope_token_with_key(key, c.get("token"), expected_request_id=c.get("requestId"),
                                          expected_sub=c.get("sub"), now=c["now"])
        elif m == "sig-consent":
            S.verify_consent_token_with_key(key, c.get("token"), expected_request_id=c.get("requestId"),
                                            expected_sub=c.get("sub"), now=c["now"])
        return "VALID"
    except S.SignatureError as e:
        return e.code
    except Exception as e:  # noqa: BLE001 — Java 는 계약 예외만 던진다. 그 밖의 예외는 버그로 드러낸다.
        return "PYTHON_EXCEPTION:" + type(e).__name__


def main(path: str) -> None:
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                print(json.dumps(verdict(json.loads(line)), ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
