"""
C 기반 빠른 퀴즈 fallback 실행기 (선택 사항, 후보 생성기).

C fallback은 LLM 대체 주 생성기가 아니라 65초 이후 90초 제한을 지키기 위한 후보 생성기다.
이 출력은 candidate이며, 반드시 validate_quiz_response(Python)를 통과해야 partial_validated로 표시한다.
바이너리가 없거나 실패하면 RuntimeError를 던지고, 호출부는 Python deterministic fallback으로 전환한다.
"""
import json
import logging
import os
import subprocess
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

FALLBACK_BIN = os.getenv(
    "FAST_QUIZ_FALLBACK_BIN",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "fast_quiz_fallback"),
)


def c_fallback_available() -> bool:
    """C fallback 바이너리가 실행 가능한 상태인지 확인."""
    return bool(FALLBACK_BIN) and os.path.isfile(FALLBACK_BIN) and os.access(FALLBACK_BIN, os.X_OK)


def run_c_quiz_fallback(
    difficulty: str,
    count: int,
    concepts: List[str],
    timeout_sec: int = 3,
) -> Dict[str, Any]:
    """
    PDF context concepts 로 C fallback 후보 문제를 만든다.
    concepts 가 비어 있으면 실행하지 않고 RuntimeError(Python fallback 으로 전환 유도).
    """
    safe_difficulty = difficulty if difficulty in {"easy", "normal", "hard"} else "normal"
    safe_count = max(5, min(int(count or 10), 20))

    safe_concepts: List[str] = []
    for c in concepts or []:
        text = str(c).strip()
        if text and len(text) <= 80:
            safe_concepts.append(text)
    safe_concepts = safe_concepts[:20]

    if not safe_concepts:
        raise RuntimeError("C fallback skipped: no PDF-based concepts")

    concept_arg = "|".join(safe_concepts)
    if len(concept_arg) > 3000:
        concept_arg = concept_arg[:3000]

    if not c_fallback_available():
        raise RuntimeError(f"C fallback binary not found/executable: {FALLBACK_BIN}")

    proc = subprocess.run(
        [FALLBACK_BIN, safe_difficulty, str(safe_count), concept_arg],
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"C fallback failed: {proc.stderr[:500]}")

    try:
        data = json.loads(proc.stdout)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"C fallback returned invalid JSON: {proc.stdout[:500]}") from exc

    data["fallback_used"] = True
    data["fallback_type"] = "C_LOCAL"
    data["candidate_only"] = True
    return data
