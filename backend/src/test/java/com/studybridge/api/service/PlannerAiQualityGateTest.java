package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.quality.GateEvidence;
import com.studybridge.api.dto.PlannerAiDTO.AssistResponse;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.PlannerAiResult;
import com.studybridge.api.repository.PlannerAiResultRepository;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.service.support.ChatGateStubServer;
import java.time.LocalDate;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

/**
 * 플래너 AI 피드백(ai-assist / ai-result) 품질 게이트(PLANNER_COACHING/text):
 * 79 거절 → 80 승인분만 저장(quality_status), 전부 거절·평가기 503 은 success=false + 저장 0, ai07 장애는 결정적 기본 피드백(usedFallback=true),
 * 저장본 조회는 폴백 표식을 따르고(기존 결함 수정) 게이트 ON 에서 미검증 AI 저장본을 가린다, 게이트 OFF 회귀 없음.
 */
class PlannerAiQualityGateTest {

    static final long USER = 7L;
    static final long PLANNER = 501L;
    static final ObjectMapper M = new ObjectMapper();
    ChatGateStubServer stub;
    PlannerAiResultRepository results;
    final AtomicReference<PlannerAiResult> stored = new AtomicReference<>();
    volatile boolean assistDown;

    @BeforeEach
    void up() throws Exception {
        stub = new ChatGateStubServer();
        stub.json("/api/ai/planner/assist", n -> assistDown ? null
                : "{\"success\":true,\"aiSummary\":\"초안 " + n + ": 합성곱 개념을 먼저 정리하고 실습으로 확인하는 계획입니다.\","
                        + "\"refinedGoal\":\"합성곱 연산 원리를 이해한다\",\"taskBreakdown\":[\"3x3 커널 손계산\",\"Conv2d 실습\"],"
                        + "\"strengths\":[\"목표가 구체적입니다\"],\"concerns\":[\"실습 시간이 부족할 수 있습니다\"],"
                        + "\"recommendations\":[\"25분 집중 후 5분 휴식\"],\"nextActions\":[\"내일 풀링 학습\"]}");
    }

    @AfterEach
    void down() {
        stub.close();
    }

    PlannerAiService service(boolean gateOn) {
        PlannerRepository planners = mock(PlannerRepository.class);
        Planner p = Planner.builder().id(PLANNER).userId(USER).title("합성곱 연산").subject("딥러닝")
                .content("합성곱 연산 원리를 이해한다").tmi("3x3 커널 손계산, Conv2d 실습").goalTime("1시간").netStudyTime("40분")
                .plannerDate(LocalDate.of(2026, 11, 4)).build();
        when(planners.findById(PLANNER)).thenReturn(Optional.of(p));
        results = mock(PlannerAiResultRepository.class);
        when(results.findByPlannerId(PLANNER)).thenAnswer(inv -> Optional.ofNullable(stored.get()));
        when(results.save(any(PlannerAiResult.class))).thenAnswer(inv -> {
            stored.set(inv.getArgument(0));
            return inv.getArgument(0);
        });
        PlannerAiService svc = new PlannerAiService(planners, results, stub.client());
        ReflectionTestUtils.setField(svc, "assistTimeoutSeconds", 5L);
        svc.setQualityGate(stub.gate(gateOn));
        return svc;
    }

    static PlannerAiResult row(String summary, String quality, Boolean fallback) {
        return PlannerAiResult.builder().id(1L).plannerId(PLANNER).aiSummary(summary).refinedGoal("목표").taskBreakdown("[\"할 일\"]")
                .aiFeedback("{\"strengths\":[\"장점\"],\"concerns\":[],\"recommendations\":[]}").nextActions("[]")
                .qualityStatus(quality).usedFallback(fallback).build();
    }

    PlannerAiResult saved() {
        ArgumentCaptor<PlannerAiResult> c = ArgumentCaptor.forClass(PlannerAiResult.class);
        verify(results).save(c.capture());
        return c.getValue();
    }

    @GateEvidence({"POST /api/planners/{plannerId}/ai-assist", "GET /api/planners/{plannerId}/ai-result"})
    @Test
    void rejected79ThenApproved80IsSavedAndReexposed() {
        stub.policy = (n, in) -> n == 1 ? ChatGateStubServer.out(79, "REJECTED", false) : ChatGateStubServer.out(80, "APPROVED", false);
        PlannerAiService svc = service(true);
        AssistResponse r = svc.assist(USER, PLANNER);
        assertEquals(Boolean.TRUE, r.getSuccess());
        assertEquals("APPROVED", r.getQualityStatus());
        assertTrue(r.getAiSummary().startsWith("초안 2"), "재생성된 두 번째 초안만 노출");
        assertEquals(2, stub.calls("/api/ai/planner/assist"));
        PlannerAiResult s = saved();
        assertEquals("APPROVED", s.getQualityStatus());
        assertEquals(Boolean.FALSE, s.getUsedFallback());
        assertTrue(s.getAiSummary().startsWith("초안 2"));
        JsonNode ev = stub.evaluations.get(0);
        assertEquals("PLANNER_COACHING", ev.get("taskType").asText());
        assertEquals("text", ev.get("outputKind").asText(), "서술형 코칭은 일정 JSON 검사를 받지 않도록 text");
        String proposed = ev.get("proposedOutput").asText();
        assertTrue(proposed.contains("초안 1") && proposed.contains("3x3 커널 손계산") && proposed.contains("25분 집중"), "보일 문자열 전체 평가");
        assertEquals("PLANNER_RECORD", ev.get("groundingEvidence").get(0).get("sourceType").asText());
        // 재노출: 승인 저장본은 그대로 보인다(AI 호출·평가 없음)
        int evals = stub.evaluations.size();
        AssistResponse again = svc.getAiResult(USER, PLANNER);
        assertTrue(again.getAiSummary().startsWith("초안 2"));
        assertEquals("APPROVED", again.getQualityStatus());
        assertEquals(evals, stub.evaluations.size());
    }

    @GateEvidence({"POST /api/planners/{plannerId}/ai-assist", "GET /api/planners/{plannerId}/ai-result"})
    @Test
    void threeRejectionsSaveNothingKeepExistingAndUnverifiedRowIsRedacted() {
        stub.policy = (n, in) -> ChatGateStubServer.out(70, "REJECTED", false);
        stored.set(row("레거시 미검증 AI 요약", null, null));
        PlannerAiService svc = service(true);
        AssistResponse r = svc.assist(USER, PLANNER);
        assertEquals(Boolean.FALSE, r.getSuccess());
        assertEquals("AI_QUALITY_REJECTED", r.getErrorCode());
        assertEquals(Boolean.TRUE, r.getRetryable());
        assertNull(r.getAiSummary());
        assertEquals(3, stub.calls("/api/ai/planner/assist"), "최초 1 + 재생성 2");
        verify(results, never()).save(any());
        assertEquals("레거시 미검증 AI 요약", stored.get().getAiSummary(), "기존 저장본은 덮어쓰지 않는다");
        // 게이트 ON 조회: 미검증 AI 저장본은 가린다
        AssistResponse view = svc.getAiResult(USER, PLANNER);
        assertNull(view.getSuccess());
        assertEquals(Boolean.TRUE, view.getQualityRedacted());
        assertNull(view.getAiSummary());
        assertNull(view.getStrengths());
    }

    @Test
    void evaluatorDownIsUnavailableNotDisguisedSuccess() {
        stub.policy = (n, in) -> null;
        AssistResponse r = service(true).assist(USER, PLANNER);
        assertEquals(Boolean.FALSE, r.getSuccess());
        assertEquals("AI_QUALITY_UNAVAILABLE", r.getErrorCode());
        assertEquals(1, stub.calls("/api/ai/planner/assist"), "평가기 장애 시 재생성 없음");
        verify(results, never()).save(any());
    }

    @Test
    void ai07DownUsesDeterministicFallbackLabelledAsFallback() {
        assistDown = true;
        PlannerAiService svc = service(true);
        AssistResponse r = svc.assist(USER, PLANNER);
        assertEquals(Boolean.TRUE, r.getUsedFallback(), "결정적 기본 피드백은 AI 로 표기하지 않는다");
        assertNull(r.getQualityStatus());
        assertEquals(0, stub.evaluations.size(), "평가할 AI 본문이 없다");
        PlannerAiResult s = saved();
        assertEquals(Boolean.TRUE, s.getUsedFallback());
        assertNull(s.getQualityStatus());
        AssistResponse view = svc.getAiResult(USER, PLANNER);
        assertEquals(Boolean.TRUE, view.getSuccess());
        assertEquals(Boolean.TRUE, view.getUsedFallback(), "조회도 폴백 표식을 따른다");
        assertNull(view.getQualityRedacted());
    }

    @Test
    void gateOffIsLegacyBehaviourButFallbackIsNoLongerLabelledAi() {
        PlannerAiService svc = service(false);
        AssistResponse r = svc.assist(USER, PLANNER);
        assertEquals(Boolean.FALSE, r.getUsedFallback());
        assertNull(r.getQualityStatus());
        assertEquals(0, stub.evaluations.size(), "게이트 OFF: 평가기 호출 0");
        assertNull(saved().getQualityStatus());
        stored.set(row("레거시 요약", null, null));
        AssistResponse legacy = svc.getAiResult(USER, PLANNER);
        assertEquals("레거시 요약", legacy.getAiSummary(), "OFF 에선 기존 저장본 그대로");
        assertEquals(Boolean.FALSE, legacy.getUsedFallback());
        assertNull(legacy.getQualityRedacted());
        stored.set(row("기본 피드백", null, true));
        assertEquals(Boolean.TRUE, svc.getAiResult(USER, PLANNER).getUsedFallback(), "폴백 저장본은 폴백으로 표기(기존 결함 수정)");
        assertFalse(M.valueToTree(legacy).has("qualityStatus"), "게이트 OFF 응답에 품질 필드가 나가지 않는다");
    }
}
