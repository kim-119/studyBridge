"""대용량 JSON 분할 평가의 무결성 검증(EC2 SegmentedQualityGate 와 짝, Phase D R2).

EC2 는 response-quality.v1 을 바꾸지 않고 분할 평가를 한다:
  proposedOutput = {"/weeks/3": {...}, "/weeks/4": {...}}   (JSON Pointer → 원본 그대로의 부분 트리)
  originalRequest 끝 = "\\n[분할 평가 {i}/{N} manifest={24hex} segment={id} checksum={16hex}]"
  requestId      = "<rid>.a<attempt>.s<i-1>"
  checksum       = sha256(UTF-8(Jackson JsonNode.toString(segment))) 의 앞 16 hex
평가기가 하는 일(세그먼트 밖 내용은 추측하지 않는다):
  1) 마커 형식·번호(1 ≤ i ≤ N) 확인, requestId 의 .s<k> 와 i 일치
  2) 받은 본문을 Jackson 과 같은 바이트로 다시 직렬화해 체크섬 대조 → 다르면 SEGMENT_CHECKSUM_MISMATCH(HARD)
  3) 포인터 형식·세그먼트 안 겹침 검사
  4) 같은 manifest 안에서 번호·체크섬 충돌(같은 세그먼트에 다른 본문, 같은 번호에 다른 세그먼트, N 불일치) → HARD
전체 커버리지(모든 문자열 잎이 정확히 한 세그먼트에)는 전체 문서를 가진 쪽(Spring)이 판정한다.
verify_manifest() 는 그 판정의 Python 참조 구현(EC2 precheck 와 같은 코드)이며, ai07 이 직접 분할 평가를 할 때도 쓴다.

이 모듈은 표준 라이브러리만 쓴다(EC2 격리 E2E 가 app.quality_gate 만 추출한다).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

MARKER_RE = re.compile(
    r"\[분할 평가 (\d{1,4})/(\d{1,4}) manifest=([0-9a-f]{24}) segment=([A-Za-z0-9._:\-]{1,64}) checksum=([0-9a-f]{16})\]\s*$")
_RID_SEG_RE = re.compile(r"\.a(\d{1,2})\.s(\d{1,4})$")
_SEGMENT_ID_RE = re.compile(r"[A-Za-z0-9._:\-]{1,64}")
MAX_SEGMENTS = 1000


# ── Jackson 호환 직렬화 ─────────────────────────────────────────────────────────────
_HEX = "0123456789ABCDEF"
_SHORT = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _jstr(s: str) -> str:
    out = ['"']
    for ch in s:
        e = _SHORT.get(ch)
        if e is not None:
            out.append(e)
        elif ord(ch) < 0x20:
            o = ord(ch)
            out.append("\\u00" + _HEX[o >> 4] + _HEX[o & 15])     # Jackson: 대문자 16진
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _jdouble(x: float) -> str:
    """java.lang.Double.toString (JDK 19+ 최단 표현) 과 같은 문자열."""
    if x == 0:
        return "-0.0" if math.copysign(1.0, x) < 0 else "0.0"
    sign = "-" if x < 0 else ""
    d = Decimal(repr(abs(x)))
    digits = d.as_tuple().digits
    exp = d.as_tuple().exponent
    # 정규화: 끝 0 제거
    ds = "".join(map(str, digits)).rstrip("0") or "0"
    n = len("".join(map(str, digits)))
    # 과학적 지수(소수점 앞 한 자리 기준)
    sci = n + exp - 1
    if 1e-3 <= abs(x) < 1e7:
        # 고정 소수점, 소수 최소 1자리
        if sci >= 0:
            int_part = ds[: sci + 1].ljust(sci + 1, "0")
            frac = ds[sci + 1:] or "0"
        else:
            int_part = "0"
            frac = "0" * (-sci - 1) + ds
        return f"{sign}{int_part}.{frac}"
    mant = ds[0] + "." + (ds[1:] or "0")
    return f"{sign}{mant}E{sci}"


def jackson_compact(obj: Any) -> str:
    """Jackson JsonNode.toString() 과 같은 문자열(키 순서 보존, 공백 없음, 비 ASCII 그대로)."""
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise ValueError("non-finite number")
        return _jdouble(obj)
    if isinstance(obj, str):
        return _jstr(obj)
    if isinstance(obj, dict):
        return "{" + ",".join(_jstr(str(k)) + ":" + jackson_compact(v) for k, v in obj.items()) + "}"
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(jackson_compact(v) for v in obj) + "]"
    raise TypeError(f"unsupported type {type(obj).__name__}")


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def checksum(obj: Any) -> str:
    """EC2 SegmentedQualityGate.checksum(JsonNode) 와 같은 값."""
    return sha256_hex(jackson_compact(obj))


# ── JSON Pointer ─────────────────────────────────────────────────────────────────
def pointer_tokens(ptr: str) -> Optional[List[str]]:
    """RFC 6901 포인터 → 토큰. 형식 오류(~ 다음 0/1 아님, / 로 시작 안 함)는 None."""
    if not isinstance(ptr, str) or not ptr.startswith("/"):
        return None
    toks = ptr[1:].split("/")
    out = []
    for t in toks:
        if re.search(r"~(?![01])", t):
            return None
        out.append(t.replace("~1", "/").replace("~0", "~"))
    return out


def escape_token(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def resolve(doc: Any, ptr: str) -> Tuple[bool, Any]:
    toks = pointer_tokens(ptr) if ptr else []
    if toks is None:
        return False, None
    cur = doc
    for t in toks:
        if isinstance(cur, dict):
            if t not in cur:
                return False, None
            cur = cur[t]
        elif isinstance(cur, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", t) or int(t) >= len(cur):
                return False, None
            cur = cur[int(t)]
        else:
            return False, None
    return True, cur


def under(leaf: str, pointer: str) -> bool:
    return pointer == "" or leaf == pointer or leaf.startswith(pointer + "/")


def text_leaves(node: Any, ptr: str = "", out: Optional[List[str]] = None) -> List[str]:
    """비어 있지 않은 문자열 잎의 포인터(EC2 textLeaves 와 같은 순서·규칙)."""
    out = [] if out is None else out
    if isinstance(node, str):
        if node.strip():
            out.append(ptr)
    elif isinstance(node, dict):
        for k, v in node.items():
            text_leaves(v, ptr + "/" + escape_token(str(k)), out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            text_leaves(v, f"{ptr}/{i}", out)
    return out


def string_values(node: Any) -> List[str]:
    out: List[str] = []

    def walk(n: Any) -> None:
        if isinstance(n, str):
            if n.strip():
                out.append(n)
        elif isinstance(n, dict):
            for x in n.values():
                walk(x)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(node)
    return out


# ── 마커 ─────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SegmentMarker:
    index: int
    count: int
    manifest_id: str
    segment_id: str
    checksum16: str


def parse_marker(original_request: str) -> Optional[SegmentMarker]:
    m = MARKER_RE.search(original_request or "")
    if not m:
        return None
    return SegmentMarker(int(m.group(1)), int(m.group(2)), m.group(3), m.group(4), m.group(5))


def strip_marker(original_request: str) -> str:
    return MARKER_RE.sub("", original_request or "").rstrip()


def is_segment_object(obj: Any) -> bool:
    return isinstance(obj, dict) and bool(obj) and all(isinstance(k, str) and k.startswith("/") for k in obj)


V = Tuple[str, str, str, Optional[str]]


def _v(code: str, sev: str, reason: str) -> V:
    return (code, sev, reason[:300], None)


class _ManifestRegistry:
    """같은 manifest 의 세그먼트 번호·체크섬 일관성(프로세스 단위, TTL·상한). 다른 인스턴스 간 공유는 하지 않는다."""

    def __init__(self, max_items: int = 2048, ttl_s: float = 1800.0) -> None:
        self._d: "OrderedDict[str, Tuple[float, int, Dict[str, Tuple[int, str]]]]" = OrderedDict()
        self._lock = threading.Lock()
        self.max_items, self.ttl_s = max_items, ttl_s

    def observe(self, m: SegmentMarker) -> List[V]:
        now = time.monotonic()
        out: List[V] = []
        with self._lock:
            for k in [k for k, (t, _, _) in self._d.items() if now - t > self.ttl_s]:
                self._d.pop(k, None)
            entry = self._d.get(m.manifest_id)
            if entry is None:
                self._d[m.manifest_id] = (now, m.count, {m.segment_id: (m.index, m.checksum16)})
            else:
                _, count, segs = entry
                if count != m.count:
                    out.append(_v("SEGMENT_COUNT_CONFLICT", "HARD", "같은 manifest 의 세그먼트 수가 다름"))
                prev = segs.get(m.segment_id)
                if prev is not None and prev != (m.index, m.checksum16):
                    out.append(_v("SEGMENT_DUPLICATE_CONFLICT", "HARD", "같은 세그먼트 ID 에 다른 본문/번호"))
                if any(i == m.index and sid != m.segment_id for sid, (i, _) in segs.items()):
                    out.append(_v("SEGMENT_INDEX_CONFLICT", "HARD", "같은 번호에 다른 세그먼트"))
                if not out:
                    segs[m.segment_id] = (m.index, m.checksum16)
                self._d[m.manifest_id] = (now, count, segs)
                self._d.move_to_end(m.manifest_id)
            while len(self._d) > self.max_items:
                self._d.popitem(last=False)
        return out

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


REGISTRY = _ManifestRegistry()


def check_segment_integrity(proposed: Any, original_request: str, request_id: str) -> Tuple[List[V], Optional[SegmentMarker]]:
    """분할 평가 세그먼트 1개의 무결성 위반(HARD 위주)과 마커."""
    out: List[V] = []
    m = parse_marker(original_request)
    if m is None:
        return [_v("SEGMENT_MARKER_MISSING", "HARD", "분할 세그먼트인데 manifest/checksum 표식이 없음")], None
    if not (1 <= m.index <= m.count <= MAX_SEGMENTS):
        out.append(_v("SEGMENT_INDEX_INVALID", "HARD", f"세그먼트 번호 범위 오류 {m.index}/{m.count}"))
    rid = _RID_SEG_RE.search(request_id or "")
    if rid and int(rid.group(2)) + 1 != m.index:
        out.append(_v("SEGMENT_INDEX_MISMATCH", "HARD", "requestId 의 세그먼트 번호와 표식 번호가 다름"))
    try:
        got = checksum(proposed)[:16]
    except (TypeError, ValueError):
        got = None
    if got != m.checksum16:
        out.append(_v("SEGMENT_CHECKSUM_MISMATCH", "HARD", "받은 세그먼트 본문의 SHA-256 이 표식 체크섬과 다름"))
    ptrs = list(proposed.keys()) if isinstance(proposed, dict) else []
    bad = [p for p in ptrs if pointer_tokens(p) is None]
    if bad:
        out.append(_v("SEGMENT_POINTER_INVALID", "HARD", f"JSON Pointer 형식 오류 {len(bad)}건"))
    good = [p for p in ptrs if p not in bad]
    if any(i != j and under(good[i], good[j]) for i in range(len(good)) for j in range(len(good))):
        out.append(_v("SEGMENT_OVERLAP", "HARD", "세그먼트 안 포인터가 서로 겹침(같은 내용 중복 평가)"))
    if not out:
        out += REGISTRY.observe(m)
    return out, m


# ── 전체 매니페스트(참조 구현) ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SegmentPlan:
    segment_id: str
    pointers: Tuple[str, ...]


def segment_content(full: Any, plan: SegmentPlan) -> Dict[str, Any]:
    return {p: resolve(full, p)[1] for p in plan.pointers}


def verify_manifest(full: Any, plans: Sequence[SegmentPlan], *, max_chars: int = 60000) -> List[str]:
    """EC2 SegmentedQualityGate.precheck 와 같은 판정(위반 코드 목록, 중복 제거·발생 순)."""
    v: List[str] = []
    if not plans:
        return ["SEGMENT_PLAN_EMPTY"]
    ids = set()
    pointers: List[str] = []
    for p in plans:
        if not p.segment_id or not _SEGMENT_ID_RE.fullmatch(p.segment_id) or p.segment_id in ids:
            v.append("SEGMENT_ID_INVALID_OR_DUPLICATE")
        ids.add(p.segment_id)
        if not p.pointers:
            v.append("SEGMENT_POINTERS_EMPTY")
            continue
        for ptr in p.pointers:
            if not isinstance(ptr, str) or not ptr.startswith("/") or not resolve(full, ptr)[0]:
                v.append("SEGMENT_POINTER_MISSING")
            else:
                pointers.append(ptr)
        if all(isinstance(x, str) and x.startswith("/") for x in p.pointers) and \
                len(jackson_compact(segment_content(full, p))) > max_chars:
            v.append("SEGMENT_TOO_LARGE")
    for i in range(len(pointers)):
        for j in range(len(pointers)):
            if i != j and under(pointers[i], pointers[j]):
                v.append("SEGMENT_OVERLAP")
    for leaf in text_leaves(full):
        owners = sum(1 for p in pointers if under(leaf, p))
        if owners == 0:
            v.append("SEGMENT_COVERAGE_MISSING")
        elif owners > 1:
            v.append("SEGMENT_COVERAGE_DUPLICATE")
    return list(dict.fromkeys(v))


def manifest_id(full_checksum: str, refs: Sequence[Tuple[str, str]]) -> str:
    """EC2: sha256(fullChecksum + ('|' + segmentId + ':' + checksum)*)[:24]."""
    s = full_checksum + "".join(f"|{sid}:{cs}" for sid, cs in refs)
    return sha256_hex(s)[:24]


def build_marker(index: int, count: int, mid: str, segment_id: str, seg_checksum: str) -> str:
    return f"[분할 평가 {index}/{count} manifest={mid} segment={segment_id} checksum={seg_checksum[:16]}]"


def plan_roadmap_segments(full: Dict[str, Any], budget: int = 20000) -> List[SegmentPlan]:
    """EC2 MaterialRoadmapQualityGate.segmenter(budget) 의 Python 이식(테스트·교차 검증용, 같은 입력 → 같은 분할)."""
    out: List[SegmentPlan] = []
    header = ["/" + escape_token(k) for k in full if k != "weeks"]
    if header:
        out.append(SegmentPlan("hdr", tuple(header)))
    units: List[List[str]] = []
    sizes: List[int] = []
    weeks = full.get("weeks")
    if isinstance(weeks, list):
        for i, w in enumerate(weeks):
            wp = f"/weeks/{i}"
            ws = len(jackson_compact(w)) + len(wp) + 4
            if ws <= budget or not isinstance(w, dict) or not isinstance(w.get("days"), list):
                units.append([wp])
                sizes.append(ws)
                continue
            fields, fs = [], 0
            for k, val in w.items():
                if k != "days":
                    p = wp + "/" + escape_token(k)
                    fields.append(p)
                    fs += len(jackson_compact(val)) + len(p) + 4
            if fields:
                units.append(fields)
                sizes.append(fs)
            for j, d in enumerate(w["days"]):
                dp = f"{wp}/days/{j}"
                units.append([dp])
                sizes.append(len(jackson_compact(d)) + len(dp) + 4)
    cur: List[str] = []
    size = 0
    for u, s in zip(units, sizes):
        if cur and size + s > budget:
            out.append(SegmentPlan(f"s{len(out)}", tuple(cur)))
            cur, size = [], 0
        cur.extend(u)
        size += s
    if cur:
        out.append(SegmentPlan(f"s{len(out)}", tuple(cur)))
    return out


def spring_segment_requests(full: Dict[str, Any], base_request: str, base_rid: str, attempt: int = 0,
                            budget: int = 20000) -> List[Tuple[str, str, Dict[str, Any]]]:
    """EC2 가 평가기에 보내는 (requestId, originalRequest, proposedOutput) 목록을 그대로 재현(테스트용)."""
    plans = plan_roadmap_segments(full, budget)
    full_cs = checksum(full)
    contents = [segment_content(full, p) for p in plans]
    refs = [(p.segment_id, checksum(c)) for p, c in zip(plans, contents)]
    mid = manifest_id(full_cs, refs)
    out = []
    for i, (p, c) in enumerate(zip(plans, contents)):
        req = base_request + "\n" + build_marker(i + 1, len(plans), mid, p.segment_id, refs[i][1])
        out.append((f"{base_rid}.a{attempt}.s{i}", req, c))
    return out


# ── 생성 응답 무결성(content-integrity.v1) ─────────────────────────────────────────────
# 15만 자 로드맵이 전송·저장 중 잘리거나(누락) 주차가 겹쳐 붙는(중복) 것을 받는 쪽이 바로 알 수 있게, ai07 이 생성 직후
# '자기 자신을 제외한 본문'의 체크섬과 구조 개수를 싣는다. 받는 쪽은 integrity·generationId 를 뺀 본문을 같은 규칙으로
# 직렬화해 checksum 과 counts 를 대조한다(Spring: Map 으로 받은 직후, 노이즈 정리·진행 상태 추가 전에).
INTEGRITY_SCHEMA = "content-integrity.v1"
INTEGRITY_EXCLUDED = ("integrity", "generationId")


def _roadmap_counts(doc: Dict[str, Any]) -> Dict[str, int]:
    weeks = doc.get("weeks") if isinstance(doc.get("weeks"), list) else []
    days = [d for w in weeks if isinstance(w, dict) for d in (w.get("days") or []) if isinstance(d, dict)]
    return {"weeks": len(weeks), "days": len(days),
            "tasks": sum(len(d.get("tasks") or []) for d in days if isinstance(d.get("tasks"), list)),
            "textLeaves": len(text_leaves({k: v for k, v in doc.items() if k not in INTEGRITY_EXCLUDED}))}


def content_integrity(doc: Dict[str, Any]) -> Dict[str, Any]:
    body = {k: v for k, v in doc.items() if k not in INTEGRITY_EXCLUDED}
    return {"schemaVersion": INTEGRITY_SCHEMA, "algorithm": "sha256", "canonicalization": "jackson-jsonnode-tostring",
            "excludedFields": list(INTEGRITY_EXCLUDED), "checksum": checksum(body), "counts": _roadmap_counts(doc)}


def attach_integrity(doc: Dict[str, Any], prefix: str = "rg") -> Dict[str, Any]:
    """doc 에 integrity 와 generationId(= prefix-체크섬 앞 24자, 같은 내용이면 같은 ID)를 붙여 돌려준다(원본 변경)."""
    integ = content_integrity(doc)
    doc["generationId"] = f"{prefix}-{integ['checksum'][:24]}"
    doc["integrity"] = integ
    return doc


def verify_integrity(doc: Any) -> List[str]:
    """받는 쪽 대조의 참조 구현. 위반 코드 목록(빈 목록 = 일치)."""
    if not isinstance(doc, dict) or not isinstance(doc.get("integrity"), dict):
        return ["INTEGRITY_MISSING"]
    integ = doc["integrity"]
    out: List[str] = []
    if integ.get("schemaVersion") != INTEGRITY_SCHEMA or integ.get("algorithm") != "sha256":
        out.append("INTEGRITY_UNSUPPORTED")
        return out
    body = {k: v for k, v in doc.items() if k not in INTEGRITY_EXCLUDED}
    try:
        if checksum(body) != integ.get("checksum"):
            out.append("INTEGRITY_CHECKSUM_MISMATCH")
    except (TypeError, ValueError):
        out.append("INTEGRITY_CHECKSUM_MISMATCH")
    counts = integ.get("counts") if isinstance(integ.get("counts"), dict) else {}
    actual = _roadmap_counts(doc)
    for k in ("weeks", "days", "tasks", "textLeaves"):
        if counts.get(k) != actual[k]:
            out.append(f"INTEGRITY_COUNT_MISMATCH_{k.upper()}")
    gid = doc.get("generationId")
    if gid is not None and not (isinstance(gid, str) and gid.endswith("-" + str(integ.get("checksum", ""))[:24])):
        out.append("INTEGRITY_GENERATION_ID_MISMATCH")
    return out
