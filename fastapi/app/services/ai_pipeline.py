"""
플래너 assist / 오답노트 피드백 전용 2단계 AI 파이프라인.

  1단계 (Qwen/Ollama):   입력을 1차 분석해 초안 JSON 생성.
  2단계 (OpenAI):        초안을 품질 보강·구조화·피드백 균형·다음 행동으로 다듬는다.
  fallback:              OpenAI 실패/비활성 → Qwen 초안 사용. 둘 다 실패 → 호출자 deterministic fallback.

환경변수:
  AI_PRIMARY_PROVIDER=ollama     (Qwen 1차)
  AI_REFINER_PROVIDER=openai     (OpenAI 보강)
  ENABLE_OPENAI_REFINER=true     OpenAI 보강 단계 사용 여부
  ENABLE_OLLAMA_FALLBACK=true    OpenAI 실패 시 Qwen 초안 사용 여부
  AI_TEMPERATURE=0.35
  AI_MAX_TOKENS=8192

자료보관함 PDF/요약/키워드/로드맵 로직은 일절 import하지 않는다(플래너·오답노트 분리 원칙).
"""
import logging
import os
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


def _flag(name: str, default: bool) -> bool:
    return str(os.getenv(name, str(default))).strip().lower() in ("1", "true", "yes", "on", "y")


ENABLE_OPENAI_REFINER = _flag("ENABLE_OPENAI_REFINER", True)
ENABLE_OLLAMA_FALLBACK = _flag("ENABLE_OLLAMA_FALLBACK", True)
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.35"))
AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "8192"))


def qwen_draft(system: str, user: str, max_tokens: Optional[int] = None) -> Optional[str]:
    """1단계 — Qwen(Ollama) 초안. 실패/미응답 시 None."""
    try:
        from app.services.ollama_client import ask_ollama, is_ollama_available
        if not is_ollama_available():
            logger.info("[ai_pipeline] Ollama 미응답 → Qwen 초안 생략")
            return None
        out = ask_ollama(
            system_prompt=system, user_prompt=user,
            max_tokens=max_tokens or AI_MAX_TOKENS, temperature=AI_TEMPERATURE,
        )
        if out and not out.strip().startswith("["):
            return out
    except Exception as e:  # noqa: BLE001
        logger.info("[ai_pipeline] qwen_draft 실패: %s", e)
    return None


def openai_refine(system: str, user: str, max_tokens: Optional[int] = None,
                  json_mode: bool = False) -> Optional[str]:
    """2단계 — OpenAI 보강/구조화/repair. 비활성/실패 시 None.

    json_mode=True 면 OpenAI JSON 모드로 호출해 유효한 JSON 객체를 강제한다
    (마크다운/산문 래핑으로 파싱 실패하던 케이스 방지)."""
    if not ENABLE_OPENAI_REFINER:
        return None
    try:
        from app.services.openai_client import chat_sync, is_enabled
        if not is_enabled():
            logger.info("[ai_pipeline] OpenAI 비활성 → 보강 생략")
            return None
        kwargs = {"max_tokens": max_tokens or AI_MAX_TOKENS, "temperature": 0.2}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        out = chat_sync(system=system, user=user, **kwargs)
        if out and not out.strip().startswith("["):
            return out
    except Exception as e:  # noqa: BLE001
        logger.info("[ai_pipeline] openai_refine 실패: %s", e)
    return None


def parse_json(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """LLM 출력에서 dict JSON 추출. 실패 시 None."""
    if not raw or raw.strip().startswith("["):
        return None
    from app.utils.json_parser import extract_json
    parsed = extract_json(raw)
    return parsed if isinstance(parsed, dict) else None


def generate_structured(
    *,
    draft_system: str,
    draft_user: str,
    refine_system: str,
    refine_user_builder: Callable[[Dict[str, Any]], str],
    validator: Callable[[Dict[str, Any]], bool],
    max_tokens: Optional[int] = None,
    stage1_enabled: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Qwen 1차 → OpenAI 보강 → 검증 순으로 구조화 JSON을 만든다.

    반환: 검증 통과 JSON, 또는 (통과 못해도) 가장 완성도 높은 JSON, 또는 None.
    None이면 호출자가 deterministic fallback으로 구조를 채운다.
    """
    draft_json: Optional[Dict[str, Any]] = None
    if stage1_enabled:
        draft_json = parse_json(qwen_draft(draft_system, draft_user, max_tokens))

    # OpenAI 보강은 초안(있으면)을 입력으로 받아 다듬는다.
    refine_user = refine_user_builder(draft_json or {})
    refined_json = parse_json(openai_refine(refine_system, refine_user, max_tokens))

    # 우선순위: 검증 통과한 보강본 > 검증 통과한 초안 > 보강본 > 초안
    if refined_json and validator(refined_json):
        return refined_json
    if draft_json and validator(draft_json):
        if ENABLE_OLLAMA_FALLBACK:
            return draft_json
    return refined_json or draft_json


def repair_to_valid(
    *,
    repair_system: str,
    repair_user: str,
    validator: Callable[[Dict[str, Any]], bool],
    max_tokens: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """검증 실패 시 복구: OpenAI repair → Qwen repair 순. 둘 다 실패 시 None."""
    fixed = parse_json(openai_refine(repair_system, repair_user, max_tokens))
    if fixed and validator(fixed):
        return fixed
    if ENABLE_OLLAMA_FALLBACK:
        fixed = parse_json(qwen_draft(repair_system, repair_user, max_tokens))
        if fixed and validator(fixed):
            return fixed
    return None
