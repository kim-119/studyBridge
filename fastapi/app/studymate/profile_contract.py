"""Canonical Agent Profile 계약.

로직은 canonical key 로만 동작하고 label 은 UI 표시용 파생값이다.

personality key (6): friendly / critical / creative / concise / sardonic / logical
knowledge  key (5): beginner / bachelor / master / phd / expert

입력 우선순위(성격):
  personalityKey > personalityStyle(Spring canonical, 프론트 7키) > personality > personalityLabel > tone > style
UNKNOWN 값은 조용히 friendly/bachelor 로 붕괴시키지 않는다:
  resolved=False, originalValue, fallbackReason 를 남기고 WARN 로그.
  자유 텍스트 성격은 archetype(가장 중립적인 logical) + overlay(원문 스타일 설명)로 분리한다.

라벨 SSOT 는 EC2 프론트(StudyMate.jsx PERSONALITY_TYPE_LABELS)와 일치시킨다.
(2026-09-16 감사: FastAPI 가 critical→'냉철형', sardonic→'냉철형' 으로 내보내 프론트 어휘와 5/6 불일치,
 critical 과 sardonic 이 같은 라벨로 붕괴)
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("studybridge.studymate.profile")

PERSONALITY_KEYS = ("friendly", "critical", "creative", "concise", "sardonic", "logical")
KNOWLEDGE_KEYS = ("beginner", "bachelor", "master", "phd", "expert")

PERSONALITY_LABELS = {
    "friendly": "친근함", "critical": "비판형", "creative": "독특함",
    "concise": "효율적", "sardonic": "냉소적", "logical": "논리형",
}
KNOWLEDGE_LABELS = {
    "beginner": "입문", "bachelor": "학사", "master": "석사", "phd": "박사", "expert": "전문가",
}
# level_policy(INTRO..EXPERT) 와의 호환 매핑
KNOWLEDGE_TO_LEVEL_ENUM = {
    "beginner": "INTRO", "bachelor": "BACHELOR", "master": "MASTER", "phd": "DOCTOR", "expert": "EXPERT",
}

# 별칭 → key. 정확 일치(공백 제거, 소문자) 기준. 부분 문자열 매칭은 하지 않는다(오분류 방지).
_PERSONALITY_ALIASES: Dict[str, str] = {}
for _k, _aliases in {
    "friendly": ["friendly", "친절", "친절형", "친근", "친근함", "친근하게", "다정", "다정함", "따뜻함"],
    "critical": ["critical", "비판", "비판형", "비판적", "비판적으로", "honest", "솔직", "솔직함", "솔직하게",
                 "정직하게", "냉철형", "직설형"],
    "creative": ["creative", "창의", "창의형", "독특", "독특함", "unique", "유머러스하게", "humorous", "엉뚱함"],
    "concise": ["concise", "간결", "간결형", "간결하게", "효율", "효율적", "efficient"],
    "sardonic": ["sardonic", "냉소", "냉소적", "cynical", "냉소형", "츤데레", "coach", "코치"],
    "logical": ["logical", "논리", "논리형", "논리적", "professional", "전문적", "전문적으로", "분석형"],
}.items():
    for _a in _aliases:
        _PERSONALITY_ALIASES[_a.replace(" ", "").lower()] = _k

# 사용자가 '기본값'을 명시 선택한 경우. unknown 이 아니다(resolution=explicit_default).
_EXPLICIT_DEFAULT = {"default", "기본", "기본값", "차분하게", "차분한", "calm"}
EXPLICIT_DEFAULT_PERSONALITY = "friendly"

_KNOWLEDGE_ALIASES: Dict[str, str] = {}
for _k, _aliases in {
    "beginner": ["beginner", "intro", "입문", "입문수준", "초급", "초보", "basic"],
    "bachelor": ["bachelor", "undergraduate", "undergrad", "학사", "학사수준", "학부", "학부생"],
    "master": ["master", "graduate", "석사", "석사수준", "대학원"],
    "phd": ["phd", "ph.d", "doctor", "doctoral", "박사", "박사수준"],
    "expert": ["expert", "전문가", "전문가수준", "실무전문가"],
}.items():
    for _a in _aliases:
        _KNOWLEDGE_ALIASES[_a.replace(" ", "").lower()] = _k


def _norm(v: Any) -> str:
    return str(v or "").strip().replace(" ", "").lower()


@dataclass
class Resolution:
    key: str
    label: str
    resolved: bool
    source: str                       # 어떤 입력 필드에서 확정됐는가
    originalValue: Optional[str] = None
    fallbackReason: Optional[str] = None
    overlay: Optional[str] = None     # 자유 텍스트 성격 overlay(archetype 과 분리)


def resolve_personality(fields: Dict[str, Any]) -> Resolution:
    order = ["personalityKey", "personalityStyle", "personality", "personalityLabel", "tone", "style"]
    first_raw: Optional[str] = None
    first_field: Optional[str] = None
    for name in order:
        raw = fields.get(name)
        if raw is None or not str(raw).strip():
            continue
        if first_raw is None:
            first_raw, first_field = str(raw).strip(), name
        n = _norm(raw)
        if n in _PERSONALITY_ALIASES:
            key = _PERSONALITY_ALIASES[n]
            return Resolution(key, PERSONALITY_LABELS[key], True, name, str(raw).strip())
        if n in _EXPLICIT_DEFAULT:
            # personalityStyle='default' 인데 personality 에 구체 성격이 있으면 그쪽을 더 본다.
            continue
    for name in order:
        if _norm(fields.get(name)) in _EXPLICIT_DEFAULT:
            k = EXPLICIT_DEFAULT_PERSONALITY
            return Resolution(k, PERSONALITY_LABELS[k], True, f"{name}:explicit_default", str(fields.get(name)))
    if first_raw is None:
        k = EXPLICIT_DEFAULT_PERSONALITY
        return Resolution(k, PERSONALITY_LABELS[k], False, "none", None, "personality_missing")
    overlay = sanitize_overlay(first_raw)
    k = "logical"   # 가장 중립적인 archetype. 원문은 overlay 로 살린다.
    logger.warning("[PROFILE] unknown personality field=%s value=%r → archetype=%s overlay=%r (resolved=false)",
                   first_field, first_raw[:40], k, overlay)
    return Resolution(k, PERSONALITY_LABELS[k], False, first_field or "unknown", first_raw,
                      "unknown_personality", overlay)


def resolve_knowledge(fields: Dict[str, Any]) -> Resolution:
    order = ["knowledgeLevelKey", "knowledgeLevel", "knowledge_level", "level", "knowledgeLevelLabel"]
    first_raw: Optional[str] = None
    first_field: Optional[str] = None
    for name in order:
        raw = fields.get(name)
        if raw is None or not str(raw).strip():
            continue
        if first_raw is None:
            first_raw, first_field = str(raw).strip(), name
        n = _norm(raw)
        n = n.replace("수준", "") if n.endswith("수준") and n != "수준" else n
        if n in _KNOWLEDGE_ALIASES:
            key = _KNOWLEDGE_ALIASES[n]
            return Resolution(key, KNOWLEDGE_LABELS[key], True, name, str(raw).strip())
        up = str(raw).strip().upper()
        for key, enum in KNOWLEDGE_TO_LEVEL_ENUM.items():
            if up == enum:
                return Resolution(key, KNOWLEDGE_LABELS[key], True, name, str(raw).strip())
    if first_raw is None:
        return Resolution("bachelor", KNOWLEDGE_LABELS["bachelor"], False, "none", None, "knowledge_missing")
    logger.warning("[PROFILE] unknown knowledgeLevel field=%s value=%r → bachelor (resolved=false)",
                   first_field, first_raw[:40])
    return Resolution("bachelor", KNOWLEDGE_LABELS["bachelor"], False, first_field or "unknown", first_raw,
                      "unknown_knowledge_level")


# ── customInstruction 격리 ────────────────────────────────────────────────────
CUSTOM_INSTRUCTION_MAX_CHARS = 400

_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"(이전|위|앞|모든|기존)\s*(의\s*)?(지시|지침|규칙|명령|프롬프트|설정)[^.\n]{0,12}(무시|잊|따르지|버려|삭제)",
        r"(무시|잊어)\s*(하고|해)\s*[^.\n]{0,20}(지시|규칙|정답)",
        r"ignore\s+(all\s+)?(previous|prior|above|system)",
        r"disregard\s+(all\s+)?(previous|prior|above|instructions)",
        r"(system|시스템)\s*(prompt|프롬프트)",
        r"(모드|mode)\s*(를|을)?\s*(무시|바꿔|변경|해제)",
        r"정답(만|을\s*바로|을\s*그냥)\s*(알려|말해|줘)",
        r"(역할|페르소나|persona)\s*(를|을)?\s*(무시|버리|벗어|해제)",
        r"(you\s+are\s+now|지금부터\s*너는)",
        r"</?\s*(system|assistant|user)\s*>",
        r"\[/?\s*(USER_CUSTOM_INSTRUCTION|SYSTEM|MODE|SAFETY)[^\]]*\]",
    )
]


@dataclass
class ContainedInstruction:
    text: str
    originalLength: int
    truncated: bool = False
    removedSegments: List[str] = field(default_factory=list)

    @property
    def sanitized(self) -> bool:
        return self.truncated or bool(self.removedSegments)


def _strip_controls(s: str) -> str:
    out = []
    for ch in s:
        cat = unicodedata.category(ch)
        if ch in "\n\t":
            out.append(ch)
        elif cat.startswith("C"):
            continue
        else:
            out.append(ch)
    return "".join(out)


def contain_custom_instruction(raw: Any) -> ContainedInstruction:
    """customInstruction 을 '교수 스타일만 바꿀 수 있는' 하위 우선순위 텍스트로 격리한다.

    - 제어문자/보이지 않는 문자 제거, 길이 상한
    - Safety/Mode/Role/Knowledge/system 을 뒤집으려는 문장은 문장 단위로 제거(나머지 스타일 지시는 유지)
    """
    text = _strip_controls(str(raw or "")).strip()
    original_len = len(text)
    removed: List[str] = []
    if text:
        parts = re.split(r"(?<=[.!?。\n])\s*", text)
        kept = []
        for part in parts:
            if not part.strip():
                continue
            if any(p.search(part) for p in _INJECTION_PATTERNS):
                removed.append(part.strip()[:80])
                continue
            kept.append(part.strip())
        text = " ".join(kept).strip()
    truncated = len(text) > CUSTOM_INSTRUCTION_MAX_CHARS
    if truncated:
        text = text[:CUSTOM_INSTRUCTION_MAX_CHARS].rstrip() + "…"
    if removed:
        logger.warning("[PROFILE] customInstruction 인젝션 의심 %d문장 제거: %r", len(removed), removed[:2])
    return ContainedInstruction(text=text, originalLength=original_len, truncated=truncated,
                                removedSegments=removed)


def sanitize_overlay(raw: str, limit: int = 40) -> str:
    return contain_custom_instruction(raw).text[:limit]


# ── Canonical profile ────────────────────────────────────────────────────────
@dataclass
class CanonicalAgent:
    agentId: str                      # 내부 키(문자열). 이벤트에는 agentIdRaw(원본 타입)를 싣는다.
    agentIndex: int
    name: str
    personalityKey: str
    personalityLabel: str
    knowledgeLevelKey: str
    knowledgeLevelLabel: str
    personalityResolved: bool
    knowledgeResolved: bool
    personalityOriginal: Optional[str] = None
    knowledgeOriginal: Optional[str] = None
    personalityFallbackReason: Optional[str] = None
    knowledgeFallbackReason: Optional[str] = None
    personalityOverlay: Optional[str] = None
    customInstruction: Optional[ContainedInstruction] = None
    role: Optional[str] = None
    goal: Optional[str] = None
    temperatureOverride: Optional[float] = None
    raw: Any = None   # 원본 AgentProfile(모드 엔진 호환용)
    agentIdRaw: Any = None            # Spring 이 보낸 원본 타입(int/str) — 프론트는 === 로 매칭한다

    def identity_payload(self) -> Dict[str, Any]:
        """SSE/JSON 공통 identity 필드. stream/non-stream 이 같은 함수만 쓴다."""
        p: Dict[str, Any] = {
            "personality": self.personalityKey,
            "personalityKey": self.personalityKey,
            "personalityLabel": self.personalityLabel,
            "knowledgeLevel": self.knowledgeLevelKey,
            "knowledgeLevelKey": self.knowledgeLevelKey,
            "knowledgeLevelLabel": self.knowledgeLevelLabel,
            "personalityResolved": self.personalityResolved,
            "knowledgeLevelResolved": self.knowledgeResolved,
        }
        if not self.personalityResolved:
            p["personalityOriginalValue"] = self.personalityOriginal
            p["personalityFallbackReason"] = self.personalityFallbackReason
        if not self.knowledgeResolved:
            p["knowledgeLevelOriginalValue"] = self.knowledgeOriginal
            p["knowledgeLevelFallbackReason"] = self.knowledgeFallbackReason
        return p


def _fields_of(agent: Any) -> Dict[str, Any]:
    if isinstance(agent, dict):
        return dict(agent)
    out: Dict[str, Any] = {}
    for name in ("agentId", "id", "agentSlot", "name", "role", "personality", "personalityKey",
                 "personalityStyle", "personalityLabel", "tone", "style", "knowledgeLevel",
                 "knowledgeLevelKey", "knowledgeLevelLabel", "customInstruction", "goal", "persona",
                 "temperature"):
        out[name] = getattr(agent, name, None)
    return out


def canonicalize_agent(agent: Any, index: int) -> CanonicalAgent:
    f = _fields_of(agent)
    p = resolve_personality(f)
    k = resolve_knowledge(f)
    aid = f.get("agentId") if f.get("agentId") not in (None, "") else f.get("id")
    slot = f.get("agentSlot")
    ci = contain_custom_instruction(f.get("customInstruction"))
    temp = f.get("temperature")
    try:
        temp = float(temp) if temp is not None else None
    except (TypeError, ValueError):
        temp = None
    return CanonicalAgent(
        agentId=str(aid) if aid not in (None, "") else f"agent-{index + 1}",
        agentIndex=int(slot) if isinstance(slot, int) and slot >= 1 else index + 1,
        name=str(f.get("name") or f"에이전트 {index + 1}"),
        personalityKey=p.key, personalityLabel=p.label,
        knowledgeLevelKey=k.key, knowledgeLevelLabel=k.label,
        personalityResolved=p.resolved, knowledgeResolved=k.resolved,
        personalityOriginal=p.originalValue, knowledgeOriginal=k.originalValue,
        personalityFallbackReason=p.fallbackReason, knowledgeFallbackReason=k.fallbackReason,
        personalityOverlay=p.overlay,
        customInstruction=ci if ci.text else None,
        role=f.get("role"), goal=f.get("goal"), temperatureOverride=temp, raw=agent,
        agentIdRaw=aid if aid not in (None, "") else f"agent-{index + 1}",
    )


def canonicalize_agents(agents: List[Any]) -> List[CanonicalAgent]:
    return [canonicalize_agent(a, i) for i, a in enumerate(agents or [])]
