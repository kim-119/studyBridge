package com.studybridge.api.service.adaptive;

import static com.studybridge.api.service.adaptive.AdaptiveFixtures.OTHER;
import static com.studybridge.api.service.adaptive.AdaptiveFixtures.TODAY;
import static com.studybridge.api.service.adaptive.AdaptiveFixtures.USER;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.studybridge.api.entity.PlanAnalysisItem;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.PlannerType;
import com.studybridge.api.service.adaptive.AdaptivePlannerContextBuilder.Context;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Set;
import java.util.stream.Collectors;
import org.junit.jupiter.api.Test;

/** DB → 적응형 엔진 items 매핑(계약 11절): 유형 확정·단계 순서·완료 상태·체크리스트 과제·퀴즈 오답·마감일 ISO·소유권·basis. */
class AdaptivePlannerContextBuilderTest {

    private final AdaptiveFixtures f = new AdaptiveFixtures();

    @SuppressWarnings("unchecked")
    private static Map<String, Object> item(Context ctx, long id) {
        return ctx.items().stream().filter(i -> ((Long) i.get("id")) == id).findFirst().orElseThrow();
    }

    private void roadmap4() {
        // id 순서와 학습 순서가 다르게 넣는다(planner_id 로 순서를 판단하지 않는다).
        f.roadmapStep(14, USER, 2, 1, TODAY.plusDays(1));
        f.roadmapStep(11, USER, 1, 1, TODAY.minusDays(2));
        f.roadmapStep(13, USER, 1, 3, TODAY);
        f.roadmapStep(12, USER, 1, 2, TODAY.minusDays(1));
        f.roadmapStep(99, OTHER, 1, 1, TODAY); // 다른 사용자의 같은 로드맵 id
        f.checklist(f.planners.get(11L), true, true);           // 완료
        f.checklist(f.planners.get(12L), true, false);          // 진행 중
        List<PlanAnalysisItem> cur = f.checklist(f.planners.get(13L), true, false, false);
        cur.get(2).setHidden(true);                              // 숨김 과제는 보내지 않는다
    }

    @Test
    void roadmap_mapsSiblingsInLearningOrder_currentIsViewedStep_detailOnlyForCurrent() {
        roadmap4();
        Context ctx = f.builder.build(USER, 13L, null, TODAY);

        assertEquals("ROADMAP_COACH", ctx.mode());
        assertEquals(PlannerType.ROADMAP, ctx.plannerType());
        assertEquals(13L, ctx.currentStepId());
        assertEquals(List.of(11L, 12L, 13L, 14L), ctx.items().stream().map(i -> (Long) i.get("id")).toList());
        assertEquals(List.of(1, 2, 3, 4), ctx.items().stream().map(i -> (Integer) i.get("orderIndex")).toList());
        assertEquals("COMPLETED", item(ctx, 11).get("status"));
        assertEquals("IN_PROGRESS", item(ctx, 12).get("status"));
        assertEquals("IN_PROGRESS", item(ctx, 13).get("status"));
        assertEquals("PENDING", item(ctx, 14).get("status"));
        assertEquals(12L, ctx.suggestedStepId(), "첫 미완료 단계");
        assertEquals(TODAY.toString(), item(ctx, 13).get("scheduledDate"));

        Map<String, Object> current = item(ctx, 13);
        assertTrue(((String) current.get("description")).startsWith("필터가 입력 위를"));
        List<Map<String, Object>> tasks = (List<Map<String, Object>>) current.get("tasks");
        assertEquals(2, tasks.size(), "숨김 과제 제외");
        assertEquals(true, tasks.get(0).get("completed"));
        assertEquals(Map.of("completed", 1, "total", 3), current.get("progress"));
        assertFalse(item(ctx, 12).containsKey("tasks"), "현재 단계가 아닌 단계는 과제·설명을 보내지 않는다");
        assertFalse(item(ctx, 12).containsKey("description"));
        assertTrue(ctx.items().stream().noneMatch(i -> ((Long) i.get("id")) == 99L), "다른 사용자 플래너 제외");
    }

    @Test
    @SuppressWarnings("unchecked")
    void roadmap_stepWithoutChecklist_usesSavedRoadmapTasks_andGoalAsDescription() {
        Planner p = f.roadmapStep(41, USER, 12, 5, TODAY);
        p.setContent("[오늘 목표] 모멘텀 (Momentum)를 리팩토링 중심으로 학습한다. 이번 주는 최종 정리 단계이다.\n\n[할 일]\n"
                + "1. 모멘텀 (Momentum) 코드 흐름 추적: 관련 코드 흐름을 따라가며 호출 순서와 데이터 변화를 메모한다.\n"
                + "2. 아담 (Adam) 구조 비교: 대체 가능한 방식과 비교해 표로 정리한다.\n\n[체크포인트]\n- 설명할 수 있다");
        Context ctx = f.builder.build(USER, 41L, null, TODAY);
        Map<String, Object> cur = item(ctx, 41);
        assertEquals("모멘텀 (Momentum)를 리팩토링 중심으로 학습한다. 이번 주는 최종 정리 단계이다.", cur.get("description"));
        List<Map<String, Object>> tasks = (List<Map<String, Object>>) cur.get("tasks");
        assertEquals(2, tasks.size(), "다음 섹션([체크포인트])은 과제가 아니다");
        assertEquals("t41-1", tasks.get(0).get("id"));
        assertEquals("모멘텀 (Momentum) 코드 흐름 추적", tasks.get(0).get("text"));
        assertEquals(false, tasks.get(1).get("completed"));
        assertEquals("PENDING", cur.get("status"), "체크리스트가 없으면 완료로 추정하지 않는다");
        assertFalse(cur.containsKey("progress"));
    }

    @Test
    void roadmap_requestedStepMustBelongToSameRoadmap() {
        roadmap4();
        assertEquals(14L, f.builder.build(USER, 13L, 14L, TODAY).currentStepId());
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> f.builder.build(USER, 13L, 99L, TODAY));
        assertEquals("ADAPTIVE_STEP_NOT_IN_ROADMAP", e.getCode());
        assertThrows(AdaptivePlannerException.class, () -> f.builder.build(USER, 13L, 123456L, TODAY));
    }

    @Test
    void roadmap_completedViewedStep_isSentAsCompleted_notSwappedForAnotherStep() {
        roadmap4();
        Context ctx = f.builder.build(USER, 11L, null, TODAY);
        assertEquals(11L, ctx.currentStepId(), "완료된 단계를 다른 단계로 바꾸지 않는다(사용자 선택 대기)");
        assertEquals("COMPLETED", item(ctx, 11).get("status"));
        assertEquals(12L, ctx.suggestedStepId());
    }

    @Test
    void roadmap_quizWrongAnswers_fromRecentReviewNotes_withoutConceptTags() {
        roadmap4();
        f.reviewNote(501, USER, 345, LocalDateTime.of(2026, 10, 27, 10, 0),
                "[{\"question\":\"ReLU 의 출력 범위는?\",\"status\":\"WRONG\",\"concept\":\"ReLU\"},{\"question\":\"패딩의 역할은?\",\"status\":\"UNANSWERED\"}]");
        f.reviewNote(502, OTHER, 345, LocalDateTime.of(2026, 10, 27, 10, 0), "[{\"question\":\"남의 오답\"}]");
        f.reviewNote(503, USER, 345, LocalDateTime.of(2026, 6, 1, 10, 0), "[{\"question\":\"너무 오래된 오답\"}]");
        Context ctx = f.builder.build(USER, 13L, null, TODAY);

        assertEquals(2, ctx.quizResults().size());
        Map<String, Object> q = ctx.quizResults().get(0);
        assertEquals("rn501-1", q.get("questionId"));
        assertEquals(false, q.get("correct"));
        assertEquals("ReLU 의 출력 범위는?", q.get("question"));
        assertFalse(q.containsKey("conceptTags"), "AI 가 붙인 개념명을 태그로 보내지 않는다");
        assertFalse(q.containsKey("itemId"));
        assertTrue(ctx.quiz().available());
        assertEquals(2, ctx.quiz().wrongCount());
        assertEquals(1, ctx.quiz().reviewNoteCount());
    }

    @Test
    void roadmap_withoutQuizData_sendsNoQuizResults() {
        roadmap4();
        Context ctx = f.builder.build(USER, 13L, null, TODAY);
        assertTrue(ctx.quizResults().isEmpty());
        assertEquals(0, ctx.quiz().wrongCount());
    }

    @Test
    void manual_window_isoDueDates_priorityLabels_completedKept_roadmapAndStaleExcluded() {
        Planner viewed = f.userPlanner(21, USER, "Java 예외 처리 복습", TODAY.plusDays(1), "보통", "2026-10-31");
        f.userPlanner(22, USER, "SQLD 기출", TODAY, "높음", "D-1");
        Planner done = f.userPlanner(23, USER, "OSI 7계층", TODAY.minusDays(1), "낮음", null);
        f.checklist(done, true, true);
        f.userPlanner(24, USER, "미적분", TODAY.minusDays(3), "중요함", "9/27");
        f.userPlanner(25, USER, "작년 계획", TODAY.minusDays(200), "보통", null);
        f.userPlanner(26, OTHER, "남의 계획", TODAY, "긴급", null);
        f.roadmapStep(27, USER, 1, 1, TODAY);
        f.planners.get(22L).setGoalTime("1시간 30분");

        Context ctx = f.builder.build(USER, viewed.getId(), null, TODAY);
        assertEquals("MANUAL_NEXT", ctx.mode());
        assertNull(ctx.currentStepId());
        assertTrue(ctx.quizResults().isEmpty());
        Set<Long> ids = ctx.items().stream().map(i -> (Long) i.get("id")).collect(Collectors.toSet());
        assertEquals(Set.of(21L, 22L, 23L, 24L), ids);

        assertEquals("2026-10-31", item(ctx, 21).get("dueDate"));
        assertEquals("2026-10-29", item(ctx, 22).get("dueDate"), "D-1 은 플래너 날짜 기준 ISO 로 바꾼다");
        assertEquals("2026-09-27", item(ctx, 24).get("dueDate"));
        assertEquals("높음", item(ctx, 22).get("priority"));
        assertFalse(item(ctx, 24).containsKey("priority"), "알 수 없는 우선순위는 보내지 않는다(미지정)");
        assertEquals(90, item(ctx, 22).get("estimatedMinutes"));
        assertEquals("COMPLETED", item(ctx, 23).get("status"), "완료 항목은 COMPLETED 로 보내 엔진이 후보에서 뺀다");
        assertTrue(ctx.items().stream().noneMatch(i -> i.containsKey("orderIndex")), "수기 플래너에는 사용자 순서가 없다");
        assertEquals("2026-10-29", item(ctx, 21).get("scheduledDate"));
    }

    @Test
    void manual_rejectsCurrentStepSelection() {
        f.userPlanner(21, USER, "A", TODAY, "보통", null);
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> f.builder.build(USER, 21L, 5L, TODAY));
        assertEquals("ADAPTIVE_STEP_NOT_ALLOWED", e.getCode());
    }

    @Test
    void ownership_otherUsersPlanner403_missing404() {
        f.userPlanner(26, OTHER, "남의 계획", TODAY, "긴급", null);
        assertThrows(SecurityException.class, () -> f.builder.build(USER, 26L, null, TODAY));
        assertThrows(NoSuchElementException.class, () -> f.builder.build(USER, 777L, null, TODAY));
    }

    @Test
    void basisToken_isStableForSameData_andChangesWhenChecklistChanges() {
        roadmap4();
        String a = f.builder.build(USER, 13L, null, TODAY).basisToken();
        assertEquals(a, f.builder.build(USER, 13L, null, TODAY).basisToken());
        f.items.stream().filter(i -> i.getText().equals("과제 13-2")).findFirst().orElseThrow().setCompleted(true);
        assertNotEquals(a, f.builder.build(USER, 13L, null, TODAY).basisToken());
    }

    @Test
    void dueDate_unparseableOrOutOfRange_isOmitted_notInvented() {
        Planner p = f.userPlanner(31, USER, "A", TODAY, "보통", "시험 전까지");
        assertNull(AdaptivePlannerContextBuilder.dueDate(p, TODAY));
        p.setDDay("1999-01-01");
        assertNull(AdaptivePlannerContextBuilder.dueDate(p, TODAY));
        p.setDDay("D-7");
        assertEquals(TODAY.plusDays(7), AdaptivePlannerContextBuilder.dueDate(p, TODAY));
    }

    @Test
    void clip_removesControlAndBidiCharacters() {
        assertEquals("ab c", AdaptivePlannerContextBuilder.clip("a\u0000b‮   c", 100));
        assertNull(AdaptivePlannerContextBuilder.clip("  \u0007 ", 100));
    }
}
