"""레거시 _auto_score 재현: 길이/키워드 휴리스틱 + 무조건 사실성 +15 가 '틀린 답'을 auto_approved 로 만들었다.

- 기준 커밋(13dae5e4, origin/LLM-clean)의 원본 코드를 git 에서 그대로 읽어 실행해 재현한다(없으면 skip).
- 보완된 현재 코드는 같은 입력을 학습 승인으로 만들지 않는다.
"""
import asyncio
import subprocess
import types
from pathlib import Path

import pytest

BASE_SHA = "13dae5e4ddf76d040e978c1a4fc29e6ece53f0e2"
WRONG_Q = "이진 탐색의 시간 복잡도는 무엇이며 왜 그런가요? 자세히 알려주세요."
# 사실과 다른 답(이진 탐색은 O(log n)). 길이/키워드만 맞춘다.
WRONG_A = ("쉽게 예시로 설명하면, 이진 탐색의 시간 복잡도는 O(n^2) 입니다. 개념 원리로 보면 배열의 모든 원소 쌍을 "
           "비교하기 때문에 제곱 시간이 걸립니다. 이렇게 비유하면 모든 학생이 서로 악수하는 것과 같습니다. "
           "기본 작동 방식은 정렬 여부와 상관없이 동일하며, 따라서 큰 데이터에서는 매우 느립니다. 핵심은 제곱 시간입니다. "
           "결론적으로 데이터가 두 배가 되면 시간은 네 배가 되므로 대규모 검색에는 적합하지 않다고 정리할 수 있습니다.")


def _legacy_module():
    try:
        src = subprocess.run(["git", "show", f"{BASE_SHA}:fastapi/app/services/training_candidate_manager.py"],
                             cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001
        pytest.skip("git unavailable")
    if src.returncode != 0:
        pytest.skip("base commit not available (shallow checkout)")
    mod = types.ModuleType("legacy_tcm")
    exec(compile(src.stdout, "legacy_tcm.py", "exec"), mod.__dict__)
    return mod


def test_legacy_heuristic_auto_approves_factually_wrong_answer():
    legacy = _legacy_module()
    score = asyncio.run(legacy._auto_score(WRONG_Q, WRONG_A, "학사", "친절_설명형"))
    assert score >= legacy.AUTO_APPROVE_MIN == 90      # 틀린 답인데 '자동 승인' 점수
    # rag_grounding_score 인자를 받지도 않는다(승인 점수와 연결 안 됨)
    import inspect
    assert "rag_grounding_score" not in inspect.signature(legacy._auto_score).parameters


def test_legacy_factuality_points_are_unconditional():
    legacy = _legacy_module()
    a = asyncio.run(legacy._auto_score(WRONG_Q, WRONG_A, "학사", "친절_설명형"))
    b = asyncio.run(legacy._auto_score(WRONG_Q, WRONG_A.replace("O(n^2)", "O(log n)"), "학사", "친절_설명형"))
    assert a == b      # 정답/오답이 점수에 전혀 반영되지 않는다


def test_fixed_manager_never_auto_approves(monkeypatch):
    monkeypatch.setenv("AI_TRAINING_COLLECTION_ENABLED", "true")
    from app.services import training_candidate_manager as m
    score = asyncio.run(m._auto_score(WRONG_Q, WRONG_A, "학사", "친절_설명형"))
    assert score < m.AUTO_APPROVE_MIN               # 근거 신호 없으면 사실성 0점
    out = asyncio.run(m.collect_candidate(WRONG_Q, WRONG_A, rag_grounding_score=None))
    assert out["auto_approved"] is False and out["stored"] is False
    assert out["quality_status"] == "consent_required"


def test_fixed_manager_rag_score_is_wired():
    from app.services import training_candidate_manager as m
    lo = asyncio.run(m._auto_score(WRONG_Q, WRONG_A, "학사", "친절_설명형", rag_grounding_score=0.0))
    hi = asyncio.run(m._auto_score(WRONG_Q, WRONG_A, "학사", "친절_설명형", rag_grounding_score=1.0))
    assert hi - lo == 20


def test_fixed_manager_negative_feedback_revokes_duplicate(monkeypatch):
    from app.contracts.training_sample_v1 import compute_content_hash
    from app.services import training_candidate_manager as m
    from app.training_pipeline import candidate_service as cs
    from app.training_pipeline.repository import InMemoryTrainingRepository, set_repository
    from tests.lq_helpers import make_sample

    repo = InMemoryTrainingRepository()
    set_repository(repo)
    try:
        s = make_sample(1, question=WRONG_Q, answer=WRONG_A)
        r = asyncio.run(cs.collect_sample(repo, s))
        asyncio.run(cs.review(repo, r.candidate_id, decision="VERIFY", actor=cs.Actor("rev-1", "training_reviewer")))
        assert asyncio.run(repo.get(r.candidate_id)).state.value == "TRAIN_ELIGIBLE"
        monkeypatch.setenv("AI_TRAINING_COLLECTION_ENABLED", "false")   # 수집 OFF 여도 철회는 동작해야 한다
        out = asyncio.run(m.collect_candidate(WRONG_Q, WRONG_A, user_feedback_score=-1))
        assert out["quality_status"] == "revoked" and out["state"] == "REVOKED"
        assert asyncio.run(repo.find_by_content_hash(compute_content_hash(WRONG_Q, WRONG_A))).state.value == "REVOKED"
    finally:
        set_repository(None)
