"""
지식수준 + 성격 + 모드 + 학문 도메인을 조합하여
최종 generation config를 계산한다.
generation_policy.yaml을 참조하며, 파일 없으면 내장 기본값 사용.
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── 내장 기본값 (YAML 없을 때 fallback) ──────────────────────────────────────
_DEFAULT_LEVEL_CONFIG: Dict[str, Dict[str, Any]] = {
    "입문": {
        "temperature": 0.35, "top_p": 0.85, "top_k": 30,
        "max_tokens": 700, "repeat_penalty": 1.05,
        "presence_penalty": 0.0, "frequency_penalty": 0.0,
        "stop_sequences": [], "reasoning_or_thinking_level": "low",
        "retrieval_top_k": 3, "use_openalex": False,
        "use_depth_verifier": False, "use_depth_rewrite": False,
    },
    "학사": {
        "temperature": 0.45, "top_p": 0.90, "top_k": 40,
        "max_tokens": 1000, "repeat_penalty": 1.05,
        "presence_penalty": 0.0, "frequency_penalty": 0.0,
        "stop_sequences": [], "reasoning_or_thinking_level": "medium",
        "retrieval_top_k": 4, "use_openalex": False,
        "use_depth_verifier": False, "use_depth_rewrite": False,
    },
    "석사": {
        "temperature": 0.50, "top_p": 0.90, "top_k": 50,
        "max_tokens": 1400, "repeat_penalty": 1.08,
        "presence_penalty": 0.0, "frequency_penalty": 0.0,
        "stop_sequences": [], "reasoning_or_thinking_level": "medium_high",
        "retrieval_top_k": 5, "use_openalex": False,
        "use_depth_verifier": False, "use_depth_rewrite": False,
    },
    "박사": {
        "temperature": 0.55, "top_p": 0.92, "top_k": 60,
        "max_tokens": 1900, "repeat_penalty": 1.08,
        "presence_penalty": 0.0, "frequency_penalty": 0.0,
        "stop_sequences": [], "reasoning_or_thinking_level": "high",
        "retrieval_top_k": 7, "use_openalex": True,
        "use_depth_verifier": True, "use_depth_rewrite": True,
    },
    "전문가": {
        "temperature": 0.50, "top_p": 0.88, "top_k": 50,
        "max_tokens": 2200, "repeat_penalty": 1.10,
        "presence_penalty": 0.0, "frequency_penalty": 0.0,
        "stop_sequences": [], "reasoning_or_thinking_level": "high",
        "retrieval_top_k": 8, "use_openalex": False,
        "use_depth_verifier": True, "use_depth_rewrite": True,
    },
}

_CLAMP = {
    "temperature_min": 0.20, "temperature_max": 0.75,
    "top_p_min": 0.70, "top_p_max": 0.95,
    "top_k_min": 10, "top_k_max": 80,
}

_policy_cache: Optional[Dict[str, Any]] = None


def _load_policy() -> Dict[str, Any]:
    global _policy_cache
    if _policy_cache is not None:
        return _policy_cache
    try:
        from pathlib import Path
        import yaml
        path = Path(__file__).parent.parent / "core" / "generation_policy.yaml"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                _policy_cache = data
                logger.debug("generation_policy.yaml 로드 완료")
                return _policy_cache
    except Exception as e:
        logger.warning("generation_policy.yaml 로드 실패 (기본값 사용): %s", e)
    _policy_cache = {}
    return _policy_cache


def _get_level_base(level: str) -> Dict[str, Any]:
    policy = _load_policy()
    levels = policy.get("levels", {})
    if level in levels:
        return dict(levels[level])
    return dict(_DEFAULT_LEVEL_CONFIG.get(level, _DEFAULT_LEVEL_CONFIG["학사"]))


def _get_personality_adj(personality: Optional[str]) -> Dict[str, Any]:
    if not personality:
        return {}
    policy = _load_policy()
    adj_map = policy.get("personality_adjustment", {})
    # 언더스코어/공백 혼용 처리
    key = personality.replace(" ", "_")
    return adj_map.get(key, adj_map.get(personality, {}))


def _get_mode_adj(mode: Optional[str]) -> Dict[str, Any]:
    if not mode:
        return {}
    policy = _load_policy()
    return policy.get("mode_adjustment", {}).get(mode, {})


def _get_domain_adj(domain: Optional[str]) -> Dict[str, Any]:
    if not domain:
        return {}
    policy = _load_policy()
    return policy.get("domain_adjustment", {}).get(domain, {})


def _clamp(config: Dict[str, Any]) -> Dict[str, Any]:
    policy = _load_policy()
    c = policy.get("clamp", _CLAMP)
    t_min = c.get("temperature_min", _CLAMP["temperature_min"])
    t_max = c.get("temperature_max", _CLAMP["temperature_max"])
    p_min = c.get("top_p_min", _CLAMP["top_p_min"])
    p_max = c.get("top_p_max", _CLAMP["top_p_max"])
    k_min = c.get("top_k_min", _CLAMP["top_k_min"])
    k_max = c.get("top_k_max", _CLAMP["top_k_max"])

    if "temperature" in config:
        config["temperature"] = max(t_min, min(t_max, config["temperature"]))
    if "top_p" in config:
        config["top_p"] = max(p_min, min(p_max, config["top_p"]))
    if "top_k" in config:
        config["top_k"] = int(max(k_min, min(k_max, config["top_k"])))
    return config


def resolve(
    knowledge_level: str = "학사",
    personality: Optional[str] = None,
    mode: Optional[str] = None,
    domain: Optional[str] = None,
) -> Dict[str, Any]:
    """
    지식수준 + 성격 + 모드 + 도메인 조합으로 최종 generation config 계산.
    반환값에는 temperature, top_p, top_k, max_tokens, use_openalex 등이 포함된다.
    """
    config = _get_level_base(knowledge_level)

    p_adj = _get_personality_adj(personality)
    m_adj = _get_mode_adj(mode)
    d_adj = _get_domain_adj(domain)

    config["temperature"] = (
        config.get("temperature", 0.45)
        + p_adj.get("temperature_delta", 0.0)
        + m_adj.get("temperature_delta", 0.0)
        + d_adj.get("temperature_delta", 0.0)
    )
    config["top_p"] = (
        config.get("top_p", 0.90)
        + p_adj.get("top_p_delta", 0.0)
        + m_adj.get("top_p_delta", 0.0)
        + d_adj.get("top_p_delta", 0.0)
    )

    mt_mult = (
        p_adj.get("max_tokens_multiplier", 1.0)
        * m_adj.get("max_tokens_multiplier", 1.0)
    )
    if mt_mult != 1.0:
        config["max_tokens"] = int(config.get("max_tokens", 1000) * mt_mult)

    config = _clamp(config)
    config["knowledge_level"] = knowledge_level
    return config


def invalidate_cache() -> None:
    global _policy_cache
    _policy_cache = None
