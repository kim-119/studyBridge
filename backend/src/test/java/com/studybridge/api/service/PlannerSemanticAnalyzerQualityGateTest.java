package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.quality.GateEvidence;
import com.studybridge.api.dto.PlannerSemanticDTO.AnalysisResponse;
import com.studybridge.api.dto.PlannerSemanticDTO.Download;
import com.studybridge.api.dto.PlannerSemanticDTO.InputItem;
import com.studybridge.api.dto.PlannerSemanticDTO.Request;
import com.studybridge.api.dto.PlannerSemanticDTO.Schedule;
import com.studybridge.api.dto.PlannerSemanticDTO.Task;
import com.studybridge.api.dto.PlannerSemanticDTO.TaskType;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.exception.AiUpstreamException;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.service.support.ChatGateStubServer;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

/**
 * 플래너 AI 계획 분석·시간표·시간표 PDF 품질 게이트(PLANNER_COACHING/text):
 * 79 거절 → 80 승인분만 캐시(plan_analysis_quality_status), 전부 거절·평가기 503 은 422/503 + 캐시 불변, 게이트 ON 조회는 승인 캐시만,
 * 시간표·PDF 는 승인 분석으로만 만든다(미승인 → 시간표·업로드 없음), 게이트 OFF 회귀 없음.
 */
class PlannerSemanticAnalyzerQualityGateTest {

    static final long USER = 9L;
    static final long PLANNER = 701L;
    static final ObjectMapper M = new ObjectMapper();
    ChatGateStubServer stub;
    Planner planner;
    PlannerRepository planners;
    PlannerAnalysisContext context;
    PlannerSchedulePdfRenderer renderer;
    S3Service s3;
    volatile boolean aiDown;

    @BeforeEach
    void up() throws Exception {
        stub = new ChatGateStubServer();
        stub.json("/api/ai/planner/analyze-semantic", n -> aiDown ? null
                : "{\"success\":true,\"summary\":\"초안 " + n + " 요약: 합성곱 개념을 정리한 뒤 실습으로 확인하는 구성입니다.\","
                        + "\"goalAlignment\":{\"level\":\"HIGH\",\"summary\":\"목표와 활동이 잘 맞는 계획입니다.\",\"reason\":\"개념과 실습이 순서대로 배치되어 있습니다.\",\"issues\":[]},"
                        + "\"tasks\":[{\"id\":\"t1\",\"type\":\"CONCEPT\",\"whyImportant\":\"이후 실습의 토대가 되는 개념입니다.\",\"recommendedMinutes\":20,"
                        + "\"learningSequence\":[\"정의 읽기\",\"예제 확인\"]},"
                        + "{\"id\":\"t2\",\"type\":\"PRACTICE\",\"whyImportant\":\"직접 실행해 감각을 익히는 활동입니다.\",\"recommendedMinutes\":40}],"
                        + "\"prerequisites\":[],\"warnings\":[]}");
        planner = Planner.builder().id(PLANNER).userId(USER).title("합성곱 연산").subject("딥러닝")
                .plannerDate(LocalDate.of(2026, 11, 4)).build();
    }

    @AfterEach
    void down() {
        stub.close();
    }

    PlannerSemanticAnalyzer analyzer(boolean gateOn) {
        context = mock(PlannerAnalysisContext.class);
        when(context.owned(USER, PLANNER)).thenReturn(planner);
        when(context.build(any(Planner.class))).thenAnswer(inv -> request());
        when(context.fingerprint(any())).thenReturn("fp-1");
        planners = mock(PlannerRepository.class);
        when(planners.save(any(Planner.class))).thenAnswer(inv -> inv.getArgument(0));
        PlannerSemanticAnalyzer a = new PlannerSemanticAnalyzer(context, new PlannerTimeAllocator(), planners, stub.client(), M);
        ReflectionTestUtils.setField(a, "timeoutSeconds", 5L);
        a.setQualityGate(stub.gate(gateOn));
        return a;
    }

    PlannerScheduleService schedules(PlannerSemanticAnalyzer a) {
        renderer = mock(PlannerSchedulePdfRenderer.class);
        when(renderer.render(any(), any(), any())).thenReturn(new byte[]{1, 2, 3});
        s3 = mock(S3Service.class);
        when(s3.uploadBytes(any(), anyString(), anyString())).thenAnswer(inv -> inv.getArgument(1));
        when(s3.getDownloadPresignedUrl(anyString(), anyString())).thenReturn("https://s3.example/x.pdf");
        return new PlannerScheduleService(a, context, renderer, s3);
    }

    static Request request() {
        Request r = new Request();
        r.setPlannerId(PLANNER);
        r.setTitle("합성곱 연산");
        r.setSubject("딥러닝");
        r.setTopic("합성곱");
        r.setLearningGoal("합성곱 연산 원리를 이해한다");
        r.setContent("합성곱 연산 원리를 이해한다");
        r.setTargetMinutes(60);
        r.setSourceType("MANUAL");
        r.setDetailTasks(new ArrayList<>(List.of(new InputItem("t1", "합성곱 개념 정리", "", false),
                new InputItem("t2", "Conv2d 실습", "", false))));
        r.setChecklist(new ArrayList<>());
        r.setCoreConcepts(List.of());
        r.setPriorConcepts(List.of());
        r.setExcludedFragments(List.of());
        return r;
    }

    /** 게이트 OFF 시절(또는 레거시)의 미검증 캐시. */
    void legacyCache(String status) throws Exception {
        Task t = new Task();
        t.setId("t1");
        t.setTitle("레거시 활동");
        t.setType(TaskType.CONCEPT);
        t.setRecommendedMinutes(30);
        t.setWhyImportant("레거시 미검증 이유");
        AnalysisResponse legacy = AnalysisResponse.builder().plannerId(PLANNER).title("합성곱 연산").summary("레거시 미검증 요약")
                .tasks(new ArrayList<>(List.of(t))).aiSource("AI07").narrativeVersion(PlannerSemanticAnalyzer.NARRATIVE_VERSION).build();
        planner.setPlanAnalysisJson(M.writeValueAsString(legacy));
        planner.setPlanAnalysisQualityStatus(status);
    }

    @GateEvidence({"POST /api/planners/{plannerId}/plan-analysis"})
    @Test
    void rejected79ThenApproved80IsCachedWithStatus() {
        stub.policy = (n, in) -> n == 1 ? ChatGateStubServer.out(79, "REJECTED", false) : ChatGateStubServer.out(80, "APPROVED", false);
        AnalysisResponse r = analyzer(true).analyze(USER, PLANNER);
        assertEquals("APPROVED", r.getQualityStatus());
        assertTrue(r.getSummary().startsWith("초안 2"), "재생성된 두 번째 초안만 노출");
        assertEquals("AI07", r.getAiSource());
        assertEquals(2, stub.calls("/api/ai/planner/analyze-semantic"));
        verify(planners, times(1)).save(any());
        assertEquals("APPROVED", planner.getPlanAnalysisQualityStatus());
        assertTrue(planner.getPlanAnalysisJson().contains("초안 2") && !planner.getPlanAnalysisJson().contains("초안 1"));
        assertFalse(planner.getPlanAnalysisJson().contains("qualityStatus"), "판정은 컬럼에만 — 캐시 JSON 에 응답 전용 필드 없음");
        JsonNode ev = stub.evaluations.get(0);
        assertEquals("PLANNER_COACHING", ev.get("taskType").asText());
        assertEquals("text", ev.get("outputKind").asText());
        String proposed = ev.get("proposedOutput").asText();
        assertTrue(proposed.contains("초안 1") && proposed.contains("합성곱 개념 정리") && proposed.contains("분)")
                && proposed.contains("정의 읽기"), "요약·task 제목·권장 분·학습 순서 전부 평가");
        assertFalse(proposed.contains("fp-1"), "지문(식별자)은 보이는 문자열이 아니다");
        assertEquals("PLANNER_RECORD", ev.get("groundingEvidence").get(0).get("sourceType").asText());
    }

    @GateEvidence({"POST /api/planners/{plannerId}/plan-analysis"})
    @Test
    void threeRejectionsAreExplicitFailureAndKeepExistingCache() throws Exception {
        stub.policy = (n, in) -> ChatGateStubServer.out(70, "REJECTED", false);
        legacyCache("APPROVED");
        String before = planner.getPlanAnalysisJson();
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> analyzer(true).analyze(USER, PLANNER));
        assertEquals("AI_QUALITY_REJECTED", e.getCode());
        assertEquals(422, e.getStatus().value());
        assertEquals(3, stub.calls("/api/ai/planner/analyze-semantic"), "최초 1 + 재생성 2");
        verify(planners, never()).save(any());
        assertEquals(before, planner.getPlanAnalysisJson());
        assertEquals("APPROVED", planner.getPlanAnalysisQualityStatus());
    }

    @Test
    void evaluatorDownIsUnavailableWithoutRegeneration() {
        stub.policy = (n, in) -> null;
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> analyzer(true).analyze(USER, PLANNER));
        assertEquals("AI_QUALITY_UNAVAILABLE", e.getCode());
        assertEquals(503, e.getStatus().value());
        assertEquals(1, stub.calls("/api/ai/planner/analyze-semantic"));
        verify(planners, never()).save(any());
    }

    @Test
    void ai07DownFallbackAnalysisIsAlsoEvaluatedAndLabelledFallback() {
        aiDown = true;
        AnalysisResponse r = analyzer(true).analyze(USER, PLANNER);
        assertEquals("FALLBACK", r.getAiSource(), "결정적 폴백은 AI07 로 표기하지 않는다");
        assertEquals("APPROVED", r.getQualityStatus());
        assertEquals(1, stub.evaluations.size(), "폴백도 로드맵·플래너 원문 문구를 담으므로 평가한다(동일 초안 반복은 1회로 끝)");
    }

    @GateEvidence({"GET /api/planners/{plannerId}/plan-analysis"})
    @Test
    void unverifiedCacheIsRedactedAndApprovedCacheIsShownWithoutAi() throws Exception {
        legacyCache(null);
        PlannerSemanticAnalyzer a = analyzer(true);
        AnalysisResponse hidden = a.get(USER, PLANNER);
        assertEquals(Boolean.TRUE, hidden.getQualityRedacted());
        assertTrue(hidden.isEmpty());
        assertNull(hidden.getTasks());
        assertFalse(M.writeValueAsString(hidden).contains("레거시"), "미검증 캐시 본문 0");
        assertEquals(0, stub.evaluations.size());
        // 승인 분석을 만든 뒤에는 그대로 보인다(조회는 AI·평가 없음)
        a.analyze(USER, PLANNER);
        int evals = stub.evaluations.size();
        int calls = stub.calls("/api/ai/planner/analyze-semantic");
        AnalysisResponse shown = a.get(USER, PLANNER);
        assertEquals("APPROVED", shown.getQualityStatus());
        assertTrue(shown.getSummary().startsWith("초안 1"));
        assertEquals(evals, stub.evaluations.size());
        assertEquals(calls, stub.calls("/api/ai/planner/analyze-semantic"));
        // 문장 규칙이 바뀐 승인 캐시는 평가받은 본문과 다르므로 가린다
        AnalysisResponse old = M.readValue(planner.getPlanAnalysisJson(), AnalysisResponse.class);
        old.setNarrativeVersion(1);
        planner.setPlanAnalysisJson(M.writeValueAsString(old));
        assertEquals(Boolean.TRUE, a.get(USER, PLANNER).getQualityRedacted());
    }

    @GateEvidence({"GET /api/planners/{plannerId}/schedule"})
    @Test
    void scheduleUsesOnlyApprovedAnalysis() throws Exception {
        legacyCache(null);
        stub.policy = (n, in) -> ChatGateStubServer.out(60, "REJECTED", false);
        PlannerSemanticAnalyzer a = analyzer(true);
        PlannerScheduleService svc = schedules(a);
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> svc.schedule(USER, PLANNER, "09:00"));
        assertEquals("AI_QUALITY_REJECTED", e.getCode());
        verify(planners, never()).save(any());
        assertTrue(planner.getPlanAnalysisJson().contains("레거시"), "미승인이면 캐시도 그대로(덮어쓰지 않음)");
        // 승인되면 그 분석의 활동으로 시간표를 만든다
        stub.policy = (n, in) -> ChatGateStubServer.out(85, "APPROVED", false);
        Schedule s = svc.schedule(USER, PLANNER, "09:00");
        assertEquals(List.of("합성곱 개념 정리", "Conv2d 실습"), s.rows().stream().map(x -> x.title()).toList());
        assertEquals(60, s.totalMinutes());
        assertEquals("APPROVED", planner.getPlanAnalysisQualityStatus());
        // 승인 캐시는 재사용(AI·평가 추가 없음)
        int evals = stub.evaluations.size();
        svc.schedule(USER, PLANNER, "10:00");
        assertEquals(evals, stub.evaluations.size());
    }

    @GateEvidence({"POST /api/planners/{plannerId}/schedule/pdf"})
    @Test
    void schedulePdfIsNotRenderedOrUploadedFromUnapprovedAnalysis() throws Exception {
        legacyCache(null);
        stub.policy = (n, in) -> null; // 평가기 장애
        PlannerSemanticAnalyzer a = analyzer(true);
        PlannerScheduleService svc = schedules(a);
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> svc.generatePdf(USER, PLANNER, "09:00"));
        assertEquals("AI_QUALITY_UNAVAILABLE", e.getCode());
        verify(renderer, never()).render(any(), any(), any());
        verify(s3, never()).uploadBytes(any(), anyString(), anyString());
        stub.policy = (n, in) -> ChatGateStubServer.out(80, "APPROVED", false);
        Download d = svc.generatePdf(USER, PLANNER, "09:00");
        assertEquals("https://s3.example/x.pdf", d.downloadUrl());
        assertEquals(List.of("합성곱 개념 정리", "Conv2d 실습"), d.schedule().rows().stream().map(x -> x.title()).toList());
        verify(s3, times(1)).uploadBytes(any(), anyString(), anyString());
        assertTrue(stub.evaluations.size() >= 2);
    }

    @Test
    void gateOffIsLegacyBehaviour() throws Exception {
        legacyCache(null);
        PlannerSemanticAnalyzer a = analyzer(false);
        assertEquals("레거시 미검증 요약", a.get(USER, PLANNER).getSummary(), "OFF 에선 기존 캐시 그대로");
        AnalysisResponse r = a.analyze(USER, PLANNER);
        assertNull(r.getQualityStatus());
        assertNull(planner.getPlanAnalysisQualityStatus());
        assertEquals(0, stub.evaluations.size(), "게이트 OFF: 평가기 호출 0");
        assertFalse(M.writeValueAsString(r).contains("qualityRedacted"));
        verify(planners, times(1)).save(any());
    }
}
