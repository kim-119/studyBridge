"""
학습 시간 배분 — C Native Engine(secret_sauce_engine/scheduler) wrapper.

설계 원칙:
  - import 시점에 .so 를 로딩하지 않는다(lazy). FastAPI 기동을 절대 막지 않는다.
  - 첫 호출/health 시점에만 ctypes.CDLL 시도. threading.Lock 으로 중복 로딩 방지.
  - C 로딩 실패/ABI 오류/반환 오류 → Python fallback(동일 스키마, engine="python-fallback").
  - 라우터는 이 모듈의 public 함수만 호출한다(ctypes 직접 사용 금지).

ABI: int optimize_schedule(subject_count, days, daily_minutes,
        const int* pri, const int* weak, const int* exam,
        int* out_day, int* out_subj, int* out_min, int max_tasks, int* out_count)
"""
from __future__ import annotations

import ctypes
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# 안전 한도 (라우터 pydantic 검증과 별개로 wrapper 자체 방어)
MAX_SUBJECTS = 20
MAX_TOPICS = 50
MAX_DAYS = 30
MIN_UNIT = 10

_REL_LIB_PATH = "secret_sauce_engine/scheduler/libscheduler.so"
_LIB_PATH = Path(__file__).resolve().parents[2] / _REL_LIB_PATH


class NativeSchedulerService:
    """C scheduler lazy-loader + fallback. module-level 싱글턴으로 재사용."""

    def __init__(self) -> None:
        self._lib = None
        self._load_tried = False
        self._available = False
        self._lock = threading.Lock()

    # ── lazy loading ────────────────────────────────────────────────
    def _load_library(self) -> None:
        if self._load_tried:
            return
        with self._lock:
            if self._load_tried:
                return
            self._load_tried = True
            try:
                if not _LIB_PATH.exists():
                    logger.info("[native_scheduler] .so 없음 → Python fallback")
                    return
                lib = ctypes.CDLL(str(_LIB_PATH))
                lib.optimize_schedule.restype = ctypes.c_int
                lib.optimize_schedule.argtypes = [
                    ctypes.c_int, ctypes.c_int, ctypes.c_int,
                    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.c_int, ctypes.POINTER(ctypes.c_int),
                ]
                self._lib = lib
                self._available = True
                logger.info("[native_scheduler] C 엔진 로드 완료")
            except Exception as e:  # noqa: BLE001 — 어떤 ctypes/ABI 오류든 fallback
                self._lib = None
                self._available = False
                logger.warning("[native_scheduler] C 로드 실패(%s) → Python fallback", type(e).__name__)

    def _usable(self) -> bool:
        # 런타임에 .so 가 삭제/이동되면(파일 부재) 즉시 fallback 으로 전환한다.
        return bool(self._available) and self._lib is not None and _LIB_PATH.exists()

    def health(self) -> Dict[str, Any]:
        self._load_library()
        usable = self._usable()
        return {
            "available": usable,
            "engine": "c-native" if usable else "python-fallback",
            "libraryPath": _REL_LIB_PATH,  # 절대경로 노출 금지(상대경로만)
        }

    # ── public API ──────────────────────────────────────────────────
    def optimize_schedule(self, request: Dict[str, Any]) -> Dict[str, Any]:
        norm = _normalize_request(request)
        days = norm["days"]
        daily_minutes = norm["daily_minutes"]
        subjects = norm["subjects"]
        n = len(subjects)

        self._load_library()
        if self._usable():
            try:
                tasks = self._call_c(n, days, daily_minutes, subjects)
                if tasks is not None:
                    return _assemble(tasks, subjects, days, daily_minutes, engine="c-native", fallback=False)
            except Exception as e:  # noqa: BLE001
                logger.warning("[native_scheduler] C 호출 예외(%s) → fallback", type(e).__name__)

        # Python fallback
        tasks = _distribute_python(n, days, daily_minutes, subjects)
        return _assemble(tasks, subjects, days, daily_minutes, engine="python-fallback", fallback=True)

    def _call_c(self, n: int, days: int, daily_minutes: int,
                subjects: List[Dict[str, Any]]) -> List[tuple] | None:
        IntArr = ctypes.c_int * n
        pri = IntArr(*[s["priority"] for s in subjects])
        weak = IntArr(*[s["weakness"] for s in subjects])
        exam = IntArr(*[s["exam_weight"] for s in subjects])
        max_tasks = n * days
        OutArr = ctypes.c_int * max_tasks
        out_day = OutArr()
        out_subj = OutArr()
        out_min = OutArr()
        out_count = ctypes.c_int(0)
        rc = self._lib.optimize_schedule(
            ctypes.c_int(n), ctypes.c_int(days), ctypes.c_int(daily_minutes),
            pri, weak, exam, out_day, out_subj, out_min,
            ctypes.c_int(max_tasks), ctypes.byref(out_count),
        )
        if rc != 0:
            logger.info("[native_scheduler] C 반환 코드 %s → fallback", rc)
            return None
        tc = out_count.value
        if tc < 0 or tc > max_tasks:
            return None
        return [(out_day[i], out_subj[i], out_min[i]) for i in range(tc)]


# ── 입력 정규화 / 조립 / Python fallback 분배 ──────────────────────────
def _clamp(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        iv = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, iv))


def _normalize_request(request: Dict[str, Any]) -> Dict[str, Any]:
    request = request if isinstance(request, dict) else {}
    daily_minutes = _clamp(request.get("daily_minutes"), 30, 720, 180)
    days = _clamp(request.get("days"), 1, MAX_DAYS, 7)
    raw_subjects = request.get("subjects")
    if not isinstance(raw_subjects, list):
        raw_subjects = []
    subjects: List[Dict[str, Any]] = []
    for s in raw_subjects[:MAX_SUBJECTS]:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or f"과목 {len(subjects) + 1}")[:100]
        topics_raw = s.get("topics") if isinstance(s.get("topics"), list) else []
        topics = [str(t)[:100] for t in topics_raw[:MAX_TOPICS] if str(t).strip()]
        if not topics:
            topics = ["기본 학습"]  # topic 빈 배열 보정
        subjects.append({
            "name": name,
            "topics": topics,
            "priority": _clamp(s.get("priority"), 1, 5, 3),
            "weakness": _clamp(s.get("weakness"), 1, 5, 3),
            "exam_weight": _clamp(s.get("exam_weight"), 1, 5, 3),
        })
    if not subjects:
        subjects = [{"name": "기본 과목", "topics": ["기본 학습"],
                     "priority": 3, "weakness": 3, "exam_weight": 3}]
    return {"daily_minutes": daily_minutes, "days": days, "subjects": subjects}


def _assemble(tasks: List[tuple], subjects: List[Dict[str, Any]], days: int,
              daily_minutes: int, *, engine: str, fallback: bool) -> Dict[str, Any]:
    """(day_idx, subj_idx, minutes) 리스트 → 표준 응답. topic은 과목별 round-robin."""
    topic_cursor = [0] * len(subjects)
    by_day: Dict[int, List[Dict[str, Any]]] = {d: [] for d in range(days)}
    total = 0
    # day → subject 순으로 정렬해 topic 회전을 일관되게
    for day_idx, subj_idx, minutes in sorted(tasks, key=lambda t: (t[0], t[1])):
        if not (0 <= subj_idx < len(subjects)) or not (0 <= day_idx < days) or minutes <= 0:
            continue
        subj = subjects[subj_idx]
        topics = subj["topics"]
        topic = topics[topic_cursor[subj_idx] % len(topics)]
        topic_cursor[subj_idx] += 1
        by_day[day_idx].append({"subject": subj["name"], "topic": topic, "minutes": int(minutes)})
        total += int(minutes)

    days_out: List[Dict[str, Any]] = []
    for d in range(days):
        day_tasks = by_day[d]
        days_out.append({
            "day": d + 1,
            "totalMinutes": sum(t["minutes"] for t in day_tasks),
            "tasks": day_tasks,
        })
    return {
        "engine": engine,
        "fallback": fallback,
        "daily_minutes": daily_minutes,
        "total_minutes": total,
        "days": days_out,
    }


def _distribute_python(n: int, days: int, daily_minutes: int,
                       subjects: List[Dict[str, Any]]) -> List[tuple]:
    """C 와 동일 규칙의 Python 분배(fallback). 10분 블록, score 비례, 일자 분산."""
    daily_cap = daily_minutes // MIN_UNIT
    total_units = daily_cap * days
    score = [s["priority"] * 4 + s["weakness"] * 4 + s["exam_weight"] * 2 for s in subjects]
    sum_score = sum(score)

    if sum_score <= 0:
        units = [total_units // n] * n
    else:
        units = [(total_units * score[i]) // sum_score for i in range(n)]
    # 남는 블록 → score 높은 과목부터(임시 감점 회전)
    remainder = total_units - sum(units)
    sc = score[:]
    while remainder > 0:
        best = max(range(n), key=lambda i: sc[i])
        units[best] += 1
        sc[best] -= 1
        remainder -= 1

    grid = [[0] * n for _ in range(days)]
    day_total = [0] * days
    for i in range(n):
        u = units[i]
        cursor = i % days
        while u > 0:
            placed_any = False
            for d in range(days):
                if u <= 0:
                    break
                day = (cursor + d) % days
                if day_total[day] < daily_cap:
                    grid[day][i] += 1
                    day_total[day] += 1
                    u -= 1
                    placed_any = True
            if not placed_any:
                break
            cursor = (cursor + 1) % days

    tasks: List[tuple] = []
    for d in range(days):
        for i in range(n):
            if grid[d][i] > 0:
                tasks.append((d, i, grid[d][i] * MIN_UNIT))
    return tasks


# module-level 싱글턴 (생성 시점에 .so 로딩하지 않음)
_SERVICE: NativeSchedulerService | None = None
_SERVICE_LOCK = threading.Lock()


def get_scheduler_service() -> NativeSchedulerService:
    global _SERVICE
    if _SERVICE is None:
        with _SERVICE_LOCK:
            if _SERVICE is None:
                _SERVICE = NativeSchedulerService()
    return _SERVICE


def optimize_schedule(request: Dict[str, Any]) -> Dict[str, Any]:
    return get_scheduler_service().optimize_schedule(request)


def scheduler_health() -> Dict[str, Any]:
    return get_scheduler_service().health()
