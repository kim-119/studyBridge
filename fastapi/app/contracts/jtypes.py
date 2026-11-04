"""EC2 canonical(Java/Jackson ContractJson.STRICT)과 같은 판정을 내기 위한 Pydantic 필드 타입·원시 JSON 파서.

EC2 Java 계약 클래스를 직접 실행해 얻은 판정(app/contracts/fixtures/differential/java-verdicts.v1.jsonl)과
Python 판정을 케이스 단위로 비교한다(tests/test_lq_contract_differential.py). 규칙:

- C-TYPE-1: 문자열→숫자, 숫자→문자열, 실수→정수, 불리언↔숫자/문자열 같은 암묵 변환 금지.
  Java Integer/Long 범위를 넘는 정수는 거부(Jackson 은 overflow 를 오류로 본다). Double 은 정수 리터럴을 받는다.
- C-ID-1: 식별자 정규식은 전체 일치(re.fullmatch). '$' 는 끝 개행을 허용하므로 쓰지 않는다.
- C-TIME-1: 타임존 없는 시각은 거부. 받아들이는 형식은 Jackson InstantDeserializer(OffsetDateTime) 와 같다:
  ISO_OFFSET_DATE_TIME(대소문자 무시 T/Z, 초·소수 0~9자리 선택, 오프셋 Z|±HH|±HH:MM|±HH:MM:SS, 콜론 없는 ±HHMM 보정),
  앞뒤 공백(≤U+0020) trim, epoch 초(정수/소수 숫자, 숫자만으로 된 문자열). 모두 오프셋이 확정된 값이다.
- 원시 JSON: NaN/Infinity 토큰·뒤따르는 토큰·주석·작은따옴표·잘못된 UTF-8 거부, UTF-8 BOM 허용(Jackson 과 동일).
  중복 키는 거부한다 — Jackson 기본값(마지막 값 채택, 단 앞선 값도 타입 변환은 거침)을 그대로 흉내 내지 않고 더 엄격하게
  막는다(파서 차이 공격면 제거). EC2 에 STRICT_DUPLICATE_DETECTION 활성화를 요청했다(C-JSON-1).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, List, Optional

from pydantic import AfterValidator, BeforeValidator, Strict

INT32_MIN, INT32_MAX = -(2 ** 31), 2 ** 31 - 1
INT64_MIN, INT64_MAX = -(2 ** 63), 2 ** 63 - 1


def _int32(v: int) -> int:
    if not INT32_MIN <= v <= INT32_MAX:
        raise ValueError("integer out of Java int range")
    return v


def _int64(v: int) -> int:
    if not INT64_MIN <= v <= INT64_MAX:
        raise ValueError("integer out of Java long range")
    return v


def _number_only(v: Any) -> Any:
    # Java Double: JSON 정수/실수만. 불리언·문자열은 Jackson STRICT 가 거부한다.
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("number required (no coercion)")
    return v


# ── 날짜/시각: Jackson InstantDeserializer<OffsetDateTime> 호환 ──────────────────────
_COLONLESS_OFFSET = re.compile(r"[+-][0-9]{4}(?=\[|$)")
_ISO_OFFSET_DT = re.compile(
    r"(?P<year>[+-]?[0-9]{4,10})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})[Tt]"
    r"(?P<h>[0-9]{2}):(?P<mi>[0-9]{2})(?::(?P<s>[0-9]{2})(?:\.(?P<f>[0-9]{0,9}))?)?"
    r"(?P<off>[Zz]|[+-][0-9]{2}(?::[0-9]{2}(?::[0-9]{2})?)?)"
)


def _java_trim(s: str) -> str:
    # String.trim(): 앞뒤의 U+0020 이하 문자 제거(유니코드 공백은 그대로 둔다).
    i, j = 0, len(s)
    while i < j and s[i] <= " ":
        i += 1
    while j > i and s[j - 1] <= " ":
        j -= 1
    return s[i:j]


def _from_epoch(seconds: Decimal) -> datetime:
    try:
        whole = int(seconds.to_integral_value(rounding="ROUND_FLOOR"))
        frac = seconds - whole
        return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=whole, microseconds=int(frac * 1_000_000))
    except (OverflowError, ValueError, InvalidOperation) as e:
        raise ValueError("epoch timestamp out of supported range") from e


def _parse_iso_offset(s: str) -> datetime:
    m = _ISO_OFFSET_DT.fullmatch(s)
    if not m:
        raise ValueError("ISO-8601 date-time with offset required")
    y = m.group("year")
    # SignStyle.EXCEEDS_PAD: 4자리는 부호 없음, 5자리 이상은 '+' 필수, '-' 는 음수 연도.
    if (len(y.lstrip("+-")) > 4 and not y.startswith(("+", "-"))) or (y.startswith("+") and len(y) <= 5):
        raise ValueError("invalid year")
    year = int(y)
    if not 1 <= year <= 9999:
        # Python datetime 표현 한계. Java 는 더 넓은 연도를 받는다(차등 기록 C-TIME-2, EC2 에 4자리 제한 제안).
        raise ValueError("year outside 0001..9999")
    off = m.group("off")
    if off in ("Z", "z"):
        tz = timezone.utc
    else:
        sign = -1 if off[0] == "-" else 1
        parts = off[1:].split(":")
        hh, mm, ss = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0, int(parts[2]) if len(parts) > 2 else 0
        if hh > 18 or mm > 59 or ss > 59 or (hh == 18 and (mm or ss)):
            raise ValueError("offset out of range")
        tz = timezone(sign * timedelta(hours=hh, minutes=mm, seconds=ss))
    frac = m.group("f") or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    try:
        return datetime(year, int(m.group("month")), int(m.group("day")), int(m.group("h")), int(m.group("mi")),
                        int(m.group("s") or 0), micro, tzinfo=tz)
    except ValueError as e:  # 2월 30일, 24시, 윤초(60초) 등 — ResolverStyle.STRICT 와 같이 거부
        raise ValueError("invalid calendar date-time") from e


def parse_offset_datetime(v: Any) -> datetime:
    if isinstance(v, datetime):
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("timezone-aware datetime required (C-TIME-1)")
        return v
    if isinstance(v, bool):
        raise ValueError("date-time required")
    if isinstance(v, int):
        return _from_epoch(Decimal(v))
    if isinstance(v, float):
        return _from_epoch(Decimal(repr(v)))
    if not isinstance(v, str):
        raise ValueError("date-time required")
    s = _java_trim(v)
    if not s:
        raise ValueError("empty date-time")
    if all(ch in "0123456789." for ch in s):
        dots = s.count(".")
        try:
            if dots == 0 and len(s) <= 19 and int(s) <= INT64_MAX:
                return _from_epoch(Decimal(s))
            if dots == 1:
                return _from_epoch(Decimal(s))
        except InvalidOperation:
            pass  # Java: NumberFormatException → 포매터 파싱으로 넘어가 실패
    m = _COLONLESS_OFFSET.search(s)
    if m:
        g = m.group(0)
        s = s[:m.start()] + g[:3] + ":" + g[3:] + s[m.end():]
    return _parse_iso_offset(s)


# ── Pydantic 필드 타입 ────────────────────────────────────────────────────────────
JStr = Annotated[str, Strict()]
JBool = Annotated[bool, Strict()]
# 범위는 제약(Field ge/le)이 아니라 검증 함수로 건다 — Annotated 안의 Field 제약은 필드 쪽 Field(ge=..) 와 병합되며
# 덮어써질 수 있다(실측: Field(..., ge=-1, le=1) 가 무시됨). 함수 검증은 필드 제약과 독립적으로 항상 적용된다.
JInt = Annotated[int, Strict(), AfterValidator(_int32)]
JLong = Annotated[int, Strict(), AfterValidator(_int64)]
JDouble = Annotated[float, BeforeValidator(_number_only)]
JOffsetDateTime = Annotated[datetime, BeforeValidator(parse_offset_datetime)]


def none_to(default_factory):
    """Java record 는 null/누락을 같은 null 로 본다 → Python 기본값 필드도 명시적 null 을 기본값으로 받는다."""
    def _v(v: Any) -> Any:
        return default_factory() if v is None else v
    return _v


def drop_nulls(v: Optional[List[Any]]) -> Optional[List[Any]]:
    """Java List<String>/List<Long> 은 null 원소를 허용(검증하지 않음)한다 → 받되 사용 전에 제거한다."""
    return None if v is None else [x for x in v if x is not None]


def full_id(pattern: re.Pattern, v: Optional[str]) -> bool:
    return v is not None and pattern.fullmatch(v) is not None


# ── 원시 JSON ─────────────────────────────────────────────────────────────────────
class ContractJsonError(ValueError):
    pass


def _reject_constant(name: str) -> Any:
    raise ContractJsonError(f"non-standard JSON token {name}")


def _no_duplicates(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ContractJsonError("duplicate JSON key")
        out[k] = v
    return out


def loads_contract(raw: bytes | str) -> Any:
    """Jackson STRICT 와 같은 규칙으로 원시 본문을 해석한다(서명 검증 후 같은 바이트로 호출)."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        text = raw.decode("utf-8")  # strict: 잘못된 UTF-8·인코딩된 서러게이트 거부
    except UnicodeDecodeError as e:
        raise ContractJsonError("invalid UTF-8") from e
    try:
        return json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_no_duplicates)
    except ContractJsonError:
        raise
    except (json.JSONDecodeError, RecursionError) as e:
        raise ContractJsonError("malformed JSON") from e
