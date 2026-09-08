package com.studybridge.api.service;

import com.studybridge.api.dto.PlannerSemanticDTO.*;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/** 목표 정합성/요약 문장: 학습 목표 원문 결합·조사 보정 표기·메타 괄호·말줄임 노출 없이 완결 문장만 만든다. */
class PlannerGoalNarratorTest {

    private static final String GOAL = "선형회귀의 고급 회귀 기법을(를) 코드 흐름 추적 중심으로 학습한다. (주차 흐름: 복습과 시험 대비)";

    private Request req() {
        Request r = new Request();
        r.setTitle("[로드맵 2주차 2일] 고급 회귀 기법");
        r.setTopic("고급 회귀 기법");
        r.setSubject("선형회귀");
        r.setLearningGoal(GOAL);
        return r;
    }

    private Task task(String title, TaskType type) {
        Task t = new Task(); t.setTitle(title); t.setType(type); return t;
    }

    private List<Task> tasks() {
        return List.of(task("고급 회귀 기법 코드 흐름 추적", TaskType.PRACTICE),
                task("고급 회귀 기법 구조 비교", TaskType.COMPARISON),
                task("고급 회귀 기법 오류 원인 추론", TaskType.CONCEPT));
    }

    private static void assertNaturalSentence(String s) {
        assertNotNull(s);
        assertFalse(s.contains("(를)") || s.contains("(을)") || s.contains("(이)") || s.contains("(가)") || s.contains("(는)"), s);
        assertFalse(s.contains("주차 흐름"), s);
        assertFalse(s.contains("…") || s.contains("..."), s);
        assertFalse(s.contains("학습한다."), s);                        // 목표 원문 결합 금지
        assertTrue(s.endsWith("다.") || s.endsWith("요."), s);          // 완결 문장
        assertTrue(s.split("(?<=[.!?])\\s+").length <= 2, s);         // 1~2문장
    }

    @Test void alignmentSummaryIsGeneratedFromMeaningNotGoalText() {
        String s = PlannerGoalNarrator.alignmentSummary(req(), tasks(), Level.HIGH);
        assertNaturalSentence(s);
        assertEquals("현재 학습 활동은 고급 회귀 기법의 개념 이해, 코드 흐름 추적, 실습을 중심으로 구성되어 있어 학습 목표와 전반적으로 잘 연결되어 있습니다.", s);
        assertTrue(PlannerGoalNarrator.alignmentSummary(req(), tasks(), Level.LOW).contains("약한 편"));
    }

    @Test void alignmentSummaryWithoutTemplateGoalStillComplete() {
        Request r = new Request(); r.setTitle("자료구조 복습"); r.setTopic("자료구조 복습"); r.setLearningGoal("스택과 큐 복습");
        String s = PlannerGoalNarrator.alignmentSummary(r, List.of(task("스택 구현", TaskType.PRACTICE), task("큐 구현", TaskType.PRACTICE)), Level.MEDIUM);
        assertNaturalSentence(s);
        assertEquals("현재 학습 활동은 자료구조 복습의 실습을 중심으로 구성되어 있어 학습 목표와 대체로 잘 연결되어 있습니다.", s);
        assertNaturalSentence(PlannerGoalNarrator.alignmentSummary(new Request(), List.of(), Level.MEDIUM));
    }

    @Test void planSummaryAndTaskReasonDoNotEmbedGoal() {
        String s = PlannerGoalNarrator.planSummary(req(), tasks(), 115);
        assertNaturalSentence(s);
        assertTrue(s.contains("3개의 활동") && s.contains("115분"), s);
        String r = PlannerGoalNarrator.taskAlignmentReason(req(), TaskType.PRACTICE, Level.HIGH);
        assertNaturalSentence(r);
        assertEquals("실습 유형의 활동으로, 고급 회귀 기법에 대한 학습 목표와 직접 연결됩니다.", r);
    }

    @Test void aiProseWithGoalConcatenationIsRejected() {
        // 버그 재현: 목표 원문 + 고정 문구 결합
        assertNull(PlannerGoalNarrator.sanitizeAiProse("현재 학습 활동 대부분이 " + GOAL + " 이해와 연결되어 있습니다.", GOAL));
        assertNull(PlannerGoalNarrator.sanitizeAiProse("'" + GOAL + "'을(를) 향해 세부 학습이 배치되어 있습니다.", GOAL));
        // 말줄임 잘림 / 미완결
        assertNull(PlannerGoalNarrator.sanitizeAiProse("현재 목표(선형회귀의 고급 회귀 기법을 코드 흐름 추적 중심으…)와 연결됩니다.", GOAL));
        assertNull(PlannerGoalNarrator.sanitizeAiProse("학습 목표와 연결되어", GOAL));
        assertNull(PlannerGoalNarrator.sanitizeAiProse("  ", GOAL));
    }

    @Test void aiProseIsCleanedAndCappedAtTwoSentences() {
        String ok = PlannerGoalNarrator.sanitizeAiProse(
                "고급 회귀 기법이(가) 실습을(를) 통해 다뤄집니다. (주차 흐름: 복습과 시험 대비) 목표와 잘 맞습니다. 세 번째 문장입니다.", GOAL);
        assertEquals("고급 회귀 기법이 실습을 통해 다뤄집니다. 목표와 잘 맞습니다.", ok);
        assertNaturalSentence(ok);
        String good = "현재 학습 활동은 고급 회귀 기법의 개념 이해와 코드 흐름 추적을 중심으로 구성되어 있어 학습 목표와 전반적으로 잘 연결되어 있습니다.";
        assertEquals(good, PlannerGoalNarrator.sanitizeAiProse(good, GOAL));
    }

    @Test void josaAndGoalMethodHelpers() {
        assertEquals("모델을 학습한다", PlannerGoalNarrator.resolveJosa("모델을(를) 학습한다"));
        assertEquals("기법를 학습한다".replace("기법를", "기법을"), PlannerGoalNarrator.resolveJosa("기법을(를) 학습한다"));
        assertEquals("정리가 필요하다", PlannerGoalNarrator.resolveJosa("정리이(가) 필요하다"));
        assertEquals("서울로 간다", PlannerGoalNarrator.resolveJosa("서울으로(로) 간다"));
        assertEquals("실습을", PlannerGoalNarrator.withJosa("실습", "을", "를"));
        assertEquals("정리를", PlannerGoalNarrator.withJosa("정리", "을", "를"));
        assertEquals("MSE", PlannerGoalNarrator.withJosa("MSE", "을", "를"));
        assertEquals("코드 흐름 추적", PlannerGoalNarrator.goalMethod(GOAL));
        assertNull(PlannerGoalNarrator.goalMethod("스택과 큐 복습"));
        assertEquals("선형회귀의 고급 회귀 기법을 코드 흐름 추적 중심으로 학습한다.", PlannerGoalNarrator.clean("[오늘 목표] " + GOAL));
    }
}
