"""
BASIC 모드 persona/role 메타 문구 유출 가드.

문제: BASIC 응답 본문에 "쉬운 풀이 튜터 관점에서", "전문가 관점에서", "저는 ~ 역할로서"
같은 자기 역할 선언이 그대로 노출됐다. 프롬프트가 모델에게 역할명(프로필 displayName,
요청의 role, 내부 위치 역할)을 주면서 '그 이름을 말하지 마라'는 계약은 없었기 때문이다.

여기서는 두 가지를 제공한다.
  1) NO_ROLE_EXPOSURE_RULE — 프롬프트에 넣는 계약 문구.
  2) strip_role_meta(...)  — 계약을 어긴 출력에서 그 문구만 제거하는 방어 계층.

원칙:
  - 페르소나는 어휘 난이도·설명 방식·예시 선택에만 영향을 준다. 역할명 자체는 출력하지 않는다.
  - 제거 대상은 '이 에이전트 자신의 정체성 어휘'를 가리키는 메타 절뿐이다. 도메인 용어를
    코드에 박지 않으며, "실무 관점에서" 같은 일반 서술은 건드리지 않는다.
  - BASIC 전용이다. 토론/소크라테스/상황극의 역할 발화 구조는 이 모듈을 쓰지 않는다.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable, List, Optional

logger = logging.getLogger(__name__)

# 프롬프트 계약 문구(BASIC 프롬프트에만 삽입한다).
NO_ROLE_EXPOSURE_RULE = (
    "[역할명 노출 금지 — 예외 없음]\n"
    "- Do not mention, restate, or expose your role/persona/profile name.\n"
    "- 네 역할·성격·프로필 이름을 본문에 쓰지 마라. 'OO 관점에서', 'OO 역할로서', "
    "'저는 OO입니다/OO로서' 같은 자기 역할 선언·자기소개로 문장을 시작하거나 끼워 넣지 마라.\n"
    "- 성격과 역할은 어휘 난이도·설명 방식·예시 선택에만 반영한다. 본문에는 질문에 대한 답만 쓴다."
)

# 우리 프롬프트가 만들어 낸 내부 위치 역할명(도메인 용어가 아니라 코드 상수다).
INTERNAL_ROLE_TERMS = (
    "첫 설명자", "검증·정리자", "검증 정리자", "검증자", "심화·확장자", "심화 확장자",
)

# "<정체성> 관점에서," / "<정체성> 역할로서," / "저는 <정체성>로서," 형태의 메타 절.
_META_TAIL = r"(?:관점|입장|시각|역할|자격)\s*(?:에서|으로서|로서|상)"
_LEAD = r"(?:저는|제가|나는|내가)?\s*"
_CONNECT = r"(?:\s*(?:말하자면|말씀드리면|보자면|본다면|설명하자면|설명하면|답하자면|정리하면))?"
_SEP = r"\s*[,:·\-—]?\s*"


def _identity_terms(agent: Any) -> List[str]:
    """이 에이전트 '자신의' 정체성 어휘만 모은다(요청 role / 성격 라벨 / 프로필 표시명 / 이름)."""
    terms: List[str] = []
    for attr in ("role", "agentRole", "agent_role", "personality", "personalityLabel",
                 "personality_label", "name", "agentName"):
        val = getattr(agent, attr, None) if not isinstance(agent, dict) else agent.get(attr)
        if isinstance(val, str) and val.strip():
            terms.append(val.strip())
    # 성격 프로필의 표시명(예: 친절형/전문적)도 모델에게 준 이름이므로 포함한다.
    try:
        from app.services.personality_prompt_builder import get_profile
        label = None
        if isinstance(agent, dict):
            label = agent.get("personalityLabel") or agent.get("personality")
        else:
            label = getattr(agent, "personalityLabel", None) or getattr(agent, "personality", None)
        if label:
            profile = get_profile(label) or {}
            v = profile.get("displayName")
            if isinstance(v, str) and v.strip():
                terms.append(v.strip())
    except Exception:  # pragma: no cover - 프로필 조회 실패는 가드를 막지 않는다
        pass
    return terms


def _identity_tokens(agent: Any, extra: Optional[Iterable[str]] = None) -> List[str]:
    """정체성 어휘를 매칭 가능한 토큰으로 쪼갠다(예: '쉬운 풀이 튜터' → '튜터' 포함)."""
    tokens: set = set(INTERNAL_ROLE_TERMS)
    for term in list(_identity_terms(agent)) + list(extra or []):
        cleaned = re.sub(r"[^\w가-힣 ]", " ", term).strip()
        # 문장형 값(긴 설명)은 토큰으로 쪼개면 '정의/기준/예시' 같은 일반어까지 잡는다.
        if not cleaned or len(cleaned) > 20 or len(cleaned.split()) > 4:
            continue
        tokens.add(cleaned)
        for piece in cleaned.split():
            # 한 글자 토큰은 오탐이 크다(예: '형'). 두 글자 이상만 쓴다.
            if len(piece) >= 2:
                tokens.add(piece)
    return sorted(tokens, key=len, reverse=True)


def _pattern(tokens: List[str]) -> Optional[re.Pattern]:
    if not tokens:
        return None
    alt = "|".join(re.escape(t) for t in tokens)
    # 정체성 토큰을 포함한 짧은 수식어구 + 메타 꼬리 + 이어지는 구분자
    body = rf"[^,.\n]{{0,12}}(?:{alt})[^,.\n]{{0,8}}"
    return re.compile(rf"{_LEAD}{body}\s*{_META_TAIL}{_CONNECT}{_SEP}")


_SELF_INTRO = re.compile(
    r"(?:저는|제가|나는|내가)\s*[^,.\n]{0,20}?(?:이다|입니다|이에요|예요|야)\s*[.,]?\s*")


def strip_role_meta(text: str, agent: Any = None, extra_terms: Optional[Iterable[str]] = None) -> str:
    """본문 첫머리(및 문단 첫머리)의 역할 선언 메타 절을 제거한다.

    문장 중간의 서술은 건드리지 않는다. 제거 후 문장이 비면 원문을 그대로 돌려준다
    (내용을 잃는 것보다 메타 문구가 남는 편이 낫다).
    """
    original = text or ""
    if not original.strip():
        return original
    pattern = _pattern(_identity_tokens(agent, extra_terms))
    if pattern is None:
        return original

    out_lines: List[str] = []
    removed: List[str] = []
    for line in original.split("\n"):
        stripped = line.lstrip()
        if stripped:
            indent = line[: len(line) - len(stripped)]
            m = pattern.match(stripped)
            if m and m.end() < len(stripped):
                removed.append(m.group(0).strip())
                rest = stripped[m.end():].lstrip()
                # 남은 문장이 소문자/조사로 시작해 어색해지는 경우는 되돌린다.
                if rest and not rest[0] in ",.":
                    line = indent + rest[0].upper() + rest[1:] if rest[0].isascii() and rest[0].isalpha() else indent + rest
        out_lines.append(line)

    result = "\n".join(out_lines)

    # "저는 OOO입니다." 형태의 자기소개 첫 문장도 제거한다(에이전트 이름이 들어간 경우만).
    names = [t for t in _identity_terms(agent) if len(t) >= 2]
    if names:
        head = result.lstrip()
        m = _SELF_INTRO.match(head)
        if m and any(n in m.group(0) for n in names) and m.end() < len(head):
            removed.append(m.group(0).strip())
            result = head[m.end():].lstrip()

    if not result.strip():
        return original
    if removed:
        logger.info("[PERSONA-GUARD] 역할 메타 문구 제거: %s", removed[:3])
    return result
