"""
개인정보(PII) 감지 유틸리티.
학습 데이터 수집 전 Q/A에서 민감정보를 감지한다.
"""
import re

# 이메일
_EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
# 한국 전화번호
_KR_PHONE = re.compile(r"(01[016789][-\s]?\d{3,4}[-\s]?\d{4})")
# 주민등록번호 (앞 6자리-뒤 7자리)
_KR_RRNO = re.compile(r"\d{6}[-\s]\d{7}")
# 신용카드 번호 (16자리)
_CARD = re.compile(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b")


def has_pii(text: str) -> bool:
    """텍스트에 개인정보가 포함되어 있으면 True를 반환한다."""
    if not text:
        return False
    return bool(
        _EMAIL.search(text)
        or _KR_PHONE.search(text)
        or _KR_RRNO.search(text)
        or _CARD.search(text)
    )


def mask_pii(text: str) -> str:
    """개인정보를 마스킹한 텍스트를 반환한다."""
    text = _EMAIL.sub("[이메일]", text)
    text = _KR_PHONE.sub("[전화번호]", text)
    text = _KR_RRNO.sub("[주민번호]", text)
    text = _CARD.sub("[카드번호]", text)
    return text
