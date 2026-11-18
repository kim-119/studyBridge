"""
Deep Search 파이프라인 오케스트레이터.
질문 분류 → 자료 수집 → 컨텍스트 통합 → Qwen2.5 답변 생성의 전체 흐름을 조율한다.
"""
from typing import Optional

from app.services.query_classifier import classify_question
from app.services.pdf_rag_service import search_pdf_context
from app.services.tavily_service import search_web
from app.services.wikipedia_service import search_wikipedia
from app.services.qwen_service import ask_qwen
from app.core.prompts import DEEP_SEARCH_SYSTEM_PROMPT, DEEP_SEARCH_USER_PROMPT_TEMPLATE


def _build_context(
    pdf_results: list[dict],
    tavily_results: list[dict],
    wiki_results: list[dict],
) -> str:
    """수집된 자료들을 하나의 컨텍스트 문자열로 통합한다."""
    parts = []

    # PDF RAG 결과: Qwen이 출처를 구분할 수 있도록 상세 메타데이터 포함
    if pdf_results:
        parts.append("[PDF_RAG_CONTEXT]")
        for r in pdf_results:
            parts.append(
                f"- material_id: {r.get('material_id', 'N/A')}\n"
                f"  document_title: {r.get('document_title', '')}\n"
                f"  chunk_index: {r.get('chunk_index', -1)}\n"
                f"  similarity: {r.get('similarity', 0.0)}\n"
                f"  content: {r.get('content', '')}"
            )

    if tavily_results:
        parts.append("\n[TAVILY_WEB_CONTEXT]")
        for i, r in enumerate(tavily_results, 1):
            title   = r.get("title", "")
            url     = r.get("url", "")
            content = r.get("content", "")
            parts.append(f"{i}. [{title}]({url})\n   {content}")

    if wiki_results:
        parts.append("\n[WIKIPEDIA_CONTEXT]")
        for i, r in enumerate(wiki_results, 1):
            title   = r.get("title", "")
            snippet = r.get("snippet", "")
            url     = r.get("url", "")
            parts.append(f"{i}. [{title}]({url})\n   {snippet}")

    if not parts:
        return "수집된 자료가 없습니다. 일반 지식으로 답변해 주세요."

    return "\n".join(parts)


def run_deep_search_pipeline(
    question: str,
    material_id: Optional[int] = None,
) -> dict:
    """
    Deep Search 파이프라인 전체를 실행하고 결과를 반환한다.

    처리 순서:
      1. 질문 유형 분류
      2. PDF RAG 검색 (use_pdf=True 일 때)
      3. Tavily 웹 검색 (use_tavily=True 일 때)
      4. Wikipedia 검색 (use_wikipedia=True 일 때)
      5. 컨텍스트 통합
      6. Qwen2.5 1차 답변 생성
      7. 결과 반환

    Args:
        question:    사용자 질문
        material_id: PDF 자료 ID (없으면 PDF 검색 생략)

    Returns:
        {
            "answer": str,
            "route": dict,
            "sources": {"pdf": list, "tavily": list, "wikipedia": list},
            "process_logs": list[str],
        }
    """
    logs: list[str] = []
    sources: dict = {"pdf": [], "tavily": [], "wikipedia": []}

    # ── 1. 질문 유형 분류 ──────────────────────────────────────────────
    route = classify_question(question)
    logs.append(f"질문 유형을 분석했습니다. ({route['reason']})")

    # ── 2. PDF RAG 검색 ───────────────────────────────────────────────
    if route["use_pdf"]:
        try:
            pdf_results = search_pdf_context(question, material_id)
            sources["pdf"] = pdf_results
            logs.append(
                f"PDF 자료에서 관련 내용을 검색했습니다. ({len(pdf_results)}개 청크)"
            )
        except Exception as e:
            logs.append(f"PDF 검색 중 오류가 발생했습니다: {e}")

    # ── 3. Tavily 웹 검색 ─────────────────────────────────────────────
    if route["use_tavily"]:
        try:
            tavily_results = search_web(question)
            sources["tavily"] = tavily_results
            logs.append(
                f"Tavily로 최신 웹 자료를 검색했습니다. ({len(tavily_results)}개 결과)"
            )
        except RuntimeError as e:
            # API Key 미설정 등 명확한 오류는 로그에 남기고 계속 진행
            logs.append(f"Tavily 검색 실패: {e}")
        except Exception as e:
            logs.append(f"Tavily 검색 중 예기치 못한 오류: {e}")

    # ── 4. Wikipedia 검색 ─────────────────────────────────────────────
    if route["use_wikipedia"]:
        try:
            wiki_results = search_wikipedia(question)
            sources["wikipedia"] = wiki_results
            logs.append(
                f"Wikipedia에서 기본 개념 자료를 검색했습니다. ({len(wiki_results)}개 결과)"
            )
        except Exception as e:
            logs.append(f"Wikipedia 검색 중 오류가 발생했습니다: {e}")

    # ── 5. 컨텍스트 통합 ──────────────────────────────────────────────
    context = _build_context(
        sources["pdf"],
        sources["tavily"],
        sources["wikipedia"],
    )
    logs.append("수집된 자료를 통합했습니다.")

    # ── 6. Qwen2.5 1차 답변 생성 ──────────────────────────────────────
    user_prompt = DEEP_SEARCH_USER_PROMPT_TEMPLATE.format(
        question=question,
        context=context,
    )

    answer = ask_qwen(
        system_prompt=DEEP_SEARCH_SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )
    logs.append("Qwen2.5가 1차 답변을 생성했습니다.")

    # ── 7. 결과 반환 ──────────────────────────────────────────────────
    return {
        "answer":       answer,
        "route":        route,
        "sources":      sources,
        "process_logs": logs,
    }
