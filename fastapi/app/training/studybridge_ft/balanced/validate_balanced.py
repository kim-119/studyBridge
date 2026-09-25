"""샘플 품질 게이트: JSON·빈응답·길이·반복·편향드리프트·위험표현 + 분포 게이트.

스펙 60-68, 90-95. 분포 게이트는 balanced_sampler.check_distribution 재사용.
"""
from __future__ import annotations
import json
import re
from . import taxonomy as tx
from .balanced_sampler import Cell, check_distribution

MIN_LEN = 40  # 너무 짧으면 학습 가치 없음 (스펙 63)

# 위험 도메인 금지 표현 (스펙 66-68) — 단정적 처방/자문/투자권유
_RISK_PATTERNS = {
    "의학/보건": [r"처방(하|해|합니다|하세요)", r"진단은\s*\S+\s*(이다|입니다|확정)", r"복용하세요"],
    "법/정책": [r"고소하세요", r"소송하세요", r"합법(이다|입니다)\s*$", r"무죄(이다|입니다)"],
    "경제/경영": [r"매수하세요", r"매도하세요", r"투자하세요", r"사야\s*한다", r"수익이?\s*보장"],
}


def _assistant(sample: dict) -> str:
    return next((m.get("content", "") for m in sample.get("messages", [])
                 if m.get("role") == "assistant"), "")


def _has_repetition(text: str) -> bool:
    """진짜 퇴행적 반복만 탐지. 구조화 템플릿(roadmap 주차/마크다운 헤더)은 오탐 제외.

    스펙 64. 마크다운 마커를 제거해 정규화한 뒤, '내용 있는' 줄/문장의 반복만 본다.
    """
    from collections import Counter

    def _norm(s: str) -> str:
        return re.sub(r"[#*\->\s·`|]", "", s).strip()

    # 1) 정규화 후 12자 이상의 '내용' 줄이 4회 이상 반복 = 퇴행
    lines = [_norm(ln) for ln in text.splitlines()]
    lines = [ln for ln in lines if len(ln) >= 12]
    if lines and Counter(lines).most_common(1)[0][1] >= 4:
        return True

    # 2) 정규화한 동일 문장(12자+)이 4회 이상 도배 = 퇴행 (마크다운 헤더는 정규화로 제외)
    sents = [_norm(s) for s in re.split(r"[。.!?\n]", text)]
    sents = [s for s in sents if len(s) >= 12]
    if sents and Counter(sents).most_common(1)[0][1] >= 4:
        return True
    return False


def _drift(domain: str, text: str) -> bool:
    """관련 없는 학문인데 AI/운동량 용어로 도배 (스펙 65)."""
    if domain in tx.DRIFT_OK_DOMAINS:
        return False
    t = text.lower()
    hits = sum(t.count(k) for k in tx.DRIFT_KEYWORDS)
    return hits >= 3


def _risk_violation(domain: str, text: str) -> bool:
    for pat in _RISK_PATTERNS.get(domain, []):
        if re.search(pat, text):
            return True
    return False


def validate_sample(sample: dict) -> tuple[bool, str | None, list[str]]:
    """(통과, reject사유, quality_tags)."""
    md = sample.get("metadata", {})
    domain = md.get("domain", "")
    task = md.get("task_type", "")
    a = _assistant(sample).strip()
    tags: list[str] = []

    if not a:
        return False, "empty", tags
    if len(a) < MIN_LEN:
        return False, "too_short", tags
    if _has_repetition(a):
        return False, "repetition", tags
    if _drift(domain, a):
        return False, "off_domain_drift", tags
    if _risk_violation(domain, a):
        return False, "risk_expression", tags

    if task == "quiz":
        try:
            p = json.loads(a)
            for k in ("question", "choices", "answer", "explanation", "difficulty", "source_hint"):
                if k not in p:
                    return False, "quiz_missing_field", tags
            ch = p["choices"]
            if not isinstance(ch, list) or len(ch) < 2:
                return False, "quiz_bad_choices", tags
            ans = p["answer"]
            if not ((isinstance(ans, int) and 0 <= ans < len(ch)) or ans in ch):
                return False, "quiz_invalid_answer", tags
        except Exception:
            return False, "quiz_invalid_json", tags

    if tx.is_risk_domain(domain):
        tags.append("risk_domain_reviewed")
    return True, None, tags


def gate_distribution(samples: list[dict]) -> tuple[bool, list[str]]:
    """수집된 샘플의 metadata로 분포 게이트 (스펙 91-93)."""
    cells = []
    for s in samples:
        md = s.get("metadata", {})
        cells.append(Cell(md.get("domain", "?"), md.get("subdomain", "?"),
                          md.get("task_type", "?"), md.get("difficulty", "?"),
                          md.get("persona", "default")))
    return check_distribution(cells)
