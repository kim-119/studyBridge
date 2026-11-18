"""P0: 기억 회상 게이트가 정상 학습 질문을 가로채지 않는다(2026-09-16 감사)."""
import pytest

from app.services.memory_recall_service import classify_memory_intent, is_recall_intent

NORMAL = [
    "TCP에 대해 질문할게",
    "재귀함수에 대해 물어볼게요",
    "운영체제 스케줄링에 대해 질문이 있어요",
    "포인터에 대해 궁금한 게 있는데 물어봐도 돼?",
    "질문: 트랜잭션 격리수준에 대해 설명해줘",
    "이 질문에 대해 답해줘",
    "딥러닝 옵티마이저에 대해 자세히 알려줘. 질문이 많아서 미안",
    "정규화에 대해 설명해줘",
    "TCP가 뭐야?",
    "질문 하나만 할게. 힙 정렬이 뭐야?",
]
RECALL = [
    "내가 아까 TCP에 대해 질문한 것 같은데?",
    "이전에 재귀에 대해 물어봤던 거 뭐였지?",
    "예전에 포인터에 관해 질문했었나?",
    "전에 스케줄링 관련해서 물어본 적 있어?",
    "내 첫 질문이 뭐였어?",
    "마지막 질문 다시 보여줘",
    "내가 두 번째로 물어본 게 뭐야?",
]


@pytest.mark.parametrize("msg", NORMAL)
def test_normal_learning_questions_are_not_recall(msg):
    intent, _ = classify_memory_intent(msg)
    assert not is_recall_intent(intent), (msg, intent)


@pytest.mark.parametrize("msg", RECALL)
def test_real_recall_questions_are_recall(msg):
    intent, _ = classify_memory_intent(msg)
    assert is_recall_intent(intent), (msg, intent)


def test_recall_requires_usable_history(monkeypatch):
    """회상 의도라도 previousAnswers 가 없으면 LLM 경로(v2 파이프라인)로 간다."""
    from app.schemas.multi_chat_schema import MultiChatRequest
    from app.services import orchestrator_service as O
    from app.studymate import basic_pipeline as BP

    called = {}

    def fake_turn(request, agents, **kw):
        called["v2"] = True
        yield {"event": "all_complete", "data": {"type": "all_complete", "answers": []}}

    monkeypatch.setattr(BP, "run_basic_turn", fake_turn)
    req = MultiChatRequest(message="내 첫 질문이 뭐였어?", mode="basic", agents=[{"agentId": 1, "name": "a"}])
    events = list(O.build_orchestrator_stream(req, req.agents))
    assert called.get("v2") is True
    assert not any((e["data"] or {}).get("route") == "memory_recall" for e in events)
