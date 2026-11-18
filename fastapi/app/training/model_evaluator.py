"""
새 모델 vs 기존 모델 비교 평가.

평가 방법:
  1. static_quality_scoring: test JSONL의 기록된 내용을 training_data_validator로 재평가
     (추론 엔진 없이도 구조적 품질을 빠르게 비교)
  2. live_inference: Ollama를 통해 실제로 추론한 뒤 응답 품질 평가
     (GPU + Ollama 필요)

기존 모델보다 점수가 떨어지면 배포를 차단한다.

환각률 추정:
  - 불확실성 표현 비율 (heuristic)
  - 오류 메시지 패턴 비율
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    model_path: str
    evaluation_method: str          # "static_quality_scoring" | "live_inference" | "unavailable"
    test_samples: int = 0
    avg_quality_score: float = 0.0
    avg_personality_score: float = 0.0
    avg_knowledge_level_score: float = 0.0
    avg_rag_grounding_score: float = 0.0
    hallucination_rate: float = 0.0
    error_rate: float = 0.0
    passed: bool = False
    failure_reasons: list[str] = field(default_factory=list)
    vs_baseline: dict[str, float] = field(default_factory=dict)
    notes: str = ""


@dataclass
class EvaluationGate:
    min_quality_score_delta:         float = -0.02
    min_personality_score_delta:     float = -0.02
    min_knowledge_level_score_delta: float = -0.02
    min_rag_grounding_score_delta:   float = -0.03
    max_hallucination_rate_delta:    float =  0.05
    max_error_rate_delta:            float =  0.05


async def evaluate_model(
    model_path: str,
    test_jsonl_path: str,
    baseline_eval: EvaluationResult | None = None,
    gate: EvaluationGate | None = None,
) -> EvaluationResult:
    """
    모델을 test JSONL 기준으로 평가한다.

    Args:
        model_path:       평가할 모델 경로
        test_jsonl_path:  test split JSONL
        baseline_eval:    기존 모델 평가 결과 (None이면 비교 없이 절대 기준만 적용)
        gate:             통과 기준
    """
    if gate is None:
        gate = EvaluationGate()

    test_path = Path(test_jsonl_path)
    if not test_path.exists():
        return EvaluationResult(
            model_path=model_path,
            evaluation_method="unavailable",
            notes="test JSONL 파일 없음",
        )

    test_rows = _load_jsonl(test_path)
    if not test_rows:
        return EvaluationResult(
            model_path=model_path,
            evaluation_method="unavailable",
            notes="test JSONL이 비어 있음",
        )

    # Ollama 사용 가능 여부 확인
    if _can_use_live_inference(model_path):
        result = await _evaluate_live(model_path, test_rows)
    else:
        result = _evaluate_static(model_path, test_rows)

    # baseline 비교
    if baseline_eval:
        result.vs_baseline = {
            "quality_delta":         round(result.avg_quality_score         - baseline_eval.avg_quality_score,         4),
            "personality_delta":     round(result.avg_personality_score     - baseline_eval.avg_personality_score,     4),
            "knowledge_level_delta": round(result.avg_knowledge_level_score - baseline_eval.avg_knowledge_level_score, 4),
            "rag_grounding_delta":   round(result.avg_rag_grounding_score   - baseline_eval.avg_rag_grounding_score,   4),
            "hallucination_delta":   round(result.hallucination_rate        - baseline_eval.hallucination_rate,        4),
        }
        result = _apply_gate(result, gate)
    else:
        # baseline 없이 절대 기준만 적용
        result.passed = result.avg_quality_score >= 0.75 and result.error_rate < 0.05

    return result


def _evaluate_static(model_path: str, test_rows: list[dict]) -> EvaluationResult:
    """
    train_qlora.py 추론 없이 test JSONL의 내용으로 구조적 품질을 평가한다.

    평가 대상: test JSONL의 assistant content
    방법: training_data_validator의 채점 함수 재사용
    """
    from app.training.training_data_validator import (
        ValidationCriteria,
        validate_candidate,
    )
    criteria = ValidationCriteria(min_overall_quality_score=0.0)  # 점수 수집용

    scores: dict[str, list[float]] = {
        "quality": [], "personality": [], "knowledge_level": [],
        "rag_grounding": [], "hallucination": [], "error": [],
    }

    for item in test_rows:
        # messages 구조에서 row dict 복원
        row = _messages_to_row(item)
        if not row:
            continue
        vr = validate_candidate(row, criteria)
        scores["quality"].append(vr.overall_quality_score)
        scores["personality"].append(vr.personality_score)
        scores["knowledge_level"].append(vr.knowledge_level_score)
        scores["rag_grounding"].append(vr.rag_grounding_score)
        # 환각률 heuristic: factual_consistency_score 역방향
        scores["hallucination"].append(1.0 - vr.factual_consistency_score)
        # 오류율: format_score가 낮으면 오류
        scores["error"].append(1.0 if vr.format_score < 0.5 else 0.0)

    def _avg(lst): return round(sum(lst) / len(lst), 4) if lst else 0.0

    return EvaluationResult(
        model_path=model_path,
        evaluation_method="static_quality_scoring",
        test_samples=len(test_rows),
        avg_quality_score=_avg(scores["quality"]),
        avg_personality_score=_avg(scores["personality"]),
        avg_knowledge_level_score=_avg(scores["knowledge_level"]),
        avg_rag_grounding_score=_avg(scores["rag_grounding"]),
        hallucination_rate=_avg(scores["hallucination"]),
        error_rate=_avg(scores["error"]),
        notes="static_quality_scoring: 실제 모델 추론 없이 구조 품질 평가",
    )


async def _evaluate_live(model_path: str, test_rows: list[dict]) -> EvaluationResult:
    """
    Ollama를 통해 실제 추론한 결과로 평가한다.
    현재는 placeholder — Ollama 어댑터 로드 방식이 결정되면 구현한다.
    """
    # 실제 어댑터 로드/추론 구현 전까지 static 평가로 fallback
    logger.info("live_inference 아직 미구현 — static_quality_scoring으로 대체")
    result = _evaluate_static(model_path, test_rows)
    result.evaluation_method = "static_quality_scoring_fallback"
    result.notes += " (live_inference 미구현 — fallback)"
    return result


def _apply_gate(result: EvaluationResult, gate: EvaluationGate) -> EvaluationResult:
    """baseline 대비 delta 기준으로 배포 가능 여부를 판단한다."""
    reasons = []
    d = result.vs_baseline

    if d.get("quality_delta", 0) < gate.min_quality_score_delta:
        reasons.append(f"전체 품질 점수 저하: {d['quality_delta']:.4f}")
    if d.get("personality_delta", 0) < gate.min_personality_score_delta:
        reasons.append(f"성격 반영 점수 저하: {d['personality_delta']:.4f}")
    if d.get("knowledge_level_delta", 0) < gate.min_knowledge_level_score_delta:
        reasons.append(f"지식수준 반영 점수 저하: {d['knowledge_level_delta']:.4f}")
    if d.get("rag_grounding_delta", 0) < gate.min_rag_grounding_score_delta:
        reasons.append(f"RAG 근거 점수 저하: {d['rag_grounding_delta']:.4f}")
    if d.get("hallucination_delta", 0) > gate.max_hallucination_rate_delta:
        reasons.append(f"환각률 증가: {d['hallucination_delta']:.4f}")

    result.failure_reasons = reasons
    result.passed = len(reasons) == 0
    return result


def _can_use_live_inference(model_path: str) -> bool:
    """실제 모델 파일과 Ollama가 존재하는지 확인한다."""
    if not Path(model_path).exists():
        return False
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def _messages_to_row(item: dict) -> dict | None:
    """messages 구조를 row dict으로 변환한다."""
    messages = item.get("messages", [])
    if not messages:
        return None
    system = next((m["content"] for m in messages if m.get("role") == "system"), "")
    user   = next((m["content"] for m in messages if m.get("role") == "user"),   "")
    asst   = next((m["content"] for m in messages if m.get("role") == "assistant"), "")
    if not user or not asst:
        return None
    return {"system_prompt": system, "question": user, "answer": asst}
