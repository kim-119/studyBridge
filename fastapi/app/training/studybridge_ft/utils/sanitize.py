"""PII/secret 스캔 — 기존 scripts.sanitize_text.check_and_mask 재사용 + 보강 패턴."""
import re

from app.scripts.sanitize_text import check_and_mask

_EXTRA = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "openai_key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "aws_key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private_key"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "ip_addr"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "email"),
]


def scan_secrets(text: str) -> list[str]:
    found: list[str] = []
    try:
        _, hit, kinds = check_and_mask(text or "")
        if hit:
            found.extend(kinds or ["masked"])
    except Exception:
        pass
    for rx, name in _EXTRA:
        if rx.search(text or ""):
            found.append(name)
    return sorted(set(found))


def scan_sample(sample: dict) -> list[str]:
    blob = "\n".join(m.get("content", "") for m in sample.get("messages", []))
    return scan_secrets(blob)
