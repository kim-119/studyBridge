"""
학습메이트 서비스 — prompt build → Ollama 호출 → 응답 변환.

Ollama-only: ask_ollama만 사용한다(call_primary_llm은 OpenAI fallback이 있어 사용하지 않음).
LLM 실패 시 가짜 답변을 만들지 않고 LearningMateLLMError를 던진다(router가 502 매핑).
"""
import logging
import time
from typing import Tuple

from app.services.ollama_client import ask_ollama
from app.utils.response_cleaner import clean_llm_response

from . import policies as P
from .prompt_builder import build_learning_mate_prompt
from .schemas import LearningMateChatRequest, LearningMateChatResponse

logger = logging.getLogger("studybridge.learning_mate")


class LearningMateLLMError(Exception):
    """Ollama 호출 실패 — 가짜 답변 대신 명확한 오류로 전달."""


# ask_ollama가 실패 시 반환하는 안내 문자열 마커(가짜 성공 방지용 탐지).
_LLM_FAILURE_MARKERS = (
    "현재 Ollama 서버",          # 연결 실패
    "AI 응답이",                  # 타임아웃("...초를 초과했습니다")
    "모델이 빈 응답을 반환",      # 빈 응답
    "[Ollama 오류]",             # 일반 예외
)


def _is_llm_failure(text: str) -> bool:
    if not text or not text.strip():
        return True
    head = text.strip()[:60]
    return any(marker in head for marker in _LLM_FAILURE_MARKERS)


def _mask_len(text: str) -> int:
    return len(text or "")


def generate_chat(request: LearningMateChatRequest) -> LearningMateChatResponse:
    system_prompt, user_prompt, effective_question, resolved = build_learning_mate_prompt(request)
    mode, tone, level = resolved["mode"], resolved["tone"], resolved["level"]
    qa = resolved.get("quickAction")
    max_tokens = int(P.mode_policy(mode).get("maxTokens", 1000))

    # 로그: 질문 전문 대신 길이만(개인정보 보호). 보정 여부는 resolved에 반영됨.
    logger.info(
        "learning_mate req: effQ_len=%d mode=%s tone=%s level=%s quickAction=%s rewrite=%s",
        _mask_len(effective_question), mode, tone, level, qa,
        bool((request.rewriteInstruction or "").strip()),
    )

    t0 = time.perf_counter()
    # think=False: qwen3 thinking이 num_predict를 소진해 빈 답변이 되는 것을 방지(지연도 감소).
    raw = ask_ollama(system_prompt=system_prompt, user_prompt=user_prompt,
                     max_tokens=max_tokens, think=False)
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    if _is_llm_failure(raw):
        logger.warning("learning_mate LLM 실패: latency=%sms head=%r", latency_ms, (raw or "")[:80])
        raise LearningMateLLMError("LLM 답변 생성에 실패했습니다.")

    answer = clean_llm_response(raw)
    if not answer.strip():
        logger.warning("learning_mate 정제 후 빈 답변")
        raise LearningMateLLMError("LLM 답변이 비어 있습니다.")

    ml, tl, ll, summary = P.labels(mode, tone, level)
    logger.info("learning_mate ok: mode=%s latency=%sms ans_len=%d", mode, latency_ms, len(answer))

    return LearningMateChatResponse(
        question=effective_question,
        answer=answer,
        mode=mode, modeLabel=ml,
        tone=tone, toneLabel=tl,
        learnerLevel=level, learnerLevelLabel=ll,
        summaryLabel=summary,
        availableModes=P.available_modes(),
        availableQuickActions=P.available_quick_actions(),
    )
