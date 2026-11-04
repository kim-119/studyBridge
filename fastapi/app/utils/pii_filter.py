"""
개인정보(PII)·비밀정보 감지 유틸리티.
학습 데이터 수집 전 Q/A, 그리고 사용자 노출 직전 AI 출력에서 민감정보를 감지한다.

원칙
- 정규식 몇 개로 '안전'을 판정하지 않는다. 탐지 범주: 이메일/전화/주민·외국인등록번호/카드(Luhn)/계좌/여권/운전면허/
  학번/이름(라벨·호칭)/주소/IP/자격증명 URL·내부 URL·presigned URL/API Key·Bearer·JWT·개인키/시스템 프롬프트 흔적/
  고엔트로피 비밀 문자열.
- severity: BLOCK(확정적: 연락처·식별번호·비밀키) / QUARANTINE(휴리스틱: 이름·주소·학번 등, 오탐 가능 → 격리 후 검토).
- 검사 중 예외 → status=ERROR → has_pii()=True (fail-closed). 결과에는 매칭 원문을 담지 않는다(로그 금지).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import List, Tuple

BLOCK = "BLOCK"
QUARANTINE = "QUARANTINE"

# 이메일
# 토큰 경계 lookbehind + 길이 상한 → 선형 시간. 예전 '[...]+@' 는 '@' 없는 긴 문자열에서 O(n²)(120KB 에 5초, 2026-11-04 측정).
_EMAIL = re.compile(r"(?<![a-zA-Z0-9._%+\-])[a-zA-Z0-9._%+\-]{1,64}@[a-zA-Z0-9\-]{1,63}(?:\.[a-zA-Z0-9\-]{1,63}){0,8}\.[a-zA-Z]{2,24}(?![a-zA-Z])")
# 한국 전화번호(휴대폰 + 지역번호 유선 + 대표번호)
_KR_PHONE = re.compile(r"(?<!\d)(01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}|0(?:2|[3-6][1-5])[-\s.)]\s?\d{3,4}[-\s.]?\d{4}|1[5-9]\d{2}-\d{4}"
                       r"|\+82[-\s.]?(?:0?1[016789]|0?(?:2|[3-6][1-5]))[-\s.]?\d{3,4}[-\s.]?\d{4})(?!\d)")   # +82 국제표기
# 주민등록번호/외국인등록번호 (구분자 없는 13자리 포함)
_KR_RRNO = re.compile(r"(?<!\d)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[-\s]?[1-8]\d{6}(?!\d)")
# 카드 번호 후보(13~19자리) — Luhn 검증 통과분만 BLOCK
_CARD = re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)")
# 운전면허(지역 2자리-2자리-6자리-2자리)
_DRIVER = re.compile(r"(?<!\d)\d{2}-\d{2}-\d{6}-\d{2}(?!\d)")
# 여권
_PASSPORT = re.compile(r"(?:여권|passport)\s*(?:번호|no\.?|number)?\s*[:：]?\s*[A-Z][A-Z0-9]\d{7}", re.IGNORECASE)
# 계좌(라벨 기반)
_BANK = re.compile(r"(?:(?:계좌|account)\s*(?:번호|no\.?)?\s*[:：]?\s*\d{2,6}[-\s]?\d{2,6}[-\s]?\d{2,8}"
                   r"|(?:국민|신한|우리|하나|농협|기업|카카오|토스|케이|SC제일|씨티|새마을|우체국|수협|부산|대구|경남|광주|전북|제주|KB|NH|IBK)"
                   r"(?:은행|뱅크|금고)?\s*[:：]?\s*\d{2,6}-\d{2,6}-\d{2,8})", re.IGNORECASE)   # 은행명 + 하이픈 계좌
# 학번(라벨 기반)
_STUDENT_ID = re.compile(r"(?:학번|student\s*id|수험번호|사번)\s*[:：은는이가]?\s*[A-Za-z]?(?:\d{4}-\d{4,8}|\d{6,12})", re.IGNORECASE)
# 이름: 라벨(이름/성명) 또는 성씨+이름+호칭
_NAME_LABEL = re.compile(r"(?:이름|성명|name)\s*[:：]\s*[가-힣]{2,4}(?![가-힣])", re.IGNORECASE)
_SURNAMES = "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예봉경사부"
_NAME_HONORIFIC_RAW = re.compile(rf"(?<![가-힣])([{_SURNAMES}][가-힣]{{1,2}})\s?(?:님|씨|학생|교수님|선생님|조교님)(?:이|가|은|는|을|를|에게|께서|께|의|도|과|와)?(?![가-힣])")
# 성씨 글자로 시작하는 일반 명사(모든/이번/신입/우수 …) + 호칭은 이름이 아니다 → 오탐 제외.
_NAME_STOP = {"모든", "많은", "이번", "이런", "이전", "이후", "여러", "어떤", "유학", "신입", "전학", "장학", "우수", "성실",
              "한국", "고등", "안내", "소속", "남학", "여학", "공대", "문과", "이과", "예비", "국제", "연구", "지도", "하는",
              "기존", "현재", "방문", "신규", "구독", "정규", "학부", "석사", "박사", "강의", "수강", "선배", "후배", "동기",
              "참여", "모집", "희망", "대상", "개별", "각각", "전체", "일부", "오늘", "내일", "어제", "주말", "인근", "지원",
              "학생", "교수", "선생", "조교", "고객", "회원", "사용", "이용", "관리", "운영", "담당", "부모", "보호", "학부모"}


class _FilteredPattern:
    """정규식 + 이름 후보 stoplist(오탐 제거). findall/sub/search 인터페이스만 흉내낸다."""

    def __init__(self, pat: re.Pattern, stop: set) -> None:
        self.pat, self.stop = pat, stop

    def _ok(self, m: re.Match) -> bool:
        return m.group(1) not in self.stop

    def findall(self, text: str) -> list:
        return [m.group(0) for m in self.pat.finditer(text) if self._ok(m)]

    def search(self, text: str):
        return next((m for m in self.pat.finditer(text) if self._ok(m)), None)

    def sub(self, repl: str, text: str) -> str:
        return self.pat.sub(lambda m: repl if self._ok(m) else m.group(0), text)


_NAME_HONORIFIC = _FilteredPattern(_NAME_HONORIFIC_RAW, _NAME_STOP)
# 주소: 시/도 + 시/군/구 + 로/길/동 + 번지
_ADDRESS = re.compile(
    r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)[가-힣]{0,6}\s{1,3}"
    r"[가-힣]{1,12}(?:시|군|구)(?:\s{1,3}[가-힣]{1,12}(?:구|군))?\s{1,3}[가-힣0-9]{1,20}(?:로|길|동|읍|면)\s{0,3}\d{1,5}(?:-\d{1,5})?(?:번지)?"
)
_ADDRESS_LABEL = re.compile(r"(?:주소|address)\s*[:：]\s*\S{2,}", re.IGNORECASE)
# IP (사설망 포함 — 운영 토폴로지 노출 방지)
_IPV4 = re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])")
# URL: 자격증명 포함 / 토큰 쿼리 / presigned / 내부 주소
_URL_CRED = re.compile(r"(?<![a-z0-9+.\-])[a-z][a-z0-9+.\-]{0,31}://[^\s/:@]{1,256}:[^\s/@]{1,256}@", re.IGNORECASE)  # 경계+상한=선형
_URL_TOKEN = re.compile(r"[?&](?:token|access_token|api_key|apikey|key|secret|password|sig|signature|X-Amz-Signature|X-Amz-Credential)=[^&\s]{6,}", re.IGNORECASE)
# 루프백(localhost/127.x)은 교육 자료의 흔한 예시라 제외한다(게이트 HARD 오거절 원인, 2026-11-04 사례 검증).
_URL_INTERNAL = re.compile(r"https?://(?:10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+|[a-z0-9\-]+\.internal)(?::\d+)?", re.IGNORECASE)
# 비밀키/토큰
_SECRETS = re.compile(
    r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,}|"
    r"xox[baprs]-[A-Za-z0-9\-]{10,}|AIza[0-9A-Za-z_\-]{35}|tvly-[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{30,}|"
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/\-]{20,}=*", re.IGNORECASE)
_JWT = re.compile(r"(?<![A-Za-z0-9_\-])eyJ[A-Za-z0-9_\-]{8,4096}\.eyJ[A-Za-z0-9_\-]{8,4096}\.[A-Za-z0-9_\-]{8,4096}")
_ASSIGNED_SECRET = re.compile(r"(?:api[_\-]?key|secret|password|passwd|비밀번호|token|AI_SERVER_API_KEY|OPENAI_API_KEY)\s*[:=]\s*['\"]?[^\s'\"]{8,}", re.IGNORECASE)
# 시스템 프롬프트/내부 지시 흔적
_SYSTEM_PROMPT = re.compile(r"<\|im_start\|>\s*system|\[SYSTEM\]|시스템\s*프롬프트\s*[:：]|system\s*prompt\s*[:：]|너는 StudyBridge [^\n]{0,40}(?:도우미|교수)다", re.IGNORECASE)
_HIGH_ENTROPY = re.compile(r"(?<![A-Za-z0-9+/_\-])[A-Za-z0-9+/_\-]{32,}={0,2}(?![A-Za-z0-9+/_\-])")

_RULES: List[Tuple[str, object, str]] = [
    ("EMAIL", _EMAIL, BLOCK),
    ("PHONE", _KR_PHONE, BLOCK),
    ("RRN", _KR_RRNO, BLOCK),
    ("DRIVER_LICENSE", _DRIVER, BLOCK),
    ("PASSPORT", _PASSPORT, BLOCK),
    ("BANK_ACCOUNT", _BANK, BLOCK),
    ("SECRET_KEY", _SECRETS, BLOCK),
    ("BEARER_TOKEN", _BEARER, BLOCK),
    ("JWT", _JWT, BLOCK),
    ("ASSIGNED_SECRET", _ASSIGNED_SECRET, BLOCK),
    ("URL_CREDENTIALS", _URL_CRED, BLOCK),
    ("URL_TOKEN", _URL_TOKEN, BLOCK),
    ("STUDENT_ID", _STUDENT_ID, QUARANTINE),
    ("PERSON_NAME", _NAME_LABEL, QUARANTINE),
    ("PERSON_NAME", _NAME_HONORIFIC, QUARANTINE),
    ("ADDRESS", _ADDRESS, QUARANTINE),
    ("ADDRESS", _ADDRESS_LABEL, QUARANTINE),
    ("IP_ADDRESS", _IPV4, QUARANTINE),
    ("INTERNAL_URL", _URL_INTERNAL, QUARANTINE),
    ("SYSTEM_PROMPT", _SYSTEM_PROMPT, QUARANTINE),
]

_MASK_LABEL = {
    "EMAIL": "[이메일]", "PHONE": "[전화번호]", "RRN": "[주민번호]", "CARD": "[카드번호]",
    "DRIVER_LICENSE": "[면허번호]", "PASSPORT": "[여권번호]", "BANK_ACCOUNT": "[계좌]",
    "SECRET_KEY": "[비밀키]", "BEARER_TOKEN": "[토큰]", "JWT": "[토큰]", "ASSIGNED_SECRET": "[비밀값]",
    "URL_CREDENTIALS": "[자격증명URL]", "URL_TOKEN": "[토큰URL]", "STUDENT_ID": "[학번]",
    "PERSON_NAME": "[이름]", "ADDRESS": "[주소]", "IP_ADDRESS": "[IP]", "INTERNAL_URL": "[내부URL]",
    "SYSTEM_PROMPT": "[내부지시]", "HIGH_ENTROPY_SECRET": "[비밀값]",
}


@dataclass(frozen=True)
class PiiScanResult:
    status: str                      # CLEAN | DETECTED | ERROR
    categories: Tuple[str, ...] = field(default_factory=tuple)
    findings: int = 0
    max_severity: str = ""           # BLOCK | QUARANTINE | ""

    @property
    def clean(self) -> bool:
        return self.status == "CLEAN"

    @property
    def blocking(self) -> bool:
        return self.status == "ERROR" or self.max_severity == BLOCK


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _entropy(s: str) -> float:
    counts = {}
    for c in s:
        counts[c] = counts.get(c, 0) + 1
    n = len(s)
    return -sum(v / n * math.log2(v / n) for v in counts.values())


def _card_spans(text: str) -> List[Tuple[int, int]]:
    spans = []
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits) and len(set(digits)) > 1:
            spans.append(m.span())
    return spans


def _entropy_spans(text: str) -> List[Tuple[int, int]]:
    spans = []
    for m in _HIGH_ENTROPY.finditer(text):
        tok = m.group(0)
        # 영문 단어만/숫자만으로 된 긴 문자열(일반 텍스트)은 제외하고, 혼합 + 고엔트로피만 비밀 후보로 본다.
        if (re.search(r"[A-Za-z]", tok) and re.search(r"\d", tok) and _entropy(tok) >= 4.0):
            spans.append(m.span())
    return spans


# 전각/호환 문자(＠, ０-９)와 보이지 않는 문자(ZWSP/ZWJ/ZWNJ/soft hyphen/BOM/word joiner)로 탐지를 피하지 못하게
# 스캔 전에 NFKC + 제거한다(예전: '홍길동＠example.com', '010\u200b1234\u200b5678' 이 CLEAN — 2026-11-04 재현).
_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad\u180e"), None)


def _scan_view(text: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKC", text).translate(_INVISIBLE)


def scan_pii(text: str) -> PiiScanResult:
    """민감정보 스캔. 매칭 원문은 반환하지 않는다."""
    try:
        if not text:
            return PiiScanResult(status="CLEAN")
        text = _scan_view(text)
        cats: List[str] = []
        sev = ""
        n = 0
        for name, pat, severity in _RULES:
            hits = len(pat.findall(text))
            if hits:
                cats.append(name)
                n += hits
                sev = BLOCK if (severity == BLOCK or sev == BLOCK) else QUARANTINE
        cards = _card_spans(text)
        if cards:
            cats.append("CARD")
            n += len(cards)
            sev = BLOCK
        ent = _entropy_spans(text)
        if ent:
            cats.append("HIGH_ENTROPY_SECRET")
            n += len(ent)
            sev = sev or QUARANTINE
        if not cats:
            return PiiScanResult(status="CLEAN")
        return PiiScanResult(status="DETECTED", categories=tuple(dict.fromkeys(cats)), findings=n, max_severity=sev)
    except Exception:  # noqa: BLE001 — 검사 실패는 '안전'이 아니다
        return PiiScanResult(status="ERROR", max_severity=BLOCK)


def has_pii(text: str) -> bool:
    """텍스트에 개인정보/비밀정보가 있거나 검사에 실패하면 True(fail-closed)."""
    return not scan_pii(text).clean


def mask_pii(text: str) -> str:
    """개인정보/비밀정보를 범주 라벨로 마스킹한 텍스트를 반환한다(탐지와 같은 정규화 뷰 위에서 — 보이지 않는 문자로
    끊어 둔 값이 마스킹을 빠져나가지 않게)."""
    if not text:
        return text
    text = _scan_view(text)
    for start, end in sorted(_card_spans(text), reverse=True):
        text = text[:start] + _MASK_LABEL["CARD"] + text[end:]
    for name, pat, _sev in _RULES:
        text = pat.sub(_MASK_LABEL[name], text)
    for start, end in sorted(_entropy_spans(text), reverse=True):
        text = text[:start] + _MASK_LABEL["HIGH_ENTROPY_SECRET"] + text[end:]
    return text
