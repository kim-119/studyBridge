"""Vision API 설정. 모든 값은 환경변수로 덮어쓴다(요청 시점마다 읽어 테스트/핫 변경 허용)."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int, lo: int = 0) -> int:
    try:
        return max(lo, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float, lo: float = 0.0) -> float:
    try:
        return max(lo, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class VisionSettings:
    enabled: bool
    backend: str                 # "ollama" | "mock"
    model: str
    ollama_base_url: str
    think: str                   # "false"|"true"|"omit"(think 필드 미전송)
    keep_alive: str
    num_predict: int
    num_ctx: int
    temperature: float
    max_body_bytes: int
    max_image_bytes: int
    max_long_side: int
    min_side: int
    max_pixels: int
    max_question_chars: int
    max_answer_chars: int
    allowed_mimes: tuple[str, ...]
    max_concurrency: int
    max_queue: int
    max_per_group: int
    queue_timeout_s: float
    inference_timeout_s: float
    duplicate_ttl_s: float
    allow_unauthenticated: bool
    mock_delay_s: float
    # VLM(화면 판독) → OpenAI(최종 답변) 2단계. VLM 은 JSON 판독만, 답변은 OpenAI 만 만든다.
    extract_num_predict: int
    extract_max_chars: int
    answer_provider: str          # "openai" | "mock"(테스트 전용)
    answer_model: str
    answer_max_tokens: int
    answer_temperature: float
    answer_timeout_s: float
    answer_max_concurrency: int
    answer_queue_timeout_s: float
    answer_daily_token_cap: int   # 비전 답변 전용 일 토큰 상한(KST). 0 은 허용하지 않고 기본값으로 돌린다.
    external_llm_enabled: bool    # 외부 전송 kill switch. false 면 VLM 단독 답변 없이 503 VISION_ANSWER_DISABLED.
    total_timeout_s: float        # 요청 전체 상한(Spring ai.vision.timeout-seconds 260초보다 짧게)
    answer_mock_delay_s: float


def get_settings() -> VisionSettings:
    return VisionSettings(
        enabled=_bool("VISION_API_ENABLED", False),
        backend=os.getenv("VISION_BACKEND", "ollama").strip().lower(),
        # 시스템 Ollama(0.24.0, :11434)는 qwen3-vl 을 받을 수 없어(registry 412) 사용자 공간
        # ~/ollama-vision 의 Ollama 0.40.11 을 :11435 에 별도로 띄워 qwen3-vl:4b-instruct 만 서비스한다.
        model=os.getenv("VISION_MODEL", "qwen3-vl:4b-instruct").strip(),
        ollama_base_url=os.getenv("VISION_OLLAMA_BASE_URL", "http://127.0.0.1:11435").rstrip("/"),
        think=os.getenv("VISION_THINK", "omit").strip().lower(),
        # 별도 데몬은 qwen3:14b 와 VRAM 을 조율하지 못한다(합계 ~16.5GB > 16GB, 늦게 적재된 쪽이 CPU 로 일부 밀림).
        # 사용 직후 VL 을 내려 qwen3:14b 가 VL 옆에서 콜드 적재되는 시간대를 줄인다.
        keep_alive=os.getenv("VISION_KEEP_ALIVE", "2m").strip(),
        num_predict=_int("VISION_NUM_PREDICT", 768, 16),
        num_ctx=_int("VISION_NUM_CTX", 4096, 1024),
        temperature=_float("VISION_TEMPERATURE", 0.2),
        max_body_bytes=_int("VISION_MAX_BODY_BYTES", 2 * 1024 * 1024, 1024),
        max_image_bytes=_int("VISION_MAX_IMAGE_BYTES", 1024 * 1024, 1024),
        max_long_side=_int("VISION_MAX_LONG_SIDE", 1280, 64),
        min_side=_int("VISION_MIN_SIDE", 32, 1),
        max_pixels=_int("VISION_MAX_PIXELS", 1280 * 1280, 1024),
        max_question_chars=_int("VISION_MAX_QUESTION_CHARS", 1000, 1),
        max_answer_chars=_int("VISION_MAX_ANSWER_CHARS", 6000, 100),
        allowed_mimes=tuple(
            m.strip().lower() for m in os.getenv("VISION_ALLOWED_MIMES", "image/jpeg").split(",") if m.strip()
        ),
        max_concurrency=_int("VISION_MAX_CONCURRENCY", 1, 1),
        max_queue=_int("VISION_MAX_QUEUE", 8, 0),
        max_per_group=_int("VISION_MAX_PER_GROUP", 2, 1),
        queue_timeout_s=_float("VISION_QUEUE_TIMEOUT_SECONDS", 120.0, 0.1),
        inference_timeout_s=_float("VISION_INFERENCE_TIMEOUT_SECONDS", 90.0, 0.1),
        duplicate_ttl_s=_float("VISION_DUPLICATE_TTL_SECONDS", 600.0, 0.0),
        allow_unauthenticated=_bool("VISION_ALLOW_UNAUTHENTICATED", False),
        mock_delay_s=_float("VISION_MOCK_DELAY_SECONDS", 0.05),
        extract_num_predict=_int("VISION_EXTRACT_NUM_PREDICT", 1024, 64),
        extract_max_chars=_int("VISION_EXTRACT_MAX_CHARS", 8000, 500),
        answer_provider=os.getenv("VISION_ANSWER_PROVIDER", "openai").strip().lower(),
        answer_model=(os.getenv("VISION_ANSWER_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip(),
        answer_max_tokens=_int("VISION_ANSWER_MAX_TOKENS", 900, 64),
        answer_temperature=_float("VISION_ANSWER_TEMPERATURE", 0.2),
        answer_timeout_s=_float("VISION_ANSWER_TIMEOUT_SECONDS", 40.0, 0.1),
        answer_max_concurrency=_int("VISION_ANSWER_MAX_CONCURRENCY", 4, 1),
        answer_queue_timeout_s=_float("VISION_ANSWER_QUEUE_TIMEOUT_SECONDS", 15.0, 0.1),
        answer_daily_token_cap=_int("VISION_ANSWER_DAILY_TOKEN_CAP", 600_000, 0) or 600_000,
        external_llm_enabled=_bool("VISION_EXTERNAL_LLM_ENABLED", True),
        total_timeout_s=_float("VISION_TOTAL_TIMEOUT_SECONDS", 240.0, 1.0),
        answer_mock_delay_s=_float("VISION_ANSWER_MOCK_DELAY_SECONDS", 0.02),
    )
