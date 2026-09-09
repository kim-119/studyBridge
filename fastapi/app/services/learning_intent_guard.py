"""
LearningIntentGuard — 학습 목적이 없는 입력이 학습 모드 파이프라인을 시작하지 못하게 막는다.

배경(근본 원인):
  guardrail_router.classify_route 는 mode=socratic/debate/simulation 이면
  인사/잡담 판정을 '건너뛰고' 바로 해당 모드 파이프라인으로 보낸다.
  그래서 "냉면 먹고 싶어" 같은 입력이 소크라테스 정상 질문처럼 처리됐다.

정책:
  - 적용 대상: socratic / debate / simulation 의 '새 세션 첫 입력'만.
  - 이미 시작된 세션의 짧은 답("모르겠어", "2번", "아니")은 절대 이 가드를 타지 않는다.
  - 비학습 입력이면 모델을 호출하지 않고 NON_LEARNING_INPUT 구조화 코드로 즉시 반환한다.
  - 판정은 결정론 우선. 애매할 때만(선택) 짧은 LLM 분류를 쓰고, 실패하면 학습으로 통과시킨다
    (진짜 학습 질문을 막는 오탐이 더 나쁘다).
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

LEARNING = "LEARNING"
NON_LEARNING = "NON_LEARNING"

NON_LEARNING_CODE = "NON_LEARNING_INPUT"
NON_LEARNING_MESSAGE = "학습할 개념, 문제, 비교 논제 또는 연습 상황을 입력해 주세요."

GUARDED_MODES = ("socratic", "debate", "simulation")


@dataclass
class IntentDecision:
    intent: str
    reason: str
    matched: str = ""
    used_llm: bool = False

    @property
    def is_learning(self) -> bool:
        return self.intent == LEARNING


# ── 결정론 규칙 ─────────────────────────────────────────────────────────────
# 단어 목록을 새로 만들지 않는다. 이미 라이브에서 쓰는 guardrail_router 의 분류 패턴을
# 그대로 재사용하고(SSOT), 여기서는 '학습 목적 여부'라는 판단만 추가한다.
from app.services.guardrail_router import (  # noqa: E402
    _GREETING_RE, _LEARNING_RE, _SELF_INTRO_RE, _SMALL_TALK_RE,
)

# 학습 목적 신호 — 모드별 활동 형태(비교/논제/연습/상황)까지 포함. 도메인 용어는 넣지 않는다.
_MODE_ACTIVITY_RE = re.compile(
    r"(비교|논제|토론|반박|더\s*나은|더\s*좋은|적합|선택|"
    r"연습|훈련|시나리오|상황|면접|발표|모의|롤플|대비)",
)
# 영문/숫자 기술 토큰(HashMap, JWT, FastAPI …) — 잡담과 구분하는 보조 신호.
_TECH_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.+#-]{1,}")
# 학습 목적이 없는 '하고 싶다' 류 욕구 표현(문법 패턴만 본다 — 음식/사물 단어를 나열하지 않는다).
_DESIRE_RE = re.compile(r"([가-힣]{1,10}\s*(먹|마시|자|놀|쉬|사|가|보)고\s*싶)")
_EMOTICON_TAIL_RE = re.compile(r"(ㅋㅋ|ㅎㅎ|ㅠㅠ|ㅜㅜ)\s*$")


def _clean(message: Optional[str]) -> str:
    from app.services.memory_recall_service import strip_memory_block
    return strip_memory_block(message or "").strip()


def has_learning_signal(msg: str) -> bool:
    return bool(_LEARNING_RE.search(msg) or _MODE_ACTIVITY_RE.search(msg))


def classify_deterministic(message: str, mode: str = "") -> Optional[IntentDecision]:
    """확실한 경우만 판정한다. 애매하면 None(→ 선택적 LLM 판정)."""
    msg = _clean(message)
    if not msg:
        return IntentDecision(NON_LEARNING, "빈 입력", "empty")

    learning = has_learning_signal(msg)
    has_tech = bool(_TECH_TOKEN.search(msg))
    is_question = "?" in msg or msg.endswith(("까", "까요", "나요", "는가", "인가"))

    if learning or (is_question and (has_tech or len(msg) >= 12)):
        return IntentDecision(LEARNING, "학습 의도 신호", "learning_signal")

    # 학습 신호가 전혀 없을 때만 잡담 판정을 본다(라이브 guardrail 패턴 재사용).
    if _GREETING_RE.match(msg) or _SELF_INTRO_RE.search(msg):
        return IntentDecision(NON_LEARNING, "인사/자기소개", "greeting")
    if _SMALL_TALK_RE.match(msg) or _EMOTICON_TAIL_RE.search(msg):
        return IntentDecision(NON_LEARNING, "잡담", "small_talk")
    if _DESIRE_RE.search(msg):
        return IntentDecision(NON_LEARNING, "학습 목적 없는 욕구 표현", "desire")
    if len(msg) <= 6 and not has_tech:
        return IntentDecision(NON_LEARNING, "의미를 알 수 없는 짧은 입력", "too_short")

    return None


def _llm_enabled() -> bool:
    return (os.getenv("LEARNING_INTENT_GUARD_LLM", "on") or "").strip().lower() not in ("0", "off", "false", "no")


def classify_with_llm(message: str, mode: str, llm=None) -> Optional[IntentDecision]:
    """애매한 입력만 짧게 분류한다(생성 아님). 실패하면 None."""
    if not _llm_enabled():
        return None
    try:
        if llm is None:
            from app.services.ollama_client import ask_ollama

            def llm(system, user):  # noqa: E731
                return ask_ollama(system_prompt=system, user_prompt=user,
                                  max_tokens=64, temperature=0.0, think=False)

        system = ("사용자 입력이 '학습 목적'인지 판정한다. 학습 목적이면 개념/문제/비교 논제/연습 상황 중 "
                  "하나를 다루려는 의도가 있다. 잡담·인사·감정 표현·먹고 싶은 것은 학습 목적이 아니다. "
                  'JSON 한 줄만 출력: {"learning": true 또는 false}')
        raw = llm(system, f"입력: {message}\n판정:")
        text = (raw or "").lower()
        if '"learning"' in text or "learning" in text:
            if "true" in text:
                return IntentDecision(LEARNING, "LLM 판정", "llm", used_llm=True)
            if "false" in text:
                return IntentDecision(NON_LEARNING, "LLM 판정", "llm", used_llm=True)
    except Exception as exc:  # pragma: no cover - 분류 실패는 통과(오탐 방지)
        logger.warning("[GUARD] 학습 의도 LLM 분류 실패: %s", type(exc).__name__)
    return None


def classify_learning_intent(message: str, mode: str = "", llm=None) -> IntentDecision:
    det = classify_deterministic(message, mode)
    if det is not None:
        return det
    llm_decision = classify_with_llm(_clean(message), mode, llm=llm)
    if llm_decision is not None:
        return llm_decision
    # 판정 실패 → 학습으로 통과(진짜 질문을 막지 않는다).
    return IntentDecision(LEARNING, "판정 불가 — 학습으로 통과", "fallback")


def should_guard(mode: str, is_new_session: bool) -> bool:
    return bool(is_new_session) and (mode or "").strip().lower() in GUARDED_MODES


def block_payload(mode: str, decision: IntentDecision) -> Dict[str, Any]:
    """모델 호출 없이 돌려줄 구조화 응답."""
    return {
        "code": NON_LEARNING_CODE,
        "blocked": True,
        "mode": mode,
        "reason": decision.reason,
        "message": NON_LEARNING_MESSAGE,
    }
