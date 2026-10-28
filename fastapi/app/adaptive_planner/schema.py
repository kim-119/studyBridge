"""요청 파싱·검증. Spring 이 소유권·완료 상태를 검증한 데이터를 보낸다는 전제에서, 형식·무결성만 본다.

- 항목 ID 는 숫자/문자열 모두 받되 비교는 문자열 키로 한다(1 과 "1" 은 같은 항목 → 중복).
  응답에는 Spring 이 보낸 원래 값(id_raw)을 그대로 돌려준다.
- 텍스트는 제어문자를 지우고 길이를 자른다. 구조(개수·ID·날짜·enum) 위반은 오류로 거절한다.
- 값이 없는 필드는 만들어 내지 않는다(마감일·우선순위·예상시간 미지정은 None 으로 남는다).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.adaptive_planner import config
from app.adaptive_planner.errors import AdaptiveError, bad

MODES = ("ROADMAP_COACH", "MANUAL_NEXT")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,64}$")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏ -‮﻿]")
_WS_RE = re.compile(r"[ \t\r\f\v]+")

_STATUS_MAP = {
    "COMPLETED": "COMPLETED", "COMPLETE": "COMPLETED", "DONE": "COMPLETED", "FINISHED": "COMPLETED",
    "IN_PROGRESS": "IN_PROGRESS", "INPROGRESS": "IN_PROGRESS", "ONGOING": "IN_PROGRESS",
    "STARTED": "IN_PROGRESS", "PARTIAL": "IN_PROGRESS",
    "PENDING": "PENDING", "NOT_STARTED": "PENDING", "TODO": "PENDING", "READY": "PENDING",
    "SCHEDULED": "PENDING", "PLANNED": "PENDING",
}
# Spring Planner.priority 는 한글 라벨(낮음/보통/높음/긴급)이다.
_PRIORITY_MAP = {
    "URGENT": "URGENT", "긴급": "URGENT",
    "HIGH": "HIGH", "높음": "HIGH",
    "MEDIUM": "MEDIUM", "NORMAL": "MEDIUM", "보통": "MEDIUM",
    "LOW": "LOW", "낮음": "LOW",
}


@dataclass
class Task:
    id_raw: Any
    key: str
    text: str
    completed: bool


@dataclass
class Item:
    id_raw: Any
    key: str
    index: int                      # 입력 순서(동점 최종 기준)
    title: str
    description: str = ""
    subject: str = ""
    status: str = "PENDING"
    priority: Optional[str] = None
    due_date: Optional[date] = None
    scheduled_date: Optional[date] = None
    estimated_minutes: Optional[int] = None
    order_index: Optional[int] = None
    progress_completed: Optional[int] = None
    progress_total: Optional[int] = None
    tasks: List[Task] = field(default_factory=list)

    @property
    def completed(self) -> bool:
        return self.status == "COMPLETED"

    @property
    def open_tasks(self) -> List[Task]:
        return [t for t in self.tasks if not t.completed]


@dataclass
class QuizResult:
    question_raw: Any
    question_key: str
    correct: bool
    concept_tags: List[str]
    item_key: Optional[str]
    question_text: str = ""


@dataclass
class AdaptiveRequest:
    request_id: str
    user_key: str
    mode: str
    available_minutes: int
    tz_name: str
    today: date
    items: List[Item]
    planner_id_raw: Any = None
    roadmap_id_raw: Any = None
    current_step_key: Optional[str] = None
    quiz_results: List[QuizResult] = field(default_factory=list)
    use_llm: bool = True
    defaulted_minutes: bool = False

    def item(self, key: Optional[str]) -> Optional[Item]:
        if key is None:
            return None
        for it in self.items:
            if it.key == key:
                return it
        return None


def clean_text(v: Any, limit: int) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        v = str(v)
    v = _CTRL_RE.sub("", v)
    v = "\n".join(_WS_RE.sub(" ", line).strip() for line in v.splitlines())
    v = re.sub(r"\n{3,}", "\n\n", v).strip()
    return v[:limit].rstrip()


def _id(v: Any, path: str, required: bool = True) -> Optional[str]:
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise bad("ADAPTIVE_INVALID_REQUEST", f"{path} 가 필요합니다.", path)
        return None
    if isinstance(v, bool) or not isinstance(v, (int, str)):
        raise bad("ADAPTIVE_INVALID_REQUEST", f"{path} 는 정수 또는 문자열이어야 합니다.", path)
    key = str(v).strip()
    if len(key) > 64 or _CTRL_RE.search(key):
        raise bad("ADAPTIVE_INVALID_REQUEST", f"{path} 형식이 올바르지 않습니다.", path)
    return key


def _opt_int(v: Any, path: str, lo: int, hi: int) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        if isinstance(v, str) and re.fullmatch(r"-?\d{1,16}", v.strip()):
            v = int(v.strip())
        else:
            raise bad("ADAPTIVE_INVALID_REQUEST", f"{path} 는 정수여야 합니다.", path)
    if not lo <= v <= hi:
        raise bad("ADAPTIVE_INVALID_REQUEST", f"{path} 는 {lo}~{hi} 범위여야 합니다.", path)
    return v


def parse_date(v: Any, path: str, tz: ZoneInfo) -> Optional[date]:
    """'YYYY-MM-DD' 또는 ISO-8601 일시. 일시는 요청 시간대의 날짜로 바꾼다(오프셋 없으면 요청 시간대로 간주)."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if not isinstance(v, str):
        raise bad("ADAPTIVE_INVALID_DATE", f"{path} 는 ISO-8601 문자열이어야 합니다.", path)
    s = v.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            d = date.fromisoformat(s)
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            d = (dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)).date()
    except ValueError:
        raise bad("ADAPTIVE_INVALID_DATE", f"{path} 날짜 형식이 올바르지 않습니다(YYYY-MM-DD 또는 ISO-8601).",
                  path) from None
    if not 2000 <= d.year <= 2100:
        raise bad("ADAPTIVE_INVALID_DATE", f"{path} 날짜 범위가 올바르지 않습니다.", path)
    return d


def _status(raw: Dict[str, Any], path: str) -> str:
    s, c = raw.get("status"), raw.get("completed")
    if c is not None and not isinstance(c, bool):
        raise bad("ADAPTIVE_INVALID_STATUS", f"{path}.completed 는 true/false 여야 합니다.", f"{path}.completed")
    if s is None or (isinstance(s, str) and not s.strip()):
        return "COMPLETED" if c else "PENDING"
    if not isinstance(s, str) or s.strip().upper().replace("-", "_") not in _STATUS_MAP:
        raise bad("ADAPTIVE_INVALID_STATUS", f"{path}.status 값이 올바르지 않습니다.", f"{path}.status")
    status = _STATUS_MAP[s.strip().upper().replace("-", "_")]
    if c is not None and c != (status == "COMPLETED"):
        raise bad("ADAPTIVE_INVALID_STATUS", f"{path}.status 와 completed 가 서로 다릅니다.", f"{path}.status")
    return status


def _priority(v: Any, path: str) -> Optional[str]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, str):
        p = _PRIORITY_MAP.get(v.strip().upper()) or _PRIORITY_MAP.get(v.strip())
        if p:
            return p
    raise bad("ADAPTIVE_INVALID_REQUEST", f"{path} 는 URGENT/HIGH/MEDIUM/LOW(또는 긴급/높음/보통/낮음)여야 합니다.", path)


def _tasks(v: Any, path: str, lim: config.Limits) -> List[Task]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise bad("ADAPTIVE_INVALID_REQUEST", f"{path} 는 배열이어야 합니다.", path)
    if len(v) > lim.max_tasks_per_item:
        raise AdaptiveError("ADAPTIVE_TOO_MANY_ITEMS", f"{path} 는 최대 {lim.max_tasks_per_item}개입니다.", field=path)
    out: List[Task] = []
    seen = set()
    for i, t in enumerate(v):
        p = f"{path}[{i}]"
        if not isinstance(t, dict):
            raise bad("ADAPTIVE_INVALID_REQUEST", f"{p} 는 객체여야 합니다.", p)
        key = _id(t.get("id"), f"{p}.id")
        if key in seen:
            raise bad("ADAPTIVE_DUPLICATE_ITEM_ID", f"{p}.id 가 중복됩니다.", f"{p}.id")
        seen.add(key)
        text = clean_text(t.get("text") if t.get("text") is not None else t.get("content"), lim.task_chars)
        if not text:
            raise bad("ADAPTIVE_INVALID_REQUEST", f"{p}.text 가 필요합니다.", f"{p}.text")
        done = t.get("completed", False)
        if not isinstance(done, bool):
            raise bad("ADAPTIVE_INVALID_STATUS", f"{p}.completed 는 true/false 여야 합니다.", f"{p}.completed")
        out.append(Task(id_raw=t.get("id"), key=key, text=text, completed=done))
    return out


def _item(raw: Any, i: int, tz: ZoneInfo, lim: config.Limits) -> Item:
    p = f"items[{i}]"
    if not isinstance(raw, dict):
        raise bad("ADAPTIVE_INVALID_REQUEST", f"{p} 는 객체여야 합니다.", p)
    key = _id(raw.get("id"), f"{p}.id")
    title = clean_text(raw.get("title"), lim.title_chars)
    if not title:
        raise bad("ADAPTIVE_INVALID_REQUEST", f"{p}.title 이 필요합니다.", f"{p}.title")
    prog = raw.get("progress")
    pc = pt = None
    if prog is not None:
        if not isinstance(prog, dict):
            raise bad("ADAPTIVE_INVALID_REQUEST", f"{p}.progress 는 객체여야 합니다.", f"{p}.progress")
        pc = _opt_int(prog.get("completed"), f"{p}.progress.completed", 0, 10_000)
        pt = _opt_int(prog.get("total"), f"{p}.progress.total", 0, 10_000)
        if pc is None or pt is None or pc > pt:
            raise bad("ADAPTIVE_INVALID_REQUEST", f"{p}.progress 는 0 ≤ completed ≤ total 이어야 합니다.",
                      f"{p}.progress")
    return Item(
        id_raw=raw.get("id"), key=key, index=i, title=title,
        description=clean_text(raw.get("description"), lim.description_chars),
        subject=clean_text(raw.get("subject"), lim.title_chars),
        status=_status(raw, p),
        priority=_priority(raw.get("priority"), f"{p}.priority"),
        due_date=parse_date(raw.get("dueDate"), f"{p}.dueDate", tz),
        scheduled_date=parse_date(raw.get("scheduledDate"), f"{p}.scheduledDate", tz),
        estimated_minutes=_opt_int(raw.get("estimatedMinutes"), f"{p}.estimatedMinutes", 1, 1440),
        order_index=_opt_int(raw.get("orderIndex"), f"{p}.orderIndex", -(10 ** 15), 10 ** 15),
        progress_completed=pc, progress_total=pt,
        tasks=_tasks(raw.get("tasks"), f"{p}.tasks", lim),
    )


def _quiz(v: Any, keys: set, lim: config.Limits) -> List[QuizResult]:
    if not isinstance(v, list):
        raise bad("ADAPTIVE_INVALID_REQUEST", "quizResults 는 배열이어야 합니다.", "quizResults")
    if len(v) > lim.max_quiz_results:
        raise AdaptiveError("ADAPTIVE_TOO_MANY_ITEMS", f"quizResults 는 최대 {lim.max_quiz_results}개입니다.",
                            field="quizResults")
    out: List[QuizResult] = []
    for i, q in enumerate(v):
        p = f"quizResults[{i}]"
        if not isinstance(q, dict):
            raise bad("ADAPTIVE_INVALID_REQUEST", f"{p} 는 객체여야 합니다.", p)
        qkey = _id(q.get("questionId"), f"{p}.questionId")
        correct = q.get("correct", q.get("isCorrect"))
        if not isinstance(correct, bool):
            raise bad("ADAPTIVE_INVALID_REQUEST", f"{p}.correct 는 true/false 여야 합니다.", f"{p}.correct")
        item_key = _id(q.get("itemId"), f"{p}.itemId", required=False)
        if item_key is not None and item_key not in keys:
            raise bad("ADAPTIVE_UNKNOWN_ITEM_REFERENCE", f"{p}.itemId 가 items 에 없습니다.", f"{p}.itemId")
        tags_raw = q.get("conceptTags") or []
        if not isinstance(tags_raw, list) or len(tags_raw) > lim.max_concepts_per_result:
            raise bad("ADAPTIVE_INVALID_REQUEST",
                      f"{p}.conceptTags 는 최대 {lim.max_concepts_per_result}개 문자열 배열이어야 합니다.",
                      f"{p}.conceptTags")
        tags: List[str] = []
        for t in tags_raw:
            if not isinstance(t, str):
                raise bad("ADAPTIVE_INVALID_REQUEST", f"{p}.conceptTags 는 문자열 배열이어야 합니다.", f"{p}.conceptTags")
            t = clean_text(t, lim.concept_chars).replace("\n", " ")
            if t and t not in tags:
                tags.append(t)
        out.append(QuizResult(question_raw=q.get("questionId"), question_key=qkey, correct=correct,
                              concept_tags=tags, item_key=item_key,
                              question_text=clean_text(q.get("question"), lim.question_chars)))
    return out


def parse_request(body: Any, header_request_id: Optional[str] = None) -> AdaptiveRequest:
    if not isinstance(body, dict):
        raise bad("ADAPTIVE_INVALID_REQUEST", "요청 바디는 JSON 객체여야 합니다.")
    lim = config.limits()

    rid = body.get("requestId") if body.get("requestId") is not None else header_request_id
    if rid is None or (isinstance(rid, str) and not rid.strip()):
        rid = uuid.uuid4().hex
    if not isinstance(rid, str) or not _REQUEST_ID_RE.match(rid.strip()):
        raise bad("ADAPTIVE_INVALID_REQUEST", "requestId 형식이 올바르지 않습니다.", "requestId")
    rid = rid.strip()

    mode = body.get("mode")
    if not isinstance(mode, str) or mode.strip().upper() not in MODES:
        raise bad("ADAPTIVE_INVALID_MODE", "mode 는 ROADMAP_COACH 또는 MANUAL_NEXT 여야 합니다.", "mode")
    mode = mode.strip().upper()

    user_key = _id(body.get("userId"), "userId")

    minutes_raw = body.get("availableMinutes")
    defaulted = minutes_raw is None
    if defaulted:
        minutes = 30
    else:
        try:
            minutes = _opt_int(minutes_raw, "availableMinutes", 0, 1440)
        except AdaptiveError:
            minutes = None
        if minutes not in config.ALLOWED_MINUTES:
            raise bad("ADAPTIVE_INVALID_MINUTES", "availableMinutes 는 15, 30, 60 중 하나여야 합니다.",
                      "availableMinutes")

    tz_name = body.get("timezone") or config.DEFAULT_TIMEZONE
    try:
        if not isinstance(tz_name, str) or len(tz_name) > 64:
            raise ValueError
        tz = ZoneInfo(tz_name.strip())
    except (ZoneInfoNotFoundError, ValueError):
        raise bad("ADAPTIVE_INVALID_TIMEZONE", "timezone 은 IANA 시간대 이름이어야 합니다(예: Asia/Seoul).",
                  "timezone") from None

    today = parse_date(body.get("referenceDate"), "referenceDate", tz) or datetime.now(tz).date()

    raw_items = body.get("items")
    if raw_items is None:
        raw_items = []
    if not isinstance(raw_items, list):
        raise bad("ADAPTIVE_INVALID_REQUEST", "items 는 배열이어야 합니다.", "items")
    if len(raw_items) > lim.max_items:
        raise AdaptiveError("ADAPTIVE_TOO_MANY_ITEMS", f"items 는 최대 {lim.max_items}개입니다.", field="items")
    items = [_item(r, i, tz, lim) for i, r in enumerate(raw_items)]
    seen: Dict[str, int] = {}
    for it in items:
        if it.key in seen:
            raise bad("ADAPTIVE_DUPLICATE_ITEM_ID", f"items[{it.index}].id 가 items[{seen[it.key]}] 와 중복됩니다.",
                      f"items[{it.index}].id")
        seen[it.key] = it.index
    keys = set(seen)

    use_llm = body.get("useLlm", True)
    if not isinstance(use_llm, bool):
        raise bad("ADAPTIVE_INVALID_REQUEST", "useLlm 은 true/false 여야 합니다.", "useLlm")

    req = AdaptiveRequest(
        request_id=rid, user_key=user_key, mode=mode, available_minutes=minutes, tz_name=tz.key,
        today=today, items=items, planner_id_raw=body.get("plannerId"), roadmap_id_raw=body.get("roadmapId"),
        use_llm=use_llm, defaulted_minutes=defaulted,
    )
    _id(body.get("plannerId"), "plannerId", required=False)
    _id(body.get("roadmapId"), "roadmapId", required=False)

    cur = _id(body.get("currentStepId"), "currentStepId", required=False)
    quiz = body.get("quizResults")
    if mode == "MANUAL_NEXT":
        if cur is not None:
            raise bad("ADAPTIVE_FIELD_NOT_ALLOWED", "MANUAL_NEXT 에는 currentStepId 를 보내지 않습니다.", "currentStepId")
        if quiz:
            raise bad("ADAPTIVE_FIELD_NOT_ALLOWED", "quizResults 는 ROADMAP_COACH 전용입니다.", "quizResults")
        return req

    # ROADMAP_COACH: 순서와 현재 단계가 있어야 '현재 단계만' 코칭할 수 있다.
    orders: Dict[int, int] = {}
    for it in items:
        if it.order_index is None:
            raise bad("ADAPTIVE_INVALID_REQUEST", f"items[{it.index}].orderIndex 가 필요합니다(ROADMAP_COACH).",
                      f"items[{it.index}].orderIndex")
        if it.order_index in orders:
            raise bad("ADAPTIVE_DUPLICATE_ORDER",
                      f"items[{it.index}].orderIndex 가 items[{orders[it.order_index]}] 와 같습니다.",
                      f"items[{it.index}].orderIndex")
        orders[it.order_index] = it.index
    if cur is None:
        if items and not all(it.completed for it in items):
            raise bad("ADAPTIVE_CURRENT_STEP_REQUIRED", "ROADMAP_COACH 에는 currentStepId 가 필요합니다.",
                      "currentStepId")
    elif cur not in keys:
        raise bad("ADAPTIVE_CURRENT_STEP_NOT_FOUND", "currentStepId 가 items 에 없습니다.", "currentStepId")
    req.current_step_key = cur
    req.quiz_results = _quiz(quiz, keys, lim) if quiz is not None else []
    return req
