"""ModelRouter — 모델/컨텍스트/디코드/thinking 옵션의 단일 진입점.

이전에는 num_ctx 가 ollama_client 의 OLLAMA_CONTEXT_LENGTH(=4096) 상수로 고정됐고
level_policy.num_ctx() 는 정의만 있고 호출되지 않았다(prompt_eval_count==4096 절단 실측).

원칙
  - num_ctx 는 학습메이트 전 태스크가 '같은 값'을 쓴다. Ollama 는 num_ctx 가 바뀌면
    러너를 재적재하므로 태스크마다 다르게 주면 호출마다 모델 리로드가 발생한다.
  - 기본값은 벤치마크(docs/.. studymate-v2 benchmark)로 확정한 값이며 env 로만 바꾼다.
  - temperature 는 페르소나의 '보조축'이다(본체는 프롬프트 정책). persona_policy.DECODE 참조.
  - think 는 기본 False. 생략하면 qwen3 는 thinking 이 켜져 num_predict 를 소진한다(실측).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def model_name() -> str:
    return (os.getenv("STUDYMATE_MODEL") or os.getenv("OLLAMA_MODEL") or "qwen3:14b").strip()


def num_ctx() -> int:
    # 벤치마크 결정값(8192). 4096 은 페르소나/시스템 프롬프트가 잘리는 것이 실측됐다.
    return max(4096, _int("STUDYMATE_NUM_CTX", 8192))


# 태스크별 출력 예약(토큰). 지식수준이 깊을수록 렌더 출력이 길어진다.
_RENDER_PREDICT = {"beginner": 900, "bachelor": 1000, "master": 1200, "phd": 1400, "expert": 1400}
_TASK_PREDICT = {"planner": 1100, "judge": 220, "summary": 500, "classify": 120, "engine": 900}
_TASK_TIMEOUT = {"render": 75.0, "repair": 60.0, "planner": 45.0, "judge": 25.0,
                 "summary": 40.0, "classify": 15.0, "engine": 75.0}


@dataclass
class RouteOptions:
    model: str
    num_ctx: int
    num_predict: int
    temperature: float
    top_p: float
    seed: Optional[int]
    think: bool
    timeout_s: float
    task: str


def output_reserve(task: str, level: Optional[str]) -> int:
    if task in ("render", "repair"):
        return _int(f"STUDYMATE_PREDICT_{(level or 'bachelor').upper()}",
                    _RENDER_PREDICT.get(level or "bachelor", 1000))
    return _int(f"STUDYMATE_PREDICT_{task.upper()}", _TASK_PREDICT.get(task, 900))


def planner_think(level: Optional[str], complex_question: bool) -> bool:
    """planner 에서만, 그리고 복잡한 고수준 질문에서만 thinking 을 허용한다(env 로 끔/강제)."""
    mode = (os.getenv("STUDYMATE_PLANNER_THINK", "off") or "off").strip().lower()
    if mode == "on":
        return True
    if mode == "auto":
        return bool(complex_question and level in ("phd", "expert"))
    return False


def resolve(task: str = "render", level: Optional[str] = None, persona: Optional[str] = None,
            *, complex_question: bool = False, seed: Optional[int] = None) -> RouteOptions:
    from app.studymate import persona_policy

    decode = persona_policy.decode_policy(persona) if persona else None
    if task in ("render", "repair") and decode is not None:
        temperature, top_p = decode.temperature, decode.top_p
    elif task in ("planner", "judge", "classify"):
        temperature, top_p = _float("STUDYMATE_TEMP_STRUCTURED", 0.2), 0.9
    else:
        temperature, top_p = _float("STUDYMATE_TEMP_DEFAULT", 0.5), 0.9
    think = planner_think(level, complex_question) if task == "planner" else False
    return RouteOptions(
        model=model_name(), num_ctx=num_ctx(), num_predict=output_reserve(task, level),
        temperature=temperature, top_p=top_p, seed=seed, think=think,
        timeout_s=_float(f"STUDYMATE_TIMEOUT_{task.upper()}", _TASK_TIMEOUT.get(task, 60.0)),
        task=task,
    )
