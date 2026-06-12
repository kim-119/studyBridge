"""
공부 플래너 전용 AI — 자료보관함 PDF 흐름과 분리된 "학습 실행 관리" AI.
브라우저 → Spring → 아래 엔드포인트.

  POST /api/ai/planner/expand   대충 적은 플래너를 깊게 확장
  POST /api/ai/planner/roadmap  플래너 기반 12주 로드맵 (각 주차 ≥3 task)

모델: GPT (material_ai_manager._call_gpt 재사용). 타임아웃/구조 보정은 서버에서 강제.
"""
import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai/planner", tags=["Planner AI"])


def _ctx_from_body(body: Dict[str, Any]) -> Dict[str, Any]:
    """Spring(camelCase)·스펙(snake_case) 양쪽 키를 모두 받아 action router용 ctx로 정규화."""
    if not isinstance(body, dict):
        body = {}
    planner = body.get("planner") if isinstance(body.get("planner"), dict) else body

    def g(*keys: str) -> Any:
        for k in keys:
            v = planner.get(k)
            if v not in (None, "", []):
                return v
            v = body.get(k)
            if v not in (None, "", []):
                return v
        return None

    return {
        "title": g("title"),
        "subject": g("subject"),
        "semester": g("semester"),
        "week": g("week"),
        "study_type": g("study_type", "studyType"),
        "priority": g("priority"),
        "target_time": g("target_time", "targetTime", "goalTime"),
        "actual_time": g("actual_time", "actualTime", "netStudyTime"),
        "deadline": g("deadline", "dDay"),
        "goal": g("goal", "content"),
        "todo": g("todo", "content"),
        "memo": g("memo"),
        "level": g("level"),
        "keywords": g("keywords"),
        "summary": g("summary"),
        "material_summary": g("material_summary", "materialSummary"),
        "user_goal": g("user_goal", "userGoal", "goal"),
        "date": g("date", "start_date", "startDate"),
        "start_date": g("start_date", "startDate", "date"),
    }

EXPAND_TIMEOUT = int(os.getenv("AI_PLANNER_EXPAND_TIMEOUT_SECONDS", "120"))
ROADMAP_TIMEOUT = int(os.getenv("AI_PLANNER_ROADMAP_TIMEOUT_SECONDS", os.getenv("AI_ROADMAP_TIMEOUT_SECONDS", "180")))
ROADMAP_WEEKS = 12
MIN_TASKS_PER_WEEK = 3


class PlannerInfo(BaseModel):
    plannerId: Optional[int] = None
    title: Optional[str] = ""
    subject: Optional[str] = ""
    content: Optional[str] = ""
    goalTime: Optional[str] = ""
    netStudyTime: Optional[str] = ""
    dDay: Optional[str] = ""
    week: Optional[int] = Field(None, description="사용자가 입력한 주차 (있으면 해당 주차를 더 구체화)")
    studyType: Optional[str] = ""
    priority: Optional[str] = ""


def _listify(v: Any) -> List[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [s.strip() for s in v.replace("\n", ",").split(",") if s.strip()]
    return []


def _planner_context(info: PlannerInfo) -> str:
    parts = [
        f"제목: {info.title}",
        f"과목: {info.subject}",
        f"내용/할 일(사용자 입력): {info.content}",
        f"목표 학습 시간: {info.goalTime}",
        f"실제(순) 학습 시간: {info.netStudyTime}",
        f"마감/시험(D-Day): {info.dDay}",
        f"학습 유형: {info.studyType}",
        f"우선순위: {info.priority}",
    ]
    if info.week:
        parts.append(f"현재 주차: {info.week}주차")
    return "\n".join(p for p in parts if p.split(": ", 1)[-1].strip())


def _llm(system: str, user: str, max_tokens: int) -> str:
    """주력 LLM(Ollama/Qwen) 우선, 실패 시 GPT fallback. ai07은 GPT 비활성이라 Ollama가 주력."""
    from app.services.material_ai_manager import _call_gpt
    try:
        from app.services.llm_engine_router import call_primary_llm
        out = call_primary_llm(system_prompt=system, user_prompt=user, max_tokens=max_tokens, temperature=0.3)
        if out and not out.strip().startswith("["):
            return out
    except Exception as e:
        logger.info("primary LLM 실패, GPT 시도: %s", e)
    return _call_gpt(system, user, max_tokens=max_tokens)


# ── 플래너 AI 확장 ───────────────────────────────────────────────────────────
def _expand_sync(info: PlannerInfo) -> Optional[Dict[str, Any]]:
    from app.utils.json_parser import extract_json

    system = (
        "너는 학습 코치다. 학생이 대충 적은 공부 플래너를 받아 '학습 실행 관리' 관점에서 "
        "깊고 구체적으로 확장한다. 반드시 한국어로, 아래 JSON 스키마로만 응답한다."
    )
    user = (
        f"## 플래너 정보\n{_planner_context(info)}\n\n"
        "아래 JSON 형식으로만 응답하라(마크다운/설명 금지):\n"
        "{\n"
        '  "expandedGoal": "확장된 학습 목표(2~3문장)",\n'
        '  "expandedTodos": ["세분화된 할 일 5~8개"],\n'
        '  "estimatedTime": "예상 총 소요 시간(예: 3시간 30분)",\n'
        '  "studyOrder": ["권장 학습 순서 단계"],\n'
        '  "riskPoints": ["학습 실패/지연 위험 요소 3~5개"],\n'
        '  "todayCheckpoints": ["오늘 반드시 점검할 체크포인트 3~5개"],\n'
        '  "aiQuestions": ["일정/시간/목표/회고 기반 질문 4개"],\n'
        '  "reflectionPrompts": ["회고/복습용 질문 3개"]\n'
        "}"
    )
    raw = _llm(system, user, max_tokens=1400)
    if not raw or raw.strip().startswith("[GPT") or raw.strip().startswith("["):
        return None
    parsed = extract_json(raw)
    if not isinstance(parsed, dict):
        return None
    return {
        "expandedGoal": str(parsed.get("expandedGoal") or "").strip(),
        "expandedTodos": _listify(parsed.get("expandedTodos")),
        "estimatedTime": str(parsed.get("estimatedTime") or "").strip(),
        "studyOrder": _listify(parsed.get("studyOrder")),
        "riskPoints": _listify(parsed.get("riskPoints")),
        "todayCheckpoints": _listify(parsed.get("todayCheckpoints")),
        "aiQuestions": _listify(parsed.get("aiQuestions")),
        "reflectionPrompts": _listify(parsed.get("reflectionPrompts")),
    }


@router.post("/expand", summary="공부 플래너 AI 확장")
async def planner_expand(info: PlannerInfo) -> Dict[str, Any]:
    try:
        result = await asyncio.wait_for(asyncio.to_thread(_expand_sync, info), timeout=EXPAND_TIMEOUT)
    except asyncio.TimeoutError:
        return {"success": False, "errorCode": "AI_TIMEOUT", "message": "AI 응답 시간이 초과되었습니다."}
    except Exception as e:
        logger.error("planner/expand 실패: %s", e)
        return {"success": False, "errorCode": "PLANNER_EXPAND_FAILED", "message": "플래너 확장에 실패했습니다."}
    if not result:
        return {"success": False, "errorCode": "PLANNER_EXPAND_FAILED", "message": "플래너 확장에 실패했습니다."}
    return {"success": True, **result}


# ── 플래너 AI 피드백 (학습 실행 관리) ────────────────────────────────────────
ASSIST_TIMEOUT = int(os.getenv("AI_PLANNER_ASSIST_TIMEOUT_SECONDS", os.getenv("AI_PLANNER_EXPAND_TIMEOUT_SECONDS", "120")))


class PlannerAssistInfo(BaseModel):
    planner_id: Optional[int] = None
    title: Optional[str] = ""
    date: Optional[str] = ""
    subject: Optional[str] = ""
    study_type: Optional[str] = ""
    priority: Optional[str] = ""
    target_time: Optional[str] = ""
    actual_time: Optional[str] = ""
    deadline: Optional[str] = ""
    goal: Optional[str] = ""
    todo: Optional[str] = ""
    memo: Optional[str] = ""
    completed_tasks: Optional[List[str]] = None
    incomplete_tasks: Optional[List[str]] = None


def _assist_context(info: PlannerAssistInfo) -> str:
    parts = [
        f"제목: {info.title}",
        f"날짜: {info.date}",
        f"과목: {info.subject}",
        f"학습 유형: {info.study_type}",
        f"우선순위: {info.priority}",
        f"목표 학습 시간: {info.target_time}",
        f"실제 학습 시간: {info.actual_time}",
        f"마감/시험: {info.deadline}",
        f"학습 목표(goal): {info.goal}",
        f"할 일(todo): {info.todo}",
        f"사용자 메모(memo): {info.memo}",
    ]
    return "\n".join(p for p in parts if p.split(": ", 1)[-1].strip())


def _assist_sync(info: PlannerAssistInfo) -> Optional[Dict[str, Any]]:
    from app.utils.json_parser import extract_json

    system = (
        "너는 학습 코치다. 학생이 작성한 하루 공부 플래너를 받아 '실행 가능한 계획'으로 정리하고 피드백한다. "
        "로드맵·퀴즈·문서 분석은 하지 않는다. 사용자가 직접 쓴 메모는 절대 바꾸지 말고 참고만 한다. "
        "반드시 한국어로, 마크다운(**, ###, 백틱) 없이, 아래 JSON 스키마로만 응답한다."
    )
    user = (
        f"## 플래너\n{_assist_context(info)}\n\n"
        "아래 JSON 형식으로만 응답하라(마크다운/설명 금지):\n"
        "{\n"
        '  "aiSummary": "플래너 전체를 2~3문장으로 요약",\n'
        '  "refinedGoal": "실행 가능하게 정리한 학습 목표 한 문장",\n'
        '  "taskBreakdown": ["실행 단위로 나눈 할 일 3~6개"],\n'
        '  "timeFeedback": "목표 대비 실제 학습 시간 진행 상태 한 문장(부족/적정/초과)",\n'
        '  "strengths": ["잘한 점 2~3개"],\n'
        '  "concerns": ["우려/위험 2~3개"],\n'
        '  "recommendations": ["권장사항 2~3개"],\n'
        '  "nextActions": ["다음 학습 행동 2~3개"]\n'
        "}"
    )
    raw = _llm(system, user, max_tokens=1400)
    if not raw or raw.strip().startswith("[GPT") or raw.strip().startswith("["):
        return None
    parsed = extract_json(raw)
    if not isinstance(parsed, dict):
        return None
    return {
        "aiSummary": str(parsed.get("aiSummary") or "").strip(),
        "refinedGoal": str(parsed.get("refinedGoal") or "").strip(),
        "taskBreakdown": _listify(parsed.get("taskBreakdown")),
        "timeFeedback": str(parsed.get("timeFeedback") or "").strip(),
        "strengths": _listify(parsed.get("strengths")),
        "concerns": _listify(parsed.get("concerns")),
        "recommendations": _listify(parsed.get("recommendations")),
        "nextActions": _listify(parsed.get("nextActions")),
    }


@router.post("/assist", summary="공부 플래너 AI 피드백 (학습 실행 관리)")
async def planner_assist(info: PlannerAssistInfo) -> Dict[str, Any]:
    try:
        result = await asyncio.wait_for(asyncio.to_thread(_assist_sync, info), timeout=ASSIST_TIMEOUT)
    except asyncio.TimeoutError:
        return {"success": False, "errorCode": "AI_TIMEOUT", "message": "AI 응답 시간이 초과되었습니다."}
    except Exception as e:
        logger.error("planner/assist 실패: %s", e)
        return {"success": False, "errorCode": "PLANNER_ASSIST_FAILED", "message": "플래너 피드백 생성에 실패했습니다."}
    if not result:
        return {"success": False, "errorCode": "PLANNER_ASSIST_FAILED", "message": "플래너 피드백 생성에 실패했습니다."}
    return {"success": True, **result}


# ── 플래너 기반 12주 로드맵 ─────────────────────────────────────────────────
def _normalize_weeks(weeks_raw: Any, info: PlannerInfo) -> List[Dict[str, Any]]:
    """정확히 12주, 각 주차 최소 3 task 보장."""
    weeks: List[Dict[str, Any]] = []
    if isinstance(weeks_raw, list):
        for i, w in enumerate(weeks_raw[:ROADMAP_WEEKS]):
            if not isinstance(w, dict):
                continue
            tasks = _listify(w.get("tasks"))
            weeks.append({
                "week": int(w.get("week") or i + 1),
                "title": str(w.get("title") or f"{i + 1}주차").strip(),
                "goal": str(w.get("goal") or w.get("description") or "").strip(),
                "tasks": tasks,
            })
    # 12주까지 채우기
    subject = info.subject or info.title or "학습"
    while len(weeks) < ROADMAP_WEEKS:
        n = len(weeks) + 1
        weeks.append({"week": n, "title": f"{n}주차 {subject} 심화",
                      "goal": f"{n}주차 학습 목표를 설정하고 복습한다.", "tasks": []})
    # week 번호 재정렬 + task 최소 보장
    for idx, w in enumerate(weeks[:ROADMAP_WEEKS]):
        w["week"] = idx + 1
        base = w.get("tasks") or []
        while len(base) < MIN_TASKS_PER_WEEK:
            k = len(base) + 1
            base.append(f"{w['week']}주차 학습 활동 {k}: 핵심 개념 정리/문제 풀이/복습")
        w["tasks"] = base
    return weeks[:ROADMAP_WEEKS]


def _roadmap_sync(info: PlannerInfo) -> Optional[List[Dict[str, Any]]]:
    from app.utils.json_parser import extract_json

    focus = f"\n특히 사용자가 입력한 {info.week}주차 내용은 다른 주차보다 더 구체적으로 반영하라." if info.week else ""
    system = (
        "너는 학습 커리큘럼 설계자다. 공부 플래너를 받아 12주 학습 로드맵을 만든다. "
        "반드시 정확히 12개 주차, 각 주차마다 최소 3개의 task를 한국어로 작성한다. JSON으로만 응답한다."
    )
    user = (
        f"## 플래너 정보\n{_planner_context(info)}{focus}\n\n"
        "아래 JSON 형식으로만 응답하라(마크다운/설명 금지):\n"
        '{ "title": "로드맵 제목", "weeks": [ '
        '{ "week": 1, "title": "주차 제목", "goal": "주차 목표", "tasks": ["과제1","과제2","과제3"] } '
        "] }\n"
        "weeks 배열은 정확히 12개여야 한다."
    )
    raw = _llm(system, user, max_tokens=2400)
    if not raw or raw.strip().startswith("[GPT") or raw.strip().startswith("["):
        return None
    parsed = extract_json(raw)
    if isinstance(parsed, dict):
        return _normalize_weeks(parsed.get("weeks"), info)
    if isinstance(parsed, list):
        return _normalize_weeks(parsed, info)
    return None


@router.post("/roadmap", summary="플래너 기반 12주 × 7일 로드맵 (총 84일)")
async def planner_roadmap(body: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    """플래너 기반 12주 × 7일 = 84일 로드맵. action router로 구조 강제 + 검증/복구.

    Spring(camelCase)과 스펙(snake_case planner 객체) 양쪽 입력을 모두 수용한다.
    """
    from app.services.study_action_router import (
        generate_12week_7day_roadmap, finalize_roadmap_response, roadmap_failure_response,
    )
    ctx = _ctx_from_body(body)
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(generate_12week_7day_roadmap, ctx), timeout=ROADMAP_TIMEOUT
        )
    except asyncio.TimeoutError:
        try:
            result = await asyncio.to_thread(generate_12week_7day_roadmap, {**ctx, "_no_llm": True})
        except Exception as e:  # noqa: BLE001
            logger.error("planner/roadmap 타임아웃 fallback 실패: %s", e)
            return roadmap_failure_response("로드맵 생성에 실패했습니다.",
                                            "LLM 타임아웃 후 결정적 fallback 생성 실패", "타임아웃",
                                            error_code="AI_TIMEOUT")
    except Exception as e:  # noqa: BLE001
        logger.error("planner/roadmap 실패: %s", e)
        return roadmap_failure_response("로드맵 생성에 실패했습니다.",
                                        "LLM 응답 파싱 실패 또는 84일 구조 검증 실패", str(e)[:120],
                                        error_code="PLANNER_ROADMAP_FAILED")
    final = finalize_roadmap_response(result)
    if not final["validation"]["passed"]:
        try:
            rebuilt = await asyncio.to_thread(generate_12week_7day_roadmap, {**ctx, "_no_llm": True})
            final = finalize_roadmap_response(rebuilt)
        except Exception as e:  # noqa: BLE001
            logger.error("planner/roadmap 재빌드 실패: %s", e)
    return final


# ── 플래너 AI assist (학습 실행 관리 — 로드맵/퀴즈/PDF 분석 아님) ──────────────
ASSIST_TIMEOUT = int(os.getenv("AI_PLANNER_ASSIST_TIMEOUT_SECONDS", "90"))

_PRIORITY_MAP = {
    "높음": "high", "high": "high", "긴급": "high",
    "보통": "medium", "medium": "medium", "normal": "medium",
    "낮음": "low", "low": "low",
}


def _norm_priority(value: Any) -> str:
    return _PRIORITY_MAP.get(str(value or "").strip().lower(), "medium")


def _parse_minutes(value: Any) -> Optional[int]:
    """'2시간', '1시간 20분', '90분', '1.5시간' 등을 분으로 변환. 실패 시 None."""
    s = str(value or "").strip()
    if not s:
        return None
    import re as _re
    total = 0
    matched = False
    h = _re.search(r"(\d+(?:\.\d+)?)\s*시간", s)
    if h:
        total += int(float(h.group(1)) * 60)
        matched = True
    m = _re.search(r"(\d+)\s*분", s)
    if m:
        total += int(m.group(1))
        matched = True
    if not matched:
        digits = _re.search(r"(\d+(?:\.\d+)?)", s)
        if digits:
            return int(float(digits.group(1)) * 60)  # 숫자만 있으면 시간으로 간주
        return None
    return total


def _time_feedback(target: Any, actual: Any) -> Dict[str, Any]:
    from app.utils.sanitize import sanitize_markdown_text
    tmin = _parse_minutes(target)
    amin = _parse_minutes(actual)
    if tmin is None or amin is None:
        status = "정보부족"
        message = "목표 시간과 실제 학습 시간을 함께 기록하면 학습량 점검이 더 정확해집니다."
    elif amin < tmin * 0.9:
        status = "부족"
        message = "목표 시간보다 실제 학습 시간이 부족하므로 실습보다 개념 정리를 우선하는 것이 좋습니다."
    elif amin > tmin * 1.1:
        status = "초과"
        message = "목표 시간을 넘겨 학습했으므로 다음에는 핵심 개념에 집중해 학습 효율을 높이는 것이 좋습니다."
    else:
        status = "적정"
        message = "목표 시간과 실제 학습 시간이 비슷하므로 현재 학습 페이스를 유지하면 됩니다."
    return {
        "target_time": sanitize_markdown_text(target) or "",
        "actual_time": sanitize_markdown_text(actual) or "",
        "status": status,
        "message": message,
    }


def _assist_fallback_tasks(subject: str, todo_items: List[str]) -> List[Dict[str, Any]]:
    """LLM 실패 시 todo 기반 deterministic task_breakdown (최소 3개 보장)."""
    base = todo_items[:] if todo_items else [f"{subject} 핵심 개념 정리", f"{subject} 예제/실습", f"{subject} 복습 및 점검"]
    while len(base) < 3:
        base.append(f"{subject} 추가 학습 활동 {len(base) + 1}")
    tasks: List[Dict[str, Any]] = []
    for i, item in enumerate(base, start=1):
        tasks.append({
            "index": i,
            "title": item,
            "description": f"{item}을(를) 작은 단위로 나눠 핵심 기준을 정리하고 직접 설명할 수 있을 때까지 학습한다.",
            "estimated_minutes": 30,
            "priority": "high" if i == 1 else "medium",
        })
    return tasks


def _assist_llm_valid(d: Dict[str, Any]) -> bool:
    """LLM 초안/보강본이 핵심 필드를 갖췄는지(느슨한) 검증."""
    if not isinstance(d, dict):
        return False
    tasks = d.get("task_breakdown")
    fb = d.get("ai_feedback")
    return (
        isinstance(tasks, list) and len(tasks) >= 3
        and isinstance(d.get("refined_goal"), str) and bool(d.get("refined_goal", "").strip())
        and isinstance(fb, dict)
        and bool(fb.get("strengths")) and bool(fb.get("concerns")) and bool(fb.get("recommendations"))
        and bool(d.get("next_actions"))
    )


def _assist_planner_context(ctx: Dict[str, Any], subject: str, goal: str, memo: str) -> str:
    return (
        f"제목: {ctx.get('title')}\n과목: {subject}\n학습 유형: {ctx.get('study_type')}\n"
        f"우선순위: {ctx.get('priority')}\n목표 시간: {ctx.get('target_time')}\n실제 시간: {ctx.get('actual_time')}\n"
        f"마감: {ctx.get('deadline')}\n목표: {goal}\n할 일: {ctx.get('todo')}\n메모: {memo}"
    )


_ASSIST_JSON_SCHEMA = (
    "{\n"
    '  "ai_summary": "현재 플래너 상태 요약 2~3문장",\n'
    '  "refined_goal": "측정 가능하고 실행 가능한 목표 1문장",\n'
    '  "task_breakdown": [{"title": "할 일", "description": "5문장 이상 구체 설명", "estimated_minutes": 30, "priority": "high|medium|low"}],\n'
    '  "ai_feedback": {"strengths": ["강점"], "concerns": ["우려/비판적 개선점"], "recommendations": ["권장사항"]},\n'
    '  "next_actions": ["다음 학습 행동 2개 이상"],\n'
    '  "memo_suggestion": "메모 작성 방법 제안 1문장"\n'
    "}"
)


def _assist_sync(body: Dict[str, Any]) -> Dict[str, Any]:
    """플래너 assist. Qwen 1차 분석 → OpenAI 보강 → 검증/복구 → deterministic fallback. 마크다운 제거."""
    from app.utils.sanitize import sanitize_markdown_text, sanitize_list
    from app.services.ai_pipeline import generate_structured, repair_to_valid

    ctx = _ctx_from_body(body)
    planner_id = body.get("planner_id") or body.get("plannerId")
    subject = sanitize_markdown_text(ctx.get("subject") or ctx.get("title")) or "학습"
    goal = sanitize_markdown_text(ctx.get("goal")) or ""
    todo_items = _listify(ctx.get("todo"))
    memo = sanitize_markdown_text(ctx.get("memo")) or ""
    planner_ctx = _assist_planner_context(ctx, subject, goal, memo)

    parsed: Optional[Dict[str, Any]] = None
    if not body.get("_no_llm"):
        try:
            # 1단계(Qwen): 학습 의도 1차 분석 + 실행 가능한 초안. 로드맵/퀴즈/PDF 금지.
            draft_system = (
                "너는 학습 실행 코치다. 학생의 공부 플래너 하나를 받아 '학습 실행 관리' 관점에서 "
                "오늘/이번 플래너 단위로 실행 가능한 계획만 1차 정리한다. 12주 로드맵, 84일 계획, 퀴즈 생성, "
                "PDF 분석은 절대 하지 않는다. 사용자가 쓴 메모는 참고만 하고 덮어쓰지 않는다. "
                "반드시 한국어로, 마크다운 없이 JSON으로만 응답한다."
            )
            draft_user = (
                f"## 플래너\n{planner_ctx}\n\n아래 JSON 형식으로만 응답하라(마크다운/별표/해시/백틱 금지):\n"
                + _ASSIST_JSON_SCHEMA + "\ntask_breakdown은 반드시 3개 이상."
            )
            # 2단계(OpenAI): 목표 측정가능화, 할 일 3~7개 세분화, 시간/우선순위/마감 위험 판단,
            #               피드백 균형(장점/권장/우려), 다음 행동 구체화.
            refine_system = (
                "너는 학습 코치 결과 보강기다. 초안 JSON을 받아 목표를 측정 가능하게 바꾸고, 할 일을 3~7개로 "
                "세분화하며, 시간 부족·우선순위·마감 위험을 판단하고, 피드백을 장점·권장사항·우려(비판적 개선점)로 "
                "균형 있게 정리하고 다음 학습 행동을 구체화한다. 로드맵/퀴즈/PDF 분석은 추가하지 않는다. "
                "메모는 덮어쓰지 않는다. 반드시 한국어, 마크다운 없이 같은 JSON 스키마로만 응답한다."
            )

            def _refine_user(draft: Dict[str, Any]) -> str:
                import json as _json
                draft_txt = _json.dumps(draft, ensure_ascii=False) if draft else "(초안 없음 — 직접 생성)"
                return (
                    f"## 플래너\n{planner_ctx}\n\n## 1차 초안\n{draft_txt}\n\n"
                    "위 초안을 보강해 아래 JSON으로만 응답하라(마크다운/별표/해시/백틱 금지):\n"
                    + _ASSIST_JSON_SCHEMA + "\ntask_breakdown은 3~7개."
                )

            parsed = generate_structured(
                draft_system=draft_system, draft_user=draft_user,
                refine_system=refine_system, refine_user_builder=_refine_user,
                validator=_assist_llm_valid, max_tokens=1600,
            )
            if parsed is not None and not _assist_llm_valid(parsed):
                repaired = repair_to_valid(
                    repair_system=refine_system,
                    repair_user=_refine_user(parsed or {}),
                    validator=_assist_llm_valid, max_tokens=1600,
                )
                if repaired:
                    parsed = repaired
        except Exception as e:  # noqa: BLE001
            logger.info("planner/assist 파이프라인 실패, fallback 사용: %s", e)

    # ── 구조 보정 + sanitize (LLM 성공/실패 무관하게 항상 완전한 구조 보장) ──
    parsed = parsed or {}

    # task_breakdown 정규화 (최소 3개)
    raw_tasks = parsed.get("task_breakdown")
    tasks: List[Dict[str, Any]] = []
    if isinstance(raw_tasks, list):
        for i, t in enumerate(raw_tasks, start=1):
            if not isinstance(t, dict):
                continue
            title = sanitize_markdown_text(t.get("title") or t.get("task"))
            if not title:
                continue
            desc = sanitize_markdown_text(t.get("description") or t.get("detail"))
            try:
                est = int(t.get("estimated_minutes") or t.get("estimatedMinutes") or 30)
            except Exception:
                est = 30
            tasks.append({
                "index": len(tasks) + 1,
                "title": title,
                "description": desc or f"{title}을(를) 핵심 기준으로 나눠 정리하고 직접 설명할 수 있을 때까지 학습한다.",
                "estimated_minutes": est,
                "priority": _norm_priority(t.get("priority")),
            })
    if len(tasks) < 3:
        for t in _assist_fallback_tasks(subject, todo_items):
            if len(tasks) >= 3:
                break
            t["index"] = len(tasks) + 1
            tasks.append(t)

    fb = parsed.get("ai_feedback") if isinstance(parsed.get("ai_feedback"), dict) else {}
    strengths = sanitize_list(fb.get("strengths")) or [f"학습 목표가 {subject} 중심으로 구체화되어 있습니다."]
    concerns = sanitize_list(fb.get("concerns")) or ["할 일이 추상적이면 실제 학습량 점검이 어려울 수 있습니다."]
    recommendations = sanitize_list(fb.get("recommendations")) or ["할 일을 측정 가능한 작은 단위로 나눠 하나씩 완료하세요."]

    next_actions = sanitize_list(parsed.get("next_actions"))
    if not next_actions:
        next_actions = [
            f"{subject} 핵심 개념을 표나 자기 설명으로 정리한다.",
            "오늘 학습한 내용을 예제나 코드 흐름 기준으로 다시 확인한다.",
        ]

    refined_goal = sanitize_markdown_text(parsed.get("refined_goal")) or (
        goal or f"{subject}의 핵심 개념을 직접 설명할 수 있을 정도로 정리한다."
    )
    ai_summary = sanitize_markdown_text(parsed.get("ai_summary")) or (
        f"현재 {subject} 학습 플래너 상태를 점검했습니다. 목표를 더 구체화하고 할 일을 작은 단위로 나누면 학습 실행이 쉬워집니다."
    )
    memo_suggestion = sanitize_markdown_text(parsed.get("memo_suggestion")) or (
        "메모에는 헷갈린 개념과 다음에 확인할 질문만 짧게 남기는 것이 좋습니다."
    )

    result = {
        "planner_id": planner_id,
        "ai_summary": ai_summary,
        "refined_goal": refined_goal,
        "task_breakdown": tasks,
        "time_feedback": _time_feedback(ctx.get("target_time"), ctx.get("actual_time")),
        "ai_feedback": {
            "strengths": strengths,
            "concerns": concerns,
            "recommendations": recommendations,
        },
        "next_actions": next_actions,
        "memo_suggestion": memo_suggestion,
        "error_code": None,
    }
    # deterministic fill로 구조는 항상 보장되지만, 최종 검증으로 한 번 더 확인한다.
    try:
        from app.utils.ai_validators import validate_planner_assist
        if not validate_planner_assist(result):
            logger.warning("planner/assist 최종 검증 실패 — 응답 구조 점검 필요")
    except Exception:  # noqa: BLE001
        pass
    return result


@router.post("/assist", summary="공부 플래너 AI assist (정리·세분화·점검·피드백)")
async def planner_assist(body: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    """플래너 단순화 정책 — 로드맵/퀴즈/PDF 분석 없이 학습 실행 관리만 수행한다.

    LLM 실패해도 deterministic fallback으로 응답 구조를 항상 유지한다.
    """
    if not isinstance(body, dict):
        body = {}
    try:
        return await asyncio.wait_for(asyncio.to_thread(_assist_sync, body), timeout=ASSIST_TIMEOUT)
    except asyncio.TimeoutError:
        # 타임아웃에도 구조는 유지 (LLM 없이 동기 fallback 재구성)
        try:
            result = _assist_sync({**body, "_no_llm": True})
        except Exception:  # noqa: BLE001
            result = {}
        result["error_code"] = "AI_TIMEOUT"
        return result or {"planner_id": body.get("planner_id"), "error_code": "AI_TIMEOUT"}
    except Exception as e:  # noqa: BLE001
        logger.error("planner/assist 실패: %s", e)
        return {"planner_id": body.get("planner_id"), "error_code": "PLANNER_ASSIST_FAILED"}


@router.post("/week-expand", summary="플래너 1주일 → 하루 1개씩 7일 일정 확장")
async def planner_week_expand(body: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    """플래너 1주일 입력을 1일차~7일차 총 7개 일정으로 확장. daily_plans 항상 7개 보장."""
    from app.services.study_action_router import expand_planner_week
    ctx = _ctx_from_body(body)
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(expand_planner_week, ctx), timeout=ROADMAP_TIMEOUT
        )
    except asyncio.TimeoutError:
        return {"success": False, "errorCode": "AI_TIMEOUT", "message": "AI 응답 시간이 초과되었습니다.",
                "recoverable": True}
    except Exception as e:  # noqa: BLE001
        logger.error("planner/week-expand 실패: %s", e)
        return {"success": False, "errorCode": "PLANNER_WEEK_EXPAND_FAILED",
                "message": "주간 일정 확장에 실패했습니다.", "recoverable": True}
    return {"success": True, **result}
