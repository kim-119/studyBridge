from __future__ import annotations

import json
import logging
import re
from typing import Any

try:
    from agent_quality_policy import build_agent_system_prompt, normalize_agent_config
except Exception:  # pragma: no cover - fallback for isolated tests
    build_agent_system_prompt = None
    normalize_agent_config = None


logger = logging.getLogger("studybridge.agent_feedback")

FEEDBACK_TYPES = {
    "general",
    "answer_review",
    "question_review",
    "compare_answers",
    "improve_answer",
    "criticize_answer",
    "support_answer",
    "agent_opinion",
    "unknown_feedback",
}

FEEDBACK_ACTION_KEYWORDS = [
    "피드백",
    "의견",
    "검토",
    "평가",
    "비판",
    "보완",
    "개선",
    "문제점",
    "장단점",
    "맞는지",
    "틀린지",
    "더 좋게",
    "다시 써",
    "다시써",
    "보충",
    "반박",
    "동의",
    "생각을 말",
    "코멘트",
    "리뷰",
]

FEEDBACK_NEGATION_PATTERNS = [
    "피드백 기능이 왜",
    "피드백이 왜",
    "피드백을 요청하지",
    "피드백 요청하지",
    "왜 피드백",
    "feedback why",
    "why feedback",
]

EXPLICIT_FEEDBACK_PATTERNS = [
    "피드백해줘",
    "피드백 해줘",
    "평가해줘",
    "평가 해줘",
    "첨삭해줘",
    "첨삭 해줘",
    "검토해줘",
    "검토 해줘",
    "개선점 알려줘",
    "보완점 알려줘",
    "채점해줘",
    "채점 해줘",
    "내 답변 어때",
    "이 답변 수준 어때",
    "문제점 알려줘",
]

EXPLICIT_IMPROVE_PATTERNS = [
    "피드백 반영해서 다시 써줘",
    "개선해서 최종본 줘",
    "수정본 만들어줘",
    "보완해서 다시 작성해줘",
    "최종 답안으로 정리해줘",
]


ANSWER_TARGET_KEYWORDS = [
    "답변",
    "대답",
    "말한 것",
    "말한거",
    "답한 것",
    "답한거",
    "이전 답",
    "방금",
    "ai가 말",
    "에이전트가 말",
]

QUESTION_TARGET_KEYWORDS = [
    "질문",
    "질문한 것",
    "질문한거",
    "ai가 질문",
]

COMPARE_KEYWORDS = [
    "비교",
    "둘 중",
    "두 답변",
    "각 답변",
    "누가 더",
    "뭐가 더",
    "어느 답변",
]

IMPROVE_KEYWORDS = [
    "보완",
    "개선",
    "더 좋게",
    "다시 써",
    "다시써",
    "고쳐",
    "수정",
]

CRITICIZE_KEYWORDS = [
    "비판",
    "문제점",
    "틀린지",
    "부족",
    "한계",
]

SUPPORT_KEYWORDS = [
    "동의",
    "타당",
    "맞는지",
    "근거",
]

GENERAL_QUESTION_PATTERNS = [
    r"피드백\s*(이란|뜻|의미|정의)",
    r"의견\s*(이란|뜻|의미|정의)",
    r"평가\s*(이란|뜻|의미|정의)",
]


def detect_feedback_intent(message: str) -> dict:
    text = _normalize_text(message)
    if not text:
        return {
            "is_feedback_request": False,
            "feedback_type": "general",
            "confidence": 0.0,
            "matched_keywords": [],
        }

    if any(pattern in text for pattern in FEEDBACK_NEGATION_PATTERNS):
        return {
            "is_feedback_request": False,
            "feedback_type": "general",
            "confidence": 0.05,
            "matched_keywords": [],
        }

    improve_matches = [pattern for pattern in EXPLICIT_IMPROVE_PATTERNS if pattern in text]
    if improve_matches:
        return {
            "is_feedback_request": True,
            "feedback_type": "improve_answer",
            "confidence": 0.95,
            "matched_keywords": improve_matches,
        }

    explicit_matches = [pattern for pattern in EXPLICIT_FEEDBACK_PATTERNS if pattern in text]
    if explicit_matches:
        return {
            "is_feedback_request": True,
            "feedback_type": "answer_review",
            "confidence": 0.95,
            "matched_keywords": explicit_matches,
        }


    for pattern in GENERAL_QUESTION_PATTERNS:
        if re.search(pattern, text):
            return {
                "is_feedback_request": False,
                "feedback_type": "general",
                "confidence": 0.2,
                "matched_keywords": [],
            }

    matched_actions = _matched_keywords(text, FEEDBACK_ACTION_KEYWORDS)
    matched_answers = _matched_keywords(text, ANSWER_TARGET_KEYWORDS)
    matched_questions = _matched_keywords(text, QUESTION_TARGET_KEYWORDS)
    matched_compare = _matched_keywords(text, COMPARE_KEYWORDS)
    matched_improve = _matched_keywords(text, IMPROVE_KEYWORDS)
    matched_criticize = _matched_keywords(text, CRITICIZE_KEYWORDS)
    matched_support = _matched_keywords(text, SUPPORT_KEYWORDS)

    matched_keywords = _dedupe(
        matched_actions
        + matched_answers
        + matched_questions
        + matched_compare
        + matched_improve
        + matched_criticize
        + matched_support
    )

    if not matched_actions and not matched_compare:
        return {
            "is_feedback_request": False,
            "feedback_type": "general",
            "confidence": 0.15,
            "matched_keywords": matched_keywords,
        }

    feedback_type = "unknown_feedback"
    confidence = 0.55

    if matched_compare:
        feedback_type = "compare_answers"
        confidence = 0.9
    elif matched_questions and matched_actions:
        feedback_type = "question_review"
        confidence = 0.88
    elif matched_criticize and matched_answers:
        feedback_type = "criticize_answer"
        confidence = 0.88
    elif matched_improve and matched_answers:
        feedback_type = "improve_answer"
        confidence = 0.86
    elif matched_support and matched_answers:
        feedback_type = "support_answer"
        confidence = 0.82
    elif matched_answers and matched_actions:
        feedback_type = "answer_review"
        confidence = 0.86
    elif "에이전트" in text or "ai 친구" in text or "선생님" in text:
        feedback_type = "agent_opinion"
        confidence = 0.78

    return {
        "is_feedback_request": feedback_type != "general",
        "feedback_type": feedback_type,
        "confidence": confidence,
        "matched_keywords": matched_keywords,
    }


def extract_feedback_targets(payload: dict) -> dict:
    data = payload or {}
    previous_answers = _normalize_previous_answers(
        data.get("previous_answers")
        or data.get("previousAnswers")
        or data.get("multiple_answers")
        or data.get("multipleAnswers")
        or []
    )
    target_answer = _clean_text(data.get("target_answer") or data.get("targetAnswer") or "")
    target_question = _clean_text(data.get("target_question") or data.get("targetQuestion") or "")

    if not target_answer and previous_answers:
        target_answer = _clean_text(previous_answers[-1].get("answer", ""))

    missing_fields = []
    has_target = bool(target_answer or target_question or previous_answers)
    if not target_answer and not previous_answers:
        missing_fields.append("target_answer")
    if not target_question:
        missing_fields.append("target_question")

    return {
        "target_answer": target_answer,
        "target_question": target_question,
        "previous_answers": previous_answers,
        "has_target": has_target,
        "missing_fields": missing_fields,
    }


def build_feedback_system_prompt(
    feedback_type: str,
    reviewer_agent_config: dict | None = None,
) -> str:
    reviewer = reviewer_agent_config or {}
    if normalize_agent_config is not None:
        reviewer = normalize_agent_config(reviewer, user_message="")
    base_quality_prompt = ""
    if build_agent_system_prompt is not None and reviewer:
        base_quality_prompt = build_agent_system_prompt(reviewer)

    level = reviewer.get("canonical_knowledge_level") or reviewer.get("knowledgeLevel") or "학사 수준"
    personality = reviewer.get("canonical_personality") or reviewer.get("personality") or "전문적"
    tone = reviewer.get("canonical_tone") or reviewer.get("tone") or "전문적"
    discipline = reviewer.get("discipline") or "general"

    type_rule = _feedback_type_rule(feedback_type)

    return f"""너는 AI 답변을 검토하고 개선 의견을 제시하는 StudyBridge 검토 에이전트다.

[검토 에이전트 설정]
지식수준: {level}
성격: {personality}
말투: {tone}
학문 분야: {discipline}

[기존 에이전트 품질 정책]
{base_quality_prompt}

[피드백 유형]
{feedback_type}

[피드백 유형별 지시]
{type_rule}

피드백 원칙:
1. 단순 칭찬만 하지 않는다.
2. 답변의 정확성, 근거성, 명확성, 누락된 관점, 수준 적합성을 평가한다.
3. 틀린 내용이 있으면 명확히 지적한다.
4. 부족한 부분은 보완 방향을 제시한다.
5. 사용자의 원래 질문과 피드백 대상 답변을 구분해서 본다.
6. 감정적 비난이 아니라 분석적 피드백을 제공한다.
7. 필요하면 개선된 답변 예시를 제시한다.
8. 피드백 대상이 아닌 새로운 일반 답변만 생성하지 않는다.
9. 한국어로 답한다.
10. 마크다운 코드블록은 사용하지 않는다."""


def build_feedback_user_prompt(
    message: str,
    feedback_type: str,
    targets: dict,
    reviewer_agent_config: dict | None = None,
) -> str:
    target_question = targets.get("target_question") or "전달되지 않음"
    target_answer = targets.get("target_answer") or "전달되지 않음"
    previous_answers = targets.get("previous_answers") or []

    if feedback_type == "question_review":
        return f"""[사용자 요청]
{message}

[피드백 대상 질문]
{target_question}

위 질문이 좋은 질문인지 평가해라.
명확성, 범위, 난이도, 학습 목적 적합성, 개선안을 기준으로 의견을 달아라."""

    if feedback_type == "compare_answers":
        return f"""[사용자 요청]
{message}

[비교 대상 답변 목록]
{_format_previous_answers(previous_answers)}

각 답변의 장단점, 정확성, 깊이, 사용자 목적 적합성을 비교하고 가장 나은 답변과 이유를 제시해라."""

    if feedback_type == "improve_answer":
        return f"""[사용자 요청]
{message}

[원래 질문]
{target_question}

[보완 대상 답변]
{target_answer}

위 답변의 부족한 부분을 평가한 뒤, 더 나은 답변 방향과 개선된 답변 예시를 제시해라."""

    if feedback_type == "criticize_answer":
        return f"""[사용자 요청]
{message}

[원래 질문]
{target_question}

[비판 대상 답변]
{target_answer}

위 답변을 비판적으로 검토해라.
정확성, 논리적 비약, 누락된 전제, 과장, 오해 가능성을 중심으로 평가해라."""

    if feedback_type == "support_answer":
        return f"""[사용자 요청]
{message}

[원래 질문]
{target_question}

[검토 대상 답변]
{target_answer}

위 답변이 타당한지 검토해라.
타당한 부분과 보완이 필요한 부분을 구분하고, 근거를 제시해라."""

    return f"""[사용자 요청]
{message}

[원래 질문]
{target_question}

[피드백 대상 답변]
{target_answer}

[참고 가능한 이전 답변 목록]
{_format_previous_answers(previous_answers)}

위 답변을 검토해라.
정확성, 논리성, 누락된 내용, 설명 수준, 개선 방향을 기준으로 피드백해라."""


def validate_feedback_output(feedback: str, feedback_type: str) -> dict:
    text = _clean_text(feedback)
    issues: list[str] = []
    score = 0.25

    has_evaluation = _contains_any(text, ["평가", "검토", "타당", "정확", "문제", "부족", "좋은 점", "한계"])
    has_improvement = _contains_any(text, ["개선", "보완", "추가", "수정", "더 나은", "제안", "예시"])
    has_reason = _contains_any(text, ["왜냐하면", "이유", "근거", "때문", "따라서", "즉"])
    separates_target = _contains_any(text, ["대상 답변", "원래 질문", "피드백", "검토 대상", "위 답변"])

    if has_evaluation:
        score += 0.25
    else:
        issues.append("평가 표현이 부족함")

    if has_improvement:
        score += 0.2
    else:
        issues.append("개선 방향이 부족함")

    if has_reason:
        score += 0.15
    else:
        issues.append("평가 이유 또는 근거가 부족함")

    if separates_target:
        score += 0.1
    else:
        issues.append("피드백 대상과 새 답변의 구분이 약함")

    if feedback_type == "compare_answers" and not _contains_any(text, ["비교", "장점", "단점", "더 나은", "가장"]):
        issues.append("비교 피드백 요소가 부족함")
        score -= 0.1

    score = max(0.0, min(1.0, score))
    return {
        "passed": score >= 0.75,
        "score": round(score, 2),
        "issues": issues,
        "has_evaluation": has_evaluation,
        "has_improvement": has_improvement,
        "has_reason": has_reason,
        "separates_target": separates_target,
    }


def revise_feedback_output(
    feedback: str,
    feedback_type: str,
    validation_result: dict,
    message: str,
    targets: dict,
    openai_client=None,
    model: str = "gpt-4o-mini",
) -> str:
    if openai_client is None:
        logger.warning("피드백 보정이 필요하지만 OpenAI client가 없어 원문 반환: %s", validation_result)
        return feedback

    prompt = f"""아래 피드백은 검증 기준을 충분히 만족하지 못했습니다.

[사용자 요청]
{message}

[피드백 유형]
{feedback_type}

[원래 질문]
{targets.get("target_question") or "전달되지 않음"}

[피드백 대상 답변]
{targets.get("target_answer") or "전달되지 않음"}

[이전 답변 목록]
{_format_previous_answers(targets.get("previous_answers") or [])}

[기존 피드백]
{feedback}

[검증 실패 사유]
{", ".join(validation_result.get("issues", []))}

기존 피드백의 핵심은 유지하되, 평가, 이유, 개선 방향, 필요 시 개선 예시를 분명히 포함해 다시 작성해라.
피드백 대상 답변과 새로 작성하는 개선안을 명확히 구분해라.
한국어로 답하고 마크다운 코드블록은 사용하지 마라."""

    try:
        response = openai_client.responses.create(model=model, input=prompt)
        output = getattr(response, "output_text", None)
        return output.strip() if output else feedback
    except Exception as exc:
        logger.warning("피드백 보정 실패: %s", exc)
        return feedback


def _feedback_type_rule(feedback_type: str) -> str:
    rules = {
        "answer_review": "답변의 정확성, 논리성, 누락 내용, 설명 수준, 개선 방향을 평가한다.",
        "question_review": "질문의 명확성, 범위, 난이도, 학습 목적 적합성, 개선안을 평가한다.",
        "compare_answers": "여러 답변의 장단점, 정확성, 깊이, 사용자 목적 적합성을 비교한다.",
        "improve_answer": "답변의 부족한 점을 짚고 더 나은 답변 구조와 예시를 제시한다.",
        "criticize_answer": "답변의 오류, 논리적 비약, 누락된 전제, 오해 가능성을 비판적으로 검토한다.",
        "support_answer": "답변의 타당한 부분과 보완할 부분을 근거 중심으로 구분한다.",
        "agent_opinion": "다른 에이전트의 답변에 대해 독립적인 의견과 보완점을 제시한다.",
        "unknown_feedback": "사용자가 원하는 피드백 대상을 명확히 확인하면서 가능한 범위에서 평가한다.",
    }
    return rules.get(feedback_type, rules["answer_review"])


def _normalize_previous_answers(items: Any) -> list[dict]:
    if not items:
        return []
    normalized = []
    for item in items:
        if hasattr(item, "model_dump"):
            raw = item.model_dump()
        elif hasattr(item, "dict"):
            raw = item.dict()
        elif isinstance(item, dict):
            raw = item
        else:
            continue
        answer = _clean_text(raw.get("answer") or raw.get("content") or "")
        if not answer:
            continue
        normalized.append(
            {
                "agent_id": raw.get("agent_id") or raw.get("agentId"),
                "agent_name": raw.get("agent_name") or raw.get("agentName") or raw.get("name") or "알 수 없는 에이전트",
                "role": raw.get("role") or "",
                "answer": answer,
            }
        )
    return normalized


def _format_previous_answers(previous_answers: list[dict]) -> str:
    if not previous_answers:
        return "전달되지 않음"
    lines = []
    for index, item in enumerate(previous_answers, start=1):
        lines.append(
            f"{index}. 에이전트: {item.get('agent_name') or '알 수 없음'}\n"
            f"역할: {item.get('role') or '전달되지 않음'}\n"
            f"답변: {item.get('answer') or ''}"
        )
    return "\n\n".join(lines)


def _matched_keywords(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword.lower() in text]


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_text(value: Any) -> str:
    return _clean_text(value).lower()
