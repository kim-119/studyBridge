"""
Deep Search 오케스트레이션 서비스 (app/api/ 전용 계층).
기존 answer_orchestrator.run_deep_search_pipeline을 위임하며,
응답 구조를 Spring 계약 형식으로 정규화한다.

흐름:
1. material_id 있으면 RAG 검색 시도
2. RAG 결과 부족 → Wikipedia 보완
3. 최신 정보 질문 → Tavily 보완
4. Ollama/GPT로 최종 답변 생성
5. route, sources, process_logs 반드시 반환
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_EMPTY_ROUTE = {
    "used_rag": False,
    "used_tavily": False,
    "used_wikipedia": False,
    "used_gpt": False,
}
_EMPTY_SOURCES = {
    "rag_chunks": [],
    "tavily": [],
    "wikipedia": [],
}


def run_deep_search(
    question: str,
    material_id: Optional[int] = None,
) -> dict:
    """
    Deep Search 파이프라인 실행.

    Returns:
        {
            "answer": str,
            "route": {"used_rag": bool, "used_tavily": bool, "used_wikipedia": bool, "used_gpt": bool},
            "sources": {"rag_chunks": list, "tavily": list, "wikipedia": list},
            "process_logs": list[str],
        }
    """
    try:
        from app.services.answer_orchestrator import run_deep_search_pipeline
        result = run_deep_search_pipeline(question=question, material_id=material_id)
        normalized = _normalize_response(result)
        normalized["answer"] = ensure_grounded_answer(normalized["answer"], normalized["sources"])
        return normalized
    except ImportError as e:
        logger.error("answer_orchestrator import 실패: %s", e)
        return _fallback_response(question, f"서비스 초기화 실패: {e}")
    except Exception as e:
        logger.error("Deep Search 파이프라인 오류: %s", e)
        return _fallback_response(question, str(e))


def _normalize_response(raw: dict) -> dict:
    """orchestrator 출력을 Spring 계약 구조로 정규화한다."""
    route = raw.get("route", {})
    sources = raw.get("sources", {})

    normalized_route = {
        "used_rag":       bool(route.get("use_pdf", route.get("used_rag", False))),
        "used_tavily":    bool(route.get("use_tavily", route.get("used_tavily", False))),
        "used_wikipedia": bool(route.get("use_wikipedia", route.get("used_wikipedia", False))),
        "used_gpt":       bool(route.get("use_gpt", route.get("used_gpt", False))),
    }

    normalized_sources = {
        "rag_chunks": sources.get("pdf", sources.get("rag_chunks", [])),
        "tavily":     sources.get("tavily", []),
        "wikipedia":  sources.get("wikipedia", []),
    }

    return {
        "answer":       raw.get("answer", ""),
        "route":        normalized_route,
        "sources":      normalized_sources,
        "process_logs": raw.get("process_logs", []),
    }


def _fallback_response(question: str, error_detail: str) -> dict:
    return {
        "answer": (
            "현재 Deep Search 서비스에 일시적인 오류가 발생했습니다. "
            "잠시 후 다시 시도해 주세요."
        ),
        "route":  dict(_EMPTY_ROUTE),
        "sources": {k: list(v) for k, v in _EMPTY_SOURCES.items()},
        "process_logs": [f"파이프라인 오류: {error_detail}"],
    }


def ensure_grounded_answer(answer: str, sources: dict) -> str:
    """
    RAG/Tavily/Wikipedia 근거가 하나도 없는데 답변이 사실을 단정하면
    근거 없음을 명시하는 disclaimer를 앞에 붙인다.
    """
    has_sources = any([
        sources.get("rag_chunks"),
        sources.get("tavily"),
        sources.get("wikipedia"),
    ])
    if has_sources:
        return answer
    disclaimer = "[검색 근거 없음] 아래 답변은 검색된 자료 없이 생성되었습니다. 사실 확인이 필요할 수 있습니다.\n\n"
    return disclaimer + answer
