"""
오답노트/그룹스터디 유사 퀴즈 생성 서비스 단위 테스트.
실제 Ollama 를 호출하지 않고 ask_ollama / is_ollama_available 를 monkeypatch 한다.
"""
import app.services.ollama_client as oc
from app.services import wrong_note_quiz_service as svc

GOOD_PAYLOAD = {
    "source": "wrong_note",
    "topic": "의사결정트리 엔트로피와 정보이득",
    "originalQuestion": "의사결정트리에서 엔트로피와 정보이득은 어떤 역할을 하는가?",
    "wrongAnswer": "엔트로피는 모델 정확도 자체를 뜻한다.",
    "correctAnswer": "엔트로피는 데이터 불순도를 나타내고, 정보이득은 분할 전후 불순도 감소량을 의미한다.",
    "explanation": "정보이득이 큰 특성을 선택해 노드를 분할하면 더 순수한 하위 집합을 만들 수 있다.",
    "sourceText": "엔트로피는 데이터의 무질서도를 측정하는 척도이며, 정보이득은 입력변수별 목표변수 "
                  "분류 시 불순도 감소량을 계산하여 가장 유리한 변수를 선택하는 기준이다.",
    "requestedCount": 2,
    "difficulty": "basic",
}

FAKE_GOOD_JSON = (
    '{"questions":[ '
    '{"question":"엔트로피 값이 0에 가까울수록 노드의 상태로 옳은 것은?",'
    '"choices":["불순도가 매우 낮다","불순도가 매우 높다","정보이득이 항상 음수가 된다","분할이 불가능하다"],'
    '"answerIndex":0,"answer":"불순도가 매우 낮다",'
    '"explanation":"엔트로피가 0이면 한 클래스로만 구성되어 불순도가 가장 낮다.",'
    '"sourceHint":"엔트로피=불순도 척도 정의 변형"},'
    '{"question":"정보이득이 가장 큰 특성을 분할 기준으로 선택하는 이유로 옳은 것은?",'
    '"choices":["분할 전후 불순도 감소가 가장 크기 때문","트리 깊이를 늘리기 위해","계산량을 줄이기 위해","과적합을 늘리기 위해"],'
    '"answerIndex":0,"answer":"분할 전후 불순도 감소가 가장 크기 때문",'
    '"explanation":"정보이득은 분할 전후 불순도 감소량이며 클수록 더 순수한 분할을 만든다.",'
    '"sourceHint":"정보이득 정의 변형"} ]}'
)


def _assert_contract(q):
    assert isinstance(q["choices"], list) and len(q["choices"]) == 4
    assert len(set(q["choices"])) == 4
    assert isinstance(q["answerIndex"], int) and 0 <= q["answerIndex"] <= 3
    assert q["answer"] == q["choices"][q["answerIndex"]]
    assert q["question"].strip()
    assert q["explanation"].strip()


def test_wrong_note_similar_quiz_success_with_fake_ollama(monkeypatch):
    monkeypatch.setattr(oc, "is_ollama_available", lambda: True)
    monkeypatch.setattr(oc, "ask_ollama", lambda **kw: FAKE_GOOD_JSON)
    out = svc.generate_wrong_note_quiz(GOOD_PAYLOAD)
    assert out["success"] is True
    assert out["source"] == "ollama"
    assert out["grounded"] is True
    assert len(out["questions"]) >= 1
    for q in out["questions"]:
        _assert_contract(q)


def test_wrong_note_similar_quiz_no_source_returns_false(monkeypatch):
    # 근거 부족이면 Ollama 를 호출하지 않고 즉시 차단되어야 한다.
    def _boom(**kw):
        raise AssertionError("ask_ollama must not be called when source is insufficient")
    monkeypatch.setattr(oc, "is_ollama_available", lambda: True)
    monkeypatch.setattr(oc, "ask_ollama", _boom)
    out = svc.generate_wrong_note_quiz({"source": "wrong_note", "requestedCount": 3})
    assert out["success"] is False
    assert out["errorCode"] == "QUIZ_SOURCE_INSUFFICIENT"
    assert out["questions"] == []


def test_quiz_ollama_unavailable_no_hardcoded_fallback(monkeypatch):
    monkeypatch.setattr(oc, "is_ollama_available", lambda: False)
    monkeypatch.setattr(oc, "ask_ollama", lambda **kw: FAKE_GOOD_JSON)  # 사용되면 안 됨
    out = svc.generate_wrong_note_quiz(GOOD_PAYLOAD)
    assert out["success"] is False
    assert out["errorCode"] == "OLLAMA_UNAVAILABLE"
    assert out["questions"] == []


def test_quiz_ollama_failure_prose_no_hardcoded_fallback(monkeypatch):
    monkeypatch.setattr(oc, "is_ollama_available", lambda: True)
    monkeypatch.setattr(
        oc, "ask_ollama",
        lambda **kw: "현재 Ollama 서버(http://localhost:11434)에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.",
    )
    out = svc.generate_wrong_note_quiz(GOOD_PAYLOAD)
    assert out["success"] is False
    assert out["errorCode"] == "OLLAMA_UNAVAILABLE"
    assert out["questions"] == []


def test_quiz_json_repair(monkeypatch):
    calls = {"n": 0}

    def _fake(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return "유사 문제를 만들어 보겠습니다. 그런데 형식 출력에 실패했습니다 ..."  # 파싱 불가(실패 prose 아님)
        return FAKE_GOOD_JSON

    monkeypatch.setattr(oc, "is_ollama_available", lambda: True)
    monkeypatch.setattr(oc, "ask_ollama", _fake)
    out = svc.generate_wrong_note_quiz(GOOD_PAYLOAD)
    assert calls["n"] == 2  # 1차 실패 → repair 1회 수행
    assert out["success"] is True
    assert len(out["questions"]) >= 1


def test_quiz_contract_violation_filtered_then_fail(monkeypatch):
    # choices 가 3개인 위반 문항만 오면, 가짜 성공 없이 success=false 가 되어야 한다.
    bad = ('{"questions":[{"question":"엔트로피란?","choices":["a","b","c"],'
           '"answerIndex":0,"answer":"a","explanation":"e"}]}')
    monkeypatch.setattr(oc, "is_ollama_available", lambda: True)
    monkeypatch.setattr(oc, "ask_ollama", lambda **kw: bad)
    out = svc.generate_wrong_note_quiz(GOOD_PAYLOAD)
    assert out["success"] is False
    assert out["questions"] == []


def test_answer_index_resolved_from_text_when_index_missing(monkeypatch):
    # answerIndex 가 없고 answer 텍스트만 있을 때 인덱스를 복원해야 한다.
    j = ('{"questions":[{"question":"정보이득이 큰 특성을 고르는 이유로 옳은 것은?",'
         '"choices":["불순도 감소가 크다","계산이 빠르다","깊이가 깊다","무작위성"],'
         '"answer":"불순도 감소가 크다",'
         '"explanation":"정보이득은 분할 전후 불순도 감소량이다.","sourceHint":"정의 변형"}]}')
    monkeypatch.setattr(oc, "is_ollama_available", lambda: True)
    monkeypatch.setattr(oc, "ask_ollama", lambda **kw: j)
    out = svc.generate_wrong_note_quiz(GOOD_PAYLOAD)
    assert out["success"] is True
    q = out["questions"][0]
    assert q["answerIndex"] == 0
    assert q["answer"] == q["choices"][0]
