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

EXPAND_TIMEOUT = int(os.getenv("AI_PLANNER_EXPAND_TIMEOUT_SECONDS", "120"))
ROADMAP_TIMEOUT = int(os.getenv("AI_PLANNER_ROADMAP_TIMEOUT_SECONDS", os.getenv("AI_ROADMAP_TIMEOUT_SECONDS", "180")))
ROADMAP_WEEKS = 12
MIN_TASKS_PER_WEEK = 3

# PDF/플래너 메타데이터(날짜/연도/교수명/표지/footer)를 학습 주제로 쓰지 못하게 하는 규칙
_NOISE_RULES = (
    "[학습 주제 규칙] 날짜·연도(예: 2026)·교수명/강사명·강의자료 표지/footer/header·"
    "슬라이드 번호는 학습 주제로 절대 사용하지 마라. '2026.04 조수연' 같은 날짜+이름 문구를 "
    "출력에 포함하지 마라. 반복되는 강의명은 자료명으로만 참고하고, 학습 항목은 개념·구조·원리·"
    "구현·비교·적용·테스트 단위로 작성하라."
)


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
        "깊고 구체적으로 확장한다. 반드시 한국어로, 아래 JSON 스키마로만 응답한다.\n"
        f"{_NOISE_RULES}"
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
    # PDF/플래너 메타데이터 노이즈 정제 (날짜/연도/교수명/표지/footer 제거)
    fb_title = info.subject or info.title or "학습"
    try:
        from app.utils.pdf_noise_filter import detect_repeated_lines, sanitize_text_fields
        repeated = detect_repeated_lines([info.content or "", info.title or ""])
        weeks = sanitize_text_fields(weeks, repeated=repeated, title=fb_title)
    except Exception as e:  # noqa: BLE001
        logger.debug("planner roadmap noise 정제 생략: %s", e)

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
        "반드시 정확히 12개 주차, 각 주차마다 최소 3개의 task를 한국어로 작성한다. JSON으로만 응답한다.\n"
        f"{_NOISE_RULES}"
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


# ── 플래너 분석 (저장된 플래너 자료 기반) ──────────────────────────────────────
#   플래너는 "이미 저장된 자료"이므로 '먼저 저장하세요' 류 메시지를 절대 만들지 않는다.
ANALYZE_TIMEOUT = int(os.getenv("AI_PLANNER_ANALYZE_TIMEOUT_SECONDS", "90"))

import re as _re  # noqa: E402

_DATE_ONLY = _re.compile(r"^\s*(\d{1,2}\s*일차|\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}\s*주차|day\s*\d+|\d+\s*일)\s*$", _re.I)
_KW_JUNK = {"있다", "없다", "하기", "한다", "그리고", "그러나", "위해", "통해", "오늘", "내일",
            "학습", "공부", "계획", "일차", "주차", "day", "오전", "오후", "정리", "복습"}


def _planner_keywords(*texts: str, limit: int = 6) -> List[str]:
    """플래너 텍스트에서 핵심 키워드(빈도 기반) 추출."""
    blob = " ".join(t for t in texts if t)
    tokens = _re.findall(r"[가-힣A-Za-z][가-힣A-Za-z0-9+.#]{1,}", blob)
    freq: Dict[str, int] = {}
    order: List[str] = []
    for tok in tokens:
        low = tok.lower()
        if len(tok) <= 1 or low in _KW_JUNK or tok in _KW_JUNK:
            continue
        if low not in freq:
            order.append(tok)
        freq[low] = freq.get(low, 0) + 1
    first_idx = {w: i for i, w in enumerate(order)}  # 정렬 중 index 변동 방지
    order.sort(key=lambda w: (-freq[w.lower()], first_idx[w]))
    # 날짜/연도/교수명/표지/footer 키워드 제외 (학습 주제 오염 차단)
    try:
        from app.utils.pdf_noise_filter import detect_repeated_lines, filter_keywords
        repeated = detect_repeated_lines([blob])
        order = filter_keywords(order, repeated=repeated)
    except Exception:  # noqa: BLE001
        pass
    return order[:limit]


def _planner_title(raw_title: str, subject: str, keywords: List[str]) -> str:
    """핵심 키워드 우선 제목. '4일차'/날짜 단독 제목은 키워드/과목으로 대체."""
    rt = (raw_title or "").strip()
    if rt and not _DATE_ONLY.match(rt) and len(rt) > 1:
        return rt
    if subject and subject.strip():
        return f"{subject.strip()} 학습 플래너"
    if keywords:
        return f"{keywords[0]} 학습 플래너"
    return "학습 플래너"


def _analyze_sync(body: Dict[str, Any]) -> Dict[str, Any]:
    from app.utils.json_parser import extract_json

    def g(*keys: str, default: str = "") -> str:
        for k in keys:
            v = body.get(k)
            if v not in (None, "", []):
                return str(v) if not isinstance(v, str) else v
        return default

    raw_title = g("title", "plannerTitle")
    subject = g("subject", "category")
    content = g("content", "todo", "memo", "description")
    goal = g("goal", "learningGoal", "goalTime")
    d_day = g("dDay", "deadline", "date")
    completed = _listify(body.get("completed_tasks") or body.get("completedTasks") or body.get("checklistDone"))
    incomplete = _listify(body.get("incomplete_tasks") or body.get("incompleteTasks") or body.get("checklistTodo"))
    checklist_in = _listify(body.get("checklist"))

    keywords = _planner_keywords(raw_title, subject, content, goal, limit=6)
    title = _planner_title(raw_title, subject, keywords)

    # 진행률: 완료/전체 기준 (없으면 명시 progress 값, 없으면 0)
    total_items = len(completed) + len(incomplete)
    if total_items > 0:
        progress = round(len(completed) / total_items * 100)
    else:
        try:
            progress = max(0, min(100, int(float(body.get("progress") or 0))))
        except (TypeError, ValueError):
            progress = 0

    context = "\n".join(p for p in [
        f"제목: {raw_title}", f"과목: {subject}", f"내용/할 일: {content}",
        f"학습 목표: {goal}", f"마감/D-Day: {d_day}",
        f"완료한 일: {', '.join(completed)}", f"남은 일: {', '.join(incomplete)}",
    ] if p.split(": ", 1)[-1].strip())

    system = (
        "너는 학습 코치다. 이미 저장된 공부 플래너 자료를 받아 분석한다. "
        "'먼저 저장하세요', '저장 후 이용', '저장하지 않으면' 같은 안내는 절대 만들지 않는다. "
        "반드시 한국어로, 마크다운 없이 아래 JSON 스키마로만 응답한다."
    )
    user = (
        f"## 저장된 플래너 자료\n{context}\n\n"
        "아래 JSON 형식으로만 응답하라(마크다운/설명 금지):\n"
        "{\n"
        '  "learningGoal": "이 플래너의 실행 가능한 학습 목표 1~2문장",\n'
        '  "schedule": ["오늘/이번 학습 일정 단계 3~5개"],\n'
        '  "checklist": ["오늘 점검할 체크리스트 항목 4~6개"],\n'
        '  "scheduleAnalysis": ["일정 분석 포인트 2~4개"],\n'
        '  "problemPoints": ["계획 문제점/리스크 2~4개"],\n'
        '  "balanceAssessment": "학습량과 일정 균형 평가 1~2문장",\n'
        '  "improvementActions": ["개선안 3~5개"],\n'
        '  "aiFeedback": "진행 상황과 시간 관리에 대한 코치 피드백 2~3문장",\n'
        '  "nextRecommendations": ["다음 학습 추천 행동 3개"],\n'
        '  "unfinishedItems": ["아직 끝내지 못한 항목 (없으면 빈 배열)"]\n'
        "}"
    )
    parsed: Any = None
    if not body.get("_no_llm"):
        try:
            raw = _llm(system, user, max_tokens=1200)
            if raw and not raw.strip().startswith("[") and not raw.strip().startswith("[GPT"):
                parsed = extract_json(raw)
        except Exception as e:  # noqa: BLE001
            logger.info("planner/analyze LLM 실패, fallback 사용: %s", e)
    if not isinstance(parsed, dict):
        parsed = {}

    schedule = _listify(parsed.get("schedule")) or (incomplete[:5] if incomplete else [
        "오늘 학습할 핵심 주제 선정", "핵심 개념 정리 및 예제 확인", "학습 내용 자기 점검",
    ])
    checklist = _listify(parsed.get("checklist")) or checklist_in or (
        incomplete[:6] if incomplete else ["핵심 개념 복습", "예제/문제 풀이", "오답·헷갈린 부분 정리", "다음 학습 범위 확인"]
    )
    unfinished = _listify(parsed.get("unfinishedItems")) or incomplete
    learning_goal = str(parsed.get("learningGoal") or "").strip() or (
        goal or f"{title}의 핵심 내용을 이해하고 오늘 분량을 끝까지 학습한다."
    )
    schedule_analysis = _listify(parsed.get("scheduleAnalysis")) or [
        f"현재 체크리스트 기준으로 남은 핵심 항목은 {max(len(unfinished), len(checklist))}개입니다.",
        "우선순위가 높은 개념 학습과 복습 단계를 분리하면 실행력이 올라갑니다.",
    ]
    problem_points = _listify(parsed.get("problemPoints")) or [
        "해야 할 일과 복습 항목이 한 덩어리로 적혀 있으면 실제 착수 순서가 흐려질 수 있습니다.",
        "시간 블록이 부족하거나 비어 있으면 목표 대비 학습량이 과소 또는 과대 편성될 수 있습니다.",
    ]
    balance_assessment = str(parsed.get("balanceAssessment") or "").strip() or (
        "핵심 개념 학습, 문제 풀이, 복습 시간이 균형 있게 배치됐는지 점검이 필요합니다."
    )
    improvement_actions = _listify(parsed.get("improvementActions")) or [
        "가장 중요한 과제 1개를 먼저 끝내고 나머지 항목을 분리해서 적기",
        "시간표가 있다면 개념 학습과 문제 풀이 시간을 구분해 배치하기",
        "학습 종료 전 10~15분 복습 시간을 별도로 확보하기",
    ]
    ai_feedback = str(parsed.get("aiFeedback") or "").strip() or (
        f"현재 진행률은 {progress}%입니다. 남은 항목을 우선순위 순으로 처리하면 목표 달성에 가까워집니다."
    )
    next_reco = _listify(parsed.get("nextRecommendations")) or [
        "가장 우선순위 높은 항목부터 처리하기",
        "이해가 부족한 개념을 따로 메모해 복습 목록 만들기",
        "오늘 학습 후 핵심 내용을 한 문장으로 요약하기",
    ]

    result = {
        "success": True,
        "title": title,
        "keywords": keywords,
        "learningGoal": learning_goal,
        "schedule": schedule,
        "checklist": checklist,
        "progress": progress,
        "scheduleAnalysis": schedule_analysis,
        "problemPoints": problem_points,
        "balanceAssessment": balance_assessment,
        "improvementActions": improvement_actions,
        "aiFeedback": ai_feedback,
        "nextRecommendations": next_reco,
        "unfinishedItems": unfinished,
        "message": "저장된 플래너 자료를 기반으로 분석했습니다.",
    }
    # PDF/플래너 메타데이터(날짜/연도/교수명/표지/footer) 정제
    try:
        from app.utils.pdf_noise_filter import detect_repeated_lines, sanitize_text_fields
        repeated = detect_repeated_lines([content or "", raw_title or ""])
        fb = subject or title or "학습 주제"
        result = sanitize_text_fields(result, repeated=repeated, title=fb)
    except Exception as e:  # noqa: BLE001
        logger.debug("planner/analyze noise 정제 생략: %s", e)
    return result


@router.post("/analyze", summary="저장된 플래너 자료 기반 AI 계획 분석")
async def planner_analyze(body: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    if not isinstance(body, dict):
        body = {}
    try:
        return await asyncio.wait_for(asyncio.to_thread(_analyze_sync, body), timeout=ANALYZE_TIMEOUT)
    except asyncio.TimeoutError:
        # 타임아웃이어도 '먼저 저장' 류 메시지 없이 deterministic 분석(LLM 생략)을 반환한다.
        try:
            return _analyze_sync({**body, "_no_llm": True})
        except Exception as e:  # noqa: BLE001
            logger.error("planner/analyze deterministic fallback 실패: %s", e)
    except Exception as e:  # noqa: BLE001
        logger.error("planner/analyze 실패: %s", e)
    # 어떤 경우에도 분석 결과(success:true)를 반환 — UNKNOWN/먼저 저장 류 금지
    if True:
        return {
            "success": True,
            "title": "학습 플래너",
            "keywords": [],
            "learningGoal": "저장된 플래너 항목을 우선순위 순으로 학습한다.",
            "schedule": ["핵심 주제 학습", "예제 확인", "자기 점검"],
            "checklist": ["핵심 개념 복습", "문제 풀이", "오답 정리"],
            "progress": 0,
            "scheduleAnalysis": ["현재 저장된 플래너 기준으로 실행 순서를 재정렬해야 합니다."],
            "problemPoints": ["세부 시간 배분과 우선순위가 더 분명하면 학습 효율이 올라갑니다."],
            "balanceAssessment": "학습량과 복습 시간의 균형을 다시 맞추는 것이 좋습니다.",
            "improvementActions": ["핵심 항목부터 처리", "복습 시간 분리", "남은 과제 재정렬"],
            "aiFeedback": "일시적으로 AI 분석이 어려워 기본 분석을 제공합니다. 남은 항목부터 차례로 진행하세요.",
            "nextRecommendations": ["우선순위 높은 항목 처리", "헷갈린 개념 메모", "학습 후 요약"],
            "unfinishedItems": [],
            "message": "저장된 플래너 자료를 기반으로 분석했습니다.",
        }


# ── 플래너 시맨틱 분석 (구조화된 리치 분석) ──────────────────────────────────────
#   Spring Java DTO가 응답 키를 1:1 매핑한다. task 순서/id/type은 코드가 authoritative,
#   LLM은 산문(정합성 이유·중요성·학습 순서·선행지식)만 보강한다. 절대 client에 raise 금지.
_TASK_TYPE_RULES = (
    ("PRACTICE", ("실습", "코드", "구현", "코딩", "실행", "작성", "practice", "code")),
    ("ANALYSIS", ("분석", "결과", "해석", "탐구", "analysis")),
    ("COMPARISON", ("비교", "대조", "차이", "compare")),
    ("REVIEW", ("복습", "정리", "요약", "review", "recap")),
    ("OUTPUT", ("산출물", "제출", "보고서", "발표", "정리본", "리포트", "output", "report")),
)


def _classify_task_type(title: str, description: str = "") -> str:
    blob = f"{title or ''} {description or ''}".lower()
    for ttype, kws in _TASK_TYPE_RULES:
        for kw in kws:
            if kw.lower() in blob:
                return ttype
    return "CONCEPT"


def _norm_level(v: Any, default: str = "MEDIUM") -> str:
    s = str(v or "").strip().upper()
    return s if s in ("HIGH", "MEDIUM", "LOW") else default


def _prereq_list(raw: Any) -> List[Dict[str, Any]]:
    """선행지식 리스트 정규화. includedInPlanTime은 항상 False."""
    out: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            reason = str(item.get("reason") or "").strip()
        else:
            name, reason = str(item or "").strip(), ""
        if name:
            out.append({"name": name, "reason": reason, "includedInPlanTime": False})
    return out


def _analyze_semantic_sync(body: Dict[str, Any]) -> Dict[str, Any]:
    from app.utils.json_parser import extract_json

    def g(*keys: str, default: str = "") -> str:
        for k in keys:
            v = body.get(k)
            if v not in (None, "", []):
                return v if isinstance(v, str) else str(v)
        return default

    title = g("title", "plannerTitle")
    subject = g("subject", "category")
    learning_type = g("learningType", "studyType")
    priority = g("priority")
    learning_goal = g("learningGoal", "goal")
    content = g("content", "todo", "description")
    memo = g("memo")
    source_type = (g("sourceType") or "MANUAL").strip().upper() or "MANUAL"

    target_minutes: Optional[int] = None
    try:
        tm = body.get("targetMinutes")
        if tm not in (None, ""):
            target_minutes = int(float(tm))
            if target_minutes <= 0:
                target_minutes = None
    except (TypeError, ValueError):
        target_minutes = None

    core_concepts = _listify(body.get("coreConcepts"))
    review_questions = _listify(body.get("reviewQuestions"))
    outputs = _listify(body.get("outputs"))

    # detailTasks 우선, 없으면 checklist, 둘 다 없으면 빈 목록
    raw_tasks = body.get("detailTasks")
    warnings: List[str] = []
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raw_tasks = body.get("checklist")
        if isinstance(raw_tasks, list) and raw_tasks:
            warnings.append("세부 학습(detailTasks)이 없어 체크리스트를 기준으로 분석했습니다.")
        else:
            raw_tasks = []
            warnings.append("세부 학습 항목이 없어 개별 task 분석을 생성하지 못했습니다.")

    # 결정적 task 구조 (id/order/title/description/type)
    det_tasks: List[Dict[str, Any]] = []
    for i, t in enumerate(raw_tasks):
        if isinstance(t, dict):
            tid = str(t.get("id") or f"task-{i + 1}")
            t_title = str(t.get("title") or t.get("name") or f"학습 항목 {i + 1}").strip()
            t_desc = str(t.get("description") or "").strip()
        else:
            tid = f"task-{i + 1}"
            t_title = str(t or f"학습 항목 {i + 1}").strip()
            t_desc = ""
        det_tasks.append({
            "id": tid, "order": i, "title": t_title,
            "description": t_desc, "type": _classify_task_type(t_title, t_desc),
        })

    # recommendedMinutes 결정적 분배 (Spring이 어차피 재정규화)
    n = len(det_tasks)
    if n > 0:
        if target_minutes:
            base = max(1, target_minutes // n)
            rem = max(0, target_minutes - base * n)
        else:
            base, rem = 20, 0
        for idx, dt in enumerate(det_tasks):
            dt["recommendedMinutes"] = base + (1 if idx < rem else 0)

    # 결정적 선행지식(전체): coreConcepts 기반, 정직하게 generic
    det_prereqs: List[Dict[str, Any]] = [
        {"name": c, "reason": f"{c}은(는) 본 학습 내용을 이해하는 데 기반이 되는 핵심 개념입니다.",
         "includedInPlanTime": False}
        for c in core_concepts
    ]

    # 결정적 목표 정합성
    det_goal_level = "MEDIUM"
    if learning_goal and det_tasks:
        det_goal_level = "HIGH"
    elif not learning_goal:
        det_goal_level = "LOW"

    # ── LLM 보강 ──
    parsed: Dict[str, Any] = {}
    if not body.get("_no_llm"):
        try:
            ctx_lines = [
                f"제목: {title}", f"과목: {subject}", f"학습 유형: {learning_type}",
                f"우선순위: {priority}", f"목표 학습 시간(분): {target_minutes}",
                f"학습 목표: {learning_goal}", f"내용: {content}", f"메모: {memo}",
                f"핵심 개념: {', '.join(core_concepts)}",
                f"복습 질문: {', '.join(review_questions)}",
                f"산출물: {', '.join(outputs)}", f"출처: {source_type}",
            ]
            rc = body.get("roadmapContext")
            if isinstance(rc, dict) and rc:
                prev = _listify(rc.get("previousLearning"))
                nxt = _listify(rc.get("nextLearning"))
                ctx_lines.append(
                    f"로드맵: {rc.get('currentWeek')}주차 {rc.get('currentDay')}일 / "
                    f"이전학습: {', '.join(prev)} / 다음학습: {', '.join(nxt)}"
                )
            task_lines = "\n".join(
                f'{dt["order"]}. [{dt["id"]}] {dt["title"]}'
                + (f' — {dt["description"]}' if dt["description"] else "")
                for dt in det_tasks
            ) or "(세부 학습 항목 없음)"
            context = "\n".join(l for l in ctx_lines if l.split(": ", 1)[-1].strip() not in ("", "None"))

            system = (
                "너는 학습 설계 코치다. 이미 저장된 공부 플래너를 받아 구조화된 학습 분석을 만든다. "
                "'먼저 저장하세요' 류 안내는 절대 하지 않는다. 입력에서 도출되지 않는 사실은 지어내지 마라. "
                "선행지식은 핵심 개념/명백한 개념 의존성에서만 도출하고 모르면 일반적으로 정직하게 쓴다. "
                "반드시 한국어로, 마크다운 없이 아래 JSON 스키마로만 응답한다. "
                "task 배열은 반드시 입력 순서(order)와 동일한 개수·순서로 채우고 각 항목의 id를 그대로 echo 한다."
            )
            user = (
                f"## 저장된 플래너\n{context}\n\n## 세부 학습 항목(순서·id 고정)\n{task_lines}\n\n"
                + _NOISE_RULES + "\n\n"
                "아래 JSON 형식으로만 응답하라(마크다운/설명 금지):\n"
                "{\n"
                '  "summary": "이 학습 계획 전체를 2~3문장으로 요약",\n'
                '  "goalAlignment": {"level":"HIGH|MEDIUM|LOW","reason":"1~2문장","summary":"목표 정합성 총평 1~2문장","issues":["정합성이 애매한 항목"]},\n'
                '  "prerequisites": [{"name":"개념","reason":"왜 먼저 알면 좋은지"}],\n'
                '  "tasks": [{"id":"입력 id 그대로","reason":"이 task가 목표와 어떻게 연결되는지 1문장","goalLevel":"HIGH|MEDIUM|LOW",'
                '"whyImportant":"1~2문장","prerequisites":[{"name":"","reason":""}],"learningSequence":["단계1","단계2"]}]\n'
                "}"
            )
            raw = _llm(system, user, max_tokens=1600)
            if raw and not raw.strip().startswith("[") and not raw.strip().startswith("[GPT"):
                cand = extract_json(raw)
                if isinstance(cand, dict):
                    parsed = cand
        except Exception as e:  # noqa: BLE001
            logger.info("planner/analyze-semantic LLM 실패, fallback 사용: %s", e)

    # LLM task 보강을 id 기준으로 매핑
    llm_task_map: Dict[str, Dict[str, Any]] = {}
    llm_tasks = parsed.get("tasks")
    if isinstance(llm_tasks, list):
        for lt in llm_tasks:
            if isinstance(lt, dict) and lt.get("id"):
                llm_task_map[str(lt["id"])] = lt

    # ── 최종 task 병합 (구조는 코드, 산문은 LLM) ──
    final_tasks: List[Dict[str, Any]] = []
    for dt in det_tasks:
        lt = llm_task_map.get(dt["id"], {})
        why = str(lt.get("whyImportant") or "").strip() or (
            f"{dt['title']}은(는) 이 학습 목표를 달성하기 위한 핵심 단계입니다."
        )
        ga_reason = str(lt.get("reason") or "").strip() or (
            f"{dt['title']} 학습은 '{learning_goal or subject or title}'와 직접 연결됩니다."
            if (learning_goal or subject or title) else f"{dt['title']}은(는) 전체 학습 목표를 뒷받침합니다."
        )
        ga_level = _norm_level(lt.get("goalLevel"), default=det_goal_level)
        seq = _listify(lt.get("learningSequence"))
        prereqs = _prereq_list(lt.get("prerequisites"))
        final_tasks.append({
            "id": dt["id"], "order": dt["order"], "title": dt["title"],
            "description": dt["description"], "type": dt["type"],
            "recommendedMinutes": dt.get("recommendedMinutes", 20),
            "goalAlignment": {"level": ga_level, "reason": ga_reason},
            "whyImportant": why,
            "prerequisites": prereqs,
            "learningSequence": seq,
        })

    # ── 전체 목표 정합성 병합 ──
    ga_in = parsed.get("goalAlignment") if isinstance(parsed.get("goalAlignment"), dict) else {}
    goal_alignment = {
        "level": _norm_level(ga_in.get("level"), default=det_goal_level),
        "reason": str(ga_in.get("reason") or "").strip() or (
            "학습 목표와 세부 항목이 대체로 일치합니다." if learning_goal and det_tasks
            else "학습 목표가 명확하지 않아 세부 항목과의 정합성 판단이 제한적입니다."
        ),
        "summary": str(ga_in.get("summary") or "").strip() or (
            f"'{learning_goal}'을(를) 향해 세부 학습이 배치되어 있습니다." if learning_goal
            else "학습 목표를 먼저 구체화하면 세부 항목과의 정합성이 뚜렷해집니다."
        ),
        "issues": _listify(ga_in.get("issues")),
    }

    # ── 전체 선행지식 병합 (LLM + 결정적) ──
    prerequisites = _prereq_list(parsed.get("prerequisites")) or det_prereqs

    # ── summary ──
    summary = str(parsed.get("summary") or "").strip()
    if not summary:
        goal_txt = learning_goal or subject or title or "이 학습"
        summary = (
            f"'{title or subject or goal_txt}' 계획은 총 {len(final_tasks)}개의 세부 학습으로 구성되어 있습니다. "
            f"{('목표는 ' + learning_goal + '이며, ') if learning_goal else ''}"
            f"개념 이해부터 실습·분석·복습까지 단계적으로 학습을 진행하도록 설계되었습니다."
        )

    flow = [t["title"] for t in final_tasks]
    total_recommended = sum(int(t.get("recommendedMinutes") or 0) for t in final_tasks)

    result = {
        "success": True,
        "summary": summary,
        "goalAlignment": goal_alignment,
        "prerequisites": prerequisites,
        "tasks": final_tasks,
        "flow": flow,
        "totalRecommendedMinutes": total_recommended,
        "warnings": warnings,
    }
    # PDF/플래너 메타데이터 노이즈 정제
    try:
        from app.utils.pdf_noise_filter import detect_repeated_lines, sanitize_text_fields
        repeated = detect_repeated_lines([content or "", title or "", memo or ""])
        fb = subject or title or "학습 주제"
        result = sanitize_text_fields(result, repeated=repeated, title=fb)
    except Exception as e:  # noqa: BLE001
        logger.debug("planner/analyze-semantic noise 정제 생략: %s", e)
    return result


@router.post("/analyze-semantic", summary="저장된 플래너 자료 기반 구조화 시맨틱 분석")
async def planner_analyze_semantic(body: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    if not isinstance(body, dict):
        body = {}
    try:
        return await asyncio.wait_for(asyncio.to_thread(_analyze_semantic_sync, body), timeout=ANALYZE_TIMEOUT)
    except asyncio.TimeoutError:
        try:
            return _analyze_semantic_sync({**body, "_no_llm": True})
        except Exception as e:  # noqa: BLE001
            logger.error("planner/analyze-semantic deterministic fallback 실패: %s", e)
    except Exception as e:  # noqa: BLE001
        logger.error("planner/analyze-semantic 실패: %s", e)
    # 어떤 경우에도 success:true 구조를 반환
    return {
        "success": True,
        "summary": "일시적으로 상세 분석이 어려워 기본 구조 분석을 제공합니다.",
        "goalAlignment": {
            "level": "MEDIUM",
            "reason": "학습 목표와 세부 항목의 정합성을 다시 점검하는 것이 좋습니다.",
            "summary": "학습 목표를 구체화하면 세부 항목과의 연결이 뚜렷해집니다.",
            "issues": [],
        },
        "prerequisites": [],
        "tasks": [],
        "flow": [],
        "totalRecommendedMinutes": 0,
        "warnings": ["AI 분석이 일시적으로 어려워 기본 구조만 제공했습니다."],
    }
