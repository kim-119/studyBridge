"""
자료보관함 AI 매니저 (GPT 70% + Qwen 30% 혼합 구조).
PDF 요약, 문서 분석, 퀴즈 생성, 로드맵 생성, RAG Q&A를 처리한다.

혼합 전략:
  GPT:  구조적 분석, 정확성, 퀴즈/로드맵/요약 본문 생성 (70%)
  Qwen: 에이전트 말투/성격 반영, 사용자 친화적 표현 보정 (30%)
"""
import logging
from typing import Optional

from app.core.config import OPENAI_API_KEY
from app.services.qwen_service import ask_qwen

logger = logging.getLogger(__name__)

_sync_client = None


def _get_gpt_client():
    global _sync_client
    if _sync_client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
        from openai import OpenAI
        _sync_client = OpenAI(api_key=OPENAI_API_KEY)
    return _sync_client


def _call_gpt(system: str, user: str, max_tokens: int = 1200) -> str:
    """GPT-4o-mini 동기 호출 (자료보관함 메인 처리)."""
    if not OPENAI_API_KEY:
        return "[GPT 미설정] OPENAI_API_KEY를 .env에 추가하세요."
    try:
        client = _get_gpt_client()
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        logger.error("GPT 호출 실패: %s", e)
        return f"[GPT 오류] {type(e).__name__}: {e}"


def _apply_qwen_tone(
    gpt_answer: str,
    personality: str,
    agent_name: str,
) -> str:
    """Qwen으로 GPT 답변에 에이전트 말투를 입힌다 (30% 역할)."""
    from app.services.personality_prompt_builder import build_personality_prompt
    personality_instr = build_personality_prompt(personality)
    system = (
        f"너는 StudyBridge 에이전트 '{agent_name}'이다.\n"
        f"{personality_instr}\n"
        "주어진 내용을 위 말투에 맞게 자연스럽게 다듬어라. "
        "핵심 내용은 변경하지 마라. 반드시 한국어로 출력하라."
    )
    user = (
        f"다음 내용을 '{agent_name}'의 말투로 자연스럽게 다듬어라:\n\n{gpt_answer}"
    )
    try:
        return ask_qwen(system_prompt=system, user_prompt=user, max_tokens=1200)
    except Exception as e:
        logger.warning("Qwen 말투 보정 실패, GPT 원본 반환: %s", e)
        return gpt_answer


# ── PDF RAG Q&A ─────────────────────────────────────────────────────────────

def answer_from_pdf(
    question: str,
    rag_chunks: list[dict],
    personality: str = "친절_설명형",
    agent_name: str = "자료봇",
    knowledge_level: str = "학사",
) -> dict:
    """
    PDF 청크 기반 Q&A.
    GPT가 구조적 답변 → Qwen이 말투 보정.

    Returns:
        {"answer": str, "sources": list[dict], "gpt_raw": str}
    """
    if not rag_chunks:
        return {
            "answer": "관련 PDF 자료를 찾지 못했습니다. 자료를 업로드하셨는지 확인해 주세요.",
            "sources": [],
            "gpt_raw": "",
        }

    context = "\n".join(
        f"[청크 {c.get('chunk_index',0)}] {c.get('content','')}" for c in rag_chunks
    )
    from app.services.knowledge_level_controller import get_level_instruction
    level_instr = get_level_instruction(knowledge_level)

    gpt_system = (
        "너는 PDF 문서 기반 Q&A 전문가다.\n"
        f"{level_instr}\n"
        "PDF_CONTEXT에 없는 내용은 단정하지 말고 '자료에 없는 내용'이라고 명시한다. "
        "답변은 한국어로 작성한다."
    )
    gpt_user = (
        f"## PDF_CONTEXT\n{context}\n\n"
        f"## 질문\n{question}\n\n"
        "위 자료를 근거로 정확하고 구조적으로 답변하라."
    )
    gpt_raw = _call_gpt(gpt_system, gpt_user)
    final_answer = _apply_qwen_tone(gpt_raw, personality, agent_name)
    return {
        "answer":  final_answer,
        "sources": rag_chunks,
        "gpt_raw": gpt_raw,
    }


# ── PDF 요약 ─────────────────────────────────────────────────────────────────

def summarize_document(
    document_title: str,
    text: str,
    personality: str = "간결_요약형",
    agent_name: str = "요약봇",
) -> dict:
    """
    PDF 전체 텍스트를 요약한다 (GPT 중심, Qwen 말투 보정).

    Returns:
        {"summary": str, "key_points": list[str], "gpt_raw": str}
    """
    gpt_system = (
        "너는 학술 문서 요약 전문가다. "
        "문서를 읽고 핵심 내용을 구조화하여 정리한다. "
        "한국어로 작성한다."
    )
    gpt_user = (
        f"## 문서 제목\n{document_title}\n\n"
        f"## 문서 내용 (최대 3000자)\n{text[:3000]}\n\n"
        "아래 형식으로 요약하라:\n"
        "### 핵심 요약 (3~5줄)\n"
        "### 주요 개념 목록 (불릿 3~7개)\n"
        "### 학습 포인트 (2~3줄)"
    )
    gpt_raw = _call_gpt(gpt_system, gpt_user)
    final = _apply_qwen_tone(gpt_raw, personality, agent_name)

    # key_points 간단 추출
    key_points = [
        line.strip().lstrip("-•").strip()
        for line in gpt_raw.splitlines()
        if line.strip().startswith(("-", "•", "*")) and len(line.strip()) > 5
    ]

    return {
        "summary":    final,
        "key_points": key_points[:7],
        "gpt_raw":    gpt_raw,
    }


# ── 퀴즈 생성 ────────────────────────────────────────────────────────────────

def generate_quiz(
    document_title: str,
    context: str,
    num_questions: int = 5,
    knowledge_level: str = "학사",
) -> dict:
    """
    PDF 내용 기반 퀴즈를 생성한다 (GPT 전담).

    Returns:
        {"quiz": str, "question_count": int}
    """
    from app.services.knowledge_level_controller import get_level_instruction
    level_instr = get_level_instruction(knowledge_level)

    gpt_system = (
        "너는 교육용 퀴즈 출제 전문가다. "
        f"{level_instr} "
        "사지선다형 객관식 문제를 출제하고, 정답과 해설을 포함한다. "
        "한국어로 작성한다."
    )
    gpt_user = (
        f"## 문서: {document_title}\n\n"
        f"## 내용 (최대 2000자)\n{context[:2000]}\n\n"
        f"위 내용을 바탕으로 {num_questions}개 사지선다 문제를 출제하라.\n"
        "형식:\nQ1. [문제]\n① ... ② ... ③ ... ④ ...\n정답: ③\n해설: ..."
    )
    quiz_text = _call_gpt(gpt_system, gpt_user, max_tokens=1500)
    actual_count = quiz_text.count("Q") if quiz_text else 0
    return {
        "quiz":           quiz_text,
        "question_count": min(actual_count, num_questions),
    }


# ── 학습 로드맵 생성 ──────────────────────────────────────────────────────────

def generate_roadmap(
    document_title: str,
    context: str,
    knowledge_level: str = "학사",
) -> dict:
    """
    문서 기반 학습 로드맵을 생성한다 (GPT 전담).

    Returns:
        {"roadmap": str}
    """
    from app.services.knowledge_level_controller import get_level_instruction
    level_instr = get_level_instruction(knowledge_level)

    gpt_system = (
        "너는 학습 커리큘럼 설계 전문가다. "
        f"{level_instr} "
        "문서 내용을 분석해 단계적 학습 로드맵을 설계한다. "
        "한국어로 작성한다."
    )
    gpt_user = (
        f"## 문서: {document_title}\n\n"
        f"## 내용 (최대 2000자)\n{context[:2000]}\n\n"
        "이 문서를 효과적으로 학습하기 위한 단계별 로드맵을 설계하라.\n"
        "형식:\n## 학습 목표\n## 선수 지식\n## 단계별 학습 계획 (1주차~)\n## 심화 학습 방향"
    )
    roadmap_text = _call_gpt(gpt_system, gpt_user, max_tokens=1200)
    return {"roadmap": roadmap_text}
