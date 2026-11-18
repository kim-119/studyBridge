import asyncio
from app.api import review_ai_routes as route


def test_count_three_is_sent_through_existing_single_question_generator(monkeypatch):
    calls = []
    def generate(body):
        calls.append(body)
        return {"questions": [{"question": body['_variant_focus'], "choices": ['a','b','c','d'], "correctAnswer": 'a'}], "error_code": None}
    monkeypatch.setattr(route, '_variant_sync', generate)
    result = asyncio.run(route.variant_question({'count': 3, 'original_question': '원본'}))
    assert len(calls) == result['requestedCount'] == result['returnedCount'] == len(result['questions']) == 3
    assert all(call['original_question'] == '원본' for call in calls)


def test_duplicates_are_not_counted_as_new_questions(monkeypatch):
    monkeypatch.setattr(route, '_variant_sync', lambda body: {'questions': [{'question': 'same'}]})
    result = asyncio.run(route.variant_question({'count': 3}))
    assert result['requestedCount'] == 3
    assert result['returnedCount'] == 1


def test_duplicate_topup_excludes_already_generated_questions(monkeypatch):
    calls = []
    def generate(body):
        calls.append(body)
        excluded = body.get('_variant_exclude', [])
        text = 'first' if not excluded else ('second' if 'second' not in excluded else 'third')
        return {'questions': [{'question': text}]}
    monkeypatch.setattr(route, '_variant_sync', generate)
    result = asyncio.run(route.variant_question({'count': 3}))
    assert result['returnedCount'] == 3
    assert len({q['question'] for q in result['questions']}) == 3
    assert any('first' in c['_variant_exclude'] for c in calls)
