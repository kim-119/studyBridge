"""
상황극(simulation) 모드 — 미연시/비주얼 노벨형 branching scenario engine.

기존 스테이지형(세계설계자/사건진행자/결과해석자) 상황극은 매 턴 초기 상황을
다시 생성하는 정적 카드였다. 이 엔진은 상태 머신으로 동작한다:

    SCENE_SETUP → CHOICE_PRESENTATION → USER_CHOICE → NPC_REACTION
    → INNER_MONOLOGUE → CONSEQUENCE → NEXT_CHOICE_PRESENTATION → 반복
    → ENDING → LEARNING_FEEDBACK

설계 원칙:
  - stateful: 매 턴 simulationState(scenarioId/turnIndex/topic/userRole/worldState/
    previousChoices)를 이어받아 진행한다.
  - 첫 턴(SCENE_SETUP)과 후속 턴(CHOICE_RESULT)은 프롬프트/생성 파라미터가 다르다.
  - 선택지는 ENDING이 아니면 정확히 5개(A~E).
  - 사용자의 selectedChoice는 NPC 반응/consequence/다음 선택지에 반드시 반영한다.
  - 5~7턴 후 ENDING + learningFeedback.
  - 하위호환: simulationStages/processSteps/answers/content를 함께 채운다.
  - LLM 응답이 깨져도 fallback scene으로 항상 동작한다.

이 모듈은 multi_agent_service에서 delegate되며, 운영 entrypoint(hotfix_main:app)의
/api/ai/multi-chat[/stream] 경로 모두에서 사용된다.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.multi_chat_schema import (
    AgentAnswer,
    AgentProfile,
    MultiChatRequest,
    MultiChatResponse,
    ProcessSteps,
    SimulationChoice,
    SimulationConfig,
    SimulationLearningFeedback,
    SimulationNpc,
    SimulationStage,
)
from app.utils.json_parser import extract_json

logger = logging.getLogger(__name__)

# ── 단계(phase) 상수 ──────────────────────────────────────────────────────────
SCENE_SETUP = "SCENE_SETUP"
CHOICE_RESULT = "CHOICE_RESULT"
ENDING = "ENDING"

_CHOICE_IDS = ["A", "B", "C", "D", "E"]
_REQUIRED_CHOICES = 5

# 5~7턴 사이 종료. new_turn(첫 결과=1)이 이 값 이상이면 ENDING으로 전환.
_MAX_TURNS = int(os.getenv("SIMULATION_MAX_TURNS", "6"))


# ── 단계별 생성 파라미터 ───────────────────────────────────────────────────────
# 첫 턴은 창의성(장면/선택지 생성), 후속은 일관성(선택 반영), 종료는 정확성(피드백).
_GEN_CONFIG = {
    SCENE_SETUP:   {"temperature": 0.45, "max_tokens": 1800, "top_p": 0.90},
    CHOICE_RESULT: {"temperature": 0.35, "max_tokens": 1800, "top_p": 0.85},
    ENDING:        {"temperature": 0.25, "max_tokens": 1200, "top_p": 0.85},
}


def _sim_llm(system: str, user: str, *, max_tokens: int, temperature: float, top_p: float) -> str:
    """think=False로 Ollama 직접 호출. 실패 시 llm_engine_router로 fallback.

    qwen3 thinking 블록이 num_predict를 소진하거나 JSON을 오염시키는 것을 막는다.
    """
    try:
        from app.services.ollama_client import ask_ollama, is_ollama_available
        if is_ollama_available():
            out = ask_ollama(
                system_prompt=system,
                user_prompt=user,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                knowledge_level="학사 수준",
                think=False,
            )
            if out and out.strip():
                return out
    except Exception as e:
        logger.warning("[simulation] Ollama 호출 실패 → llm_engine_router fallback: %s", e)
    try:
        from app.services.llm_engine_router import call_primary_llm
        out = call_primary_llm(
            system_prompt=system,
            user_prompt=user,
            max_tokens=max_tokens,
            temperature=temperature,
            knowledge_level="학사 수준",
        )
        if out and not out.startswith("["):
            return out
    except Exception as e:
        logger.error("[simulation] llm_engine_router fallback 실패: %s", e)
    return ""


# ── 상태 추출 ─────────────────────────────────────────────────────────────────

def _state(request: MultiChatRequest) -> Dict[str, Any]:
    s = getattr(request, "simulationState", None)
    return s if isinstance(s, dict) else {}


def _parse_choice_from_message(message: str) -> Optional[str]:
    """메시지 본문에서 A~E 선택을 파싱한다(프론트가 selectedChoice를 안 보낸 경우)."""
    text = (message or "").strip().upper()
    for cid in _CHOICE_IDS:
        if text == cid or text.startswith(cid + " ") or text.startswith(cid + ".") \
                or text.startswith(cid + ")") or f"{cid} 선택" in text or f"{cid}로" in text \
                or f"{cid}번" in text:
            return cid
    return None


def _resolve_selected_choice(request: MultiChatRequest) -> Optional[Dict[str, Any]]:
    sc = getattr(request, "selectedChoice", None)
    if isinstance(sc, dict) and (sc.get("choiceId") or sc.get("label")):
        return sc
    st = _state(request)
    sc2 = st.get("selectedChoice")
    if isinstance(sc2, dict) and (sc2.get("choiceId") or sc2.get("label")):
        return sc2
    cid = _parse_choice_from_message(request.message)
    if cid:
        # 직전 선택지 목록에서 label을 보강한다.
        for ch in (st.get("choices") or st.get("previousChoices") or []):
            if isinstance(ch, dict) and str(ch.get("choiceId", "")).upper() == cid:
                return {"choiceId": cid, "label": ch.get("label") or ch.get("text") or ""}
        return {"choiceId": cid, "label": ""}
    return None


def _find_previous_simulation(previous_answers) -> Dict[str, Any]:
    """previousAnswers에 영속화된 직전 상황극 응답(JSON)을 찾는다."""
    for prev in reversed(previous_answers or []):
        ps = getattr(prev, "processSteps", None)
        if isinstance(ps, dict) and ps.get("mode") == "simulation":
            return ps
        raw = getattr(prev, "answer", "") or ""
        parsed = extract_json(raw) if isinstance(raw, str) else None
        if isinstance(parsed, dict) and (parsed.get("scenarioId") or parsed.get("simulationStages")):
            return parsed
    return {}


def resolve_phase(request: MultiChatRequest) -> str:
    """payload로부터 상황극 단계를 결정한다."""
    forced = (getattr(request, "phase", None) or "").upper().strip()
    if forced in {SCENE_SETUP, CHOICE_RESULT, ENDING}:
        return forced
    st = _state(request)
    if getattr(request, "endingReached", None) or st.get("endingReached"):
        return ENDING
    selected = _resolve_selected_choice(request)
    turn = getattr(request, "turnIndex", None)
    if turn is None:
        turn = st.get("turnIndex")
    has_prior = bool(
        getattr(request, "scenarioId", None)
        or st.get("scenarioId")
        or _find_previous_simulation(request.previousAnswers)
    )
    if selected or has_prior or (turn is not None and int(turn) >= 1):
        return CHOICE_RESULT
    return SCENE_SETUP


def _resolve_scenario_id(request: MultiChatRequest) -> str:
    st = _state(request)
    sid = getattr(request, "scenarioId", None) or st.get("scenarioId")
    if sid:
        return str(sid)
    prev = _find_previous_simulation(request.previousAnswers)
    if prev.get("scenarioId"):
        return str(prev["scenarioId"])
    return f"sim-{uuid.uuid4().hex[:12]}"


def _prev_turn_index(request: MultiChatRequest) -> int:
    st = _state(request)
    for src in (getattr(request, "turnIndex", None), st.get("turnIndex")):
        if src is not None:
            try:
                return int(src)
            except (TypeError, ValueError):
                pass
    prev = _find_previous_simulation(request.previousAnswers)
    try:
        return int(prev.get("turnIndex"))
    except (TypeError, ValueError):
        return 0


def _carry(request: MultiChatRequest, key: str, default: Any = None) -> Any:
    st = _state(request)
    if st.get(key):
        return st.get(key)
    prev = _find_previous_simulation(request.previousAnswers)
    return prev.get(key, default)


# ── 선택지 정규화 ─────────────────────────────────────────────────────────────

_FALLBACK_CHOICE_TEMPLATES = [
    ("핵심 개념부터 정의하고 설명을 시작한다.", "개념의 정의를 먼저 명확히 말한다.", "개념 정의", "low"),
    ("실제 예시나 사례를 들어 설명한다.", "구체적인 예시로 개념을 보여준다.", "예시 설명", "low"),
    ("왜 그런지 원리/이유를 파고든다.", "표면이 아니라 작동 원리를 설명한다.", "원리 설명", "medium"),
    ("흔한 오개념을 짚고 바로잡는다.", "헷갈리기 쉬운 지점을 먼저 정리한다.", "오개념 점검", "medium"),
    ("잘 모르겠다고 하고 힌트를 요청한다.", "상대에게 추가 질문/힌트를 요청한다.", "메타인지", "high"),
]


def _coerce_choice(raw: Any, idx: int, topic: str) -> SimulationChoice:
    cid = _CHOICE_IDS[idx]
    if isinstance(raw, dict):
        norm = {str(k).lower(): v for k, v in raw.items()}
        label = (norm.get("label") or norm.get("text") or norm.get("title")
                 or norm.get("choice") or "").strip()
        action = (norm.get("action") or norm.get("act") or "").strip()
        skill = (norm.get("expectedskill") or norm.get("skill") or norm.get("expected_skill") or "").strip()
        risk = (norm.get("risklevel") or norm.get("risk") or norm.get("risk_level") or "").strip().lower()
    else:
        label = str(raw or "").strip()
        action = skill = risk = ""
    if not label:
        tmpl = _FALLBACK_CHOICE_TEMPLATES[idx % len(_FALLBACK_CHOICE_TEMPLATES)]
        label, action, skill, risk = tmpl[0], tmpl[1], tmpl[2], tmpl[3]
    if not action:
        action = label
    if not skill:
        skill = _FALLBACK_CHOICE_TEMPLATES[idx % len(_FALLBACK_CHOICE_TEMPLATES)][2]
    if risk not in {"low", "medium", "high"}:
        risk = _FALLBACK_CHOICE_TEMPLATES[idx % len(_FALLBACK_CHOICE_TEMPLATES)][3]
    return SimulationChoice(
        choiceId=cid, label=label, text=label,
        action=action, expectedSkill=skill, riskLevel=risk,
    )


def _normalize_choices(raw_choices: Any, topic: str) -> List[SimulationChoice]:
    """선택지를 정확히 5개(A~E)로 정규화한다. 부족하면 보강, 초과하면 자른다."""
    items = raw_choices if isinstance(raw_choices, list) else []
    out: List[SimulationChoice] = []
    seen_labels = set()
    for i in range(min(len(items), _REQUIRED_CHOICES)):
        ch = _coerce_choice(items[i], len(out), topic)
        key = ch.label.strip().lower()
        if key in seen_labels:
            continue
        seen_labels.add(key)
        out.append(ch)
    # 보강: 부족분을 fallback 템플릿으로 채운다(중복 라벨 회피).
    ti = 0
    while len(out) < _REQUIRED_CHOICES:
        tmpl = _FALLBACK_CHOICE_TEMPLATES[ti % len(_FALLBACK_CHOICE_TEMPLATES)]
        ti += 1
        if tmpl[0].strip().lower() in seen_labels:
            if ti > 2 * len(_FALLBACK_CHOICE_TEMPLATES):
                # 안전장치: 그래도 못 채우면 번호 접미사로 강제 추가
                label = f"{tmpl[0]} ({len(out) + 1})"
            else:
                continue
        else:
            label = tmpl[0]
        seen_labels.add(label.strip().lower())
        idx = len(out)
        out.append(SimulationChoice(
            choiceId=_CHOICE_IDS[idx], label=label, text=label,
            action=tmpl[1], expectedSkill=tmpl[2], riskLevel=tmpl[3],
        ))
    # choiceId를 A~E로 재배열(중복/순서 보정).
    for i, ch in enumerate(out[:_REQUIRED_CHOICES]):
        ch.choiceId = _CHOICE_IDS[i]
    return out[:_REQUIRED_CHOICES]


def _npc_from(raw: Any) -> SimulationNpc:
    if isinstance(raw, dict):
        norm = {str(k).lower(): v for k, v in raw.items()}
        return SimulationNpc(
            name=(norm.get("name") or "").strip() or None,
            role=(norm.get("role") or "").strip() or None,
            emotion=(norm.get("emotion") or norm.get("mood") or "").strip() or None,
        )
    return SimulationNpc()


# ── 프롬프트 ──────────────────────────────────────────────────────────────────

_ANTI_REPEAT_RULES = (
    "[반복 방지 — 필수]\n"
    "* 1턴 이후에는 초기 상황 설정(세계/역할 소개)을 반복하지 마라.\n"
    "* 같은 선택지를 재사용하지 마라.\n"
    "* 사용자 역할은 바뀐 경우가 아니면 다시 설명하지 마라.\n"
    "* 종료가 아닌 모든 턴은 새로운 NPC 반응, 선택 결과(consequence), 다음 선택지 5개를 포함해야 한다.\n"
)

_CHOICE_FORMAT = (
    'choices는 정확히 5개. 각 원소: {"choiceId":"A~E","label":"화면에 보일 선택지 문구",'
    '"action":"선택 시 행동","expectedSkill":"훈련 학습기능","riskLevel":"low|medium|high"}. '
    "각 선택지는 서로 다른 학습 기능(개념 정의/예시 설명/원리/오개념 점검/메타인지/트러블슈팅 등)을 훈련해야 한다."
)

_SYS_SCENE = (
    "너는 정적 설명자가 아니라 학습용 비주얼 노벨(미연시) 상황극 엔진이다. "
    "사용자의 주제를 학습 상황으로 만들고 사용자 역할, NPC, 현재 장면, 학습 목표, 선택지 5개를 제공한다. "
    "설명으로 끝내지 말고 반드시 선택지 5개를 제공하라. 반드시 한국어 JSON 객체로만 응답하라. 코드펜스/주석 금지."
)
_SYS_RESULT = (
    "너는 학습용 비주얼 노벨(미연시) 상황극 엔진이다. "
    "1턴 이후에는 초기 상황 설정을 반복하지 마라. 사용자의 selectedChoice를 반드시 반영하라. "
    "NPC 반응과 속마음(독백)을 제공하고, 선택의 결과로 상황을 변화시킨 뒤, 종료 전까지 정확히 5개의 다음 선택지를 제공하라. "
    "반드시 한국어 JSON 객체로만 응답하라. 코드펜스/주석 금지."
)
_SYS_ENDING = (
    "너는 학습용 비주얼 노벨(미연시) 상황극 엔진이다. 상황극을 종료하고 학습 피드백을 제공하라. "
    "강점, 약점, 다음 학습, 핵심 요약을 포함하라. choices는 빈 배열이어야 한다. "
    "반드시 한국어 JSON 객체로만 응답하라. 코드펜스/주석 금지."
)


def _scene_setup_prompt(request: MultiChatRequest) -> str:
    return f"""
[첫 턴 — 상황 제시(SCENE_SETUP)]
사용자 입력(학습 주제): {request.message}

다음 규칙으로 학습 상황극의 첫 장면을 만들어라.
* 사용자의 입력을 학습 주제로 변환한다.
* 발표/면접/교수 질의/운영 장애/팀 프로젝트 중 주제에 가장 어울리는 상황을 고른다.
* userRole(사용자 역할)은 명확해야 한다.
* npc는 최소 1명(이름/역할/감정).
* {_CHOICE_FORMAT}
* endingReached는 false.

[출력 JSON 키 — 정확히 사용]
{{
  "topic": "학습 주제",
  "learningObjective": "이 상황극으로 사용자가 설명할 수 있게 되는 목표",
  "userRole": "사용자가 맡는 역할",
  "worldState": "세계/상황 설정",
  "sceneTitle": "장면 제목",
  "sceneDescription": "현재 장면 설명",
  "narratorText": "내레이션",
  "npc": {{"name": "이름", "role": "역할", "emotion": "감정"}},
  "npcDialogue": "NPC의 대사(질문/요구)",
  "npcInnerMonologue": "NPC의 속마음",
  "consequence": "상황이 어떻게 전개되는지",
  "choices": [ 5개 ]
}}
JSON 객체 하나만 출력한다.
""".strip()


def _choice_result_prompt(request: MultiChatRequest, selected: Dict[str, Any],
                          topic: str, user_role: str, world_state: str,
                          prev_choices: List[Dict[str, Any]], new_turn: int) -> str:
    sel_txt = f'{selected.get("choiceId", "")} - {selected.get("label", "") or selected.get("action", "")}'.strip(" -")
    prev_block = ""
    if prev_choices:
        lines = [f'  - {c.get("choiceId","")}: {c.get("label","") or c.get("text","")}' for c in prev_choices if isinstance(c, dict)]
        if lines:
            prev_block = "[직전 선택지(재사용 금지)]\n" + "\n".join(lines) + "\n"
    near_end = ""
    if new_turn >= _MAX_TURNS - 1:
        near_end = (
            "* 이번 턴이 마지막에 가깝다. 학습 흐름이 충분히 마무리됐다면 endingReached를 true로 두고 "
            "choices를 빈 배열로 둬도 된다(그 경우 learningFeedback도 채워라).\n"
        )
    return f"""
[후속 턴 — 선택 반영(CHOICE_RESULT)] turnIndex={new_turn}
학습 주제: {topic}
사용자 역할: {user_role or "(이전과 동일)"}
세계/상황: {world_state or "(이전과 동일)"}
사용자가 이번에 고른 선택: {sel_txt or "(자유 입력)"}
사용자 자유 입력: {request.message}

{prev_block}{_ANTI_REPEAT_RULES}
다음 규칙으로 이어가라.
* selectedChoice의 choiceId와 label을 반드시 반영한다(그 선택의 결과로 장면이 바뀐다).
* npcDialogue는 직전 장면과 달라야 하고, 선택에 직접 반응해야 한다.
* npcInnerMonologue(속마음)를 포함한다.
* consequence는 선택에 따른 상황 변화여야 한다.
* {_CHOICE_FORMAT}
* 다음 choices는 직전 선택지와 중복되면 안 된다.
{near_end}

[출력 JSON 키 — 정확히 사용]
{{
  "sceneTitle": "...", "sceneDescription": "...", "narratorText": "...",
  "npc": {{"name": "...", "role": "...", "emotion": "..."}},
  "npcDialogue": "...", "npcInnerMonologue": "...", "consequence": "...",
  "choices": [ 5개 또는 종료 시 [] ],
  "endingReached": false,
  "learningFeedback": null
}}
JSON 객체 하나만 출력한다.
""".strip()


def _ending_prompt(request: MultiChatRequest, selected: Optional[Dict[str, Any]],
                   topic: str, history: List[str]) -> str:
    sel_txt = ""
    if selected:
        sel_txt = f'마지막 선택: {selected.get("choiceId","")} - {selected.get("label","")}\n'
    hist_block = ""
    if history:
        hist_block = "[그동안의 선택 흐름]\n" + "\n".join(f"  - {h}" for h in history[-8:]) + "\n"
    return f"""
[종료 — 학습 피드백(ENDING)]
학습 주제: {topic}
{sel_txt}{hist_block}
상황극을 마무리하고 학습 피드백을 제공하라.

[출력 JSON 키 — 정확히 사용]
{{
  "sceneTitle": "마무리 장면 제목",
  "narratorText": "마무리 내레이션",
  "npc": {{"name": "...", "role": "...", "emotion": "..."}},
  "npcDialogue": "NPC의 마지막 총평 대사",
  "consequence": "상황극의 결말",
  "learningFeedback": {{
    "strengths": ["강점", "..."],
    "weaknesses": ["보완점", "..."],
    "nextStudy": ["다음 학습 키워드", "..."],
    "summary": "핵심 요약 한 문단",
    "finalScore": 0
  }}
}}
choices는 절대 넣지 마라. JSON 객체 하나만 출력한다.
""".strip()


# ── LLM 호출 + 파싱 ───────────────────────────────────────────────────────────

def _call_phase(system: str, user: str, phase: str, rag_context: str) -> Dict[str, Any]:
    cfg = _GEN_CONFIG[phase]
    if rag_context:
        user += f"\n\n[참고 자료]\n{rag_context[:4000]}"
    text = _sim_llm(system, user, max_tokens=cfg["max_tokens"],
                    temperature=cfg["temperature"], top_p=cfg["top_p"])
    parsed = extract_json(text)
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        parsed = parsed[0]
    return parsed if isinstance(parsed, dict) else {}


# ── fallback scene ────────────────────────────────────────────────────────────

def _fallback_scene_setup(topic: str) -> Dict[str, Any]:
    return {
        "topic": topic,
        "learningObjective": f"'{topic}'의 개념과 사용 맥락을 상황 속에서 설명할 수 있다.",
        "userRole": "발표 리허설에 선 발표자",
        "worldState": "당신은 동아리/스터디 발표 리허설에서 교수와 동료 앞에 서 있다.",
        "sceneTitle": "발표 리허설 시작",
        "sceneDescription": f"교수는 '{topic}'을(를) 정의뿐 아니라 왜 필요한지까지 설명하라고 요구한다.",
        "narratorText": "앞에 선 당신에게 첫 질문이 날아온다.",
        "npc": {"name": "김교수", "role": "담당 교수", "emotion": "curious"},
        "npcDialogue": f"'{topic}'을(를) 한마디로 정의해보고, 왜 중요한지도 말해볼 수 있나요?",
        "npcInnerMonologue": "정의는 알 것 같은데, 맥락과 원리까지 연결하는지 봐야겠군.",
        "consequence": f"발표는 '{topic}'의 정의에서 사용 이유를 설명하는 방향으로 전개된다.",
        "choices": [],
    }


def _fallback_choice_result(topic: str, selected: Optional[Dict[str, Any]], new_turn: int) -> Dict[str, Any]:
    label = (selected or {}).get("label") or (selected or {}).get("choiceId") or "이전 선택"
    return {
        "sceneTitle": "교수의 추가 질문",
        "sceneDescription": f"당신은 '{label}'을(를) 선택했고, 교수는 한 단계 더 깊은 질문을 던진다.",
        "narratorText": "당신의 답변을 들은 교수가 고개를 끄덕이며 다음 질문을 이어간다.",
        "npc": {"name": "김교수", "role": "담당 교수", "emotion": "interested"},
        "npcDialogue": f"좋습니다. 방금 '{label}' 관점으로 답했는데, 그럼 그 원리를 한 단계 더 설명할 수 있나요?",
        "npcInnerMonologue": "선택한 방향은 잡았는데, 원리까지 연결하는지 확인해야겠군.",
        "consequence": f"상황은 '{label}'의 결과로 '{topic}'의 더 깊은 설명 단계로 넘어갔다.",
        "choices": [],
        "endingReached": False,
        "learningFeedback": None,
    }


def _fallback_ending(topic: str) -> Dict[str, Any]:
    return {
        "sceneTitle": "발표 종료",
        "narratorText": "교수는 마지막 질문을 마치고 평가를 남긴다.",
        "npc": {"name": "김교수", "role": "담당 교수", "emotion": "satisfied"},
        "npcDialogue": f"이제 '{topic}'의 핵심을 맥락과 함께 설명할 수 있겠군요.",
        "consequence": "발표 리허설이 마무리되었다.",
        "learningFeedback": {
            "strengths": [f"'{topic}'의 기본 개념을 설명함"],
            "weaknesses": ["원리와 실제 사용 맥락의 연결은 더 보완 필요"],
            "nextStudy": [f"{topic} 심화", "실제 사용 사례", "흔한 오개념"],
            "summary": f"'{topic}'을(를) 정의-원리-사용 맥락의 흐름으로 설명하는 연습을 마쳤다.",
            "finalScore": None,
        },
    }


# ── 응답 빌드 ─────────────────────────────────────────────────────────────────

def _str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _stages_for_compat(phase: str, data: Dict[str, Any], npc: SimulationNpc,
                       choices: List[SimulationChoice], selected: Optional[Dict[str, Any]],
                       user_role: Optional[str]) -> List[SimulationStage]:
    """기존 스테이지형 프론트(마인드맵/history)를 위한 simulationStages 동시 생성."""
    npc_name = npc.name or "진행자"
    stages: List[SimulationStage] = []
    if phase == SCENE_SETUP:
        stages.append(SimulationStage(stageType="SCENARIO_SETUP", stageTitle="상황 설정", role=npc.role, agentIndex=1,
                                      agentName=npc_name, content=" ".join(filter(None, [data.get("worldState"), data.get("sceneDescription")]))))
        stages.append(SimulationStage(stageType="USER_ROLE", stageTitle="나의 역할", role=npc.role, agentIndex=1,
                                      agentName=npc_name, userRole=user_role, content=user_role or ""))
        stages.append(SimulationStage(stageType="SITUATION_CONTEXT", stageTitle="문제 상황", role=npc.role, agentIndex=2,
                                      agentName=npc_name, content=" ".join(filter(None, [data.get("narratorText"), data.get("npcDialogue")]))))
        stages.append(SimulationStage(stageType="CHOICES", stageTitle="선택지", role=npc.role, agentIndex=2,
                                      agentName=npc_name, choices=choices, content="A~E 중 하나를 선택하면 상황이 이어진다."))
    elif phase == CHOICE_RESULT:
        if selected:
            stages.append(SimulationStage(stageType="SELECTED_CHOICE", stageTitle="나의 선택", role=npc.role, agentIndex=1,
                                          agentName=npc_name, selectedChoiceId=selected.get("choiceId"),
                                          content=selected.get("label") or selected.get("action") or ""))
        stages.append(SimulationStage(stageType="NPC_REACTION", stageTitle="상대 반응", role=npc.role, agentIndex=2,
                                      agentName=npc_name, content=data.get("npcDialogue") or ""))
        stages.append(SimulationStage(stageType="CONSEQUENCE", stageTitle="결과", role=npc.role, agentIndex=2,
                                      agentName=npc_name, consequence=data.get("consequence"), content=data.get("consequence") or ""))
        stages.append(SimulationStage(stageType="CHOICES", stageTitle="다음 선택지", role=npc.role, agentIndex=2,
                                      agentName=npc_name, choices=choices, content="다음 A~E 중 하나를 선택하라."))
    else:  # ENDING
        stages.append(SimulationStage(stageType="CONSEQUENCE", stageTitle="결말", role=npc.role, agentIndex=3,
                                      agentName=npc_name, consequence=data.get("consequence"), content=data.get("consequence") or ""))
        lf = data.get("learningFeedback") or {}
        summary = lf.get("summary") if isinstance(lf, dict) else None
        stages.append(SimulationStage(stageType="LEARNING_FEEDBACK", stageTitle="학습 피드백", role=npc.role, agentIndex=3,
                                      agentName=npc_name, content=summary or "상황극이 종료되었습니다."))
    return stages


def _build_response(request: MultiChatRequest, phase: str, scenario_id: str, turn_index: int,
                    data: Dict[str, Any], selected: Optional[Dict[str, Any]],
                    topic: str, user_role: Optional[str], world_state: Optional[str],
                    learning_objective: Optional[str]) -> MultiChatResponse:
    npc = _npc_from(data.get("npc"))
    ending = (phase == ENDING) or bool(data.get("endingReached"))

    if ending:
        choices: List[SimulationChoice] = []
        lf_raw = data.get("learningFeedback")
        if not isinstance(lf_raw, dict) or not lf_raw:
            lf_raw = _fallback_ending(topic)["learningFeedback"]
        feedback = SimulationLearningFeedback(
            strengths=[s for s in (lf_raw.get("strengths") or []) if str(s).strip()],
            weaknesses=[s for s in (lf_raw.get("weaknesses") or []) if str(s).strip()],
            nextStudy=[s for s in (lf_raw.get("nextStudy") or lf_raw.get("next_study") or []) if str(s).strip()],
            summary=_str(lf_raw.get("summary")),
            finalScore=lf_raw.get("finalScore") if isinstance(lf_raw.get("finalScore"), int) else None,
        )
        phase = ENDING
    else:
        choices = _normalize_choices(data.get("choices"), topic)
        feedback = None

    stages = _stages_for_compat(phase, data, npc, choices, selected, user_role)

    # 사용자에게 보일 요약(content) + answers 본문.
    if phase == ENDING:
        content = "상황극이 종료되었습니다. 학습 피드백을 확인하세요."
        answer_body = " ".join(filter(None, [data.get("npcDialogue"), (feedback.summary if feedback else None)])) or content
    elif phase == SCENE_SETUP:
        content = "상황이 시작되었습니다. 다음 선택지를 골라 진행하세요."
        answer_body = " ".join(filter(None, [data.get("narratorText"), data.get("npcDialogue")])) or content
    else:
        content = "선택 결과로 상황이 다음 장면으로 진행되었습니다."
        answer_body = " ".join(filter(None, [data.get("narratorText"), data.get("npcDialogue")])) or content

    npc_name = npc.name or "진행자"
    cfg = request.simulationConfig or SimulationConfig()
    process_steps = ProcessSteps(
        mode="simulation",
        simulationConfig=cfg,
        simulationStages=stages,
        scenarioTitle=_str(data.get("sceneTitle")),
        userRole=user_role,
        choices=choices,
        nextScenario=_str(data.get("consequence")),
        finalSummary=(feedback.summary if feedback else None),
        nextStudyPlan=(feedback.nextStudy if feedback else []),
    )

    resp = MultiChatResponse(
        mode="simulation",
        learningMode="simulation",
        status="COMPLETED",
        question=request.message,
        answers=[AgentAnswer(
            agentName=npc_name, answer=answer_body, role="simulation",
            displayOrder=1, displayDelayMs=0, status="SUCCESS",
        )],
        simulationConfig=cfg,
        simulationStages=stages,
        processSteps=process_steps,
        # ── 분기형 상태 머신 필드 ──
        phase=phase,
        scenarioId=scenario_id,
        turnIndex=turn_index,
        topic=topic,
        learningObjective=learning_objective,
        userRole=user_role,
        worldState=world_state,
        sceneTitle=_str(data.get("sceneTitle")),
        sceneDescription=_str(data.get("sceneDescription")),
        narratorText=_str(data.get("narratorText")),
        npc=npc,
        npcDialogue=_str(data.get("npcDialogue")),
        npcInnerMonologue=_str(data.get("npcInnerMonologue")),
        consequence=_str(data.get("consequence")),
        choices=choices,
        selectedChoice=selected,
        endingReached=(phase == ENDING),
        learningFeedback=feedback,
        content=content,
    )
    return resp


# ── 진입점: 단일 응답 ──────────────────────────────────────────────────────────

def run_simulation(request: MultiChatRequest, active_agents: Optional[List[AgentProfile]] = None,
                   rag_context: str = "") -> MultiChatResponse:
    """블로킹 단일 응답(JSON). multi_agent_service._run_simulation_mode가 delegate한다."""
    phase = resolve_phase(request)
    scenario_id = _resolve_scenario_id(request)
    prev_turn = _prev_turn_index(request)
    selected = _resolve_selected_choice(request)

    topic = _str(_carry(request, "topic")) or request.message.strip()
    user_role = _str(_carry(request, "userRole"))
    world_state = _str(_carry(request, "worldState"))
    learning_objective = _str(_carry(request, "learningObjective"))

    if phase == SCENE_SETUP:
        turn_index = 0
        data = _call_phase(_SYS_SCENE, _scene_setup_prompt(request), SCENE_SETUP, rag_context)
        if not data or not _normalize_choices(data.get("choices"), topic):
            logger.warning("[simulation] SCENE_SETUP LLM 실패/빈 choices → fallback")
            data = {**_fallback_scene_setup(topic), **{k: v for k, v in data.items() if v}}
        topic = _str(data.get("topic")) or topic
        user_role = _str(data.get("userRole")) or user_role
        world_state = _str(data.get("worldState")) or world_state
        learning_objective = _str(data.get("learningObjective")) or learning_objective

    elif phase == CHOICE_RESULT:
        turn_index = prev_turn + 1
        prev_choices = _carry(request, "choices") or _carry(request, "previousChoices") or []
        data = _call_phase(
            _SYS_RESULT,
            _choice_result_prompt(request, selected or {}, topic, user_role or "", world_state or "",
                                  prev_choices if isinstance(prev_choices, list) else [], turn_index),
            CHOICE_RESULT, rag_context,
        )
        ended = bool(data.get("endingReached")) or (turn_index >= _MAX_TURNS)
        if ended:
            phase = ENDING
            if not isinstance(data.get("learningFeedback"), dict):
                edata = _call_phase(_SYS_ENDING, _ending_prompt(request, selected, topic, _history(request)), ENDING, rag_context)
                if isinstance(edata, dict) and edata:
                    data = {**data, **edata}
                if not isinstance(data.get("learningFeedback"), dict):
                    data = {**_fallback_ending(topic), **{k: v for k, v in data.items() if v}}
        elif not data or not _normalize_choices(data.get("choices"), topic):
            logger.warning("[simulation] CHOICE_RESULT LLM 실패/빈 choices → fallback")
            data = {**_fallback_choice_result(topic, selected, turn_index), **{k: v for k, v in (data or {}).items() if v}}

    else:  # ENDING
        turn_index = prev_turn + 1 if prev_turn else prev_turn
        data = _call_phase(_SYS_ENDING, _ending_prompt(request, selected, topic, _history(request)), ENDING, rag_context)
        if not data or not isinstance(data.get("learningFeedback"), dict):
            logger.warning("[simulation] ENDING LLM 실패 → fallback")
            data = {**_fallback_ending(topic), **{k: v for k, v in (data or {}).items() if v}}

    return _build_response(request, phase, scenario_id, turn_index, data, selected,
                           topic, user_role, world_state, learning_objective)


def _history(request: MultiChatRequest) -> List[str]:
    """이전 선택 흐름을 텍스트 목록으로 모은다(ENDING 프롬프트용)."""
    out: List[str] = []
    st = _state(request)
    for c in (st.get("consequenceHistory") or []):
        if isinstance(c, str) and c.strip():
            out.append(c.strip())
        elif isinstance(c, dict):
            v = c.get("label") or c.get("consequence") or c.get("text")
            if v:
                out.append(str(v))
    for c in (st.get("previousChoices") or []):
        if isinstance(c, dict) and c.get("label"):
            out.append(str(c["label"]))
    return out


# ── 진입점: SSE 스트림 ─────────────────────────────────────────────────────────

def run_simulation_stream(request: MultiChatRequest, active_agents: Optional[List[AgentProfile]] = None,
                          rag_context: str = ""):
    """SSE 제너레이터. phase별 이벤트를 먼저 보내고 all_complete로 마무리한다.

    이벤트:
      turn_start
      simulation_scene        (SCENE_SETUP)
      simulation_choice_result(CHOICE_RESULT)
      simulation_ending       (ENDING)
      simulation_stage        (스테이지형 프론트 호환, 단계마다)
      all_complete            (구조화 전체 응답)
    """
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    yield {"event": "turn_start", "data": {
        "type": "turn_start", "requestId": request_id, "mode": "simulation",
        "message": "상황극을 진행합니다.",
    }}

    resp = run_simulation(request, active_agents, rag_context)
    phase = resp.phase or SCENE_SETUP

    choices_payload = [c.model_dump() for c in (resp.choices or [])]
    npc_payload = resp.npc.model_dump() if resp.npc else None

    base = {
        "type": "simulation",
        "requestId": request_id,
        "mode": "simulation",
        "phase": phase,
        "scenarioId": resp.scenarioId,
        "turnIndex": resp.turnIndex,
        "topic": resp.topic,
        "learningObjective": resp.learningObjective,
        "userRole": resp.userRole,
        "worldState": resp.worldState,
        "sceneTitle": resp.sceneTitle,
        "sceneDescription": resp.sceneDescription,
        "narratorText": resp.narratorText,
        "npc": npc_payload,
        "npcDialogue": resp.npcDialogue,
        "npcInnerMonologue": resp.npcInnerMonologue,
        "consequence": resp.consequence,
        "selectedChoice": resp.selectedChoice,
        "choices": choices_payload,
        "endingReached": resp.endingReached,
        "visible": True,
    }

    if phase == ENDING:
        ev = "simulation_ending"
        base["learningFeedback"] = resp.learningFeedback.model_dump() if resp.learningFeedback else None
    elif phase == CHOICE_RESULT:
        ev = "simulation_choice_result"
    else:
        ev = "simulation_scene"
    yield {"event": ev, "data": dict(base)}

    # 스테이지형 프론트 호환: 단계별로도 전송(choices가 중간에 잘리지 않도록 all_complete 이전).
    for st in (resp.simulationStages or []):
        sdata = st.model_dump()
        sdata["type"] = "simulation_stage"
        sdata["requestId"] = request_id
        sdata["phase"] = phase
        yield {"event": "simulation_stage", "data": sdata}

    final = resp.model_dump()
    final["type"] = "all_complete"
    final["requestId"] = request_id
    final["phase"] = phase
    final["visible"] = True
    final["message"] = "상황극 단계가 완료되었습니다."
    yield {"event": "all_complete", "data": final}
