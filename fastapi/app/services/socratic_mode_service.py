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
            "> [DIAGNOSTIC_LOG]\nLog: 현재 접근 방식에 혼선이 있음.\n\n> [CONCEPT_HINT]\nHint: 이 개념은 '결과'와 '발생 조건'을 구분하는 것이 핵심이다.\n\n> [PROMPT]\n두 가지의 차이점이 무엇일지 논리적으로 도출해 보겠나?",
        )
    except Exception:
        return "> [DIAGNOSTIC_LOG]\nLog: 현재 접근 방식에 혼선이 있음.\n\n> [CONCEPT_HINT]\nHint: 이 개념은 '결과'와 '발생 조건'을 구분하는 것이 핵심이다.\n\n> [PROMPT]\n두 가지의 차이점이 무엇일지 논리적으로 도출해 보겠나?"


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
        direct_markers = ["정답은", "결론은", "결론부터", "즉, 답은", "정리하자면", "요약하자면"]
        max_chars = 350

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
    # 성격은 '질문 방식'으로만 반영한다(정답 제공 금지는 모든 성격 공통).
    if tutor_personality:
        try:
            from app.services.personality_prompt_builder import get_socratic_style, get_profile
            style = get_socratic_style(tutor_personality)
            disp = get_profile(tutor_personality).get("displayName") or tutor_personality
            system_prompt += f"\n\n[에이전트 성격: {disp}] 질문 방식: {style}"
        except Exception:
            system_prompt += f"\n성격: {tutor_personality} (정답은 주지 말고 질문으로만 유도)"
    if rag_context:
        system_prompt += (
            f"\n\n[참고 자료(PDF/RAG) — 판단 기준]\n{rag_context}\n"
            "위 자료를 기준으로 사용자의 답이 맞는지 비교하라. 자료에 없는 내용을 확정적으로 말하지 마라. "
            "자료와 사용자 답이 충돌하면 정답을 주지 말고 충돌 지점을 질문으로 유도하라."
        )
    else:
        system_prompt += "\n\n참고 자료가 없으니, 일반 개념 수준에서 판단하되 정답을 단정하지 말고 질문으로 유도하라."

    # 사용자 입력 구성 — 시도 답변 유무에 따라 진단/칭찬/좁히기 방향을 안내한다.
    user_parts = [f"[사용자 질문]\n{question}"]
    if user_attempt:
        user_parts.append(f"\n[사용자의 시도 답변]\n{user_attempt}")
        user_parts.append(
            "\n위 시도 답변을 자료 기준으로 디버깅하라. "
            "맞게 접근했으면 맞춘 부분을 인정하고 한 단계 더 깊은 원리를 짚어준 뒤 질문하고, "
            "틀렸으면 충돌 지점을 명시하고 올바른 방향의 키워드를 힌트로 준 뒤 재고를 요청하라."
        )
    else:
        user_parts.append(
            "\n사용자가 아직 시도 답변을 내지 않았다. 정답을 덤프하지 말고, "
            "사용자가 첫걸음을 뗄 수 있도록 핵심 개념 힌트를 준 뒤 이지선다 형태나 기초적인 꼬리질문을 제시하라."
        )
    user_parts.append(
        "\n반드시 > [DIAGNOSTIC_LOG] / > [CONCEPT_HINT] / > [PROMPT] 세 블록 형식으로만, 짧고 명확하게 답하라. "
        "PROMPT에는 딱 하나(물음표 하나)의 질문만 포함한다. 정답·결론·완성답안·개념강의 전체 제공은 절대 금지."
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
            "이전 답변에 정답·강의가 포함되었거나 형식/질문 수가 어긋났습니다. "
            "반드시 > [DIAGNOSTIC_LOG] / > [CONCEPT_HINT] / > [PROMPT] 세 블록으로만, 정답 전체를 말하지 말고 "
            "사용자 사고를 유도하는 꼬리질문 하나(물음표 하나)만 PROMPT에 남겨라. "
            f"이 표현들을 절대 사용하지 않는다: {', '.join(direct_markers)}"
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
