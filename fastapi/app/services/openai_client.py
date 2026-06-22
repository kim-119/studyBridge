"""
OpenAI 클라이언트 (동기/비동기).
GPT 답변 생성, 검증, 임베딩 생성을 담당한다.
OPENAI_API_KEY 미설정 시 disabled 상태로 동작 (서버 죽지 않음).
"""
import logging
from typing import Optional, Union

from app.core.config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_EMBEDDING_MODEL, OPENAI_EMBEDDING_DIM

logger = logging.getLogger(__name__)

_sync_client = None
_async_client = None


def is_enabled() -> bool:
    """OpenAI API Key가 설정되어 있는지 반환한다."""
    return bool(OPENAI_API_KEY)


def get_sync_client():
    global _sync_client
    if _sync_client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
        from openai import OpenAI
        _sync_client = OpenAI(api_key=OPENAI_API_KEY)
    return _sync_client


def get_async_client():
    global _async_client
    if _async_client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
        from openai import AsyncOpenAI
        _async_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _async_client


def chat_sync(
    system: str,
    user: Union[str, list],
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 1200,
    top_p: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
    timeout: Optional[float] = None,
) -> str:
    """GPT 동기 호출. API Key 미설정 시 안내 문자열 반환."""
    if not is_enabled():
        return "[GPT 비활성화] OPENAI_API_KEY를 설정하면 GPT 기능이 활성화됩니다."
    try:
        client = get_sync_client()
        # 선택적 파라미터는 전달된 경우에만 추가 (OpenAI는 top_k 미지원이라 받지 않는다)
        extra = {}
        if top_p is not None:
            extra["top_p"] = top_p
        if presence_penalty is not None:
            extra["presence_penalty"] = presence_penalty
        if frequency_penalty is not None:
            extra["frequency_penalty"] = frequency_penalty
        if timeout is not None:
            extra["timeout"] = timeout
        resp = client.chat.completions.create(
            model=model or OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            **extra,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        logger.error("GPT 동기 호출 실패: %s", e)
        return f"[GPT 오류] {type(e).__name__}: {e}"


async def chat_async(
    system: str,
    user: Union[str, list],
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 1200,
) -> str:
    """GPT 비동기 호출. API Key 미설정 시 안내 문자열 반환."""
    if not is_enabled():
        return "[GPT 비활성화] OPENAI_API_KEY를 설정하면 GPT 기능이 활성화됩니다."
    try:
        client = get_async_client()
        resp = await client.chat.completions.create(
            model=model or OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        logger.error("GPT 비동기 호출 실패: %s", e)
        return f"[GPT 오류] {type(e).__name__}: {e}"


def embed_sync(text: str) -> list[float]:
    """
    OpenAI text-embedding-3-small로 텍스트를 임베딩한다.
    API Key 미설정 시 RuntimeError 발생.
    """
    if not is_enabled():
        raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다. 임베딩을 생성할 수 없습니다.")
    client = get_sync_client()
    resp = client.embeddings.create(
        model=OPENAI_EMBEDDING_MODEL,
        input=text,
    )
    vec = resp.data[0].embedding
    if len(vec) != OPENAI_EMBEDDING_DIM:
        raise ValueError(
            f"임베딩 차원 불일치: 기대={OPENAI_EMBEDDING_DIM}, 실제={len(vec)}"
        )
    return vec
