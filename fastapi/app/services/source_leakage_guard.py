"""
최종 답변에서 출처 노출 표현(OpenAlex, DOI, 인용 수 등)을 감지하고 제거한다.
stop sequence만으로 막지 않고 별도 guard로 검사한다.
"""
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_policy_cache: Optional[List[str]] = None

# 내장 금지 표현 (YAML 없을 때 fallback)
_DEFAULT_FORBIDDEN = [
    "OpenAlex",
    "논문에서 발췌",
    "2020년 이후 논문",
    "최근 논문에 따르면",
    "인용 수",
    "DOI:",
    "doi.org",
    "학술 문헌에 따르면",
    "발표된 연구에 따르면",
    "피인용 횟수",
    "arXiv",
    "논문에 따르면",
    "논문에서",
    "2020년 이후 연구",
]


def _get_forbidden_phrases() -> List[str]:
    global _policy_cache
    if _policy_cache is not None:
        return _policy_cache
    try:
        import yaml
        path = Path(__file__).parent.parent / "core" / "source_policy.yaml"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            phrases = data.get("leakage_guard", {}).get("forbidden_phrases", [])
            if phrases:
                _policy_cache = phrases
                return _policy_cache
    except Exception as e:
        logger.warning("source_policy.yaml 로드 실패 (기본값 사용): %s", e)
    _policy_cache = _DEFAULT_FORBIDDEN
    return _policy_cache


def detect(text: str) -> Tuple[bool, List[str]]:
    """
    텍스트에서 금지 표현을 감지한다.
    반환: (감지_여부, 감지된_표현_목록)
    """
    forbidden = _get_forbidden_phrases()
    found = [phrase for phrase in forbidden if phrase.lower() in text.lower()]
    return bool(found), found


def clean(text: str) -> str:
    """금지 표현을 텍스트에서 제거하거나 대체하는 단순 정제."""
    forbidden = _get_forbidden_phrases()
    cleaned = text
    for phrase in forbidden:
        # 대소문자 무시 패턴으로 제거
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        cleaned = pattern.sub("", cleaned)
    # 연속 공백 정리
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def invalidate_cache() -> None:
    global _policy_cache
    _policy_cache = None
