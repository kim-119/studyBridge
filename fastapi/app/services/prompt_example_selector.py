"""
프롬프트 엔지니어링 전략 선택기.
prompt_engineering_policy.yaml을 참조하여 zero-shot/one-shot/few-shot 전략과
예시 파일을 선택한다.
"""
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_policy_cache: Optional[Dict[str, Any]] = None
_example_cache: Dict[str, str] = {}


def _load_policy() -> Dict[str, Any]:
    global _policy_cache
    if _policy_cache is not None:
        return _policy_cache
    try:
        import yaml
        path = Path(__file__).parent.parent / "core" / "prompt_engineering_policy.yaml"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                _policy_cache = data
                return _policy_cache
    except Exception as e:
        logger.warning("prompt_engineering_policy.yaml 로드 실패: %s", e)
    _policy_cache = {}
    return _policy_cache


def _load_example(filename: str) -> str:
    if filename in _example_cache:
        return _example_cache[filename]
    path = Path(__file__).parent.parent / "core" / "fewshot_examples" / filename
    if not path.exists():
        logger.warning("few-shot 예시 파일 없음: %s", filename)
        return ""
    try:
        text = path.read_text(encoding="utf-8").strip()
        _example_cache[filename] = text
        return text
    except Exception as e:
        logger.warning("few-shot 예시 로드 실패: %s — %s", filename, e)
        return ""


def select(
    knowledge_level: Optional[str] = None,
    mode: Optional[str] = None,
    context_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    지식수준 + 모드 + 컨텍스트 키를 조합하여 프롬프트 전략과 예시를 반환한다.
    반환: {"strategy": "few_shot", "example_text": "...", "example_file": "..."}
    """
    policy = _load_policy()
    prompting = policy.get("prompting", {})
    level_strategy = policy.get("level_strategy", {})
    mode_strategy = policy.get("mode_strategy", {})

    # context_key로 먼저 찾기 (quiz_generation, socratic, debate, doctoral_depth 등)
    if context_key and context_key in prompting:
        cfg = prompting[context_key]
        strategy = cfg.get("strategy", "zero_shot")
        example_file = cfg.get("example_file", "")
        example_text = _load_example(example_file) if example_file else ""
        return {"strategy": strategy, "example_text": example_text, "example_file": example_file}

    # 박사 수준 depth
    if knowledge_level == "박사":
        cfg = prompting.get("doctoral_depth", {})
        strategy = cfg.get("strategy", "few_shot")
        example_file = cfg.get("example_file", "doctoral_answer_depth_examples.md")
        example_text = _load_example(example_file)
        return {"strategy": strategy, "example_text": example_text, "example_file": example_file}

    # 모드별 전략
    if mode and mode in prompting:
        cfg = prompting[mode]
        strategy = cfg.get("strategy", "zero_shot")
        example_file = cfg.get("example_file", "")
        example_text = _load_example(example_file) if example_file else ""
        return {"strategy": strategy, "example_text": example_text, "example_file": example_file}

    # 지식수준별 기본 전략
    if knowledge_level:
        strategy = level_strategy.get(knowledge_level, "zero_shot")
    elif mode:
        strategy = mode_strategy.get(mode, "zero_shot")
    else:
        strategy = "zero_shot"

    return {"strategy": strategy, "example_text": "", "example_file": ""}


def build_few_shot_prefix(example_text: str, max_tokens: int = 800) -> str:
    """few-shot 예시를 시스템 프롬프트 앞에 삽입할 텍스트로 변환."""
    if not example_text:
        return ""
    # 토큰 예산 초과 방지 (한국어 기준 대략 1자 = 1.5토큰)
    max_chars = int(max_tokens / 1.5)
    if len(example_text) > max_chars:
        example_text = example_text[:max_chars] + "\n..."
    return f"[답변 스타일 예시]\n{example_text}\n\n"


def invalidate_cache() -> None:
    global _policy_cache
    _policy_cache = None
    _example_cache.clear()
