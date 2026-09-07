package com.studybridge.api.service;

import com.studybridge.api.dto.PlannerSemanticDTO.*;
import com.studybridge.api.entity.Planner;
import com.lowagie.text.pdf.PdfReader;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/** 시간 정규화 + LocalTime 시간표 결정성 + 한글 시간표 PDF 렌더링 검증. */
class PlannerScheduleVerificationTest {

    private final PlannerTimeAllocator allocator = new PlannerTimeAllocator();

    @Test void normalizesToTargetExactlyKeepingRatioAndMinimumOne() {
        // AI 비율 20/20/30/20/20/20(=130) 이지만 target=125 → 정확히 125, 순서 유지, 0/음수 없음
        List<Integer> out = allocator.normalize(List.of(20, 20, 30, 20, 20, 20), 125);
        assertEquals(125, out.stream().mapToInt(Integer::intValue).sum());
        assertEquals(6, out.size());
        out.forEach(m -> assertTrue(m >= 1));
        // 가장 큰 비중(index 2, weight 30)이 정규화 후에도 최대값을 유지
        int max = out.stream().mapToInt(Integer::intValue).max().orElse(0);
        assertEquals(max, out.get(2).intValue());
    }

    @Test void exactMatchIsPreserved() {
        List<Integer> out = allocator.normalize(List.of(20, 20, 30, 20, 20, 15), 125);
        assertEquals(List.of(20, 20, 30, 20, 20, 15), out);
    }

    @Test void noTargetUsesAiEstimate() {
        List<Integer> out = allocator.normalize(List.of(20, 20, 15), null);
        assertEquals(List.of(20, 20, 15), out);
    }

    @Test void scheduleComputesLocalTimeDeterministicallyAndReactsToStartTimeWithoutAi() {
        PlannerSemanticAnalyzer analyzer = mock(PlannerSemanticAnalyzer.class);
        PlannerAnalysisContext context = mock(PlannerAnalysisContext.class);
        S3Service s3 = mock(S3Service.class);
        PlannerScheduleService svc = new PlannerScheduleService(analyzer, context, new PlannerSchedulePdfRenderer(), s3);

        Planner planner = Planner.builder().id(7L).userId(1L).title("[로드맵 11주차 2일] 고급 회귀 기법")
                .plannerDate(LocalDate.of(2026, 9, 8)).build();
        when(context.owned(1L, 7L)).thenReturn(planner);
        when(analyzer.ensure(1L, 7L)).thenReturn(analysis());

        Schedule at9 = svc.schedule(1L, 7L, "09:00");
        assertEquals(125, at9.totalMinutes());
        assertEquals(6, at9.rows().size());
        assertEquals("09:00", at9.rows().get(0).startTime());
        assertEquals("09:20", at9.rows().get(0).endTime());
        assertEquals("09:40", at9.rows().get(2).startTime());   // 20+20
        assertEquals("10:10", at9.rows().get(2).endTime());     // +30
        assertEquals("11:05", at9.rows().get(5).endTime());     // 최종 종료

        // 시작시간만 14:00 으로 바꿔도 AI 재호출 없이 동일 duration 으로 재계산
        Schedule at14 = svc.schedule(1L, 7L, "14:00");
        assertEquals("14:00", at14.rows().get(0).startTime());
        assertEquals("16:05", at14.rows().get(5).endTime());
        verify(analyzer, never()).analyze(anyLong(), anyLong());  // 시간 변경은 결정적 계산만
    }

    @Test void rejectsBadStartTime() {
        PlannerAnalysisContext context = mock(PlannerAnalysisContext.class);
        PlannerSemanticAnalyzer analyzer = mock(PlannerSemanticAnalyzer.class);
        when(context.owned(1L, 7L)).thenReturn(Planner.builder().id(7L).userId(1L).title("t").build());
        when(analyzer.ensure(1L, 7L)).thenReturn(analysis());
        PlannerScheduleService svc = new PlannerScheduleService(
                analyzer, context, new PlannerSchedulePdfRenderer(), mock(S3Service.class));
        assertThrows(IllegalArgumentException.class, () -> svc.schedule(1L, 7L, "25:00"));
        assertThrows(IllegalArgumentException.class, () -> svc.schedule(1L, 7L, "9am"));
    }

    @Test void rendersReadableKoreanSchedulePdfWithDynamicRowsOnly() throws Exception {
        Schedule schedule = new Schedule(7L, "[로드맵 11주차 2일] 고급 회귀 기법", "2026.09.08", 125, "09:00", rows());
        byte[] pdf = new PlannerSchedulePdfRenderer().render(
                schedule, "[로드맵 11주차 2일] 고급 회귀 기법", "2026.09.08");
        assertNotNull(pdf);
        assertTrue(pdf.length > 800);
        PdfReader reader = new PdfReader(pdf);
        assertTrue(reader.getNumberOfPages() >= 1);
        reader.close();
        Path out = Path.of("/tmp/schedule_test.pdf");
        Files.write(out, pdf);
        System.out.println("WROTE_PDF=" + out.toAbsolutePath() + " bytes=" + pdf.length);
    }

    private AnalysisResponse analysis() {
        List<Task> tasks = new ArrayList<>();
        String[] titles = {"선형회귀 기본 개념", "독립변수와 종속변수 관계", "코드 흐름 추적",
                "결과 분석", "오류 및 비교 분석", "복습 및 정리"};
        TaskType[] types = {TaskType.CONCEPT, TaskType.CONCEPT, TaskType.PRACTICE,
                TaskType.ANALYSIS, TaskType.COMPARISON, TaskType.REVIEW};
        int[] mins = {20, 20, 30, 20, 20, 15};
        for (int i = 0; i < titles.length; i++) {
            Task t = new Task();
            t.setId("t" + i); t.setOrder(i); t.setTitle(titles[i]); t.setType(types[i]);
            t.setRecommendedMinutes(mins[i]);
            tasks.add(t);
        }
        return AnalysisResponse.builder().plannerId(7L).tasks(tasks).totalRecommendedMinutes(125).build();
    }

    private List<ScheduleRow> rows() {
        String[] titles = {"선형회귀 기본 개념", "독립변수와 종속변수 관계",
                "코드 흐름 추적 — 입력 데이터부터 예측 결과까지 전체 파이프라인을 한 줄씩 따라가며 확인하기",
                "결과 분석", "오류 및 비교 분석", "복습 및 정리"};
        TaskType[] types = {TaskType.CONCEPT, TaskType.CONCEPT, TaskType.PRACTICE,
                TaskType.ANALYSIS, TaskType.COMPARISON, TaskType.REVIEW};
        int[] mins = {20, 20, 30, 20, 20, 15};
        String[] starts = {"09:00", "09:20", "09:40", "10:10", "10:30", "10:50"};
        String[] ends = {"09:20", "09:40", "10:10", "10:30", "10:50", "11:05"};
        List<ScheduleRow> rows = new ArrayList<>();
        for (int i = 0; i < titles.length; i++) {
            rows.add(new ScheduleRow("t" + i, titles[i], types[i], mins[i], starts[i], ends[i], 0, 0));
        }
        return rows;
    }
}
