"""
학습 왕복 루프 단위 테스트 (LLM/DB 불필요 — 컨텍스트 결합 + 정규화 + 디스패치).

pytest: cd ~/capstoneLLM/fastapi && .venv/bin/python -m pytest tests/test_learning_loop.py -q
plain : cd ~/capstoneLLM/fastapi && .venv/bin/python -m tests.test_learning_loop
"""
from datetime import date, timedelta

from app.api.learning_loop_routes import LearningLoopContext, LearningLoopRequest
from app.services import learning_loop_service as svc


# ── resolve_material_id ───────────────────────────────────────────────────────
def test_resolve_material_id():
    assert svc.resolve_material_id(10, None) == 10
    assert svc.resolve_material_id(None, "doc_7") == 7
    assert svc.resolve_material_id(None, "12") == 12
    assert svc.resolve_material_id(None, None) is None
    assert svc.resolve_material_id(None, "folder-abc") is None


# ── 컨텍스트 결합 + usedContext 플래그 (RAG/DB 미사용 경로) ──────────────────────
def test_assemble_context_flags():
    req = LearningLoopRequest(
        taskType="AI_CHAT_WITH_LEARNING_LOOP",
        userQuestion="",          # 빈 질문 + materialId None → RAG 미호출(DB 미접근)
        materialId=None,
        learningLoopContext=LearningLoopContext(
            summaries=[{"title": "안드로이드 요약", "content": "Activity, Intent 설명"}],
            wrongNotes=[{"question": "Activity의 역할은?", "userAnswer": "DB 관리",
                         "correctAnswer": "화면/상호작용", "explanation": "UI 단위"}],
            userMemos=["Activity와 Fragment 차이가 헷갈림"],
        ),
    )
    text, used, chunks = svc.assemble_context(req)
    assert used["summaryUsed"] is True
    assert used["wrongNotesUsed"] is True
    assert used["userMemosUsed"] is True
    assert used["quizResultsUsed"] is False
    assert used["ragUsed"] is False
    assert "오답노트" in text and "사용자 메모" in text
    assert chunks == []


def test_assemble_context_sourcetext_sets_grounding():
    req = LearningLoopRequest(taskType="SUMMARY_WITH_LEARNING_LOOP",
                              sourceText="Retrofit2는 REST API 호출을 인터페이스로 정의한다.")
    text, used, _ = svc.assemble_context(req)
    assert used["ragUsed"] is True
    assert "sourceText" in text


# ── 퀴즈 item 정규화 ──────────────────────────────────────────────────────────
def test_normalize_quiz_item_ok():
    item = svc._normalize_quiz_item({
        "question": "Activity의 역할은?",
        "choices": ["UI 화면 단위", "DB 테이블 생성", "포트 개방", "커널 수정"],
        "answer": "UI 화면 단위",
        "explanation": "Activity는 화면 단위 구성 요소다.",
    })
    assert item is not None
    assert item["answerIndex"] == 0
    assert item["answer"] == "UI 화면 단위"


def test_normalize_quiz_item_by_index():
    item = svc._normalize_quiz_item({
        "question": "Q?", "choices": ["A", "B", "C", "D"],
        "answerIndex": 2, "explanation": "C 이유",
    })
    assert item is not None and item["answer"] == "C" and item["answerIndex"] == 2


def test_normalize_quiz_item_reject():
    # 보기 3개 → reject
    assert svc._normalize_quiz_item({"question": "Q", "choices": ["A", "B", "C"],
                                     "answerIndex": 0, "explanation": "x"}) is None
    # 정답이 보기에 없음 → reject
    assert svc._normalize_quiz_item({"question": "Q", "choices": ["A", "B", "C", "D"],
                                     "answer": "Z", "explanation": "x"}) is None


# ── 복습일 계산 ────────────────────────────────────────────────────────────────
def test_review_date_and_clamp():
    expected = (date.today() + timedelta(days=3)).isoformat()
    assert svc._review_date(3) == expected
    assert svc._clamp_days("5", 3) == 5
    assert svc._clamp_days(None, 3) == 3
    assert svc._clamp_days(999, 3) == 30
    assert svc._clamp_days(0, 3) == 1


# ── 디스패치: 미지원 taskType ─────────────────────────────────────────────────
def test_unsupported_task_type():
    req = LearningLoopRequest(taskType="NOPE")
    out = svc.run_learning_loop(req)
    assert out["success"] is False
    assert out["errorCode"] == "UNSUPPORTED_TASK_TYPE"
    assert "usedContext" in out and "warnings" in out


def test_supported_task_types_registered():
    for t in ("AI_CHAT_WITH_LEARNING_LOOP", "SUMMARY_WITH_LEARNING_LOOP",
              "QUIZ_WITH_LEARNING_LOOP", "ROADMAP_WITH_LEARNING_LOOP",
              "WRONG_NOTE_EXPLANATION", "SIMILAR_QUESTION_FROM_WRONG_NOTE",
              "REVIEW_RECOMMENDATION", "AGENT_CHAT_WITH_FEEDBACK"):
        assert t in svc.SUPPORTED_TASK_TYPES


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
