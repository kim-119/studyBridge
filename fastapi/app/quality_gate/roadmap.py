"""84일(12주×7일) 학습 로드맵의 세그먼트 단위 결정적 검사(Phase D R2·R5-1).

입력은 둘 중 하나다:
  (a) EC2 분할 세그먼트 {"/hdr필드": …, "/weeks/3": {...}, "/weeks/5/days/2": {...}} — 원본에서 그대로 떼어 낸 부분 트리
  (b) 로드맵 전체 {"title": …, "weeks": [...]} (6만 자 이하일 때)
세그먼트 밖 내용(다른 주차·총 일수·주차 간 선수학습)은 추측하지 않는다 — 그건 전체 문서를 가진 Spring 결정적 검사가 한다.
여기서는 세그먼트 안에서 확정할 수 있는 것만 본다: 일자 제목/목표/과제 필수, 번호 순서, 과제 시간(1..600분)·하루 합계,
날짜 형식·순서, 자료 관련성(일자 개념이 자료 원문/요청에 나오는가), 일자 중복 반복.
실제 로드맵 JSON(study_action_router.build_week/build_day 와 LLM overlay)의 필드만 쓴다.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.quality_gate.segments import pointer_tokens, string_values

V = Tuple[str, str, str, Optional[str]]
HARD, MAJOR, MINOR, INFO = "HARD", "MAJOR", "MINOR", "INFO"

MAX_TASK_MINUTES = 600
DAY_MINUTES = 24 * 60
_HEADER_INT_FIELDS = ("total_weeks", "days_per_week", "total_days")


def _v(code: str, sev: str, reason: str) -> V:
    return (code, sev, reason[:300], None)


def is_roadmap_document(obj: Any) -> bool:
    return isinstance(obj, dict) and isinstance(obj.get("weeks"), list) and any(
        isinstance(w, dict) and isinstance(w.get("days"), list) for w in obj["weeks"])


def looks_like_roadmap_segment(obj: Any) -> bool:
    """세그먼트 객체이고 키가 로드맵 포인터(/weeks/… 또는 최상위 헤더 1단계)뿐인가."""
    if not isinstance(obj, dict) or not obj:
        return False
    has_week = False
    for k in obj:
        t = pointer_tokens(k) if isinstance(k, str) else None
        if t is None:
            return False
        if t[0] == "weeks":
            if len(t) < 2 or not t[1].isdigit():
                return False
            has_week = True
        elif len(t) != 1:
            return False
    return has_week or all(len(pointer_tokens(k) or []) == 1 for k in obj)


# ── 단위 추출 ───────────────────────────────────────────────────────────────────
class Unit:
    """세그먼트에서 평가할 단위: 일자(day), 주차 필드 묶음(week_meta), 헤더 필드(header)."""

    def __init__(self, kind: str, value: Any, week_idx: Optional[int] = None, day_idx: Optional[int] = None,
                 field: Optional[str] = None) -> None:
        self.kind, self.value, self.week_idx, self.day_idx, self.field = kind, value, week_idx, day_idx, field


def extract_units(obj: Any) -> Tuple[List[Unit], List[V]]:
    units: List[Unit] = []
    vs: List[V] = []
    if is_roadmap_document(obj):
        for k, val in obj.items():
            if k != "weeks":
                units.append(Unit("header", val, field=k))
        for i, w in enumerate(obj["weeks"]):
            units += _week_units(w, i, vs)
        return units, vs
    for ptr, val in obj.items():
        t = pointer_tokens(ptr) or []
        if t and t[0] == "weeks":
            wi = int(t[1])
            if len(t) == 2:
                units += _week_units(val, wi, vs)
            elif len(t) == 4 and t[2] == "days" and t[3].isdigit():
                units.append(Unit("day", val, wi, int(t[3])))
            elif len(t) == 3 and t[2] != "days":
                units.append(Unit("week_meta", val, wi, field=t[2]))
            else:
                vs.append(_v("SEGMENT_POINTER_UNSUPPORTED", MINOR, "로드맵 단위가 아닌 포인터"))
        elif len(t) == 1:
            units.append(Unit("header", val, field=t[0]))
    return units, vs


def _week_units(w: Any, wi: int, vs: List[V]) -> List[Unit]:
    if not isinstance(w, dict):
        vs.append(_v("ROADMAP_WEEK_NOT_OBJECT", HARD, f"{wi + 1}주차가 객체가 아님"))
        return []
    out: List[Unit] = []
    for k, val in w.items():
        if k != "days":
            out.append(Unit("week_meta", val, wi, field=k))
    days = w.get("days")
    if not isinstance(days, list) or not days:
        vs.append(_v("ROADMAP_DAYS_MISSING", HARD, f"{wi + 1}주차 일자 목록 없음"))
        return out
    for j, d in enumerate(days):
        out.append(Unit("day", d, wi, j))
    return out


# ── 검사 ────────────────────────────────────────────────────────────────────────
def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _num(x: Any) -> Optional[float]:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def _date(s: Any) -> Tuple[bool, Optional[date]]:
    """(형식 오류 여부, 날짜). None/빈 문자열은 '날짜 없음'(오류 아님)."""
    if s is None or (isinstance(s, str) and not s.strip()):
        return False, None
    if not isinstance(s, str):
        return True, None
    try:
        return False, datetime.fromisoformat(s.strip()[:10]).date()
    except ValueError:
        return True, None


def check_units(units: Sequence[Unit], *, max_daily_hours: Optional[float], deadline: Optional[str]) -> Tuple[List[V], Dict[str, Any]]:
    vs: List[V] = []
    stats = {"days": 0, "tasks": 0, "weekMeta": 0, "header": 0, "structureHard": 0, "structureMajor": 0,
             "capacityHard": 0}
    cap_min = DAY_MINUTES if not max_daily_hours else min(DAY_MINUTES, max_daily_hours * 60.0)
    dl_bad, dl = _date(deadline) if deadline else (False, None)
    seen_codes: Dict[str, int] = {}

    def add(code: str, sev: str, reason: str) -> None:
        seen_codes[code] = seen_codes.get(code, 0) + 1
        if seen_codes[code] == 1:           # 같은 위반은 한 번만 보고(감점 폭주 방지), 개수는 사유에
            vs.append(_v(code, sev, reason))
        if code.startswith("ROADMAP_"):
            if sev == HARD:
                stats["structureHard"] += 1
            elif sev == MAJOR:
                stats["structureMajor"] += 1

    prev_date: Optional[date] = None
    last_day_key: Optional[Tuple[int, int]] = None
    for u in units:
        if u.kind == "header":
            stats["header"] += 1
            if u.field in _HEADER_INT_FIELDS and u.value is not None and not (_is_int(u.value) and u.value >= 1):
                add("ROADMAP_DECLARED_INVALID", HARD, f"{u.field} 값이 양의 정수가 아님")
            if u.field == "title" and u.value is not None and not (isinstance(u.value, str) and u.value.strip()):
                add("ROADMAP_TITLE_MISSING", MAJOR, "로드맵 제목이 비어 있음")
            continue
        if u.kind == "week_meta":
            stats["weekMeta"] += 1
            if u.field == "week" and not (_is_int(u.value) and u.value == (u.week_idx or 0) + 1):
                add("ROADMAP_WEEK_ORDER", MAJOR, f"{(u.week_idx or 0) + 1}번째 주차 번호 불일치")
            continue
        # day
        stats["days"] += 1
        d = u.value
        if not isinstance(d, dict):
            add("ROADMAP_DAY_NOT_OBJECT", HARD, "일자가 객체가 아님")
            continue
        key = (u.week_idx or 0, u.day_idx or 0)
        if last_day_key is not None and key <= last_day_key:
            add("ROADMAP_DAY_ORDER", MAJOR, "세그먼트 안 일자 순서 역전")
        last_day_key = key
        if not (_is_int(d.get("day_index")) and d.get("day_index") == (u.day_idx or 0) + 1):
            add("ROADMAP_DAY_ORDER", MAJOR, "일자 번호(day_index) 불일치")
        if not (isinstance(d.get("title"), str) and d["title"].strip()):
            add("ROADMAP_DAY_TITLE_MISSING", HARD, "일자 제목 없음")
        if not (isinstance(d.get("objective"), str) and d["objective"].strip()):
            add("ROADMAP_DAY_OBJECTIVE_MISSING", HARD, "일자 학습 목표 없음")
        tasks = d.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            add("ROADMAP_DAY_TASKS_MISSING", HARD, "일자 과제 없음")
        else:
            minutes = 0.0
            for t in tasks:
                stats["tasks"] += 1
                if isinstance(t, dict):
                    if not (isinstance(t.get("title"), str) and t["title"].strip()):
                        add("ROADMAP_TASK_TITLE_MISSING", MAJOR, "과제 제목 없음")
                    em = t.get("estimated_minutes")
                    if em is None:
                        continue
                    n = _num(em)
                    if n is None or n < 1 or n > MAX_TASK_MINUTES:
                        add("ROADMAP_TASK_MINUTES_OUT_OF_RANGE", HARD, "과제 예상 시간이 1..600분 밖")
                        stats["capacityHard"] += 1
                    else:
                        minutes += n
                elif not (isinstance(t, str) and t.strip()):
                    add("ROADMAP_TASK_TITLE_MISSING", MAJOR, "과제가 비어 있음")
            if minutes > cap_min + 1e-9:
                add("ROADMAP_DAY_OVER_CAPACITY", HARD, f"하루 과제 시간 {int(minutes)}분 > 상한 {int(cap_min)}분")
                stats["capacityHard"] += 1
        bad, dd = _date(d.get("date"))
        if bad:
            add("ROADMAP_DATE_INVALID", HARD, "날짜 형식 오류")
        elif dd is not None:
            if prev_date is not None and dd <= prev_date:
                add("ROADMAP_DATE_ORDER", MAJOR, "날짜가 오름차순이 아님")
            prev_date = dd
            if dl is not None and dd > dl:
                add("PLAN_PAST_DEADLINE", HARD, "마감일 이후 일정")
                stats["capacityHard"] += 1
    if dl_bad:
        add("PLAN_DEADLINE_INVALID", MINOR, "마감일 형식 오류(검사 생략)")
    for code, n in seen_codes.items():
        if n > 1:
            vs[:] = [(c, s, (r + f" (총 {n}건)")[:300], e) if c == code else (c, s, r, e) for (c, s, r, e) in vs]
    return vs, stats


# ── 자료 관련성 ────────────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def day_concepts(d: Dict[str, Any]) -> List[str]:
    """일자의 '개념 슬롯': core_concepts(키워드) 우선, 없으면 제목의 '—' 앞부분/제목."""
    cc = d.get("core_concepts")
    out = [c for c in cc if isinstance(c, str) and c.strip()] if isinstance(cc, list) else []
    if not out:
        t = d.get("title") if isinstance(d.get("title"), str) else ""
        head = re.split(r"\s[—\-–:]\s", t, maxsplit=1)[0] if t else ""
        out = [x for x in (head, t) if x and x.strip()][:1]
    return out[:6]


def material_relevance(units: Sequence[Unit], evidence_texts: Sequence[str], request_text: str,
                       stems_fn) -> Tuple[Optional[float], int, int]:
    """(관련 일자 비율 또는 None, 관련 일자 수, 평가 일자 수). 근거가 없으면 None(검증 불가 → 점수에서 제외)."""
    if not evidence_texts:
        return None, 0, 0
    corpus = " ".join(evidence_texts) + " " + (request_text or "")
    ncorpus = _norm(corpus)
    cstems = stems_fn(corpus)
    total = related = 0
    for u in units:
        if u.kind != "day" or not isinstance(u.value, dict):
            continue
        concepts = day_concepts(u.value)
        if not concepts:
            continue
        total += 1
        if any(_norm(c) and (_norm(c) in ncorpus or (stems_fn(c) & cstems)) for c in concepts):
            related += 1
    if not total:
        return None, 0, 0
    return related / total, related, total


def duplicate_day_ratio(units: Sequence[Unit]) -> float:
    keys = []
    for u in units:
        if u.kind == "day" and isinstance(u.value, dict):
            keys.append((_norm(str(u.value.get("title") or "")), _norm(str(u.value.get("objective") or ""))))
    if len(keys) < 3:
        return 0.0
    return 1.0 - len(set(keys)) / len(keys)


def unit_text(units: Iterable[Unit]) -> str:
    parts: List[str] = []
    for u in units:
        parts += string_values(u.value)
    return "\n".join(parts)


def fallback_declared(units: Sequence[Unit]) -> bool:
    return any(u.kind == "header" and u.field in ("fallback_used", "isFallback") and u.value is True for u in units)
