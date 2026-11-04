"""
OpenAI 클라이언트 (동기/비동기).
GPT 답변 생성, 검증, 임베딩 생성을 담당한다.
OPENAI_API_KEY 미설정 시 disabled 상태로 동작 (서버 죽지 않음).

외부 전송 정책(app.core.egress_policy, 2026-11-04): 이 모듈이 프로세스의 유일한 OpenAI SDK 클라이언트 생성 지점이다.
main.py / material_ai_manager / roadmap_service / gpt_verifier 의 전용 클라이언트도 여기로 위임한다.
모든 진입점은 feature 이름을 받아 egress_allowed("openai", feature) 를 확인한다.
  - is_enabled(feature)      : 키 설정 AND 정책 허용. False 면 호출부의 기존 'OpenAI 비활성' 분기가 그대로 선택된다.
  - get_*_client(feature)    : 정책 불허 시 EgressBlocked(RuntimeError 하위) — 클라이언트 객체를 넘겨주지 않는다.
  - chat_sync/chat_async     : 정책 불허 시 "[GPT 차단] ..." 문자열(기존 "[GPT ..." 실패 규약과 동일) — 네트워크 호출 없음.
feature 를 넘기지 않은 레거시 호출은 "unspecified" 로 판정되어 AI_EGRESS_ALLOW=openai:* 일 때만 허용된다.
"""
import logging
from typing import Optional, Union

from app.core.config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_EMBEDDING_MODEL, OPENAI_EMBEDDING_DIM
from app.core.egress_policy import EgressBlocked, egress_allowed, require_egress

logger = logging.getLogger(__name__)

_sync_client = None
_async_client = None

BLOCKED_MESSAGE = "[GPT 차단] 외부 전송 정책(AI_EXTERNAL_EGRESS_ENABLED/AI_EGRESS_ALLOW)에 의해 OpenAI 호출이 차단되었습니다."


def key_configured() -> bool:
    """OPENAI_API_KEY 설정 여부만 반환한다(정책과 무관 — 상태 표시용)."""
    return bool(OPENAI_API_KEY)


def is_enabled(feature: Optional[str] = None) -> bool:
    """OpenAI 를 이 feature 에서 쓸 수 있는지: API Key 설정 AND 외부 전송 정책 허용."""
    if not OPENAI_API_KEY:
        return False
    return egress_allowed("openai", feature)


def get_sync_client(feature: Optional[str] = None):
    require_egress("openai", feature)
    return _raw_sync_client()


def get_async_client(feature: Optional[str] = None):
    require_egress("openai", feature)
    return _raw_async_client()


def _raw_sync_client():
    """정책 확인을 이미 마친 내부 경로 전용(중복 판정 카운트 방지)."""
    global _sync_client
    if _sync_client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
        from openai import OpenAI
        _sync_client = OpenAI(api_key=OPENAI_API_KEY)
    return _sync_client


def _raw_async_client():
    global _async_client
    if _async_client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
        from openai import AsyncOpenAI
        _async_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _async_client


def _disabled_message(feature: Optional[str]) -> str:
    if not OPENAI_API_KEY:
        return "[GPT 비활성화] OPENAI_API_KEY를 설정하면 GPT 기능이 활성화됩니다."
    return BLOCKED_MESSAGE


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
    response_format: Optional[dict] = None,
    feature: Optional[str] = None,
) -> str:
    """GPT 동기 호출. API Key 미설정 시 안내 문자열 반환.

    response_format={"type":"json_object"} 를 주면 OpenAI JSON 모드로 호출해
    항상 유효한 JSON 객체를 반환받는다(마크다운/산문 래핑 방지). 단, 프롬프트에
    'json' 단어가 있어야 하고 max_tokens 초과 시엔 여전히 잘릴 수 있다.
    """
    if not is_enabled(feature):
        return _disabled_message(feature)
    import app.ai_gateway as _gw
    if not _gw.openai_allowed(max_tokens or 0):
        # 일 토큰 예산/브레이커 차단 → 기존 오류 문자열 경로(호출부 fallback)로 보낸다.
        return "[GPT 오류] BudgetExceeded: OpenAI 사용 한도 또는 장애 차단 상태입니다."
    try:
        client = _raw_sync_client()
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
        if response_format is not None:
            extra["response_format"] = response_format
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
        _gw.record_openai_usage(model or OPENAI_MODEL, getattr(resp, "usage", None), ok=True)
        return resp.choices[0].message.content or ""
    except Exception as e:
        _gw.record_openai_usage(model or OPENAI_MODEL, None, ok=False)
        logger.error("GPT 동기 호출 실패: %s", e)
        return f"[GPT 오류] {type(e).__name__}: {e}"


async def chat_async(
    system: str,
    user: Union[str, list],
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 1200,
    feature: Optional[str] = None,
) -> str:
    """GPT 비동기 호출. API Key 미설정/정책 차단 시 안내 문자열 반환."""
    if not is_enabled(feature):
        return _disabled_message(feature)
    import app.ai_gateway as _gw
    if not _gw.openai_allowed(max_tokens or 0):
        return "[GPT 오류] BudgetExceeded: OpenAI 사용 한도 또는 장애 차단 상태입니다."
    try:
        client = _raw_async_client()
        resp = await client.chat.completions.create(
            model=model or OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        _gw.record_openai_usage(model or OPENAI_MODEL, getattr(resp, "usage", None), ok=True)
        return resp.choices[0].message.content or ""
    except Exception as e:
        _gw.record_openai_usage(model or OPENAI_MODEL, None, ok=False)
        logger.error("GPT 비동기 호출 실패: %s", e)
        return f"[GPT 오류] {type(e).__name__}: {e}"


def embed_sync(text: str, feature: str = "embedding") -> list[float]:
    """
    OpenAI text-embedding-3-small로 텍스트를 임베딩한다.
    API Key 미설정 시 RuntimeError, 정책 차단 시 EgressBlocked(RuntimeError 하위) 발생.
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다. 임베딩을 생성할 수 없습니다.")
    client = get_sync_client(feature)
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
