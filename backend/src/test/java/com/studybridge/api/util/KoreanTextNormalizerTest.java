package com.studybridge.api.util;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/** 조사 확정·불릿·메타 괄호·문장 종결 보정 — 도메인 무관 규칙. */
class KoreanTextNormalizerTest {

    @Test void resolvesJosaByFinalConsonant() {
        assertEquals("기법을 코드 흐름 추적 중심으로", KoreanTextNormalizer.resolveJosa("기법을(를) 코드 흐름 추적 중심으로"));
        assertEquals("모델이 내부적으로", KoreanTextNormalizer.resolveJosa("모델이(가) 내부적으로"));
        assertEquals("정리가 필요하다", KoreanTextNormalizer.resolveJosa("정리이(가) 필요하다"));
        assertEquals("노트는", KoreanTextNormalizer.resolveJosa("노트은(는)"));
        assertEquals("점검과 비슷하지만", KoreanTextNormalizer.resolveJosa("점검과(와) 비슷하지만"));
        assertEquals("서울로 간다", KoreanTextNormalizer.resolveJosa("서울으로(로) 간다"));
        assertEquals("실습을", KoreanTextNormalizer.withJosa("실습", "을", "를"));
        assertEquals("정리를", KoreanTextNormalizer.withJosa("정리", "을", "를"));
        assertEquals("MSE를", KoreanTextNormalizer.withJosa("MSE", "을", "를"));
        assertEquals("선형회귀가", KoreanTextNormalizer.withJosa("선형회귀", "이", "가"));
    }

    @Test void cleanRemovesBulletsMetaParensAndPrefix() {
        assertEquals("선형회귀의 고급 회귀 기법을 코드 흐름 추적 중심으로 학습한다.",
                KoreanTextNormalizer.clean("[오늘 목표] 선형회귀의 • 고급 회귀 기법을(를) 코드 흐름 추적 중심으로 학습한다. (주차 흐름: 복습과 시험 대비)"));
        assertEquals("정리 노트 또는 비교 표", KoreanTextNormalizer.clean("정리 노트 또는 • 비교 표"));
        assertEquals("2026-04-01 입력 - 출력", KoreanTextNormalizer.clean("2026-04-01 입력 - 출력"));   // 하이픈은 보존
        assertArrayEquals(new String[]{"A을 B 중심으로 학습한다.", "최종 정리 및 회고"},
                KoreanTextNormalizer.splitWeekTheme("A을 B 중심으로 학습한다. (주차 흐름: 최종 정리 및 회고)"));
    }

    @Test void sentenceAndQuestionEndings() {
        assertEquals("핵심을 설명할 수 있다.", KoreanTextNormalizer.ensureSentenceEnd("핵심을 설명할 수 있다"));
        assertEquals("핵심을 설명할 수 있다.", KoreanTextNormalizer.ensureSentenceEnd("핵심을 설명할 수 있다."));
        assertEquals("핵심 구성 요소는 무엇인가?", KoreanTextNormalizer.ensureQuestionEnd("핵심 구성 요소는 무엇인가"));
        assertEquals("핵심 구성 요소는 무엇인가?", KoreanTextNormalizer.ensureQuestionEnd("핵심 구성 요소는 무엇인가."));
        assertEquals("왜 사용하는가?", KoreanTextNormalizer.ensureQuestionEnd("왜 사용하는가?"));
    }
}
