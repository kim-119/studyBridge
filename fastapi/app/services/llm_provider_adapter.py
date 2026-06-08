"""
LLM 프로바이더별 generation config 어댑터.
Ollama/Qwen과 OpenAI가 지원하는 파라미터가 다르므로
resolve()된 config를 각 프로바이더 형식으로 변환한다.
지원하지 않는 파라미터는 무시하여 서버가 죽지 않도록 한다.
"""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Ollama API가 지원하는 options 키
_OLLAMA_SUPPORTED = {
    "temperature", "top_p", "top_k", "num_predict",
    "repeat_penalty", "stop", "seed",
}

# OpenAI Chat Completions API가 지원하는 키
_OPENAI_SUPPORTED = {
    "temperature", "top_p", "max_tokens", "presence_penalty",
    "frequency_penalty", "stop",
}


def to_ollama_options(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    generation_config_resolver.resolve() 결과를 Ollama options dict로 변환.
    num_predict = max_tokens, stop = stop_sequences.
    """
    opts: Dict[str, Any] = {}
    try:
        if "temperature" in config:
            opts["temperature"] = float(config["temperature"])
        if "top_p" in config:
            opts["top_p"] = float(config["top_p"])
        if "top_k" in config:
            opts["top_k"] = int(config["top_k"])
        if "max_tokens" in config:
            opts["num_predict"] = int(config["max_tokens"])
        if "repeat_penalty" in config:
            opts["repeat_penalty"] = float(config["repeat_penalty"])
        seqs = config.get("stop_sequences", [])
        if seqs:
            opts["stop"] = seqs
    except Exception as e:
        logger.warning("Ollama options 변환 중 오류 (일부 파라미터 무시): %s", e)
    return opts


def to_openai_params(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    generation_config_resolver.resolve() 결과를 OpenAI API 파라미터로 변환.
    """
    params: Dict[str, Any] = {}
    try:
        if "temperature" in config:
            params["temperature"] = float(config["temperature"])
        if "top_p" in config:
            params["top_p"] = float(config["top_p"])
        if "max_tokens" in config:
            params["max_tokens"] = int(config["max_tokens"])
        if "presence_penalty" in config:
            params["presence_penalty"] = float(config["presence_penalty"])
        if "frequency_penalty" in config:
            params["frequency_penalty"] = float(config["frequency_penalty"])
        seqs = config.get("stop_sequences", [])
        if seqs:
            params["stop"] = seqs
    except Exception as e:
        logger.warning("OpenAI params 변환 중 오류 (일부 파라미터 무시): %s", e)
    return params
