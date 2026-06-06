"""
토론 모드 서비스.
supporter → critic → moderator 순차 체인으로 답변을 생성한다.
이전 단계 답변이 다음 단계 프롬프트의 입력으로 주입된다.
프롬프트는 prompt_templates/*.md에서 읽는다.
"""
import logging
from typing import Any, Dict, List, Optional

from app.schemas.multi_chat_schema import AgentAnswer, AgentProfile, AgentAnswerMetadata

logger = logging.getLogger(__name__)

_ROLE_DISPLAY_ORDER = {"supporter": 1, "critic": 2, "moderator": 3}
_ROLE_SPEECH_TYPE = {
    "supporter": "support_argument",
    "critic": "counter_argument",
    "moderator": "moderation_summary",
}


def _load_role_prompt(role: str) -> str:
    """역할별 프롬프트 템플릿을 로드한다. 없으면 기본값 사용."""
    try:
        from app.core.policy_loader import get_debate_chain, get_prompt_template
        chain = get_debate_chain()
        for step in chain:
            if step.get("role") == role:
                tmpl = get_prompt_template(step.get("prompt_template", ""))
                if tmpl:
                    return tmpl
    except Exception as e:
        logger.debug("프롬프트 로드 실패, 기본값 사용: %s", e)
    # 내장 기본 프롬프트
    defaults = {
        "supporter": (
            "너는 학습 토론 에이전트 [찬성/지지자] 역할이다.\n"
            "주제의 장점과 옹호 근거를 논리적으로 제시한다.\n"
            "인신공격 금지. 반드시 한국어로. 300자 내외."
        ),
        "critic": (
            "너는 학습 토론 에이전트 [반대/비판자] 역할이다.\n"
            "찬성 주장의 맹점·한계·반례를 논리적으로 지적한다.\n"
            "인신공격 금지. 반드시 한국어로. 300자 내외."
        ),
        "moderator": (
            "너는 학습 토론 에이전트 [사회자/정리자] 역할이다.\n"
            "찬성·반대를 균형 있게 요약하고, 사용자에게 생각을 묻는 질문 1개를 포함한다.\n"
            "반드시 한국어로. 350자 내외."
        ),
    }
    return defaults.get(role, f"너는 토론 {role} 에이전트다. 반드시 한국어로 답변하라.")


def _call_llm(system: str, user: str) -> str:
    """Ollama(Qwen) 우선 → OpenAI fallback."""
    try:
        from app.services.qwen_service import ask_qwen
        result = ask_qwen(system, user, temperature=0.4, max_tokens=500)
        if result and len(result.strip()) > 10:
            return result.strip()
    except Exception as e:
        logger.warning("Qwen 호출 실패: %s", e)
    try:
        from app.services.openai_client import chat_sync
        result = chat_sync(system, user, max_tokens=500)
        if result:
            return result.strip()
    except Exception as e:
        logger.warning("OpenAI 호출 실패: %s", e)
    return "일시적인 오류로 답변을 생성할 수 없습니다."


def _find_agent_by_role(agents: List[AgentProfile], role: str) -> Optional[AgentProfile]:
    """role이 일치하는 에이전트를 반환한다. 없으면 None."""
    for a in agents:
        if (a.role or "").lower() == role.lower():
            return a
    return None


def _build_agent_context(
    agent: Optional[AgentProfile],
    role: str,
    knowledge_level: str,
    rag_context: str,
) -> str:
    """에이전트 설정 + RAG 컨텍스트를 시스템 프롬프트에 합성한다."""
    role_prompt = _load_role_prompt(role)
    level_hint = f"사용자 지식수준: {knowledge_level}" if knowledge_level else ""
    personality_hint = ""
    if agent and agent.personality:
        personality_hint = f"성격: {agent.personality}"
    rag_block = f"\n\n[참고 자료]\n{rag_context}" if rag_context else ""

    parts = [role_prompt]
    if level_hint:
        parts.append(level_hint)
    if personality_hint:
        parts.append(personality_hint)
    parts.append(rag_block)
    return "\n".join(p for p in parts if p)


def run_debate_mode(
    question: str,
    agents: List[AgentProfile],
    knowledge_level: str,
    rag_context: str,
    delay_ms: int,
) -> List[AgentAnswer]:
    """
    토론 모드 순차 체인 실행.

    Step 1. supporter: 옹호 근거 제시 (RAG 활용)
    Step 2. critic: supporter 답변 + 반론 생성
    Step 3. moderator: supporter + critic 요약 + 사용자 질문

    반환: AgentAnswer 리스트 (displayOrder 포함)
    """
    try:
        from app.core.policy_loader import get_mode_config
        max_rewrite = get_mode_config("debate").get("max_rewrite_attempts", 1)
    except Exception:
        max_rewrite = 1

    answers: List[AgentAnswer] = []
    supporter_answer = ""
    critic_answer = ""

    # ── Step 1: supporter ────────────────────────────────────────────────
    sup_agent = _find_agent_by_role(agents, "supporter")
    sup_name = sup_agent.name if sup_agent else "찬성봇"
    sup_id = sup_agent.agentId if sup_agent else 1
    sup_kl = (sup_agent.knowledgeLevel if sup_agent else None) or knowledge_level

    system_sup = _build_agent_context(sup_agent, "supporter", sup_kl, rag_context)
    user_sup = f"[토론 주제/질문]\n{question}\n\n위 주제에 대한 긍정적 관점과 옹호 근거를 제시하라."

    try:
        supporter_answer = _call_llm(system_sup, user_sup)
        sup_ans = AgentAnswer(
            agentName=sup_name,
            answer=supporter_answer,
            agentId=sup_id,
            role="supporter",
            speechType="support_argument",
            displayOrder=1,
            displayDelayMs=0,
            status="SUCCESS",
            metadata=AgentAnswerMetadata(
                knowledgeLevel=sup_kl,
                personality=sup_agent.personality if sup_agent else None,
                usedRag=bool(rag_context),
            ),
        )
    except Exception as e:
        logger.error("supporter 답변 실패: %s", e)
        sup_ans = AgentAnswer(
            agentName=sup_name, answer="찬성 입장을 생성하지 못했습니다.",
            agentId=sup_id, role="supporter", speechType="support_argument",
            displayOrder=1, displayDelayMs=0, status="FAILED",
        )
    answers.append(sup_ans)

    # 검증 + 재작성 (최대 1회)
    if sup_ans.status == "SUCCESS":
        try:
            from app.services.mode_validator import validate_debate_answers
            v = validate_debate_answers([a.model_dump() for a in answers])
            if not v["passed"] and max_rewrite > 0:
                rewrite_user = (
                    f"{user_sup}\n\n"
                    "이전 답변에 옹호 근거가 부족합니다. "
                    "장점·이점·효과를 포함하여 다시 작성하라."
                )
                rewritten = _call_llm(system_sup, rewrite_user)
                if rewritten:
                    answers[-1] = sup_ans.model_copy(
                        update={"answer": rewritten, "status": "REWRITTEN"}
                    )
                    supporter_answer = rewritten
        except Exception:
            pass

    # ── Step 2: critic ────────────────────────────────────────────────────
    crit_agent = _find_agent_by_role(agents, "critic")
    crit_name = crit_agent.name if crit_agent else "반대봇"
    crit_id = crit_agent.agentId if crit_agent else 2
    crit_kl = (crit_agent.knowledgeLevel if crit_agent else None) or knowledge_level

    system_crit = _build_agent_context(crit_agent, "critic", crit_kl, rag_context)
    user_crit = (
        f"[토론 주제/질문]\n{question}\n\n"
        f"[찬성 측 주장]\n{supporter_answer}\n\n"
        "위 찬성 주장의 맹점·한계·반례를 논리적으로 지적하고, 개선 방향을 제시하라. "
        "인신공격 없이 논리와 근거 중심으로."
    )

    try:
        raw_critic = _call_llm(system_crit, user_crit)

        # 비방 검증
        try:
            from app.services.constructive_feedback_rewriter import process_feedback
            fb_result = process_feedback(raw_critic)
            critic_answer = fb_result.finalFeedback
            crit_status = "REWRITTEN" if fb_result.wasRewritten else "SUCCESS"
            if fb_result.wasBlocked:
                crit_status = "BLOCKED"
        except Exception:
            critic_answer = raw_critic
            crit_status = "SUCCESS"

        crit_ans = AgentAnswer(
            agentName=crit_name,
            answer=critic_answer,
            agentId=crit_id,
            role="critic",
            speechType="counter_argument",
            displayOrder=2,
            displayDelayMs=delay_ms,
            status=crit_status,
            metadata=AgentAnswerMetadata(
                knowledgeLevel=crit_kl,
                personality=crit_agent.personality if crit_agent else None,
                usedRag=bool(rag_context),
            ),
        )
    except Exception as e:
        logger.error("critic 답변 실패: %s", e)
        try:
            from app.core.policy_loader import get_safe_fallback
            fallback = get_safe_fallback()
        except Exception:
            fallback = "반대 입장을 생성하지 못했습니다."
        crit_ans = AgentAnswer(
            agentName=crit_name, answer=fallback,
            agentId=crit_id, role="critic", speechType="counter_argument",
            displayOrder=2, displayDelayMs=delay_ms, status="FAILED",
        )
        critic_answer = fallback
    answers.append(crit_ans)

    # ── Step 3: moderator ────────────────────────────────────────────────
    mod_agent = _find_agent_by_role(agents, "moderator")
    mod_name = mod_agent.name if mod_agent else "사회자봇"
    mod_id = mod_agent.agentId if mod_agent else 3
    mod_kl = (mod_agent.knowledgeLevel if mod_agent else None) or knowledge_level

    system_mod = _build_agent_context(mod_agent, "moderator", mod_kl, "")
    user_mod = (
        f"[토론 주제/질문]\n{question}\n\n"
        f"[찬성 측 주장]\n{supporter_answer}\n\n"
        f"[반대 측 주장]\n{critic_answer}\n\n"
        "두 주장을 균형 있게 요약하고, 마지막에 사용자의 사고를 유도하는 질문을 1개 포함하라."
    )

    try:
        mod_answer = _call_llm(system_mod, user_mod)
        mod_ans = AgentAnswer(
            agentName=mod_name,
            answer=mod_answer,
            agentId=mod_id,
            role="moderator",
            speechType="moderation_summary",
            displayOrder=3,
            displayDelayMs=delay_ms * 2,
            status="SUCCESS",
            metadata=AgentAnswerMetadata(
                knowledgeLevel=mod_kl,
                personality=mod_agent.personality if mod_agent else None,
                usedRag=False,
            ),
        )
    except Exception as e:
        logger.error("moderator 답변 실패: %s", e)
        mod_ans = AgentAnswer(
            agentName=mod_name,
            answer="현재 토론 답변을 안정적으로 생성하지 못했습니다. 주제를 조금 더 구체화하면 찬성·반대·정리 관점으로 다시 구성할 수 있습니다.",
            agentId=mod_id, role="moderator", speechType="moderation_summary",
            displayOrder=3, displayDelayMs=delay_ms * 2, status="FAILED",
        )
    answers.append(mod_ans)

    return answers
