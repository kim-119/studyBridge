"""
AI 에이전트 채팅 오케스트레이터.
성격/지식수준 프롬프트 빌드 → 의도 분류 → RAG 검색 → Qwen 1차 답변 → 티키타카(선택)
까지의 흐름을 조율한다.

검증(GPT verify)은 이 모듈에서 실행하지 않는다.
라우터가 background task로 gpt_verifier를 별도 실행한다.
"""
import logging
from typing import Optional

from app.services.knowledge_level_controller import get_level_instruction
from app.services.personality_prompt_builder import build_personality_prompt
from app.services.message_intent_classifier import classify_message_intent
from app.services.llm_engine_router import call_primary_llm
from app.services.tiki_taka_manager import run_tiki_taka, TikiTakaTurn

logger = logging.getLogger(__name__)

# 학습 질문용 시스템 프롬프트 뼈대
_BASE_SYSTEM = """\
너는 StudyBridge의 AI 학습 에이전트 '{agent_name}'이다.

{level_instruction}

{personality_instruction}

공통 규칙:
- 반드시 한국어로 답변한다.
- PDF 자료(PDF_RAG_CONTEXT)가 있으면 최우선 근거로 사용한다.
- 자료에 없는 내용은 단정하지 말고, 추정임을 명시한다.
- 답변 마지막에 '참고 자료 출처'를 간단히 포함한다.
- ★ [절대 규칙] 사용자가 개념 질문이 아니라 불만 표현("이상해", "뭐라는거야"), 버그 리포트, 일상 대화를 할 때는 억지로 '개념 정의'나 '원리 분석'을 하지 마라. '답변 구성(정의/예시 등)'과 '지식수준'을 무시하고, 오직 너의 '성격/말투'만 유지한 채 사람처럼 자연스럽게 대화하고 공감/안내하라.

# 일상 대화용 시스템 프롬프트 뼈대 (짧고 자연스럽게)
_CASUAL_SYSTEM = """\
너는 StudyBridge의 AI 학습 에이전트 '{agent_name}'이다.
지금은 가벼운 대화 상황이다. 짧고 자연스럽게 응답하라.
전공 지식 설명, 이론, 전문 용어를 불필요하게 붙이지 않는다.
반드시 한국어로 답변한다.
"""


def _build_system_prompt(
    agent_name: str,
    effective_knowledge_level: str,
    personality: str,
    custom_instruction: Optional[str] = None,
    is_casual: bool = False,
) -> str:
    if is_casual:
        return _CASUAL_SYSTEM.format(agent_name=agent_name)
    level_instr = get_level_instruction(effective_knowledge_level)
    personality_instr = build_personality_prompt(personality, custom_instruction)
    return _BASE_SYSTEM.format(
        agent_name=agent_name,
        level_instruction=level_instr,
        personality_instruction=personality_instr,
    )


def _build_user_prompt(question: str, rag_context: str, personality: str, custom_instruction: Optional[str] = None) -> str:
    from app.services.personality_prompt_builder import build_persona_directive
    persona_reminder = build_persona_directive(personality, custom_instruction)
    
    parts = []
    if rag_context:
        parts.append(f"## 수집된 자료\n{rag_context}")
    parts.append(f"## 사용자 질문\n{question}")
    parts.append(f"\n{persona_reminder}")
    
    return "\n\n".join(parts)


def run_agent_chat(
    question: str,
    knowledge_level: str = "학사",
    personality: str = "친절_설명형",
    agent_name: str = "자바도우미",
    custom_instruction: Optional[str] = None,
    material_id: Optional[int] = None,
    enable_tiki_taka: bool = False,
    enable_round2: bool = False,
) -> dict:
    """
    에이전트 채팅 파이프라인 전체를 실행한다.

    Returns:
        {
          "answer": str,
          "tiki_taka_dialogue": list,
          "process_logs": list[str],
          "knowledge_level": str,          # 사용자가 선택한 원본 지식수준
          "personality": str,
          "requested_knowledge_level": str,
          "effective_knowledge_level": str, # 실제 적용된 지식수준
          "intent": str,
        }
    """
    logs: list[str] = []

    # ── 메시지 의도 분류 (Tiki-Taka 및 RAG 스킵 용도) ────────────────────────
    intent_result = classify_message_intent(question, knowledge_level)
    # 지식수준 족쇄는 풀고 사용자가 선택한 수준을 강제 적용 (성격 유지)
    effective_level = knowledge_level
    is_casual = intent_result.is_casual_message
    logs.append(
        f"의도 분류: {intent_result.intent} | is_casual={is_casual} (TikiTaka 스킵용)"
    )

    # ── RAG 컨텍스트 수집 (학습 질문이고 material_id 있을 때만) ──────
    rag_context = ""
    if not is_casual and material_id is not None:
        try:
            from app.services.pdf_rag_service import search_pdf_context
            pdf_chunks = search_pdf_context(question, material_id)
            if pdf_chunks:
                parts = ["[PDF_RAG_CONTEXT]"]
                for c in pdf_chunks:
                    parts.append(
                        f"- {c.get('document_title','')} (chunk {c.get('chunk_index',0)}, "
                        f"score={c.get('similarity',0):.3f})\n  {c.get('content','')}"
                    )
                rag_context = "\n".join(parts)
                logs.append(f"PDF 자료에서 {len(pdf_chunks)}개 청크를 검색했습니다.")
            else:
                logs.append("RAG 검색 결과 없음 — 일반 지식 기반으로 답변합니다.")
        except Exception as e:
            logs.append(f"RAG 검색 실패 (계속 진행): {e}")

    # ── 시스템/사용자 프롬프트 조립 ──────────────────────────────────
    system_prompt = _build_system_prompt(
        agent_name=agent_name,
        effective_knowledge_level=effective_level,
        personality=personality,
        custom_instruction=custom_instruction,
        is_casual=False,  # 성격을 무조건 적용하기 위해 항상 False
    )
    user_prompt = _build_user_prompt(question, rag_context, personality, custom_instruction)
    logs.append("프롬프트를 조립했습니다.")

    # ── LLM 1차 답변 생성 (Ollama → OpenAI fallback) ────────────────
    answer = call_primary_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        knowledge_level=effective_level if not is_casual else None,
    )
    logs.append("LLM 1차 답변을 생성했습니다.")

    # ── 티키타카 (선택, 일상대화이면 skip) ───────────────────────────
    tiki_taka_serialized: list[dict] = []
    if enable_tiki_taka and not is_casual:
        try:
            turns: list[TikiTakaTurn] = run_tiki_taka(
                question=question,
                agent_a_answer=answer,
                agent_a_name=agent_name,
                agent_b_name=f"{agent_name}B",
                agent_c_name=f"{agent_name}C",
                moderator_name="정리",
                enable_round2=enable_round2,
            )
            tiki_taka_serialized = [
                {
                    "agent_name":       t.agent_name,
                    "role_description": t.role_description,
                    "content":          t.content,
                }
                for t in turns
            ]
            logs.append(f"티키타카 대화 생성 완료 ({len(turns)} 발화).")
        except Exception as e:
            logs.append(f"티키타카 생성 실패 (계속 진행): {e}")

    return {
        "answer":                     answer,
        "tiki_taka_dialogue":         tiki_taka_serialized,
        "process_logs":               logs,
        "knowledge_level":            knowledge_level,   # 원본 선택값
        "personality":                personality,
        "requested_knowledge_level":  knowledge_level,
        "effective_knowledge_level":  effective_level,
        "intent":                     "direct_chat",
    }
