"""
Ollama HTTP 클라이언트 — 주력 엔진: Qwen2.5 14B 양자화 모델.

설계 원칙:
- vLLM을 사용하지 않는다. Ollama /api/chat 만 사용한다.
- 기본 모델: qwen2.5:14b (서버컴에서 ollama list 확인 후 .env로 덮어쓸 것)
- 16GB VRAM 환경: full precision 14B는 OOM 가능. 반드시 양자화 모델 사용.
- num_predict는 용도에 따라 분리:
    일반 답변: OLLAMA_NUM_PREDICT (기본 512)
    전문가/박사: OLLAMA_NUM_PREDICT_ADVANCED (기본 768)
- context_length를 크게 잡으면 메모리 증가 → 기본 4096.
- 3명 에이전트 × n라운드 = 모델 호출 n배. 답변 길이를 제한해 속도를 맞춘다.
"""
import logging
from typing import Optional

import requests

from app.core.config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    OLLAMA_NUM_PREDICT,
    OLLAMA_NUM_PREDICT_ADVANCED,
    OLLAMA_TEMPERATURE,
    OLLAMA_TOP_P,
    OLLAMA_CONTEXT_LENGTH,
    OLLAMA_KEEP_ALIVE,
)

logger = logging.getLogger(__name__)

# 전문가/박사 수준에서 더 긴 응답을 허용하는 지식수준 목록
_ADVANCED_LEVELS = {"박사", "전문가", "박사 수준", "전문가 수준"}


def ask_ollama(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    knowledge_level: Optional[str] = None,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
    repeat_penalty: Optional[float] = None,
    timeout: Optional[int] = None,
    think: Optional[bool] = None,
) -> str:
    """
    Ollama /api/chat 엔드포인트를 호출한다.

    Args:
        system_prompt:   시스템 지시사항
        user_prompt:     사용자 메시지
        model:           모델명 (None이면 OLLAMA_MODEL)
        temperature:     샘플링 온도 (None이면 OLLAMA_TEMPERATURE)
        max_tokens:      최대 출력 토큰 (None이면 지식수준에 따라 자동)
        knowledge_level: 지식수준 — 박사/전문가는 num_predict를 더 크게 허용
        top_p:           top-p 값 (None이면 OLLAMA_TOP_P)

    Returns:
        모델 생성 답변 문자열. 오류 시 fallback 문자열 반환.
    """
    _model = model or OLLAMA_MODEL
    _temperature = temperature if temperature is not None else OLLAMA_TEMPERATURE
    _top_p = top_p if top_p is not None else OLLAMA_TOP_P

    # 지식수준에 따라 최대 토큰 분기
    if max_tokens is not None:
        _num_predict = max_tokens
    elif knowledge_level and knowledge_level in _ADVANCED_LEVELS:
        _num_predict = OLLAMA_NUM_PREDICT_ADVANCED
    else:
        _num_predict = OLLAMA_NUM_PREDICT

    _timeout = timeout if timeout is not None else OLLAMA_TIMEOUT

    options = {
        "temperature":  _temperature,
        "top_p":        _top_p,
        "num_predict":  _num_predict,
        "num_ctx":      OLLAMA_CONTEXT_LENGTH,
    }
    # 선택적 샘플링 파라미터: 전달된 경우에만 추가 (미전달 시 Ollama 기본값 사용)
    if top_k is not None:
        options["top_k"] = top_k
    if repeat_penalty is not None:
        options["repeat_penalty"] = repeat_penalty

    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": _model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "stream": False,
        "options": options,
    }
    # keep_alive 검증값(설정 시에만 전송). 모델 상주로 재호출 cold load 회피. 미설정 시 기존 동작 유지.
    if OLLAMA_KEEP_ALIVE:
        payload["keep_alive"] = OLLAMA_KEEP_ALIVE
    # think: qwen3 등 thinking 모델에서 추론블록이 num_predict를 소진해 빈 답변이 되는 것을 방지.
    # None이면 미전송(기존 동작 유지). False면 thinking 비활성 → 답변 토큰 확보 + 지연 감소.
    if think is not None:
        payload["think"] = think

    try:
        resp = requests.post(url, json=payload, timeout=_timeout)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        if not content or not content.strip():
            logger.warning("Ollama 응답이 비어 있습니다. model=%s", _model)
            return _empty_response_fallback(_model)
        return content.strip()
    except requests.ConnectionError:
        logger.warning("Ollama 서버 연결 실패. URL=%s", OLLAMA_BASE_URL)
        return _connection_fallback(_model)
    except requests.Timeout:
        logger.warning("Ollama 요청 타임아웃 (%ss). model=%s", _timeout, _model)
        return _timeout_fallback(_timeout)
    except Exception as e:
        logger.error("Ollama 호출 중 예외: %s", e)
        return _error_fallback(_model, e)


def is_ollama_available() -> bool:
    """Ollama 서버가 살아있고 OLLAMA_MODEL이 로드되어 있는지 확인한다."""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        if resp.status_code != 200:
            return False
        # 모델 목록에 설정된 모델이 있는지 확인 (모델명 prefix 매칭)
        models = resp.json().get("models", [])
        model_names = [m.get("name", "") for m in models]
        target = OLLAMA_MODEL.split(":")[0]  # "qwen2.5:14b" → "qwen2.5"
        return any(target in name for name in model_names)
    except Exception:
        return False


def get_loaded_model_name() -> Optional[str]:
    """
    Ollama에 로드된 모델 목록을 반환한다.
    서버컴에서 `ollama list` 결과와 동일한 정보.
    """
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        if resp.status_code != 200:
            return None
        models = resp.json().get("models", [])
        if not models:
            return None
        return models[0].get("name")
    except Exception:
        return None


# ── 내부 fallback 메시지 ────────────────────────────────────────────────────

def _connection_fallback(model: str) -> str:
    return (
        f"현재 Ollama 서버({OLLAMA_BASE_URL})에 연결할 수 없습니다. "
        f"'{model}' 모델을 사용하려면 Ollama가 실행 중이어야 합니다. "
        "잠시 후 다시 시도해 주세요."
    )


def _timeout_fallback(timeout: int) -> str:
    return (
        f"AI 응답이 {timeout}초를 초과했습니다. "
        "num_predict 또는 context_length를 줄이거나 양자화 수준을 낮춰 주세요."
    )


def _empty_response_fallback(model: str) -> str:
    return (
        f"'{model}' 모델이 빈 응답을 반환했습니다. "
        "모델 로딩 상태를 확인하거나 ollama run으로 테스트해 주세요."
    )


def _error_fallback(model: str, exc: Exception) -> str:
    return (
        f"[Ollama 오류] 모델={model}, 유형={type(exc).__name__}: {exc}. "
        "서버 상태와 모델명을 확인해 주세요."
    )
