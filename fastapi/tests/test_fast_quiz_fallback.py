"""
fast_quiz_fallback (C 후보 생성기) 계약 테스트.

대상: app.fallback.c_fallback_runner.run_c_quiz_fallback / c_fallback_available
- C fallback 은 LLM 대체 주 생성기가 아니라 90초 제한을 지키기 위한 "후보(candidate)" 생성기다.
- 출력은 candidate_only=True 이며 화면 직접 노출 금지(반드시 Python validate 통과 후 partial_validated).
- concepts 가 (필터링 후) 비면 실행하지 않고 RuntimeError → 호출부 Python deterministic fallback 전환.

운영 로직은 수정하지 않는다. 이 테스트는 기존 동작을 고정(regression)만 한다.
바이너리(fast_quiz_fallback)가 빌드되어 있지 않은 환경에서는 해당 테스트를 skip 한다.
"""
import time

import pytest

from app.fallback.c_fallback_runner import (
    c_fallback_available,
    run_c_quiz_fallback,
)

# 바이너리가 없으면 C 실행 의존 테스트는 의미가 없으므로 skip.
_BIN_AVAILABLE = c_fallback_available()
requires_bin = pytest.mark.skipif(
    not _BIN_AVAILABLE,
    reason="fast_quiz_fallback C 바이너리가 빌드/실행 가능 상태가 아님",
)

CONCEPTS = ["FastAPI 의존성 주입", "Pydantic 모델", "라우터 분리"]


# ---------------------------------------------------------------------------
# 바이너리 존재 여부와 무관한 순수 Python 계약 (입력 검증/필터링)
# ---------------------------------------------------------------------------
def test_empty_concepts_raises_runtime_error():
    """concepts 가 비어 있으면 바이너리를 실행하지 않고 RuntimeError 를 던진다."""
    with pytest.raises(RuntimeError):
        run_c_quiz_fallback("easy", 5, [])


def test_blank_and_oversized_concepts_filtered_to_empty_raises():
    """
    계약 gotcha: 80자 초과 concept 는 truncate 가 아니라 filter-out 된다.
    공백/80자 초과만 들어오면 유효 concept 가 0개가 되어 RuntimeError.
    (주의: None 은 str(None)="None" 으로 살아남으므로 여기서 제외한다 — 실제 계약 반영.)
    """
    oversized = "가" * 81  # 80자 초과 → 제거 대상
    with pytest.raises(RuntimeError):
        run_c_quiz_fallback("normal", 10, ["", "   ", oversized])


# ---------------------------------------------------------------------------
# 바이너리 실행이 필요한 계약 (출력 스키마/난이도/카운트)
# ---------------------------------------------------------------------------
@requires_bin
def test_valid_run_returns_candidate_envelope():
    """정상 실행 시 candidate 메타데이터와 questions 리스트를 돌려준다."""
    data = run_c_quiz_fallback("easy", 5, CONCEPTS)

    assert data["success"] is True
    assert data["fallback_used"] is True
    assert data["fallback_type"] == "C_LOCAL"
    assert data["candidate_only"] is True  # 화면 직접 노출 금지 표식
    assert data["source_mode"] == "PDF_BASED"
    assert isinstance(data["questions"], list)
    assert len(data["questions"]) == 5


@requires_bin
def test_question_schema_and_source_trace():
    """각 문항은 필수 필드를 갖고 source_trace 는 PDF_BASED 근거를 남긴다."""
    data = run_c_quiz_fallback("easy", 5, CONCEPTS)

    for q in data["questions"]:
        assert q["question"]
        assert isinstance(q["choices"], list) and len(q["choices"]) == 4
        # 정답은 보기 중 하나여야 한다.
        assert q["correct_answer"] in q["choices"]
        assert q["explanation"]

        trace = q["source_trace"]
        assert trace["source_type"] == "PDF_BASED"
        assert trace["fallback"] == "C_LOCAL"
        assert isinstance(trace["concepts"], list) and trace["concepts"]


@requires_bin
def test_count_clamped_low_and_high():
    """count 는 [5, 20] 으로 클램프된다 (3 → 5, 50 → 20)."""
    low = run_c_quiz_fallback("normal", 3, CONCEPTS)
    assert len(low["questions"]) == 5
    assert low["applied_count"] == 5

    high = run_c_quiz_fallback("normal", 50, CONCEPTS)
    assert len(high["questions"]) == 20
    assert high["applied_count"] == 20


@requires_bin
def test_invalid_difficulty_normalized_to_normal():
    """허용되지 않은 난이도는 normal 로 정규화되어 실행된다."""
    data = run_c_quiz_fallback("impossible", 5, CONCEPTS)
    assert data["difficulty_applied"] == "normal"


@requires_bin
def test_hard_difficulty_includes_wrong_explanations():
    """hard 난이도 문항은 오답 해설(wrong_explanations)을 포함한다."""
    data = run_c_quiz_fallback("hard", 5, CONCEPTS)
    for q in data["questions"]:
        assert isinstance(q["wrong_explanations"], list)
        assert len(q["wrong_explanations"]) >= 1


@requires_bin
def test_concepts_capped_at_20_still_runs():
    """20개 초과 concepts 를 넘겨도 잘리고 정상 실행된다(상위 20개만 사용)."""
    many = [f"개념{i}" for i in range(30)]
    data = run_c_quiz_fallback("easy", 5, many)
    assert data["success"] is True
    assert len(data["questions"]) == 5


# ---------------------------------------------------------------------------
# 성능 회귀 가드 (후보 생성기는 90초 제한 보조용이므로 빨라야 한다)
# ---------------------------------------------------------------------------
@requires_bin
def test_performance_under_one_second():
    """C 후보 생성은 LLM 타임아웃 보조용이므로 단일 호출이 1초 미만이어야 한다."""
    start = time.perf_counter()
    run_c_quiz_fallback("normal", 20, CONCEPTS)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"C fallback 후보 생성이 너무 느림: {elapsed:.3f}s"
