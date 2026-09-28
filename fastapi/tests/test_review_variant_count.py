import asyncio

from app.api import review_ai_routes


def _fake_variant(body):
    slot = body.get("_slot", 0)
    return {
        "questions": [
            {
                "question": f"변형 문제 {slot + 1}",
                "choices": ["1", "2", "3", "4"],
                "correct_answer": "1",
                "explanation": "해설",
            }
        ],
        "difficulty_applied": body.get("difficulty", "normal"),
    }


def test_variant_question_returns_requested_count(monkeypatch):
    monkeypatch.setattr(review_ai_routes, "_variant_sync", _fake_variant)

    result = asyncio.run(review_ai_routes.variant_question({"count": 5, "difficulty": "hard"}))

    assert result["requested_count"] == 5
    assert result["generated_count"] == 5
    assert [item["question"] for item in result["questions"]] == [f"변형 문제 {index}" for index in range(1, 6)]


def test_variant_question_reports_shortfall_instead_of_padding(monkeypatch):
    def flaky_variant(body):
        if body.get("_slot") in (1, 3):
            raise RuntimeError("model failure")
        return _fake_variant(body)

    monkeypatch.setattr(review_ai_routes, "_variant_sync", flaky_variant)

    result = asyncio.run(review_ai_routes.variant_question({"count": 5}))

    assert result["requested_count"] == 5
    assert result["generated_count"] == 3


def test_variant_question_clamps_count_to_supported_range(monkeypatch):
    monkeypatch.setattr(review_ai_routes, "_variant_sync", _fake_variant)

    result = asyncio.run(review_ai_routes.variant_question({"count": 50}))

    assert result["generated_count"] == 5
