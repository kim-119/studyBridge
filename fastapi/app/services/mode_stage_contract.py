"""
모드별 SSE 출력 계약(stage/라벨/색상) + 사용자 표시 라벨 정규화 + 스트림 contract 래퍼.

목적:
  - 내부 단계명("1차 초안","FIRST_ANSWER","DRAFT","validation_score","성격 검증")이
    사용자 표시 payload(content/stage_label/agent_role)에 절대 노출되지 않게 한다.
  - 프론트가 3명 카드를 안정적으로 렌더링하도록 모든 이벤트에 공통 필드를 부착한다:
      event_type / turn_id / mode / stage / stage_label / agent_id / agent_name /
      agent_role / content / sequence / is_final / ui_group_color
  - 같은 turn_id+stage+agent_id는 1회만, all_complete는 turn당 1회만, 빈 content는 drop.

기존 SSE 이벤트명/camelCase 키는 불변(additive). snake_case 계약 필드만 *추가*한다.
신규 파일 — 기존 endpoint/계약 불변.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, Iterable, Iterator, Optional

# ── stage → 사용자 라벨/색상 ──────────────────────────────────────────────────
STAGE_LABELS: Dict[str, str] = {
    "answer": "답변",
    "validation": "근거 검증",
    "peer_feedback": "상호 피드백",
    "debate_claim": "주장",
    "debate_rebuttal": "반박",
    "debate_mediation": "중재",
    "simulation_context": "상황 진행",
    "simulation_role": "역할 응답",
    "simulation_feedback": "피드백",
    # simulation_engine 이벤트명(프론트 호환 이름 유지) 표시 라벨
    "simulation_scene": "상황 진행",
    "simulation_choice_result": "역할 응답",
    "simulation_ending": "피드백",
    "simulation_stage": "상황 진행",
    "topic_selection": "토론 주제 선택",
    "debate_section": "토론",
    "debate_round": "토론",
    "all_complete": "완료",
}

STAGE_COLORS: Dict[str, str] = {
    "answer": "#2563EB",
    "validation": "#D97706",
    "peer_feedback": "#7C3AED",
    "debate_claim": "#2563EB",
    "debate_rebuttal": "#DC2626",
    "debate_mediation": "#059669",
    "simulation_context": "#0EA5E9",
    "simulation_role": "#7C3AED",
    "simulation_feedback": "#059669",
    "topic_selection": "#0891B2",
    "all_complete": "#6B7280",
}

# stage → 3에이전트 역할 라벨(있으면 agent_role 기본값으로 사용)
STAGE_ROLE_LABELS: Dict[str, str] = {
    "debate_claim": "주장자",
    "debate_rebuttal": "반박자",
    "debate_mediation": "중재자",
    "simulation_context": "상황 진행자",
    "simulation_role": "상대 역할",
    "simulation_feedback": "피드백 코치",
}

_DEFAULT_COLOR = "#64748B"

# content 추출 우선순위
_CONTENT_KEYS = ("content", "answer", "feedback", "question", "hint", "message")

# 콘텐츠(답변)성 이벤트 — dedupe/빈content drop 대상
CONTENT_EVENTS = {
    "agent_answer", "agent_message", "direct_reply",
    "validation", "peer_feedback", "socratic_step",
    "debate_section", "debate_claim", "debate_rebuttal", "debate_mediation",
    "simulation_context", "simulation_role", "simulation_feedback",
}
TERMINAL_EVENTS = {"all_complete", "done"}


# ── 라벨 정규화 ───────────────────────────────────────────────────────────────
# 내부 라벨/단계명 → 허용 라벨(정확 매칭, 소문자 비교)
_LABEL_NORMALIZE = {
    "1차 초안": "답변", "2차 초안": "답변", "3차 초안": "답변", "초안": "답변",
    "draft": "답변", "first_answer": "답변", "first answer": "답변",
    "1차 답변": "답변", "1차": "답변", "raw_response": "답변",
    "validation": "근거 검증", "validation_score": "근거 검증",
    "2차 검증": "근거 검증", "검증 답안": "근거 검증",
    "peer_feedback": "상호 피드백", "peer feedback": "상호 피드백",
    "3차 상호 피드백": "상호 피드백", "에이전트 피드백": "상호 피드백",
    "personality_score": "", "성격 검증": "",
}

# 자유 텍스트에서 제거/치환할 금지 내부 용어(긴 것부터)
_FORBIDDEN_SUBSTITUTIONS = [
    ("1차 초안", "답변"), ("2차 초안", "답변"), ("3차 초안", "답변"),
    ("FIRST_ANSWER", "답변"), ("first_answer", "답변"),
    ("DRAFT", "답변"), ("draft", "답변"),
    ("raw_response", ""), ("validation_score", "근거 검증"),
    ("personality_score", ""), ("성격 검증", ""),
    ("초안", "답변"),
]


def normalize_user_label(label: Any) -> str:
    """단일 라벨 문자열을 허용 라벨로 정규화한다(매핑에 없으면 원형 유지)."""
    s = str(label or "").strip()
    if not s:
        return ""
    mapped = _LABEL_NORMALIZE.get(s) or _LABEL_NORMALIZE.get(s.lower())
    if mapped is not None:
        return mapped
    return s


def strip_internal_labels(text: Any) -> str:
    """자유 텍스트(content)에서 금지 내부 용어를 제거/치환한다."""
    s = str(text or "")
    if not s:
        return ""
    for bad, repl in _FORBIDDEN_SUBSTITUTIONS:
        if bad in s:
            s = s.replace(bad, repl)
    # 치환으로 생긴 이중 공백 정리(개행은 보존)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def deep_strip_internal_labels(obj: Any) -> Any:
    """중첩 payload(all_complete의 answers/processSteps 등)에서 content류 문자열의 내부 라벨을 제거한다."""
    if isinstance(obj, dict):
        return {k: (strip_internal_labels(v) if (k in _CONTENT_KEYS and isinstance(v, str))
                    else deep_strip_internal_labels(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deep_strip_internal_labels(x) for x in obj]
    return obj


def stage_label_for(stage: str) -> str:
    return STAGE_LABELS.get(stage, normalize_user_label(stage))


def ui_group_color_for(stage: str) -> str:
    return STAGE_COLORS.get(stage, _DEFAULT_COLOR)


def dedupe_key(turn_id: str, stage: str, agent_id: Any) -> str:
    return f"{turn_id}:{stage}:{agent_id}"


def new_turn_id() -> str:
    return f"turn_{uuid.uuid4().hex[:16]}"


# ── stage 도출 ────────────────────────────────────────────────────────────────
_CLEAN_STAGES = set(STAGE_LABELS.keys())
_STAGETYPE_TO_STAGE = {
    "FIRST_ANSWER": "answer",
    "VALIDATION": "validation",
    "PEER_FEEDBACK": "peer_feedback",
}


def derive_stage(event: str, data: Dict[str, Any]) -> str:
    """이벤트/데이터로부터 깨끗한 stage 토큰을 도출한다."""
    explicit = data.get("stage")
    if isinstance(explicit, str) and explicit in _CLEAN_STAGES:
        return explicit
    ev = (event or "").strip().lower()
    if ev in TERMINAL_EVENTS:
        return "all_complete"
    st = str(data.get("stageType") or "").strip().upper()
    if st in _STAGETYPE_TO_STAGE:
        return _STAGETYPE_TO_STAGE[st]
    if ev in ("agent_answer", "agent_message", "direct_reply"):
        return "answer"
    if ev == "validation":
        return "validation"
    if ev == "peer_feedback":
        return "peer_feedback"
    if ev in _CLEAN_STAGES:
        return ev
    # 제어/기타 이벤트: 이벤트명 자체를 stage로(라벨은 normalize)
    return ev or "event"


def _content_of(data: Dict[str, Any]) -> str:
    for k in _CONTENT_KEYS:
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


# ── 스트림 contract 래퍼 ──────────────────────────────────────────────────────
def apply_mode_contract(
    events: Iterable[Dict[str, Any]],
    *,
    mode: str,
    turn_id: Optional[str] = None,
) -> Iterator[Dict[str, Any]]:
    """run_*_mode_stream 제너레이터를 감싸 계약 필드 부착 + 중복/빈content/이중 all_complete를 방어한다.

    - 모든 이벤트 data에 snake_case 계약 필드를 *추가*한다(기존 camelCase 키 보존).
    - content/stage_label/agent_role에서 내부 라벨을 제거한다.
    - CONTENT_EVENTS는 (turn_id, stage, agent_id) 기준 1회만, 빈 content는 drop.
    - all_complete/done은 turn당 1회만.
    """
    tid = turn_id or new_turn_id()
    seq = 0
    seen: set = set()
    completed = False

    for item in events:
        if not isinstance(item, dict):
            continue
        event = item.get("event") or "message"
        data = dict(item.get("data") or {})
        ev = event.strip().lower()
        stage = derive_stage(event, data)
        is_content = ev in CONTENT_EVENTS
        is_terminal = stage == "all_complete"

        # all_complete 게이트(turn당 1회) + 중첩 content 내부 라벨 정제(최종 상태 카드 누출 방지)
        if is_terminal:
            if completed:
                continue
            completed = True
            data = deep_strip_internal_labels(data)

        content = strip_internal_labels(_content_of(data))

        # 빈 content content-이벤트 drop
        if is_content and not content:
            continue

        agent_id = data.get("agentId") if data.get("agentId") is not None else data.get("agent_id")

        # 중복 방어 — content 이벤트 한정.
        #  - agent_id가 있으면 명세대로 (turn, stage, agent) 1회.
        #  - agent_id가 없으면(예: 소크라테스 단계, 레거시 토론 stage) content 해시로 정확 중복만 차단
        #    (서로 다른 단계/내용을 over-drop하지 않기 위함).
        if is_content:
            if agent_id is not None:
                key = dedupe_key(tid, stage, agent_id)
            else:
                # agent_id 부재 시: agentIndex(서로 다른 카드) → content 해시 순으로 식별
                discriminator = data.get("agentIndex") if data.get("agentIndex") is not None else data.get("agent_index")
                if discriminator is not None:
                    key = f"{tid}:{stage}:idx{discriminator}"
                else:
                    key = f"{tid}:{stage}:#{hash(content)}"
            if key in seen:
                continue
            seen.add(key)

        seq += 1
        # 역할 라벨: 명시 agent_role > stage 기본 역할 > 기존 role
        agent_role = (data.get("agent_role") or data.get("agentRole")
                      or STAGE_ROLE_LABELS.get(stage) or data.get("role") or "")
        agent_role = normalize_user_label(agent_role)
        agent_name = data.get("agent_name") or data.get("agentName") or data.get("name")

        # snake_case 계약 필드 부착(additive). content가 있으면 정제본으로 갱신.
        data["event_type"] = event
        data["turn_id"] = tid
        data["mode"] = mode
        data["stage"] = stage
        data["stage_label"] = stage_label_for(stage)
        data["agent_id"] = agent_id
        data["agent_name"] = agent_name
        data["agent_role"] = agent_role
        if content:
            data["content"] = content
        else:
            data.setdefault("content", "")
        data["sequence"] = seq
        data["is_final"] = bool(data.get("isFinal")) or is_terminal or is_content
        data["ui_group_color"] = ui_group_color_for(stage)

        yield {"event": event, "data": data}
