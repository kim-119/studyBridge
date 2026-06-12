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

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai/planner", tags=["Planner AI"])

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


@router.post("/roadmap", summary="플래너 기반 12주 로드맵")
async def planner_roadmap(info: PlannerInfo) -> Dict[str, Any]:
    try:
        weeks = await asyncio.wait_for(asyncio.to_thread(_roadmap_sync, info), timeout=ROADMAP_TIMEOUT)
    except asyncio.TimeoutError:
        return {"success": False, "errorCode": "AI_TIMEOUT", "message": "AI 응답 시간이 초과되었습니다."}
    except Exception as e:
        logger.error("planner/roadmap 실패: %s", e)
        weeks = None
    is_fallback = False
    if not weeks:
        is_fallback = True
        weeks = _normalize_weeks([], info)  # 전부 fallback 12주
    title = (info.subject or info.title or "학습") + " 12주 로드맵"
    return {"success": True, "title": title, "weeks": weeks, "isFallback": is_fallback}
