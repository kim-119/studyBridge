package com.studybridge.api.util;

import com.studybridge.api.util.LearningDayNormalizer.DayContent;
import com.studybridge.api.util.LearningDayNormalizer.DayInput;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 로드맵 day → 플래너 문장 재구성: 템플릿 조립 흔적 제거(A), 개념 정규화(B), 범주 혼합 차단(C), 완결 문장(D).
 * 실제 운영 RDS 에 저장돼 있던 깨진 데이터를 그대로 입력으로 쓴다(도메인 문자열 하드코딩 없이 동작해야 한다).
 */
class LearningDayNormalizerTest {

    static final String FRAG_REG = "관측된데이터를통해독립변수와종속변수사이의관계를추정하는것";
    static final String FRAG_CLU = "데이터를서로유사한특성을가진그룹으로묶는것";
    static final String FRAG_CLS = "이산적인라벨값에따라데이터를분류하는것";

    static DayInput realDay() {
        return new DayInput("2일차 고급 회귀 기법", "선형회귀",
                "선형회귀의 • " + FRAG_REG + "을(를) 코드 흐름 추적 중심으로 학습한다. (주차 흐름: 복습과 시험 대비)",
                List.of(FRAG_REG + " 코드 흐름 추적: 선형회귀의 • " + FRAG_REG + " 관련 코드 흐름을 따라가며 호출 순서와 데이터 변화를 메모한다",
                        FRAG_CLU + " 구조 비교: " + FRAG_CLU + "을(를) 대체 가능한 방식과 비교해 장단점과 선택 기준을 표로 정리한다",
                        FRAG_CLS + " 오류 원인 추론: " + FRAG_CLS + " 사용 시 발생하기 쉬운 오류 상황 1가지를 정하고 원인과 해결 가설을 적는다"),
                List.of(FRAG_REG, FRAG_CLU, FRAG_CLS),
                List.of(FRAG_REG + "의 핵심 구성 요소는 무엇인가?",
                        "선형회귀에서 데이터를 서로 유사한 특성을 가진 그룹으로 묶는 것을(를) 사용하는 이유는 무엇인가?",
                        FRAG_CLS + "이(가) 해결하는 문제는 무엇인가?"),
                FRAG_REG + "의 핵심을 본인 말로 설명할 수 있다",
                FRAG_REG + " 정리 노트 또는 • " + FRAG_CLU + " 비교 표");
    }

    static List<String> allUserFacing(DayContent c) {
        List<String> all = new ArrayList<>();
        all.add(c.objective()); all.addAll(c.tasks()); all.addAll(c.concepts()); all.addAll(c.reviewQuestions());
        all.add(c.checkpoint()); all.add(c.deliverable());
        return all;
    }

    static void assertNoTemplateArtifacts(String s) {
        assertNotNull(s);
        for (String bad : List.of("을(를)", "를(을)", "이(가)", "가(이)", "은(는)", "는(은)", "과(와)", "와(과)", "• ", "•", "(주차 흐름", "[오늘 목표]", "…"))
            assertFalse(s.contains(bad), "'" + bad + "' in: " + s);
        for (String frag : List.of(FRAG_REG, FRAG_CLU, FRAG_CLS))
            assertFalse(LearningConceptValidator.containsFragment(s, frag), "fragment in: " + s);
        assertFalse(s.matches(".*[가-힣]{18,}.*"), "unspaced run in: " + s);
    }

    @Test void A_noTemplateAssemblyArtifactsRemain() {
        DayContent c = LearningDayNormalizer.normalize(realDay());
        for (String s : allUserFacing(c)) assertNoTemplateArtifacts(s);
        assertEquals(3, c.rejectedFragments().size());
    }

    @Test void B_conceptsAreSemanticNamesDerivedFromTopicAndObjective() {
        DayContent c = LearningDayNormalizer.normalize(realDay());
        assertEquals(List.of("고급 회귀 기법", "선형회귀"), c.concepts());
        for (String concept : c.concepts()) {
            assertTrue(LearningConceptValidator.isConceptLike(concept), concept);
            assertTrue(concept.replace(" ", "").length() <= 15, concept);
        }
        // 설명문 전체가 개념으로 남지 않는다
        assertTrue(c.concepts().stream().noneMatch(x -> x.endsWith("것")));
    }

    @Test void C_unrelatedCategoryConceptsDoNotMixIntoRegressionDay() {
        // 형태는 개념명이지만 회귀 day 정체성과 이어지지 않는 클러스터링/분류 개념 + 연관 개념(릿지 회귀·회귀계수)
        DayInput in = new DayInput("[로드맵 11주차 2일] 고급 회귀 기법", "선형회귀",
                "선형회귀의 릿지 회귀을(를) 코드 흐름 추적 중심으로 학습한다.",
                List.of("릿지 회귀 코드 흐름 추적: 릿지 회귀 관련 코드 흐름을 따라간다",
                        "K-평균 군집화 구조 비교: K-평균 군집화을(를) 대체 가능한 방식과 비교한다",
                        "의사결정나무 분류 오류 원인 추론: 의사결정나무 분류 사용 시 오류를 정리한다"),
                List.of("릿지 회귀", "회귀계수", "K-평균 군집화", "의사결정나무 분류", FRAG_CLU),
                List.of("선형회귀에서 K-평균 군집화을(를) 사용하는 이유는 무엇인가?", "회귀계수의 핵심 구성 요소는 무엇인가?"),
                "릿지 회귀의 핵심을 본인 말로 설명할 수 있다", "릿지 회귀 정리 노트");
        DayContent c = LearningDayNormalizer.normalize(in);
        assertEquals(List.of("K-평균 군집화", "의사결정나무 분류"), c.unrelatedConcepts());
        assertEquals(List.of(FRAG_CLU), c.rejectedFragments());
        assertEquals(List.of("고급 회귀 기법", "선형회귀", "릿지 회귀", "회귀계수"), c.concepts());
        for (String s : allUserFacing(c)) {
            assertFalse(s.contains("군집화") || s.contains("의사결정나무"), s);
            assertNoTemplateArtifacts(s);
        }
        // 무관 개념으로 만든 문장은 day 주제어로 재구성된다(삭제가 아니라 재구성)
        assertEquals(3, c.tasks().size());
        assertEquals("선형회귀에서 고급 회귀 기법을 사용하는 이유는 무엇인가?", c.reviewQuestions().get(0));
    }

    @Test void D_questionsCheckpointDeliverableAreCompleteKoreanSentences() {
        DayContent c = LearningDayNormalizer.normalize(realDay());
        assertEquals(List.of("고급 회귀 기법의 핵심 구성 요소는 무엇인가?",
                        "선형회귀에서 고급 회귀 기법을 사용하는 이유는 무엇인가?",
                        "고급 회귀 기법이 해결하는 문제는 무엇인가?"), c.reviewQuestions());
        for (String q : c.reviewQuestions()) assertTrue(q.endsWith("?"), q);
        assertEquals("고급 회귀 기법의 핵심을 본인 말로 설명할 수 있다.", c.checkpoint());
        assertEquals("고급 회귀 기법 정리 노트 또는 고급 회귀 기법 비교 표", c.deliverable());
        assertEquals("선형회귀의 고급 회귀 기법을 코드 흐름 추적 중심으로 학습한다. 이번 주는 복습과 시험 대비 단계이다.", c.objective());
        assertEquals("고급 회귀 기법 코드 흐름 추적: 선형회귀의 고급 회귀 기법 관련 코드 흐름을 따라가며 호출 순서와 데이터 변화를 메모한다.", c.tasks().get(0));
        assertEquals("고급 회귀 기법 구조 비교: 고급 회귀 기법을 대체 가능한 방식과 비교해 장단점과 선택 기준을 표로 정리한다.", c.tasks().get(1));
    }

    @Test void objectiveWithoutTemplateAndCleanConceptsPassesThroughNaturally() {
        DayInput in = new DayInput("[로드맵 1주차 1일] 선형회귀란?", "선형회귀", "선형회귀의 기본 개념과 핵심 용어를 이해한다.",
                List.of("선형회귀의 기본 개념을 정리한다.", "독립변수와 종속변수의 역할을 확인한다."),
                List.of("독립변수와 종속변수", "회귀계수", "평균제곱오차(MSE)"),
                List.of("독립변수와 종속변수의 관계를 어떻게 설명할 수 있는가"),
                "독립변수와 종속변수의 관계를 설명할 수 있다", "선형회귀 핵심 개념 요약 노트");
        DayContent c = LearningDayNormalizer.normalize(in);
        assertFalse(c.hasRewrites());
        assertEquals("선형회귀의 기본 개념과 핵심 용어를 이해한다.", c.objective());
        assertEquals(List.of("선형회귀", "독립변수와 종속변수", "회귀계수", "평균제곱오차(MSE)"), c.concepts());
        assertEquals("독립변수와 종속변수의 관계를 어떻게 설명할 수 있는가?", c.reviewQuestions().get(0));
        assertEquals("독립변수와 종속변수의 관계를 설명할 수 있다.", c.checkpoint());
        assertEquals("선형회귀 핵심 개념 요약 노트", c.deliverable());
    }

    @Test void emptyConceptSlotsAreFilledWithDayTopic() {
        // 실제 사례: 로드맵 JSON 의 개념 슬롯이 빈 문자열 → "구조 비교: 을(를) …", "MVVM 1의를", "의 핵심을"
        DayInput in = new DayInput("[로드맵 12주차 6일] 최종 점검", "MVVM 1",
                "MVVM 1의 을(를) 실제 프로젝트 적용 중심으로 학습한다. (주차 흐름: 최종 정리 및 회고)",
                List.of("구조 비교: 을(를) 대체 가능한 방식과 비교해 장단점과 선택 기준을 표로 정리한다",
                        "동작 원리 분석: 이(가) 내부적으로 어떻게 동작하는지 입력·처리·출력 흐름으로 분석해 정리한다"),
                List.of("", "권한 요청"),
                List.of("MVVM 1에서 을(를) 사용하는 이유는 무엇인가?"),
                "의 핵심을 본인 말로 설명할 수 있다", " 정리 노트 또는 권한 요청 비교 표");
        DayContent c = LearningDayNormalizer.normalize(in);
        assertEquals("MVVM 1의 최종 점검을 실제 프로젝트 적용 중심으로 학습한다. 이번 주는 최종 정리 및 회고 단계이다.", c.objective());
        assertEquals("구조 비교: 최종 점검을 대체 가능한 방식과 비교해 장단점과 선택 기준을 표로 정리한다.", c.tasks().get(0));
        assertEquals("동작 원리 분석: 최종 점검이 내부적으로 어떻게 동작하는지 입력·처리·출력 흐름으로 분석해 정리한다.", c.tasks().get(1));
        assertEquals("MVVM 1에서 최종 점검을 사용하는 이유는 무엇인가?", c.reviewQuestions().get(0));
        assertEquals("최종 점검의 핵심을 본인 말로 설명할 수 있다.", c.checkpoint());
        assertEquals(List.of("최종 점검", "MVVM 1", "권한 요청"), c.concepts());
        for (String s : allUserFacing(c)) assertNoTemplateArtifacts(s);
        // 저장본 개념 목록에 "MVVM 1의" 처럼 조사가 붙은 채 남은 항목도 개념명으로 정리된다
        DayContent stored = LearningDayNormalizer.normalize(new DayInput("[로드맵 12주차 6일] 최종 점검", "MVVM 1",
                "MVVM 1의 최종 점검을 실제 프로젝트 적용 중심으로 학습한다.", List.of(), List.of("최종 점검", "MVVM 1의"), List.of(), "", ""));
        assertEquals(List.of("최종 점검", "MVVM 1"), stored.concepts());
        // "정의/논의" 처럼 '의'로 끝나는 단어는 잘리지 않는다
        assertEquals("회귀 문제 정의", LearningDayNormalizer.stripTrailingPossessive("회귀 문제 정의"));
        assertEquals("ViewModel", LearningDayNormalizer.stripTrailingPossessive("ViewModel의"));
        DayContent def = LearningDayNormalizer.normalize(new DayInput("[로드맵 5주차 1일] 회귀 문제 정의", "머신러닝",
                "머신러닝의 회귀 문제 정의를 개념 정의 이해 중심으로 학습한다.", List.of("회귀 문제 정의 핵심 개념 정리: 정의를 노트에 정리한다"),
                List.of("회귀 문제 정의", "ViewModel의 정의"), List.of("회귀 문제 정의가 해결하는 문제는 무엇인가?"), "", ""));
        assertEquals(List.of("회귀 문제 정의", "머신러닝", "ViewModel의 정의"), def.concepts());
        assertEquals("회귀 문제 정의가 해결하는 문제는 무엇인가?", def.reviewQuestions().get(0));
        assertEquals("머신러닝의 회귀 문제 정의를 개념 정의 이해 중심으로 학습한다.", def.objective());
        // 저장본 형태("MVVM 1의를", "MVVM 1에서를")도 같은 규칙으로 복구된다
        assertEquals("MVVM 1의 최종 점검을 실제 프로젝트 적용 중심으로 학습한다.",
                LearningDayNormalizer.rewrite("MVVM 1의를 실제 프로젝트 적용 중심으로 학습한다.", List.of(), "최종 점검"));
        assertEquals("MVVM 1에서 최종 점검을 사용하는 이유는 무엇인가?",
                LearningDayNormalizer.rewrite("MVVM 1에서를 사용하는 이유는 무엇인가?", List.of(), "최종 점검"));
    }

    @Test void reviewDayWithOnlyFragmentsFallsBackToTopicAndSubject() {
        // 12주차 복습 day: core_concepts 가 전부 설명문 조각인 실제 사례
        DayInput in = new DayInput("[로드맵 12주차 7일] 시험 전 최종 점검", "선형회귀",
                "선형회귀의 거래가격은종속변수이다을(를) 응용 문제와 복습 중심으로 학습한다. (주차 흐름: 최종 정리 및 회고)",
                List.of("거래가격은종속변수이다 오류 원인 추론: 거래가격은종속변수이다 사용 시 발생하기 쉬운 오류 상황 1가지를 정하고 원인과 해결 가설을 적는다",
                        "두변수모두다른변수에영향을받지않는독립변수이다 간단 리팩토링: 두변수모두다른변수에영향을받지않는독립변수이다을(를) 쓰는 예제 코드를 더 읽기 쉽게 한 부분 리팩토링하고 이유를 적는다"),
                List.of("거래가격은종속변수이다", "두변수모두다른변수에영향을받지않는독립변수이다", "어떤값이원인이되고어떤값이결과가되는지생각해보세요"),
                List.of("거래가격은종속변수이다과(와) 비슷하지만 다른 개념은 무엇이고 어떻게 구분하는가?"),
                "거래가격은종속변수이다의 핵심을 본인 말로 설명할 수 있다",
                "거래가격은종속변수이다 정리 노트 또는 • 두변수모두다른변수에영향을받지않는독립변수이다 비교 표");
        DayContent c = LearningDayNormalizer.normalize(in);
        assertEquals(3, c.rejectedFragments().size());
        assertEquals(List.of("시험 전 최종 점검", "선형회귀"), c.concepts());
        assertEquals("선형회귀의 시험 전 최종 점검을 응용 문제와 복습 중심으로 학습한다. 이번 주는 최종 정리 및 회고 단계이다.", c.objective());
        assertEquals("시험 전 최종 점검과 비슷하지만 다른 개념은 무엇이고 어떻게 구분하는가?", c.reviewQuestions().get(0));
        for (String s : allUserFacing(c)) {
            assertFalse(s.contains("(를)") || s.contains("(와)") || s.contains("•"), s);
            assertFalse(s.matches(".*[가-힣]{18,}.*"), s);
        }
    }
}
