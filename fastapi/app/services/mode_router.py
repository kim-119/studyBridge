"""
학습 모드 라우팅 SSOT.

목적:
  - mode / learningMode 값을 하나의 canonical 모드로 확정한다.
  - ★ 인식하지 못한 모드가 조용히 basic/default 로 폴백하지 않게 한다.
    (기존에는 알 수 없는 값이 전부 basic 으로 흘러가서, mode=debate 오타 하나가
     '토론이 아닌 일반 답변'으로 나가도 아무도 몰랐다.)
  - mode 가 아예 없는 legacy 요청만 basic 으로 처리한다.
"""
from __future__ import annotations

import logging
import os
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

BASIC = "basic"
SOCRATIC = "socratic"
DEBATE = "debate"
SIMULATION = "simulation"        # 상황극. UI 명칭이 "상황극"이어도 코드값은 simulation 으로 고정한다
ROLEPLAY = SIMULATION            # 하위 호환 별칭(값 동일)
GROUP_STUDY_AI = "group_study_ai"

CANONICAL_MODES = (BASIC, SOCRATIC, DEBATE, SIMULATION, GROUP_STUDY_AI)

# 알려진 값 → canonical. 여기에 없는 값은 '이상한 mode'로 보고 거절한다.
_ALIASES = {
    # basic 계열(레거시 generic 값 포함 — 실제로 EC2/Spring 이 보내던 값들)
    "": BASIC, "basic": BASIC, "default": BASIC, "normal": BASIC, "기본": BASIC, "기본 모드": BASIC,
    "chat": BASIC, "single": BASIC, "local": BASIC,
    # Spring ChatService 3단계 흐름(1차/검증/피드백)이 실제로 보내는 값 — 막으면 기본 답변이 죽는다.
    "single_answer": BASIC, "single-answer": BASIC, "singleanswer": BASIC, "stage": BASIC,
    "non-stream": BASIC, "non_stream": BASIC, "nonstream": BASIC, "stream": BASIC,
    "tikitaka": BASIC, "티키타카": BASIC,
    "multi": BASIC, "parallel": BASIC, "multi_agent": BASIC, "multi-agent": BASIC,
    "multi_agent_discussion": BASIC, "discussion": BASIC,
    "collaboration": BASIC, "internal_collaboration": BASIC, "natural_collaboration": BASIC,
    "validation": BASIC, "검증": BASIC, "협업": BASIC,
    # socratic
    "socratic": SOCRATIC, "소크라테스": SOCRATIC, "소크라테스 모드": SOCRATIC,
    # debate
    "debate": DEBATE, "토론": DEBATE, "토론 모드": DEBATE,
    # simulation(상황극)
    "simulation": SIMULATION, "situation": SIMULATION, "roleplay": SIMULATION, "role_play": SIMULATION,
    "sim": SIMULATION, "상황극": SIMULATION, "상황극 모드": SIMULATION,
    "시뮬레이션": SIMULATION, "시뮬레이션 모드": SIMULATION,
    # group study bots
    "group_study_ai": GROUP_STUDY_AI, "group_chat": GROUP_STUDY_AI,
}


class UnsupportedModeError(ValueError):
    """알 수 없는 mode / learningMode. 조용한 basic 폴백 대신 422 로 거절한다."""

    def __init__(self, field: str, value: Any):
        self.field = field
        self.value = value
        self.supported = supported_values()
        super().__init__(f"{field}={value!r} 는 지원하지 않는 모드입니다.")


def supported_values() -> List[str]:
    return sorted({k for k in _ALIASES if k})


def strict_enabled() -> bool:
    """STRICT 모드 검증 on/off. 운영 사고 시 즉시 되돌릴 수 있는 탈출구."""
    return (os.getenv("AI_STRICT_MODE_VALIDATION", "on") or "").strip().lower() not in ("0", "off", "false", "no")


def normalize(value: Any) -> Optional[str]:
    """알려진 값이면 canonical, 아니면 None."""
    return _ALIASES.get(str(value or "").strip().lower())


def resolve_mode(mode: Any = None, learning_mode: Any = None) -> str:
    """
    mode / learningMode → canonical 모드.

    - learningMode 가 명시되면 우선한다(프론트 학습모드 토글).
    - 둘 다 비어 있으면 basic (mode 자체가 없는 legacy 요청).
    - 값이 있는데 알 수 없으면 UnsupportedModeError (silent fallback 금지).
    """
    lm_raw, m_raw = str(learning_mode or "").strip(), str(mode or "").strip()

    if lm_raw:
        lm = normalize(lm_raw)
        if lm is None:
            if strict_enabled():
                raise UnsupportedModeError("learningMode", lm_raw)
            logger.warning("[MODE-ROUTER] 알 수 없는 learningMode=%r (strict off → basic)", lm_raw)
            return BASIC
        # learningMode 가 generic basic 계열이고 mode 가 구체적이면 mode 를 살린다.
        if lm == BASIC and m_raw:
            m = normalize(m_raw)
            if m is None:
                if strict_enabled():
                    raise UnsupportedModeError("mode", m_raw)
                return BASIC
            if m != BASIC:
                return m
        return lm

    if m_raw:
        m = normalize(m_raw)
        if m is None:
            if strict_enabled():
                raise UnsupportedModeError("mode", m_raw)
            logger.warning("[MODE-ROUTER] 알 수 없는 mode=%r (strict off → basic)", m_raw)
            return BASIC
        return m

    return BASIC


def resolve_request_mode(request: Any) -> str:
    """MultiChatRequest(또는 동등 객체) → canonical 모드."""
    return resolve_mode(getattr(request, "mode", None), getattr(request, "learningMode", None))


def error_detail(exc: UnsupportedModeError) -> dict:
    """422 응답 본문(다른 422 계약과 형태를 맞춘다)."""
    return {
        "code": "UNSUPPORTED_MODE",
        "field": exc.field,
        "value": str(exc.value),
        "supportedModes": exc.supported,
        "message": "지원하지 않는 학습 모드입니다. mode/learningMode 값을 확인해 주세요.",
    }
