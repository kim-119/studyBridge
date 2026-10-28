"""ENGINE A — ROADMAP_COACH: 현재 단계 학습 코칭(다음 단계 추천 없음).

판단 순서
  1) 현재 단계 확정(Spring 이 보낸 currentStepId, 검증은 schema 에서 끝남)
  2) 퀴즈 오답 → 취약 개념(개념 태그가 실제로 있을 때만) / 태그 없는 오답 → 오답 재풀이
  3) 선택 시간 템플릿으로 활동 구성(미완료 과제가 있으면 과제가 곧 활동 초점)
  4) 지연·시간 초과 시 '현재 단계 안에서만' 세션 분할 제안(순서 변경·자동 완료 없음)
"""
from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, List, Optional, Set

from app.adaptive_planner import config
from app.adaptive_planner.activities import (Activity, Remediation, plan_sessions, remaining_minutes,
                                             roadmap_activities)
from app.adaptive_planner.schema import AdaptiveRequest, Item


@dataclass
class EngineResult:
    status: str
    status_reason: Optional[str] = None
    message: Optional[str] = None
    recommendation: Optional[Dict[str, Any]] = None
    activities: List[Activity] = field(default_factory=list)
    alternatives: List[Dict[str, Any]] = field(default_factory=list)
    recovery: Optional[Dict[str, Any]] = None
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)
    llm: Optional[Dict[str, Any]] = None          # LLM 프롬프트·검증 컨텍스트(LLM 을 쓸 때만)


def _first_sentence(text: str, limit: int = 160) -> str:
    if not text:
        return ""
    s = re.split(r"(?<=[.!?。])\s+|\n", text.strip(), maxsplit=1)[0]
    return s[:limit].rstrip()


def _quiz_insight(req: AdaptiveRequest, current: Item) -> Dict[str, Any]:
    """현재 단계까지의 실제 퀴즈 결과만 본다. 미래 단계에 연결된 결과는 쓰지 않는다."""
    order = {it.key: it.order_index for it in req.items}
    relevant = [q for q in req.quiz_results
                if q.item_key is None or order[q.item_key] <= current.order_index]
    wrong = [q for q in relevant if not q.correct]
    stats: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    for q in relevant:
        for t in q.concept_tags:
            s = stats.setdefault(t, {"concept": t, "wrongCount": 0, "correctCount": 0, "evidenceQuestionIds": []})
            if q.correct:
                s["correctCount"] += 1
            else:
                s["wrongCount"] += 1
                s["evidenceQuestionIds"].append(q.question_raw)
    # 취약 = 오답이 있고 오답 수 ≥ 정답 수. 점수·확률은 만들지 않고 실제 개수만 보여 준다.
    weak = [s for s in stats.values() if s["wrongCount"] >= 1 and s["wrongCount"] >= s["correctCount"]]
    weak.sort(key=lambda s: (-s["wrongCount"], s["correctCount"], list(stats).index(s["concept"])))
    untagged = [q for q in wrong if not q.concept_tags]
    return {"available": bool(relevant), "attempted": len(relevant), "wrong": len(wrong),
            "weakConcepts": weak[:2], "untaggedWrongQuestionIds": [q.question_raw for q in untagged],
            "_untagged": untagged}


def coach(req: AdaptiveRequest) -> EngineResult:
    B = req.available_minutes
    if not req.items:
        return EngineResult(status="INSUFFICIENT_DATA", status_reason="EMPTY_ROADMAP",
                            message="로드맵 단계 데이터가 없어 코칭을 구성할 수 없습니다.")
    if all(it.completed for it in req.items):
        return EngineResult(status="ALL_COMPLETED", status_reason="ALL_STEPS_COMPLETED",
                            message="로드맵의 모든 단계를 완료했습니다.")
    current = req.item(req.current_step_key)
    steps = sorted(req.items, key=lambda it: it.order_index)
    pos = steps.index(current) + 1
    if current.completed:
        return EngineResult(status="CURRENT_STEP_COMPLETED", status_reason="CURRENT_STEP_ALREADY_COMPLETED",
                            message="요청한 현재 단계는 이미 완료되었습니다. 로드맵 순서상 현재 단계는 Spring 이 확정해 보냅니다.")

    previous = [s for s in steps if s.order_index < current.order_index]
    prev_done = [s for s in previous if s.completed]
    prev_open = [s for s in previous if not s.completed]
    future = [s for s in steps if s.order_index > current.order_index]
    warnings: List[Dict[str, Any]] = []
    if prev_open:
        warnings.append({"code": "PREVIOUS_STEPS_INCOMPLETE", "itemIds": [s.id_raw for s in prev_open],
                         "message": "현재 단계보다 앞선 단계 중 완료되지 않은 단계가 있습니다(순서는 변경하지 않습니다)."})

    quiz = _quiz_insight(req, current)
    remediation: Optional[Remediation] = None
    if quiz["weakConcepts"]:
        w = quiz["weakConcepts"]
        remediation = Remediation(concept_tags=[s["concept"] for s in w],
                                  question_raws=[q for s in w for q in s["evidenceQuestionIds"]],
                                  wrong_count=sum(s["wrongCount"] for s in w))
    elif quiz["_untagged"]:
        remediation = Remediation(concept_tags=[], question_raws=quiz["untaggedWrongQuestionIds"],
                                  wrong_count=len(quiz["_untagged"]))

    acts, covered = roadmap_activities(current, B, remediation)
    open_tasks = current.open_tasks

    # 추천 이유: 실제로 쓴 데이터만 문장으로 만든다.
    reason = [f"현재 진행 중인 '{current.title}' 단계({pos}/{len(steps)}단계)를 {B}분 안에 학습하도록 구성했습니다."]
    if open_tasks:
        reason.append(f"미완료 과제 {len(open_tasks)}개 중 {len(covered)}개를 이번 세션에서 다룹니다.")
    if remediation and remediation.concept_tags:
        tags = ", ".join(f"'{t}'" for t in remediation.concept_tags)
        reason.append(f"최근 퀴즈에서 {tags} 관련 오답 {remediation.wrong_count}개가 확인되어 짧은 복습을 먼저 넣었습니다.")
    elif remediation:
        reason.append(f"최근 퀴즈 오답 {remediation.wrong_count}문항을 다시 푸는 활동을 먼저 넣었습니다.")
    evidence = [current.id_raw]
    if prev_done:
        last = prev_done[-1]
        reason.append(f"이전에 완료한 '{last.title}' 단계와 이어서 학습합니다.")
        evidence.append(last.id_raw)

    goal = _first_sentence(current.description)
    coaching = (f"이번 단계 목표: {goal} " if goal else "") + \
        f"{B}분 동안 '{current.title}' 단계에만 집중하세요. 활동별 시간은 예상치이며, 끝나지 않은 부분은 다음 세션에 이어서 진행합니다."

    # 지연·시간 초과 → 현재 단계 내부 분할(로드맵 순서는 그대로, 완료 처리 없음, 사용자 승인 필요).
    recovery = None
    triggers: List[str] = []
    delay_days = None
    marker = next((d for d in (current.due_date, current.scheduled_date) if d is not None and d < req.today), None)
    if marker is not None:
        triggers.append("DELAYED")
        delay_days = (req.today - marker).days
    remaining = remaining_minutes(current)
    max_tasks = config.ROADMAP_TEMPLATES[B]["max_tasks"]
    if (remaining is not None and remaining > B) or len(open_tasks) > max_tasks:
        triggers.append("EXCEEDS_AVAILABLE_TIME")
    if triggers:
        today_minutes = sum(a.minutes for a in acts)
        sessions, truncated = plan_sessions(today_minutes, covered, open_tasks[len(covered):],
                                            None if remaining is None else remaining - today_minutes, B, max_tasks)
        when = "어제" if delay_days == 1 else (f"{delay_days}일 전" if delay_days else None)
        plan = (f"오늘 {B}분 세션으로 이어서 진행하는 것을 권장합니다." if len(sessions) == 1
                else f"오늘부터 {B}분 이내 세션 {len(sessions)}회로 나눠 진행하는 계획을 제안합니다.")
        msg = (f"{when} 예정이었던 '{current.title}' 단계가 아직 완료되지 않았습니다. " if when
               else f"'{current.title}' 단계는 한 번에 끝내기 어려운 분량입니다. ") + plan
        recovery = {
            "type": "SPLIT_CURRENT_STEP", "itemId": current.id_raw, "triggers": triggers,
            "delayDays": delay_days, "remainingMinutes": remaining,
            "remainingEstimateAvailable": remaining is not None,
            "sessions": [{"order": i + 1, "action": "SCHEDULE_SESSION", "itemId": current.id_raw,
                          "date": (req.today + timedelta(days=s["dayOffset"])).isoformat(), "minutes": s["minutes"],
                          "taskIds": [t.id_raw for t in s["tasks"]]} for i, s in enumerate(sessions)],
            "truncated": truncated, "message": msg, "requiresUserApproval": True,
            "constraints": {"keepsRoadmapOrder": True, "autoCompletesStep": False},
        }

    insight = {k: v for k, v in quiz.items() if not k.startswith("_")}
    rec = {
        "itemId": current.id_raw, "title": f"{current.title} 학습 코칭", "reason": " ".join(reason),
        "coachingMessage": coaching, "estimatedMinutes": sum(a.minutes for a in acts),
        "timeEstimate": {"isEstimate": True, "basis": "ALLOCATED_FROM_AVAILABLE_TIME",
                         "stepRemainingMinutes": remaining},
        "evidenceItemIds": evidence, "coveredTaskIds": [t.id_raw for t in covered],
        "quizInsight": insight,
        "nextAction": {"type": "START_STEP_SESSION", "itemId": current.id_raw, "minutes": sum(a.minutes for a in acts),
                       "label": f"{B}분 학습 시작"},
    }

    grounded: Set[str] = {str(B), str(pos), str(len(steps))} | {str(a.minutes) for a in acts}
    for n in (len(open_tasks), len(covered), delay_days, remaining, quiz["wrong"], quiz["attempted"]):
        if n is not None:
            grounded.add(str(n))
    for s in quiz["weakConcepts"]:
        grounded |= {str(s["wrongCount"]), str(s["correctCount"])}
    texts = [current.title, current.description] + [t.text for t in current.tasks] + [s.title for s in prev_done]
    llm_ctx = {
        "mode": "ROADMAP_COACH", "availableMinutes": B,
        "data": {
            "currentStep": {"title": current.title, "description": current.description[:600],
                            "position": f"{pos}/{len(steps)}",
                            "coveredTasks": [t.text for t in covered]},
            "completedPreviousSteps": [s.title for s in prev_done[-3:]],
            "weakConcepts": [{"concept": s["concept"], "wrongCount": s["wrongCount"]} for s in quiz["weakConcepts"]],
            "wrongAnswersWithoutConcept": len(quiz["_untagged"]),
        },
        "forbiddenTitles": [s.title for s in future] + [s.title for s in prev_open],
        "allowWeakness": remediation is not None,
        "allowedConcepts": remediation.concept_tags if remediation else [],
        "groundTexts": texts,
        "groundedNumbers": grounded,
    }
    return EngineResult(status="READY", recommendation=rec, activities=acts, recovery=recovery,
                        warnings=warnings, llm=llm_ctx)
