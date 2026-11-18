"""
GPT 답변 검증기.
Qwen/자체 생성 답변의 품질을 GPT-4o-mini로 비동기 교차 검증한다.
OPENAI_API_KEY 미설정 시 검증을 건너뛰고 통과 처리한다.
"""
import json
import logging
from typing import Optional

from app.core.config import OPENAI_API_KEY
from app.services.knowledge_level_controller import get_validation_criteria as level_criteria
from app.services.personality_prompt_builder import get_validation_criteria as personality_criteria

logger = logging.getLogger(__name__)

_async_client = None


def _get_client():
    global _async_client
    if _async_client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
        from openai import AsyncOpenAI
        _async_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _async_client


_VERIFY_SYSTEM = """\
너는 교육용 AI 답변 품질을 평가하는 전문 검수자다.
설정된 지식수준과 성격에 맞게 답변이 작성되었는지 평가한다.

출력 형식: JSON 객체만 출력하라 (마크다운 불필요).
{
  "is_valid": true/false,
  "score": 0.0~1.0,
  "issues": ["문제점1", "문제점2"],
  "correction_needed": true/false,
  "suggestion": "개선 제안 한 줄 (없으면 빈 문자열)"
}"""


async def verify_answer_async(
    question: str,
    answer: str,
    knowledge_level: str,
    personality: str,
) -> dict:
    """
    GPT-4o-mini를 사용해 답변 품질을 비동기 검증한다.

    Returns:
        {
          "is_valid": bool,
          "score": float,         # 0~1
          "issues": list[str],
          "correction_needed": bool,
          "suggestion": str,
        }
    """
    _fallback = {
        "is_valid": True,
        "score": 0.5,
        "issues": [],
        "correction_needed": False,
        "suggestion": "",
    }

    if not OPENAI_API_KEY:
        _fallback["issues"] = ["OPENAI_API_KEY 미설정 — 검증 건너뜀"]
        return _fallback

    user_prompt = (
        f"## 질문\n{question}\n\n"
        f"## 설정\n"
        f"- 지식수준: {knowledge_level} (기준: {level_criteria(knowledge_level)})\n"
        f"- 성격: {personality} (기준: {personality_criteria(personality)})\n\n"
        f"## 검증 대상 답변\n{answer}\n\n"
        "위 기준에 따라 평가하고 JSON 형식으로만 응답하라."
    )

    try:
        from openai import APIConnectionError, APIStatusError
        client = _get_client()
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _VERIFY_SYSTEM},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        return {
            "is_valid":          bool(data.get("is_valid", True)),
            "score":             float(data.get("score", 0.7)),
            "issues":            list(data.get("issues", [])),
            "correction_needed": bool(data.get("correction_needed", False)),
            "suggestion":        str(data.get("suggestion", "")),
        }
    except Exception as e:
        logger.warning("GPT 검증 실패: %s", e)
        _fallback["issues"] = [f"GPT 검증 실패: {type(e).__name__}"]
        return _fallback


async def generate_corrected_answer_async(
    question: str,
    original_answer: str,
    suggestion: str,
    knowledge_level: str,
    personality: str,
) -> str:
    """
    GPT 검증 제안을 바탕으로 보정된 답변을 생성한다.
    GPT 호출 실패 시 원본 답변을 그대로 반환한다.
    """
    if not OPENAI_API_KEY or not suggestion:
        return original_answer

    prompt = (
        f"아래 답변을 개선하라.\n\n"
        f"질문: {question}\n"
        f"지식수준: {knowledge_level} / 성격: {personality}\n"
        f"개선 제안: {suggestion}\n\n"
        f"원본 답변:\n{original_answer}\n\n"
        "제안을 반영해 개선된 답변을 한국어로 작성하라."
    )

    try:
        client = _get_client()
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=800,
        )
        return resp.choices[0].message.content or original_answer
    except Exception as e:
        logger.warning("GPT 보정 답변 생성 실패: %s", e)
        return original_answer
