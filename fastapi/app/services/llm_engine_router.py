"""
LLM 엔진 라우터.

우선순위:
  1. Ollama (Qwen2.5 14B 양자화) — 주력 엔진
  2. OpenAI/GPT — fallback 및 검증/보정 전용
  vLLM은 사용하지 않는다.

fine-tuned adapter가 활성화되어 있으면 (FINETUNED_MODEL_ENABLED=true) Ollama 호출 전
adapter 기반 응답을 시도한다. 비활성 또는 실패 시 qwen2.5:14b 기본 추론으로 진행한다.

설계 원칙:
- 이 모듈이 ollama_client, openai_client 두 모듈을 묶는 단일 진입점.
- 호출자(multi_agent_service, quiz_generation_service 등)는 이 모듈만 사용해도 된다.
- vLLM 의존성 없음. QWEN_BASE_URL 등 vLLM 설정은 무시한다.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def call_primary_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    knowledge_level: Optional[str] = None,
) -> str:
    """
    주력 LLM을 호출한다. Ollama(qwen2.5:14b) → OpenAI fallback 순서.

    Args:
        system_prompt:   시스템 지시사항
        user_prompt:     사용자 메시지
        max_tokens:      최대 출력 토큰
        temperature:     샘플링 온도
        knowledge_level: 지식수준 (박사/전문가는 더 긴 응답 허용)

    Returns:
        생성된 답변 문자열.
    """
    from app.core.finetune_config import FINETUNED_MODEL_ENABLED

    # 1. fine-tuned adapter optional 시도
    if FINETUNED_MODEL_ENABLED:
        result = _try_finetuned_adapter(system_prompt, user_prompt, max_tokens, temperature)
        if result and not result.startswith("["):
            logger.debug("fine-tuned adapter 응답 사용")
            return result
        logger.info("fine-tuned adapter 비활성/실패 → Ollama 기본 모델로 진행")

    # 2. Ollama 주력 호출
    result = _try_ollama(system_prompt, user_prompt, max_tokens, temperature, knowledge_level)
    if result and not result.startswith("[Ollama"):
        return result

    # 3. OpenAI fallback
    logger.info("Ollama 실패 → OpenAI fallback 시도")
    return _try_openai(system_prompt, user_prompt, max_tokens, temperature)


def call_verifier_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 400,
) -> str:
    """
    검증/보정 전용 LLM 호출 (GPT 우선).
    GPT는 검증·보정·요약 용도로만 사용한다.
    """
    result = _try_openai(system_prompt, user_prompt, max_tokens, temperature=0.1)
    if not result.startswith("[GPT"):
        return result
    # GPT 실패 시 Ollama로 대체 검증
    return _try_ollama(system_prompt, user_prompt, max_tokens, temperature=0.1)


def is_primary_available() -> bool:
    """주력 LLM(Ollama) 사용 가능 여부."""
    try:
        from app.services.ollama_client import is_ollama_available
        return is_ollama_available()
    except Exception:
        return False


# ── 내부 호출 함수 ──────────────────────────────────────────────────────────

def _try_ollama(
    system_prompt: str,
    user_prompt: str,
    max_tokens: Optional[int],
    temperature: Optional[float],
    knowledge_level: Optional[str] = None,
) -> str:
    try:
        from app.services.ollama_client import ask_ollama, is_ollama_available
        if not is_ollama_available():
            logger.warning("Ollama 서버 미응답")
            return "[Ollama 미응답]"
        return ask_ollama(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            knowledge_level=knowledge_level,
        )
    except Exception as e:
        logger.error("Ollama 호출 예외: %s", e)
        return f"[Ollama 오류] {e}"


def _try_openai(
    system_prompt: str,
    user_prompt: str,
    max_tokens: Optional[int],
    temperature: Optional[float],
) -> str:
    try:
        from app.services.openai_client import chat_sync, is_enabled
        if not is_enabled():
            return "[GPT 비활성화] OPENAI_API_KEY 미설정"
        return chat_sync(
            system=system_prompt,
            user=user_prompt,
            max_tokens=max_tokens or 1024,
            temperature=temperature or 0.4,
        )
    except Exception as e:
        logger.error("OpenAI fallback 호출 예외: %s", e)
        return f"[GPT 오류] {e}"


def _try_finetuned_adapter(
    system_prompt: str,
    user_prompt: str,
    max_tokens: Optional[int],
    temperature: Optional[float],
) -> str:
    """
    fine-tuned adapter를 통한 추론 시도.
    FINETUNED_ADAPTER_PATH에 adapter 파일이 있어야 동작한다.
    없거나 실패하면 빈 문자열 반환 → caller가 Ollama로 fallback.

    현재 구현: adapter path를 Ollama Modelfile 기반으로 사용하거나
    transformers PEFT 기반으로 확장 가능. 서버컴에서만 활성화 권장.
    """
    try:
        from app.core.finetune_config import FINETUNED_ADAPTER_PATH
        if not FINETUNED_ADAPTER_PATH:
            return ""
        # adapter 기반 Ollama 커스텀 모델명이 있으면 해당 모델로 호출
        from app.services.ollama_client import ask_ollama
        return ask_ollama(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=FINETUNED_ADAPTER_PATH,  # ollama create로 만든 커스텀 모델명
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as e:
        logger.warning("fine-tuned adapter 호출 실패: %s", e)
        return ""
