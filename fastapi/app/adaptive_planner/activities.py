"""시간 적응형 활동 구성(두 엔진 공용). 분 배분은 결정적이며 합계는 항상 선택 시간 이하다.

활동 문구는 '학습 방법'만 말한다(무엇을 어떻게 할지). 도메인 지식은 넣지 않고,
초점(focus)은 사용자 데이터(과제 문장·단계 제목)에서만 가져온다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.adaptive_planner import config
from app.adaptive_planner.schema import Item, Task

PHASES: Dict[str, Tuple[str, str]] = {
    "CONCEPT": ("핵심 개념 정리", "'{focus}'의 정의와 핵심 용어를 정리하고, 학습 목표를 자신의 말로 한 문장으로 적어 봅니다."),
    "UNDERSTAND": ("원리 이해", "'{focus}'가 어떤 순서로 동작하는지 단계별로 따라가며 흐름을 설명해 봅니다."),
    "EXAMPLE": ("예제 풀이", "'{focus}'를 적용한 예제를 직접 풀고 풀이 과정을 단계별로 적어 봅니다."),
    "PRACTICE": ("직접 적용", "'{focus}'를 직접 구현하거나 새 문제에 적용해 보고 막힌 지점을 기록합니다."),
    "CHECK": ("확인 문제", "자료를 덮고 '{focus}'의 핵심 질문에 스스로 답해 보며 이해한 범위를 확인합니다."),
    "REVIEW": ("핵심 복습", "오늘 다룬 '{focus}' 내용을 세 줄로 요약하고 헷갈린 부분을 표시해 둡니다."),
    "PREP": ("목표 확인", "'{focus}'에서 이번 세션에 끝낼 범위를 정하고 필요한 자료를 준비합니다."),
    "WORK": ("집중 학습", "'{focus}'를 정한 범위까지 집중해서 진행합니다."),
    "WRAP": ("정리 및 기록", "진행한 범위와 남은 분량을 기록해 다음 세션에 바로 이어갈 수 있게 합니다."),
}


@dataclass
class Activity:
    type: str
    title: str
    description: str
    minutes: int
    tasks: List[Task] = field(default_factory=list)
    concept_tags: List[str] = field(default_factory=list)
    question_raws: List[Any] = field(default_factory=list)

    def to_dict(self, order: int) -> Dict[str, Any]:
        d: Dict[str, Any] = {"order": order, "type": self.type, "title": self.title,
                             "description": self.description, "minutes": self.minutes,
                             "sourceTaskIds": [t.id_raw for t in self.tasks]}
        if self.concept_tags:
            d["conceptTags"] = list(self.concept_tags)
        if self.question_raws:
            d["evidenceQuestionIds"] = list(self.question_raws)
        return d


@dataclass
class Remediation:
    """실제 퀴즈 오답에서만 만든다. concept_tags 가 비면 '오답 재풀이'(개념명 없음)."""
    concept_tags: List[str]
    question_raws: List[Any]
    wrong_count: int


def _phase(typ: str, focus: str, minutes: int, tasks: Sequence[Task] = ()) -> Activity:
    label, desc = PHASES[typ]
    title = f"{focus} · {label}" if focus else label
    return Activity(type=typ, title=title, description=desc.format(focus=focus), minutes=minutes, tasks=list(tasks))


def _shrink(mins: List[int], amount: int, floor: int = 3) -> List[int]:
    """가장 큰 단계부터 1분씩 줄여 amount 만큼 확보한다(각 단계 floor 분 유지)."""
    out = list(mins)
    while amount > 0:
        idx = max(range(len(out)), key=lambda i: (out[i], -i))
        if out[idx] <= floor:
            break
        out[idx] -= 1
        amount -= 1
    return out


def remaining_minutes(item: Item) -> Optional[int]:
    """남은 예상 분. 예상시간이 없으면 None(만들어 내지 않는다)."""
    est = item.estimated_minutes
    if est is None:
        return None
    if item.progress_total:
        left = item.progress_total - (item.progress_completed or 0)
        rem = math.ceil(est * left / item.progress_total)
    elif item.tasks:
        rem = math.ceil(est * len(item.open_tasks) / len(item.tasks))
    else:
        rem = est
    return rem if rem > 0 else None


def roadmap_activities(step: Item, minutes: int, remediation: Optional[Remediation]
                       ) -> Tuple[List[Activity], List[Task]]:
    """현재 단계 활동. 반환: (활동, 이번 세션에서 다루는 미완료 과제)."""
    tpl = config.ROADMAP_TEMPLATES[minutes]
    core: List[Tuple[str, int]] = list(tpl["core"])
    wrap_type, wrap_min = tpl["wrap"]
    core_mins = [m for _, m in core]
    acts: List[Activity] = []
    if remediation is not None:
        r = tpl["remediation"]
        shrunk = _shrink(core_mins, r)
        r = sum(core_mins) - sum(shrunk)
        core_mins = shrunk
        if remediation.concept_tags:
            tags = ", ".join(remediation.concept_tags)
            acts.append(Activity(
                type="REMEDIATION", title=f"선행 개념 복습: {tags}",
                description=f"최근 퀴즈에서 오답이 나온 '{tags}' 개념을 짧게 다시 확인하고, 틀린 문항을 다시 풀어 봅니다.",
                minutes=r, concept_tags=list(remediation.concept_tags), question_raws=list(remediation.question_raws)))
        else:
            acts.append(Activity(
                type="WRONG_ANSWER_REVIEW", title="최근 오답 다시 풀기",
                description=f"최근 퀴즈에서 틀린 {remediation.wrong_count}문항을 다시 풀고 틀린 이유를 한 줄씩 적어 봅니다.",
                minutes=r, question_raws=list(remediation.question_raws)))
    covered = step.open_tasks[: tpl["max_tasks"]]
    for i, (typ, _) in enumerate(core):
        task = covered[i * len(covered) // len(core)] if covered else None
        focus = task.text if task else step.title
        acts.append(_phase(typ, focus, core_mins[i], [task] if task else []))
    acts.append(_phase(wrap_type, step.title, wrap_min))
    assert sum(a.minutes for a in acts) <= minutes
    return acts, covered


def manual_activities(item: Item, minutes: int) -> Tuple[List[Activity], int, Optional[int], List[Task]]:
    """수기 항목 세션. 반환: (활동, 세션 분, 남은 예상 분|None, 다루는 미완료 과제)."""
    remaining = remaining_minutes(item)
    session = minutes if remaining is None else min(minutes, max(5, remaining))
    tpl = config.MANUAL_TEMPLATES[minutes]
    covered = item.open_tasks[: tpl["max_tasks"]]
    if session <= 10:
        acts = [_phase("WORK", covered[0].text if covered else item.title, session, covered[:1])]
        return acts, session, remaining, covered[:1]
    prep = max(1, round(tpl["prep"] * session / minutes))
    wrap = max(2, round(tpl["wrap"] * session / minutes))
    work = session - prep - wrap
    acts = [_phase("PREP", item.title, prep)]
    if covered:
        base, extra = divmod(work, len(covered))
        for i, t in enumerate(covered):
            acts.append(_phase("WORK", t.text, base + (1 if i < extra else 0), [t]))
    else:
        acts.append(_phase("WORK", item.title, work))
    acts.append(_phase("WRAP", item.title, wrap))
    assert sum(a.minutes for a in acts) == session <= minutes
    return acts, session, remaining, covered


def plan_sessions(today_minutes: int, today_tasks: Sequence[Task], rest_tasks: Sequence[Task],
                  rest_remaining: Optional[int], minutes: int, max_tasks: int) -> Tuple[List[Dict[str, Any]], bool]:
    """하루 한 세션씩 나눈 일정 제안(날짜는 오프셋 일수). 반환: (세션들, 상한으로 잘렸는지).

    첫 세션은 오늘 추천한 세션 그대로이고, 남은 과제·남은 예상 분은 다음 날부터 하루 minutes 이하로 나눈다.
    남은 예상 분을 알면 세션 분 합계가 그 값과 같다(과제 묶음 하나가 하루에 안 끝나면 여러 날에 걸친다).
    """
    sessions: List[Dict[str, Any]] = [{"dayOffset": 0, "minutes": today_minutes, "tasks": list(today_tasks)}]
    chunks = [list(rest_tasks[i:i + max_tasks]) for i in range(0, len(rest_tasks), max_tasks)]
    if rest_remaining is not None and rest_remaining > 0:
        per = math.ceil(rest_remaining / len(chunks)) if chunks else rest_remaining
        for ch in chunks or [[]]:
            need = per
            while need > 0:
                m = min(minutes, need)
                sessions.append({"dayOffset": len(sessions), "minutes": max(5, m), "tasks": ch})
                need -= m
    else:
        # 남은 예상 분이 없으면 과제 묶음마다 선택 시간 한 세션.
        for ch in chunks:
            sessions.append({"dayOffset": len(sessions), "minutes": minutes, "tasks": ch})
    truncated = len(sessions) > config.MAX_RECOVERY_SESSIONS
    return sessions[: config.MAX_RECOVERY_SESSIONS], truncated
