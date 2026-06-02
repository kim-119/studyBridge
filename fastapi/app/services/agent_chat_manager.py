"""
AI 에이전트 채팅 오케스트레이터.
성격/지식수준 프롬프트 빌드 → RAG 검색 → Qwen 1차 답변 → 티키타카(선택)
까지의 흐름을 조율한다.

검증(GPT verify)은 이 모듈에서 실행하지 않는다.
라우터가 background task로 gpt_verifier를 별도 실행한다.
"""
import logging
from typing import Optional

from app.services.knowledge_level_controller import get_level_instruction
from app.services.personality_prompt_builder import build_personality_prompt
from app.services.qwen_service import ask_qwen
from app.services.tiki_taka_manager import run_tiki_taka, TikiTakaTurn

logger = logging.getLogger(__name__)

# 에이전트 채팅 시스템 프롬프트 뼈대
_BASE_SYSTEM = """\
너는 StudyBridge의 AI 학습 에이전트 '{agent_name}'이다.

{level_instruction}

{personality_instruction}

공통 규칙:
- 반드시 한국어로 답변한다.
- PDF 자료(PDF_RAG_CONTEXT)가 있으면 최우선 근거로 사용한다.
- 자료에 없는 내용은 단정하지 말고, 추정임을 명시한다.
- 답변 마지막에 '참고 자료 출처'를 간단히 포함한다.
"""


def _build_system_prompt(
    agent_name: str,
    knowledge_level: str,
    personality: str,
    custom_instruction: Optional[str] = None,
) -> str:
    level_instr = get_level_instruction(knowledge_level)
    personality_instr = build_personality_prompt(personality, custom_instruction)
    return _BASE_SYSTEM.format(
        agent_name=agent_name,
        level_instruction=level_instr,
        personality_instruction=personality_instr,
    )


def _build_user_prompt(question: str, rag_context: str) -> str:
    if rag_context:
        return (
            f"## 수집된 자료\n{rag_context}\n\n"
            f"## 사용자 질문\n{question}"
        )
    return f"## 사용자 질문\n{question}"


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
          "answer": str,                 # Qwen 1차 답변
          "tiki_taka_dialogue": list,    # TikiTakaTurn 직렬화 목록 (비활성 시 [])
          "process_logs": list[str],
          "knowledge_level": str,
          "personality": str,
        }
    """
    logs: list[str] = []

    # ── RAG 컨텍스트 수집 (optional) ─────────────────────────────────
    rag_context = ""
    if material_id is not None:
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
        except Exception as e:
            logs.append(f"RAG 검색 실패 (계속 진행): {e}")

    # ── 시스템/사용자 프롬프트 조립 ──────────────────────────────────
    system_prompt = _build_system_prompt(
        agent_name=agent_name,
        knowledge_level=knowledge_level,
        personality=personality,
        custom_instruction=custom_instruction,
    )
    user_prompt = _build_user_prompt(question, rag_context)
    logs.append("프롬프트를 조립했습니다.")

    # ── Qwen 1차 답변 생성 ────────────────────────────────────────────
    answer = ask_qwen(system_prompt=system_prompt, user_prompt=user_prompt)
    logs.append("Qwen 1차 답변을 생성했습니다.")

    # ── 티키타카 (선택) ───────────────────────────────────────────────
    tiki_taka_serialized: list[dict] = []
    if enable_tiki_taka:
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
        "answer":             answer,
        "tiki_taka_dialogue": tiki_taka_serialized,
        "process_logs":       logs,
        "knowledge_level":    knowledge_level,
        "personality":        personality,
    }
