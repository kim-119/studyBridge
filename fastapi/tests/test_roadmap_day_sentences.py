"""
로드맵 day 스켈레톤(build_day) 문장 품질 — LLM 호출 없음.

계약:
  - 개념 자리에는 개념명(명사구)만 들어간다. PDF 본문 설명문 조각은 core_concepts/템플릿에 끼우지 않는다.
  - 사용자 노출 문장에 조사 보정 표기("을(를)", "이(가)", "과(와)")·불릿("•")이 남지 않는다.
  - 복습 질문은 "?" 로, 체크포인트/objective 는 "." 로 끝나는 완결 문장이다.
"""
import pytest

from app.services.korean_text import clean_sentence, concept_keywords, is_concept_like, resolve_josa, with_josa
from app.services.study_action_router import build_day

FRAG = "관측된데이터를통해독립변수와종속변수사이의관계를추정하는것"
FRAG2 = "데이터를서로유사한특성을가진그룹으로묶는것"
ARTIFACTS = ["을(를)", "를(을)", "이(가)", "은(는)", "과(와)", "와(과)", "•"]


def _strings(day):
    out = [day["title"], day["objective"], day["practice"], day["checkpoint"], day["deliverable"]]
    out += day["review_questions"]
    for t in day["tasks"]:
        out += [t["title"], t["description"]]
    return out


def test_resolve_josa_by_final_consonant():
    assert resolve_josa("기법을(를) 코드 흐름 추적") == "기법을 코드 흐름 추적"
    assert resolve_josa("모델이(가) 내부적으로") == "모델이 내부적으로"
    assert resolve_josa("정리이(가) 필요하다") == "정리가 필요하다"
    assert resolve_josa("점검과(와) 비슷하지만") == "점검과 비슷하지만"
    assert with_josa("선형회귀", "이", "가") == "선형회귀가"
    assert with_josa("MSE", "을", "를") == "MSE를"
    assert clean_sentence("선형회귀의 • 고급 회귀 기법을(를) 학습한다.") == "선형회귀의 고급 회귀 기법을 학습한다."


def test_concept_keywords_drop_sentence_fragments():
    assert concept_keywords([FRAG, "회귀계수", FRAG2, "독립변수와 종속변수"]) == ["회귀계수", "독립변수와 종속변수"]
    assert not is_concept_like(FRAG) and is_concept_like("회귀계수")


def test_build_day_has_no_template_artifacts_and_uses_concept_names():
    day = build_day(2, subject="선형회귀", keywords=[FRAG, FRAG2, "회귀계수"], week=11, tasks_min=3)
    assert day["core_concepts"] == ["회귀계수"]
    for s in _strings(day):
        for bad in ARTIFACTS:
            assert bad not in s, s
        assert FRAG not in s and FRAG2 not in s, s
    for q in day["review_questions"]:
        assert q.endswith("?"), q
    assert day["checkpoint"].endswith("."), day["checkpoint"]
    assert day["objective"].startswith("선형회귀의 회귀계수를 "), day["objective"]


def test_build_day_falls_back_to_subject_when_all_keywords_are_fragments():
    day = build_day(1, subject="선형회귀", keywords=[FRAG, FRAG2], week=1, tasks_min=3)
    assert day["core_concepts"] == ["선형회귀"]
    for s in _strings(day):
        for bad in ARTIFACTS:
            assert bad not in s, s
