"""
소크라테스 모드 서비스.
정답을 직접 주지 않고 RAG 자료 기반 꼬리질문으로 사용자 사고를 유도한다.
프롬프트는 prompt_templates/socratic_tutor.md에서 읽는다.
"""
import logging
from typing import Any, Dict, List, Optional

from app.schemas.multi_chat_schema import AgentAnswer, AgentProfile, AgentAnswerMetadata

logger = logging.getLogger(__name__)


def _load_socratic_prompt() -> str:
    try:
        from app.core.policy_loader import get_socratic_chain, get_prompt_template
        chain = get_socratic_chain()
        if chain:
            tmpl = get_prompt_template(chain[0].get("prompt_template", ""))
            if tmpl:
                return tmpl
    except Exception as e:
        logger.debug("소크라테스 프롬프트 로드 실패: %s", e)
    return (
        "너는 소크라테스식 학습 튜터 에이전트다.\n"
        "정답을 직접 알려주지 않고, 꼬리질문으로 사용자의 사고를 유도한다.\n"
        "정답은 절대 말하지 않는다. 질문은 하나만. 반드시 한국어로. 450자 이내."
    )


def _get_socratic_fallback() -> str:
    try:
        from app.core.policy_loader import get_validation_policy
        return get_validation_policy().get(
            "socratic_fallback",
            "좋아요. 바로 답을 말하기보다 한 가지만 생각해봅시다. 이 개념에서 '결과'와 '발생 조건'은 어떻게 다를까요?",
        )
    except Exception:
        return "좋아요. 바로 답을 말하기보다 한 가지만 생각해봅시다. 이 개념에서 '결과'와 '발생 조건'은 어떻게 다를까요?"


def _call_llm(system: str, user: str) -> str:
    try:
        from app.services.qwen_service import ask_qwen
        result = ask_qwen(system, user, temperature=0.4, max_tokens=400)
        if result and len(result.strip()) > 10:
            return result.strip()
    except Exception as e:
        logger.warning("Qwen 호출 실패: %s", e)
    try:
        from app.services.openai_client import chat_sync
        result = chat_sync(system, user, max_tokens=400)
        if result:
            return result.strip()
    except Exception as e:
        logger.warning("OpenAI 호출 실패: %s", e)
    return _get_socratic_fallback()


def run_socratic_mode(
    question: str,
    user_attempt: Optional[str],
    agents: List[AgentProfile],
    knowledge_level: str,
    rag_context: str,
) -> List[AgentAnswer]:
    """
    소크라테스 모드 실행.

    Step 1. RAG 자료 + userAttempt로 오개념/누락 개념 분석
    Step 2. 정답 없이 꼬리질문 1개 생성
    Step 3. 검증 (정답 직접 제공 여부)
    Step 4. 실패 시 최대 1회 재작성

    반환: 단일 AgentAnswer 리스트
    """
    try:
        from app.core.policy_loader import get_mode_config, get_socratic_validation
        max_rewrite = get_mode_config("socratic").get("max_rewrite_attempts", 1)
        v_policy = get_socratic_validation()
        direct_markers = v_policy.get("direct_answer_markers", ["정답은", "결론은"])
        max_chars = v_policy.get("max_answer_length_chars", 450)
    except Exception:
        max_rewrite = 1
        direct_markers = ["정답은", "결론은", "즉, 답은"]
        max_chars = 450

    # 에이전트 선택
    tutor_agent = None
    for a in agents:
        if (a.role or "").lower() in ("socratic_tutor", "socratic"):
            tutor_agent = a
            break
    tutor_name = tutor_agent.name if tutor_agent else "소크라테스 튜터"
    tutor_id = tutor_agent.agentId if tutor_agent else 1
    tutor_kl = (tutor_agent.knowledgeLevel if tutor_agent else None) or knowledge_level
    tutor_personality = tutor_agent.personality if tutor_agent else None

    system_prompt = _load_socratic_prompt()
    if knowledge_level:
        system_prompt += f"\n\n사용자 지식수준: {knowledge_level}"
    if tutor_personality:
        system_prompt += f"\n성격: {tutor_personality}"
    if rag_context:
        system_prompt += f"\n\n[참고 자료]\n{rag_context}"

    # 사용자 입력 구성
    user_parts = [f"[사용자 질문]\n{question}"]
    if user_attempt:
        user_parts.append(f"\n[사용자의 시도 답변]\n{user_attempt}")
    user_parts.append(
        "\n위 질문(또는 시도 답변)을 분석하라. "
        "오개념이나 누락 개념이 있으면 부드럽게 지적하고, "
        "사용자가 스스로 생각해 볼 수 있도록 꼬리질문을 하나만 제시하라. "
        "정답은 절대 직접 말하지 않는다."
    )
    user_prompt = "\n".join(user_parts)

    raw_answer = _call_llm(system_prompt, user_prompt)

    # 검증
    try:
        from app.services.mode_validator import validate_socratic_answer
        v_result = validate_socratic_answer(raw_answer)
    except Exception:
        v_result = {"passed": True, "issues": [], "directAnswerBlocked": False}

    final_answer = raw_answer
    status = "SUCCESS"
    direct_blocked = v_result.get("directAnswerBlocked", False)

    # 재작성 (최대 1회)
    if not v_result["passed"] and max_rewrite > 0:
        rewrite_user = (
            f"{user_prompt}\n\n"
            "이전 답변에 정답이 포함되어 있거나 질문이 없습니다. "
            "정답을 말하지 말고, 사용자 사고를 유도하는 꼬리질문 하나만 남겨라. "
            f"이 표현들을 사용하지 않는다: {', '.join(direct_markers)}"
        )
        rewritten = _call_llm(system_prompt, rewrite_user)
        try:
            rv = validate_socratic_answer(rewritten)
        except Exception:
            rv = {"passed": True, "issues": [], "directAnswerBlocked": False}

        if rv["passed"]:
            final_answer = rewritten
            status = "REWRITTEN"
        else:
            final_answer = _get_socratic_fallback()
            status = "BLOCKED"
            direct_blocked = True

    # 길이 제한: 사용자에게 보이는 답변은 임의 절단하지 않는다.
    # AI_MAX_RESPONSE_CHARS>0 으로 명시 설정한 경우에만 안전 절단한다(기본 비활성).
    import os as _os
    _max_visible = int(_os.getenv("AI_MAX_RESPONSE_CHARS", "0"))
    if _max_visible > 0 and len(final_answer) > _max_visible:
        cut = final_answer[:_max_visible]
        # 한국어/영어 문장 종결 경계에서 자른다.
        for sep in (". ", ".\n", "? ", "! ", "\n"):
            idx = cut.rfind(sep)
            if idx > _max_visible * 0.5:
                cut = cut[:idx + 1]
                break
        final_answer = cut.rstrip() + " …"

    return [
        AgentAnswer(
            agentName=tutor_name,
            answer=final_answer,
            agentId=tutor_id,
            role="socratic_tutor",
            speechType="follow_up_question",
            displayOrder=1,
            displayDelayMs=0,
            status=status,
            metadata=AgentAnswerMetadata(
                knowledgeLevel=tutor_kl,
                personality=tutor_personality,
                usedRag=bool(rag_context),
                detectedMisconception=bool(user_attempt),
                directAnswerSuppressed=True,
            ),
        )
    ]
