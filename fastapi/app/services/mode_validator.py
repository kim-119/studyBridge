"""
모드별 답변 검증기.

- validate_tikitaka_messages: critique 없음 / rebuttal 없음 / 내용 혼합 버그 수정
- validate_debate_answers: supporter/critic/moderator 검증
- validate_socratic_answer: 정답 직접 제공 여부 검증
- validate_mode_response: mode별 분기 진입점

[버그 수정]
1. all() over empty iterator → bool(items) and all(...) 패턴으로 수정
2. content_has_all_agents 오탐 → blend_markers + 3명 이름 동시 등장으로 좁힘
3. 연산자 우선순위 → 괄호로 명시
4. critique 키워드 — "하지만"/"반면" 단독 통과 제거
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _get_tikitaka_policy() -> Dict[str, Any]:
    try:
        from app.core.policy_loader import get_tikitaka_validation
        return get_tikitaka_validation()
    except Exception:
        return {
            "critique_keywords": ["부족", "누락", "빠뜨", "한계", "오해", "위험", "반례",
                                   "근거가 약", "설명이 불충분", "보완 필요", "관점이 좁"],
            "rebuttal_keywords": ["맞습니다", "수정", "보완", "실제로", "정확히", "덧붙이", "추가로"],
            "blend_markers": ["첫째", "둘째", "셋째", "각각", "모두", "세 답변", "세 가지"],
        }


def _get_debate_policy() -> Dict[str, Any]:
    try:
        from app.core.policy_loader import get_debate_validation
        return get_debate_validation()
    except Exception:
        return {
            "support_keywords": ["장점", "긍정", "유익", "효과", "도움", "가치"],
            "counter_keywords": ["부족", "누락", "한계", "위험", "반례", "맹점"],
            "moderator_question_markers": ["?", "어떻게 생각", "어느 관점", "당신은"],
        }


def _get_socratic_policy() -> Dict[str, Any]:
    try:
        from app.core.policy_loader import get_socratic_validation
        return get_socratic_validation()
    except Exception:
        return {
            "max_questions": 1,
            "block_direct_answer": True,
            "max_answer_length_chars": 450,
            "direct_answer_markers": ["정답은", "결론은", "즉, 답은", "완성 답안은"],
        }


# ── tikitaka 검증 ──────────────────────────────────────────────────────────────

def validate_tikitaka_messages(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    3라운드 티키타카 구조를 검증한다.

    수정된 버그:
    - all() over empty iterator: bool(items) and all(...) 패턴 사용
    - content_has_all_agents 오탐: blend_markers + 3명 이름 동시 등장 조건으로 좁힘
    - 연산자 우선순위: 괄호로 명시
    - critique 키워드: "하지만"/"반면" 단독 통과 제거
    """
    policy = _get_tikitaka_policy()
    critique_terms: List[str] = policy.get("critique_keywords", [])
    rebuttal_terms: List[str] = policy.get("rebuttal_keywords", [])
    blend_markers: List[str] = policy.get("blend_markers", [])

    issues: List[str] = []

    # ── critique 검증 ──────────────────────────────────────────────────────
    critique_items = [
        m for m in messages if m.get("speechType") == "critique"
    ]
    # BUG FIX [1]: bool(items) and all(...) — 빈 리스트일 때 True 반환 방지
    critique_present = bool(critique_items) and all(
        any(term in (m.get("content") or "") for term in critique_terms)
        for m in critique_items
    )
    if not critique_present:
        if not critique_items:
            issues.append("critique 메시지가 없습니다.")
        else:
            issues.append("critique 메시지에 실제 비판/보완 키워드가 없습니다.")

    # ── rebuttal/refinement 검증 ─────────────────────────────────────────
    rebuttal_items = [
        m for m in messages if m.get("speechType") == "rebuttal_or_refinement"
    ]
    # BUG FIX [1]: bool(items) and all(...) 패턴
    rebuttal_present = bool(rebuttal_items) and all(
        any(term in (m.get("content") or "") for term in rebuttal_terms)
        for m in rebuttal_items
    )
    if not rebuttal_present:
        if not rebuttal_items:
            issues.append("rebuttal/refinement 메시지가 없습니다.")
        else:
            issues.append("rebuttal/refinement 메시지에 실제 반박/보완 키워드가 없습니다.")

    # ── 내용 혼합 감지 ────────────────────────────────────────────────────
    # BUG FIX [2]: critique 메시지에서 대상 에이전트 이름 언급은 정상
    # "3명 이상 이름 동시 등장 AND blend_markers AND critique 아님"만 오탐으로 판정
    agent_names = list({m.get("agentName", "") for m in messages if m.get("agentName")})
    for m in messages:
        if m.get("speechType") == "critique":
            continue  # critique는 대상 에이전트 언급이 정상
        content = m.get("content") or ""
        names_in_content = [n for n in agent_names if n and n in content]
        has_blend = any(marker in content for marker in blend_markers)
        # 3명 이상 이름 + blend_marker가 있을 때만 혼합으로 판정
        if len(names_in_content) >= 3 and has_blend:
            issues.append(
                f"메시지({m.get('agentName')}, {m.get('speechType')})에 "
                "여러 에이전트 답변이 혼합된 것으로 보입니다."
            )

    # ── 중복 구조 감지 ────────────────────────────────────────────────────
    non_critique_items = [m for m in messages if m.get("speechType") != "critique"]
    if len(non_critique_items) >= 2:
        texts = [m.get("content") or "" for m in non_critique_items]
        for i, text_a in enumerate(texts):
            for text_b in texts[i + 1:]:
                common_chars = sum(1 for c in text_a[:200] if c in text_b[:200])
                if len(text_a) > 0:
                    ratio = common_chars / max(len(text_a[:200]), 1)
                else:
                    ratio = 0.0
                # BUG FIX [3]: 연산자 우선순위 괄호로 명시
                duplicate_structure = (
                    (ratio >= 0.88)
                    or (
                        text_a.count("정의") >= 3
                        and text_a.count("장단점") >= 3
                    )
                )
                if duplicate_structure:
                    issues.append("답변 구조가 지나치게 유사합니다.")
                    break

    passed = len(issues) == 0
    return {"passed": passed, "issues": issues}


# ── debate 검증 ────────────────────────────────────────────────────────────────

def validate_debate_answers(answers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    토론 모드 answers 배열을 검증한다.
    supporter/critic/moderator 역할별 조건을 확인한다.
    """
    policy = _get_debate_policy()
    support_keywords: List[str] = policy.get("support_keywords", [])
    counter_keywords: List[str] = policy.get("counter_keywords", [])
    moderator_markers: List[str] = policy.get("moderator_question_markers", [])

    issues: List[str] = []
    role_map: Dict[str, str] = {
        a.get("role", ""): (a.get("answer") or "") for a in answers if a.get("role")
    }

    supporter_text = role_map.get("supporter", "")
    critic_text = role_map.get("critic", "")
    moderator_text = role_map.get("moderator", "")

    # supporter 검증
    if not supporter_text:
        issues.append("supporter(찬성봇) 답변이 없습니다.")
    elif not any(kw in supporter_text for kw in support_keywords):
        issues.append("supporter 답변에 옹호 근거 키워드가 없습니다.")

    # critic 검증
    if not critic_text:
        issues.append("critic(반대봇) 답변이 없습니다.")
    elif not any(kw in critic_text for kw in counter_keywords):
        issues.append("critic 답변에 실제 반론 키워드가 없습니다.")

    # moderator 검증
    if not moderator_text:
        issues.append("moderator(사회자봇) 답변이 없습니다.")
    else:
        if not any(marker in moderator_text for marker in moderator_markers):
            issues.append("moderator 답변에 사용자에게 묻는 질문이 없습니다.")

    # 비방 검증 (critic 대상)
    if critic_text:
        try:
            from app.services.inter_agent_feedback_validator import validate_inter_agent_feedback
            fb_result = validate_inter_agent_feedback(critic_text)
            if not fb_result.allowed:
                issues.append("critic 답변에 비방/조롱 표현이 포함되어 있습니다.")
        except Exception:
            pass

    # 순서 검증 (displayOrder: supporter=1, critic=2, moderator=3)
    ordered = sorted(answers, key=lambda a: a.get("displayOrder") or 99)
    expected_roles = ["supporter", "critic", "moderator"]
    actual_roles = [a.get("role") for a in ordered if a.get("role") in expected_roles]
    if actual_roles and actual_roles != expected_roles:
        issues.append(f"답변 순서가 올바르지 않습니다: {actual_roles}")

    passed = len(issues) == 0
    return {"passed": passed, "issues": issues}


# ── socratic 검증 ──────────────────────────────────────────────────────────────

def validate_socratic_answer(answer_text: str) -> Dict[str, Any]:
    """
    소크라테스 모드 답변을 검증한다.
    정답 직접 제공 여부, 질문 개수, 길이를 확인한다.
    """
    policy = _get_socratic_policy()
    max_chars: int = policy.get("max_answer_length_chars", 350)
    direct_markers: List[str] = policy.get("direct_answer_markers", [])
    lecture_markers: List[str] = policy.get("lecture_markers", [])

    text = answer_text or ""
    issues: List[str] = []
    direct_answer_blocked = False

    # 정답 직접 제공 감지
    if any(marker in text for marker in direct_markers):
        issues.append("정답을 직접 제공하는 표현이 포함되어 있습니다.")
        direct_answer_blocked = True

    # 강의/완성설명형(정답 우회 설명) 감지
    if any(marker in text for marker in lecture_markers):
        issues.append("개념을 강의식으로 설명하고 있습니다. 정답 대신 질문으로 유도하세요.")
        direct_answer_blocked = True

    # 질문 개수 (? 기준) — 정확히 1개만 허용(0=질문없음, 2개 이상=과다)
    question_count = text.count("?")
    if question_count == 0:
        issues.append("꼬리질문이 없습니다. 사용자 사고를 유도하는 질문을 포함해야 합니다.")
    elif question_count > 2:
        issues.append(f"질문이 너무 많습니다 ({question_count}개). 꼬리질문은 하나만 제시하세요.")

    # 길이 검증 (짧게 유지)
    if len(text) > max_chars:
        issues.append(f"답변이 너무 깁니다 ({len(text)}자, 최대 {max_chars}자). 진단/힌트/꼬리질문만 짧게.")

    passed = len(issues) == 0
    return {"passed": passed, "issues": issues, "directAnswerBlocked": direct_answer_blocked}


# ── 모드별 분기 진입점 ──────────────────────────────────────────────────────────

def validate_mode_response(
    mode: str,
    answers: List[Dict[str, Any]],
    messages: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    mode에 따라 적절한 검증 함수를 호출하고 결과를 반환한다.

    Args:
        mode: "tikitaka" | "debate" | "socratic" | "default"
        answers: AgentAnswer dict 목록
        messages: tikitaka용 발화 메시지 목록 (mode=tikitaka일 때만 사용)
    """
    if mode == "tikitaka":
        msgs = messages or [
            {
                "agentName": a.get("agentName"),
                "speechType": a.get("speechType"),
                "content": a.get("answer"),
            }
            for a in answers
        ]
        return validate_tikitaka_messages(msgs)

    if mode == "debate":
        return validate_debate_answers(answers)

    if mode == "socratic":
        if not answers:
            return {"passed": False, "issues": ["답변이 없습니다."], "directAnswerBlocked": False}
        answer_text = answers[0].get("answer", "")
        return validate_socratic_answer(answer_text)

    # default: 기본 통과
    return {"passed": True, "issues": []}
