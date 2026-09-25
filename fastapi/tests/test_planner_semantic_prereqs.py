"""
planner/analyze-semantic 선행 개념(prerequisites) 검증 — LLM 호출 없음(_no_llm).

계약:
  - 예제/설명 문장("~은 종속변수이다", "~을 추정하는 것")은 선행 개념으로 통과하지 않는다.
  - 오늘의 coreConcepts 를 선행 개념으로 복사하지 않는다(폴백은 priorConcepts 중 주제 연관 개념만).
  - prerequisites 는 tasks/flow 제목·학습 목표와 사실상 동일한 문자열을 갖지 않는다(독립).
  - includedInPlanTime 은 항상 False. recommendedMinutes 합은 targetMinutes 와 같다.
"""
import pytest

from app.api.planner_ai_routes import _analyze_semantic_sync, _is_concept_like, _validate_prereqs

FRAG = "관측된데이터를통해독립변수와종속변수사이의관계를추정하는것"
FRAG2 = "데이터를서로유사한특성을가진그룹으로묶는것"


@pytest.mark.parametrize("name", [
    "독립변수와 종속변수", "기본 선형회귀", "손실함수 / 평균제곱오차(MSE)", "경사하강법", "정밀도(Precision)", "람다", "넘파이",
])
def test_concept_like_accepts_noun_phrases(name):
    assert _is_concept_like(name)


@pytest.mark.parametrize("name", [
    "주택면적은관측불가능한잠재변수이다", "주택면적은독립변수이고", "거래가격은종속변수이다", FRAG, FRAG2,
    "이산적인라벨값에따라데이터를분류하는것", "1에가까울수록좋은모델", "무엇입니까?", "from sklearn.metrics import f1_score",
    "선형회귀 코드 흐름을 따라가며 호출 순서를 메모한다",
])
def test_concept_like_rejects_sentences_and_code(name):
    assert not _is_concept_like(name)


def _body():
    return {
        "plannerId": 1, "title": "[로드맵 2주차 2일] 고급 회귀 기법", "topic": "고급 회귀 기법", "subject": "선형회귀",
        "targetMinutes": 115, "sourceType": "ROADMAP",
        "learningGoal": "선형회귀의 고급 회귀 기법을(를) 코드 흐름 추적 중심으로 학습한다.",
        "content": "[오늘 목표] ...\n[할 일]\n1. 고급 회귀 기법 코드 흐름 추적",
        "coreConcepts": ["정규화"],
        "priorConcepts": ["넘파이", "선형회귀모델", "다중회귀분석"],
        "detailTasks": [
            {"id": "a", "title": "고급 회귀 기법 코드 흐름 추적", "description": "호출 순서를 메모한다"},
            {"id": "b", "title": "고급 회귀 기법 구조 비교", "description": "장단점을 표로 정리한다"},
            {"id": "c", "title": "고급 회귀 기법 오류 원인 추론", "description": "오류 상황을 정한다"},
        ],
        "_no_llm": True,
    }


def test_fallback_prerequisites_come_from_related_prior_concepts_not_today():
    r = _analyze_semantic_sync(_body())
    names = [p["name"] for p in r["prerequisites"]]
    assert names == ["선형회귀모델", "다중회귀분석"]          # 넘파이(비연관)·정규화(오늘 개념) 제외
    assert all(p["includedInPlanTime"] is False for p in r["prerequisites"])
    assert all("권장" in p["reason"] for p in r["prerequisites"])
    task_titles = {t["title"] for t in r["tasks"]}
    assert not (set(names) & task_titles) and not (set(names) & set(r["flow"]))
    assert sum(t["recommendedMinutes"] for t in r["tasks"]) == 115


def test_sentence_fragments_never_become_prerequisites():
    body = _body()
    body["coreConcepts"] = [FRAG, FRAG2]
    body["priorConcepts"] = [FRAG, "주택면적은독립변수이고", "선형회귀모델"]
    r = _analyze_semantic_sync(body)
    names = [p["name"] for p in r["prerequisites"]]
    assert names == ["선형회귀모델"]


def test_validate_prereqs_rejects_task_copies_and_goal_copies():
    forbidden = ["고급 회귀 기법 코드 흐름 추적", "선형회귀의 고급 회귀 기법을(를) 코드 흐름 추적 중심으로 학습한다."]
    out = _validate_prereqs([
        {"name": "독립변수와 종속변수", "reason": ""},
        {"name": "고급회귀기법 코드흐름 추적", "reason": "x"},
        {"name": "선형회귀의 고급 회귀 기법을(를) 코드 흐름 추적 중심으로 학습한다.", "reason": "x"},
        {"name": FRAG, "reason": "x"},
        {"name": "독립변수와 종속변수", "reason": "dup"},
    ], forbidden)
    assert [p["name"] for p in out] == ["독립변수와 종속변수"]
    assert out[0]["reason"]
