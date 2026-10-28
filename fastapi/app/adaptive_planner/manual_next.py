"""ENGINE B — MANUAL_NEXT: 수기 플래너 다음 학습 우선순위(결정적 점수 + 안정 정렬).

점수 요인(가중치는 config.ManualWeights): 사용자 우선순위 · 마감 근접 · 마감 경과 · 예정일 경과 ·
오늘 예정 · 진행 중 · 가용 시간 내 완료 가능 · 사용자 순서. 완료 항목은 후보에서 뺀다.
동점: 마감 경과일↓ → 마감일↑(없음은 뒤) → 우선순위↓ → 사용자 순서↑(없음은 뒤) → 입력 순서↑.
로드맵 코치와 달리 '무엇을 할지'를 고르는 엔진이며, 입력 순서 첫 항목을 그대로 내지 않는다.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from app.adaptive_planner import config
from app.adaptive_planner.activities import manual_activities, plan_sessions, remaining_minutes
from app.adaptive_planner.roadmap_coach import EngineResult
from app.adaptive_planner.schema import AdaptiveRequest, Item

_PRIORITY_LABEL = {"URGENT": "긴급", "HIGH": "높음", "MEDIUM": "보통", "LOW": "낮음"}
_PRIORITY_RANK = {"URGENT": 0, "HIGH": 1, "MEDIUM": 2, None: 2, "LOW": 3}
_TIE_RULES = ("마감 경과일", "마감일", "우선순위", "사용자 순서", "입력 순서")


@dataclass
class Scored:
    item: Item
    score: int
    factors: List[Dict[str, Any]]       # points > 0 인 실제 기여 요인
    overdue_days: int
    delay: Optional[Tuple[str, int]]    # ("OVERDUE"|"SCHEDULE_PASSED", 일수)
    remaining: Optional[int]
    sort_key: Tuple


def _factor(code: str, points: int, detail: str, cite: bool = True) -> Dict[str, Any]:
    return {"factor": code, "points": points, "detail": detail, "cited": cite}


def score_items(req: AdaptiveRequest, w: Optional[config.ManualWeights] = None) -> List[Scored]:
    w = w or config.manual_weights()
    B, today = req.available_minutes, req.today
    cands = [it for it in req.items if not it.completed]
    ordered = sorted((it for it in cands if it.order_index is not None), key=lambda it: (it.order_index, it.index))
    order_rank = {it.key: r for r, it in enumerate(ordered)}
    out: List[Scored] = []
    for it in cands:
        f: List[Dict[str, Any]] = []
        if it.priority:
            f.append(_factor("PRIORITY", w.priority[it.priority], f"사용자 우선순위 {_PRIORITY_LABEL[it.priority]}"))
        else:
            f.append(_factor("PRIORITY_UNSET", w.priority_unset, "우선순위 미지정(중립값)", cite=False))
        overdue_days, delay = 0, None
        if it.due_date is not None:
            d = (it.due_date - today).days
            if d < 0:
                overdue_days = -d
                delay = ("OVERDUE", -d)
                f.append(_factor("OVERDUE", w.overdue_base + min(w.overdue_cap, w.overdue_per_day * -d),
                                 "마감이 어제였던 미완료 항목" if d == -1 else f"마감이 {-d}일 지난 미완료 항목"))
            else:
                pts = max(0, w.due_max - w.due_step * d)
                if pts:
                    f.append(_factor("DUE_SOON", pts, "오늘 마감" if d == 0 else ("내일 마감" if d == 1 else f"마감 {d}일 전")))
        if it.scheduled_date is not None and delay is None:
            d = (it.scheduled_date - today).days
            if d < 0:
                delay = ("SCHEDULE_PASSED", -d)
                f.append(_factor("SCHEDULE_PASSED", w.delayed_base + min(w.delayed_cap, w.delayed_per_day * -d),
                                 "어제 예정이었던 미완료 일정" if d == -1 else f"예정일이 {-d}일 지난 미완료 일정"))
            elif d == 0:
                f.append(_factor("SCHEDULED_TODAY", w.scheduled_today, "오늘 예정된 일정"))
        if it.status == "IN_PROGRESS":
            f.append(_factor("IN_PROGRESS", w.in_progress, "이미 진행 중인 항목"))
        rem = remaining_minutes(it)
        if rem is not None and rem <= B:
            f.append(_factor("FITS_AVAILABLE_TIME", w.fits_available_time, f"남은 예상 {rem}분으로 {B}분 안에 마칠 수 있음"))
        if it.key in order_rank:
            pts = max(0, w.order_max - order_rank[it.key])
            if pts:
                f.append(_factor("USER_ORDER", pts, f"사용자 지정 순서 {order_rank[it.key] + 1}번째"))
        f = [x for x in f if x["points"] > 0]
        total = sum(x["points"] for x in f)
        key = (-total, -overdue_days, it.due_date or date.max, _PRIORITY_RANK[it.priority],
               it.order_index if it.order_index is not None else math.inf, it.index, it.key)
        out.append(Scored(it, total, f, overdue_days, delay, rem, key))
    out.sort(key=lambda s: s.sort_key)
    return out


def _tie_rule(a: Scored, b: Scored) -> Optional[str]:
    """점수가 같을 때 a 를 b 보다 앞세운 첫 번째 동점 규칙."""
    for i, name in enumerate(_TIE_RULES):
        if a.sort_key[i + 1] != b.sort_key[i + 1]:
            return name
    return None


def _day_word(today: date, offset: int) -> str:
    if offset <= 2:
        return ("오늘", "내일", "모레")[offset]
    d = today + timedelta(days=offset)
    return f"{d.month}월 {d.day}일"


def _cited(s: Scored, n: int = 2) -> List[Dict[str, Any]]:
    return sorted((x for x in s.factors if x["cited"]), key=lambda x: -x["points"])[:n]


def _reason(top: Scored, runner: Optional[Scored], B: int) -> str:
    cited = _cited(top)
    basis = " · ".join(x["detail"] for x in cited) if cited else "다른 미완료 항목과 조건이 같음"
    parts = [f"'{top.item.title}'을(를) 가장 먼저 추천합니다(근거: {basis})."]
    if runner is not None:
        if runner.score < top.score:
            rc = _cited(runner, 1)
            why = f"({rc[0]['detail']})" if rc else ""
            parts.append(f"다음 후보 '{runner.item.title}'{why}보다 우선순위 점수가 {top.score - runner.score}점 높습니다.")
        else:
            rule = _tie_rule(top, runner)
            parts.append(f"다음 후보 '{runner.item.title}'와 점수가 같아 동점 규칙({rule or '항목 ID'})으로 앞섰습니다.")
    if top.remaining is not None and top.remaining > B:
        parts.append(f"남은 예상 {top.remaining}분은 {B}분 안에 끝나지 않아 이번에는 일부만 진행합니다.")
    return " ".join(parts)


def recommend(req: AdaptiveRequest) -> EngineResult:
    B, today = req.available_minutes, req.today
    if not req.items:
        return EngineResult(status="INSUFFICIENT_DATA", status_reason="EMPTY_PLANNER",
                            message="플래너에 학습 항목이 없어 다음 학습을 정할 수 없습니다.")
    ranked = score_items(req)
    if not ranked:
        return EngineResult(status="ALL_COMPLETED", status_reason="ALL_ITEMS_COMPLETED",
                            message="플래너의 모든 학습 항목을 완료했습니다.")
    top = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else None
    it = top.item
    acts, session, remaining, covered = manual_activities(it, B)

    # 제안 일정의 날짜별 사용 분(하루 합계 ≤ B). 채우는 순서:
    #   오늘 세션 → 1순위 항목의 마감일까지 이어가기 → 다른 지연 항목 복구 → 1순위 항목의 마감 뒤 이어가기.
    used: Dict[int, int] = {0: session}
    sessions: List[Dict[str, Any]] = []
    truncated = False
    if remaining is not None and remaining > B:
        sessions, truncated = plan_sessions(session, covered, it.open_tasks[len(covered):], remaining - session,
                                            B, config.MANUAL_TEMPLATES[B]["max_tasks"])
        due_off = (it.due_date - today).days if it.due_date is not None else -1
        for s in sessions[1:]:
            if s["dayOffset"] <= due_off:
                used[s["dayOffset"]] = used.get(s["dayOffset"], 0) + s["minutes"]

    # 지연 복구: 마감/예정일이 지난 미완료 항목을 순위대로 최대 N개. 1순위 추천이 지연 항목이면 오늘 세션이 곧 복구다.
    # 다른 항목은 남은 시간이 MIN_RECOVERY_SESSION_MINUTES 이상인 가장 이른 날에, 그날 남은 시간만큼 넣는다.
    delayed = [s for s in ranked if s.delay is not None][: config.MAX_RECOVERY_ITEMS]
    recovery = None
    if delayed:
        entries = []
        for s in delayed:
            if s is top:
                day, mins = 0, session
            else:
                want = min(B, s.remaining) if s.remaining is not None else B
                need = min(want, config.MIN_RECOVERY_SESSION_MINUTES)
                day = next(d for d in itertools.count() if B - used.get(d, 0) >= need)
                mins = min(want, B - used.get(day, 0))
                used[day] = used.get(day, 0) + mins
            entries.append({
                "itemId": s.item.id_raw, "title": s.item.title, "delayType": s.delay[0], "delayDays": s.delay[1],
                "remainingMinutes": s.remaining,
                "proposal": {"action": "SCHEDULE_PARTIAL_SESSION" if (s.remaining or 0) > mins else "SCHEDULE_SESSION",
                             "itemId": s.item.id_raw, "date": (today + timedelta(days=day)).isoformat(),
                             "minutes": mins},
            })
            if s is delayed[0]:
                first_day, first_mins = day, mins
        first = delayed[0]
        when = "어제" if first.delay[1] == 1 else f"{first.delay[1]}일 전"
        what = "마감이었던" if first.delay[0] == "OVERDUE" else "예정됐던"
        partial = "일부를 먼저" if first.remaining is None or first.remaining > first_mins else "먼저"
        msg = (f"{when} {what} '{first.item.title}'이(가) 완료되지 않았습니다. "
               f"{_day_word(today, first_day)} {first_mins}분 동안 {partial} 처리하는 것을 권장합니다.")
        recovery = {"type": "CATCH_UP_DELAYED_ITEMS", "items": entries, "message": msg,
                    "requiresUserApproval": True,
                    "constraints": {"modifiesPlanner": False, "autoCompletesItem": False}}

    split = None
    if sessions:
        # 마감 뒤(또는 마감 없는) 이어가기는 복구 제안이 차지한 날을 피해, 앞 세션 다음 날부터 자리가 있는 날에 둔다.
        last = 0
        for s in sessions[1:]:
            if s["dayOffset"] > due_off:
                s["dayOffset"] = next(d for d in itertools.count(last + 1) if used.get(d, 0) + s["minutes"] <= B)
                used[s["dayOffset"]] = used.get(s["dayOffset"], 0) + s["minutes"]
            last = s["dayOffset"]
        split = {"isPartial": True, "thisSessionMinutes": session, "remainingMinutes": remaining,
                 "remainingAfterSession": remaining - session, "sessionsNeeded": math.ceil(remaining / B),
                 "sessions": [{"order": i + 1, "action": "SCHEDULE_PARTIAL_SESSION", "itemId": it.id_raw,
                               "date": (today + timedelta(days=s["dayOffset"])).isoformat(), "minutes": s["minutes"],
                               "taskIds": [t.id_raw for t in s["tasks"]]} for i, s in enumerate(sessions)],
                 "truncated": truncated, "requiresUserApproval": True}

    alternatives = [{"itemId": s.item.id_raw, "title": s.item.title, "rank": i + 2, "score": s.score,
                     "reason": ", ".join(x["detail"] for x in _cited(s)) or "기본 조건",
                     "scoreBreakdown": [{k: v for k, v in x.items() if k != "cited"} for x in s.factors]}
                    for i, s in enumerate(ranked[1:1 + config.MAX_ALTERNATIVES])]
    coaching = (f"이번 {session}분은 '{it.title}'에 집중하세요. "
                + ("정한 범위까지만 진행하고 남은 분량은 기록해 두세요." if split else "끝나면 완료 여부를 직접 체크해 주세요."))
    rec = {
        "itemId": it.id_raw, "title": it.title, "rank": 1, "score": top.score,
        "scoreBreakdown": [{k: v for k, v in x.items() if k != "cited"} for x in top.factors],
        "reason": _reason(top, runner, B), "coachingMessage": coaching,
        "estimatedMinutes": session,
        "timeEstimate": {"isEstimate": True,
                         "basis": "ITEM_ESTIMATE" if remaining is not None else "ALLOCATED_FROM_AVAILABLE_TIME",
                         "itemRemainingMinutes": remaining},
        "evidenceItemIds": [it.id_raw] + ([runner.item.id_raw] if runner else []),
        "coveredTaskIds": [t.id_raw for t in covered],
        "partialPlan": split,
        "nextAction": {"type": "START_FOCUS_SESSION", "itemId": it.id_raw, "minutes": session,
                       "label": f"{session}분 학습 시작"},
    }

    grounded: Set[str] = {str(B), str(session)} | {str(a.minutes) for a in acts}
    for n in (remaining, (remaining - session) if remaining else None, top.overdue_days,
              top.delay[1] if top.delay else None, len(it.open_tasks), len(covered)):
        if n is not None:
            grounded.add(str(n))
    if it.due_date is not None:
        grounded.add(str(abs((it.due_date - today).days)))
    others = [s.item.title for s in ranked[1:]]
    llm_ctx = {
        "mode": "MANUAL_NEXT", "availableMinutes": B,
        "data": {
            "selectedItem": {"title": it.title, "subject": it.subject, "description": it.description[:600],
                             "coveredTasks": [t.text for t in covered]},
            "selectionReasons": [x["detail"] for x in top.factors if x["cited"]],
            "sessionMinutes": session, "isPartial": split is not None,
        },
        "forbiddenTitles": others,
        "allowWeakness": False, "allowedConcepts": [],
        "groundTexts": [it.title, it.subject, it.description] + [t.text for t in it.tasks],
        "groundedNumbers": grounded,
    }
    return EngineResult(status="READY", recommendation=rec, activities=acts, alternatives=alternatives,
                        recovery=recovery, llm=llm_ctx,
                        extra={"candidateCount": len(ranked)})
