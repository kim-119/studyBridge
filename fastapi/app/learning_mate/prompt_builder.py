"""
Prompt Builder — 정책 레지스트리를 lookup해 조합만 한다(mode별 분기문 없음).

mode를 추가/수정할 때 policies.py만 바꾸면 되고, 이 파일은 손대지 않는다.
build_learning_mate_prompt는 (system_prompt, user_prompt, effective_question, resolved)를 돌려준다.
"""
from typing import Dict, Tuple

from . import policies as P
from .schemas import LearningMateChatRequest

_COMMON_ROLE = (
    "너는 AI 학습메이트다.\n"
    "사용자의 질문을 학습 목적에 맞게 설명한다.\n"
    "AI의 전문성은 항상 전문가 수준으로 유지한다.\n"
    "단, 설명 방식과 난이도는 사용자의 학습자 수준에 맞춘다.\n"
    "한국어로 답한다. 마크다운 코드블록 외의 불필요한 메타발화는 피한다."
)


def resolve_effective_question(request: LearningMateChatRequest) -> str:
    """
    실제 설명 대상 질문 결정:
      previousQuestion이 있고 (quickAction 또는 rewriteInstruction)이 있으면 previousQuestion,
      아니면 request.question.
    """
    prev = (request.previousQuestion or "").strip()
    has_rewrite = bool((request.rewriteInstruction or "").strip()) or bool(request.quickAction)
    if prev and has_rewrite:
        return prev
    return (request.question or "").strip()


def build_learning_mate_prompt(request: LearningMateChatRequest) -> Tuple[str, str, str, Dict[str, str]]:
    """
    Returns:
        system_prompt, user_prompt, effective_question,
        resolved = {mode, tone, level, quickAction(optional)}
    """
    mode = P.resolve_mode(request.mode)
    tone = P.resolve_tone(request.persona.tone)
    level = P.resolve_level(request.persona.learnerLevel)
    qa = P.resolve_quick_action(request.quickAction)

    mp = P.mode_policy(mode)
    tp = P.tone_policy(tone)
    lp = P.level_policy(level)
    qap = P.quick_action_policy(qa)

    effective_question = resolve_effective_question(request)
    custom = (request.persona.customInstruction or "").strip()
    rewrite = (request.rewriteInstruction or "").strip()

    parts = [
        "[공통 역할]", _COMMON_ROLE, "",
        "[모드 정책]", mp["instruction"],
        f"답변 구조: {' → '.join(mp['structure'])}", "",
        "[말투 정책]", tp["instruction"], "",
        "[학습자 수준 정책]", lp["instruction"],
    ]
    if custom:
        parts += ["", "[사용자 추가 요청]", custom]
    if qap or rewrite:
        parts += ["", "[재생성 지시]"]
        if qap:
            parts.append(qap["instruction"])
        if rewrite:
            parts.append(rewrite)
    system_prompt = "\n".join(parts)

    user_prompt = f"[사용자 질문]\n{effective_question}"

    resolved = {"mode": mode, "tone": tone, "level": level}
    if qa:
        resolved["quickAction"] = qa
    return system_prompt, user_prompt, effective_question, resolved
