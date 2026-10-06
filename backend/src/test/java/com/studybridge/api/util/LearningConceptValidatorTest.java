package com.studybridge.api.util;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/** 개념명 vs 문장/예제/코드 조각 판별 — 도메인 문자열 하드코딩 없이 형태 신호만으로 동작해야 한다. */
class LearningConceptValidatorTest {

    @Test void acceptsShortNounPhraseConcepts() {
        for (String c : List.of("독립변수와 종속변수", "기본 선형회귀", "손실함수 / 평균제곱오차(MSE)", "경사하강법",
                "다중회귀분석", "머신러닝모델의성능평가지표", "정밀도(Precision)", "K평균", "F1 score",
                "Android Activity 생명주기", "View Model", "람다", "화면", "결과", "넘파이", "정확도")) {
            assertTrue(LearningConceptValidator.isConceptLike(c), c);
        }
    }

    @Test void rejectsExampleSentencesAndDescriptions() {
        // 회귀/클러스터링/분류 예제 문장(PDF 본문 조각) — 특정 단어가 아니라 서술 어미/조사 밀도/길이로 거부되어야 한다
        for (String s : List.of(
                "주택면적은관측불가능한잠재변수이다", "주택면적은독립변수이고", "거래가격은종속변수이다",
                "관측된데이터를통해독립변수와종속변수사이의관계를추정하는것",
                "데이터를서로유사한특성을가진그룹으로묶는것", "이산적인라벨값에따라데이터를분류하는것",
                "1에가까울수록좋은모델", "각변수의역할에대한설명", "무엇입니까?", "퍼셉트론에서딥러닝으로",
                "재현율(Recall)이중요한사례", "Recall이낮다 True인데못찾은것이많다(FN이크다)",
                "이 개념을 정리하고 예제를 직접 풀어 본다.", "선형회귀 코드 흐름을 따라가며 호출 순서를 메모한다")) {
            assertFalse(LearningConceptValidator.isConceptLike(s), s);
        }
    }

    @Test void rejectsCodeFragments() {
        for (String s : List.of("from sklearn.metrics import accuracy_score", "accuracy_score(y_test", "pred = pipe.predict(X_test)",
                "x_guesses = [0", "~ 사이의값", "Hit rate라고도함)")) {
            assertFalse(LearningConceptValidator.isConceptLike(s), s);
        }
    }

    @Test void splitKeepsOrderAndSeparatesFragments() {
        var split = LearningConceptValidator.split(List.of("선형회귀모델", "주택면적은독립변수이고", "다중회귀분석", "선형회귀모델"));
        assertEquals(List.of("선형회귀모델", "다중회귀분석"), split.accepted());
        assertEquals(List.of("주택면적은독립변수이고"), split.rejected());
    }

    @Test void scrubReplacesFragmentsWithTopicAndCleansBullets() {
        String frag = "관측된데이터를통해독립변수와종속변수사이의관계를추정하는것";
        assertEquals("선형회귀의 고급 회귀 기법을(를) 코드 흐름 추적 중심으로 학습한다. (주차 흐름: 복습과 시험 대비)",
                LearningConceptValidator.scrub("선형회귀의 • " + frag + "을(를) 코드 흐름 추적 중심으로 학습한다. (주차 흐름: 복습과 시험 대비)",
                        List.of(frag), "고급 회귀 기법"));
        assertEquals("고급 회귀 기법 코드 흐름 추적",
                LearningConceptValidator.scrub(frag + " 코드 흐름 추적", List.of(frag), "고급 회귀 기법"));
        // 조각이 없으면 불릿/공백 정리만
        assertEquals("선형회귀의 넘파이 관련 코드", LearningConceptValidator.scrub("선형회귀의 • 넘파이  관련 코드", List.of(), "x"));
    }

    @Test void scrubMatchesFragmentsRegardlessOfSpacing() {
        String frag = "데이터를서로유사한특성을가진그룹으로묶는것";
        assertEquals("선형회귀에서 고급 회귀 기법을(를) 사용하는 이유는 무엇인가?",
                LearningConceptValidator.scrub("선형회귀에서 데이터를 서로 유사한 특성을 가진 그룹으로 묶는 것을(를) 사용하는 이유는 무엇인가?",
                        List.of(frag), "고급 회귀 기법"));
        assertTrue(LearningConceptValidator.containsFragment("데이터를 서로 유사한 특성을 가진 그룹으로 묶는 것", frag));
        assertFalse(LearningConceptValidator.containsFragment("고급 회귀 기법", frag));
    }

    @Test void lexicalRelatednessIgnoresGenericAcademicWords() {
        List<String> anchors = List.of("고급 회귀 기법", "선형회귀");
        assertTrue(LearningConceptValidator.isLexicallyRelated("회귀계수", anchors));
        assertTrue(LearningConceptValidator.isLexicallyRelated("릿지 회귀", anchors));
        assertTrue(LearningConceptValidator.isLexicallyRelated("다중회귀분석", anchors));
        assertFalse(LearningConceptValidator.isLexicallyRelated("K-평균 군집화 기법", anchors));   // "기법"은 일반어
        assertFalse(LearningConceptValidator.isLexicallyRelated("의사결정나무 분류", anchors));
        assertFalse(LearningConceptValidator.isLexicallyRelated("개념 정리", anchors));
    }

    @Test void nearDuplicateDetectsTaskCopies() {
        assertTrue(LearningConceptValidator.isNearDuplicate("고급 회귀 기법 코드 흐름 추적", "고급회귀기법 코드흐름 추적"));
        assertTrue(LearningConceptValidator.duplicatesAny("선형회귀 핵심 개념 점검", List.of("1. 선형회귀 핵심 개념 점검")));
        assertFalse(LearningConceptValidator.isNearDuplicate("선형회귀", "고급 회귀 기법 코드 흐름 추적"));
    }

    @Test void relatedUsesLexicalOverlapOnly() {
        List<String> anchors = List.of("고급 회귀 기법", "선형회귀");
        assertTrue(LearningConceptValidator.isRelated("다중회귀분석", anchors));
        assertTrue(LearningConceptValidator.isRelated("선형회귀모델", anchors));
        assertFalse(LearningConceptValidator.isRelated("넘파이", anchors));
    }

    @Test void topicStripsRoadmapAndDayPrefixes() {
        assertEquals("고급 회귀 기법", LearningConceptValidator.topicOf("[로드맵 11주차 2일] 고급 회귀 기법"));
        assertEquals("고급 회귀 기법", LearningConceptValidator.topicOf("2일차 고급 회귀 기법"));
        assertEquals("공부 플래너", LearningConceptValidator.topicOf("공부 플래너"));
    }
}
