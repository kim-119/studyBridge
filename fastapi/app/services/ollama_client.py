"""
Ollama HTTP 클라이언트.
qwen2.5:7b 등 로컬 LLM을 Ollama API로 호출한다.
연결 실패 시 fallback 응답을 반환하고 예외를 전파하지 않는다.
"""
import logging
from typing import Optional

import requests

from app.core.config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT

logger = logging.getLogger(__name__)


def ask_ollama(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> str:
    """
    Ollama /api/chat 엔드포인트를 호출하여 답변을 반환한다.

    Args:
        system_prompt: 시스템 지시사항
        user_prompt:   사용자 메시지
        model:         모델명 (None이면 OLLAMA_MODEL 환경변수 사용)
        temperature:   샘플링 온도
        max_tokens:    최대 출력 토큰

    Returns:
        모델 생성 답변 문자열. 오류 시 오류 메시지 문자열.
    """
    _model = model or OLLAMA_MODEL
    url = f"{OLLAMA_BASE_URL}/api/chat"

    payload = {
        "model": _model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "")
    except requests.ConnectionError:
        logger.warning("Ollama 서버에 연결할 수 없습니다. URL=%s", OLLAMA_BASE_URL)
        return _fallback_message(_model)
    except requests.Timeout:
        logger.warning("Ollama 요청 타임아웃 (timeout=%ss)", OLLAMA_TIMEOUT)
        return f"[타임아웃] Ollama 응답이 {OLLAMA_TIMEOUT}초 이내에 오지 않았습니다."
    except Exception as e:
        logger.error("Ollama 호출 중 오류: %s", e)
        return f"[Ollama 오류] {type(e).__name__}: {e}"


def is_ollama_available() -> bool:
    """Ollama 서버가 응답 가능한지 확인한다."""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def _fallback_message(model: str) -> str:
    return (
        f"현재 Ollama 서버({OLLAMA_BASE_URL})에 연결할 수 없습니다. "
        f"모델 '{model}'을 사용하려면 Ollama가 실행 중이어야 합니다.\n"
        "잠시 후 다시 시도해 주세요."
    )
