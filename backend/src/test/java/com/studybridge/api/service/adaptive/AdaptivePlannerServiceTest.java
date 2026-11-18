package com.studybridge.api.service.adaptive;

import static com.studybridge.api.service.adaptive.AdaptiveFixtures.TODAY;
import static com.studybridge.api.service.adaptive.AdaptiveFixtures.USER;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.studybridge.api.service.adaptive.AdaptiveProposalSigner.Payload;
import java.io.InputStream;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.HttpStatus;
import org.springframework.transaction.PlatformTransactionManager;

/**
 * 추천 오케스트레이션(Mock ai07, 실제 ai07 응답 원본 사용): 엔진 모드 선택·요청 본문·응답 무결성 검증·일정 제안 정제·반영 후보 서명.
 */
class AdaptivePlannerServiceTest {

    static final Clock CLOCK = Clock.fixed(Instant.parse("2026-10-28T03:00:00Z"), ZoneId.of("Asia/Seoul"));
    private final ObjectMapper om = new ObjectMapper();
    private AdaptiveFixtures f;
    private AdaptivePlannerClient client;
    private AdaptiveProposalSigner signer;
    private AdaptivePlannerService service;

    @BeforeEach
    void setUp() {
        f = new AdaptiveFixtures();
        client = mock(AdaptivePlannerClient.class);
        signer = new AdaptiveProposalSigner("test-secret", Duration.ofMinutes(30), om, CLOCK);
        service = new AdaptivePlannerService(f.builder, client, signer, mock(PlatformTransactionManager.class), CLOCK);
    }

    /** fastapi/docs/planner 실제 qwen3:14b 응답 원본에서 id 만 이 테스트의 planner id 로 바꾼다. */
    static ObjectNode real(ObjectMapper om, String key, Map<String, String> ids) throws Exception {
        try (InputStream in = AdaptivePlannerServiceTest.class.getResourceAsStream("/adaptive/real-examples.json")) {
            String s = om.writeValueAsString(om.readTree(in).path(key).path("response"));
            for (Map.Entry<String, String> e : ids.entrySet()) s = s.replaceAll(e.getKey(), e.getValue());
            return (ObjectNode) om.readTree(s);
        }
    }

    private void roadmap() {
        f.roadmapStep(11, USER, 1, 1, TODAY.minusDays(2));
        f.roadmapStep(12, USER, 1, 2, TODAY.minusDays(1));
        f.roadmapStep(13, USER, 1, 3, TODAY);
        f.roadmapStep(14, USER, 2, 1, TODAY.plusDays(1));
        f.checklist(f.planners.get(11L), true);
        f.checklist(f.planners.get(12L), true, true);
        f.checklist(f.planners.get(13L), false, false, false);
    }

    private static final Map<String, String> ROADMAP_IDS = Map.of("\"cnn-3\"", "13", "\"cnn-2\"", "12", "\"cnn-1\"", "11", "\"cnn-4\"", "14");
    private static final Map<String, String> MANUAL_IDS = Map.of("\\b9001\\b", "21", "\\b9002\\b", "22", "\\b9003\\b", "23", "\\b9004\\b", "24");

    private void manual() {
        f.userPlanner(21, USER, "Java 예외 처리 복습", TODAY.plusDays(1), "보통", "2026-10-31");
        f.userPlanner(22, USER, "SQLD 기출문제 풀이", TODAY, "높음", "2026-10-29");
        f.checklist(f.userPlanner(23, USER, "네트워크 OSI 7계층", TODAY.minusDays(1), "보통", null), true);
        f.userPlanner(24, USER, "미적분 문제 풀이", TODAY.minusDays(3), null, "2026-10-27");
    }

    @Test
    @SuppressWarnings("unchecked")
    void roadmap30_realResponse_isCoachingForCurrentStep_withSignedRecoverySessions() throws Exception {
        roadmap();
        when(client.recommend(any(), anyString())).thenReturn(real(om, "roadmap30", ROADMAP_IDS));
        Map<String, Object> out = service.recommend(USER, 13L, 30, true, null);

        ArgumentCaptor<Map<String, Object>> body = ArgumentCaptor.forClass(Map.class);
        verify(client).recommend(body.capture(), anyString());
        assertEquals("ROADMAP_COACH", body.getValue().get("mode"));
        assertEquals(13L, body.getValue().get("currentStepId"));
        assertEquals(30, body.getValue().get("availableMinutes"));
        assertEquals("Asia/Seoul", body.getValue().get("timezone"));
        assertEquals(USER, body.getValue().get("userId"));
        assertEquals(4, ((List<?>) body.getValue().get("items")).size());
        assertTrue(body.getValue().containsKey("quizResults"));

        assertEquals("ROADMAP", out.get("plannerType"));
        JsonNode result = (JsonNode) out.get("result");
        assertEquals(13, result.path("recommendation").path("itemId").asInt());
        List<Map<String, Object>> changes = (List<Map<String, Object>>) out.get("changes");
        assertEquals(2, changes.size());
        assertEquals("ADD_STUDY_SESSION", changes.get(0).get("kind"));
        assertEquals("2026-10-28", changes.get(0).get("date"));
        assertEquals("2026-10-29", changes.get(1).get("date"));
        assertEquals(30, changes.get(1).get("minutes"));
        assertEquals("[로드맵 1주차 3일] 단계 1-3", changes.get(0).get("title"));
        assertTrue(changes.stream().noneMatch(c -> "RESCHEDULE_PLANNER".equals(c.get("kind"))), "로드맵 단계 날짜는 바꾸지 않는다");

        Payload p = signer.verify((String) out.get("proposalToken"), USER, 13L);
        assertEquals(2, p.changes().size());
        assertEquals(f.builder.build(USER, 13L, null, TODAY).basisToken(), p.basis());
    }

    @Test
    void roadmap60_realResponse_withoutRecoveryPlan_hasNoChangesOrToken() throws Exception {
        roadmap();
        when(client.recommend(any(), anyString())).thenReturn(real(om, "roadmap60", ROADMAP_IDS));
        Map<String, Object> out = service.recommend(USER, 13L, 60, true, null);
        assertEquals(List.of(), out.get("changes"));
        assertNull(out.get("proposalToken"));
        assertEquals(4, ((JsonNode) out.get("result")).path("recommendation").path("activities").size());
    }

    @Test
    @SuppressWarnings("unchecked")
    void manual30_realResponse_derivesPartialSessions_catchUp_andReschedule() throws Exception {
        manual();
        when(client.recommend(any(), anyString())).thenReturn(real(om, "manual30", MANUAL_IDS));
        Map<String, Object> out = service.recommend(USER, 21L, 30, true, null);

        ArgumentCaptor<Map<String, Object>> body = ArgumentCaptor.forClass(Map.class);
        verify(client).recommend(body.capture(), anyString());
        assertEquals("MANUAL_NEXT", body.getValue().get("mode"));
        assertFalse(body.getValue().containsKey("currentStepId"), "MANUAL_NEXT 에 currentStepId 를 보내지 않는다(400 방지)");
        assertFalse(body.getValue().containsKey("quizResults"));

        assertEquals("USER", out.get("plannerType"));
        List<Map<String, Object>> changes = (List<Map<String, Object>>) out.get("changes");
        assertEquals(List.of("S:22:2026-10-28", "S:22:2026-10-29", "S:24:2026-10-29", "R:24:2026-10-29"),
                changes.stream().map(c -> c.get("id")).toList());
        Map<String, Object> resched = changes.get(3);
        assertEquals("2026-10-25", resched.get("fromDate"));
        assertEquals("2026-10-29", resched.get("toDate"));
        assertEquals(20, changes.get(1).get("minutes"));
        assertNotNull(out.get("proposalToken"));
    }

    @Test
    void responseNaming_unknownItem_isRejected502() throws Exception {
        manual();
        ObjectNode r = real(om, "manual30", MANUAL_IDS);
        ((ObjectNode) r.get("recommendation")).put("itemId", 999);
        when(client.recommend(any(), anyString())).thenReturn(r);
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> service.recommend(USER, 21L, 30, true, null));
        assertEquals("ADAPTIVE_INVALID_RESPONSE", e.getCode());
        assertEquals(HttpStatus.BAD_GATEWAY, e.getStatus());
        assertEquals("UNKNOWN_ITEM", e.getDetails().get("reason"));
    }

    @Test
    void manual_recommendingCompletedItem_isRejected() throws Exception {
        manual();
        ObjectNode r = real(om, "manual30", MANUAL_IDS);
        ((ObjectNode) r.get("recommendation")).put("itemId", 23);
        when(client.recommend(any(), anyString())).thenReturn(r);
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> service.recommend(USER, 21L, 30, true, null));
        assertEquals("COMPLETED_ITEM_RECOMMENDED", e.getDetails().get("reason"));
    }

    @Test
    void manual_completedAlternative_isRejected() throws Exception {
        manual();
        ObjectNode r = real(om, "manual30", MANUAL_IDS);
        ((ObjectNode) r.get("alternatives").get(0)).put("itemId", 23);
        when(client.recommend(any(), anyString())).thenReturn(r);
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> service.recommend(USER, 21L, 30, true, null));
        assertEquals("INVALID_ALTERNATIVE", e.getDetails().get("reason"));
    }

    @Test
    void roadmap_recommendingAnotherStep_isRejected() throws Exception {
        roadmap();
        ObjectNode r = real(om, "roadmap30", ROADMAP_IDS);
        ((ObjectNode) r.get("recommendation")).put("itemId", 14);
        when(client.recommend(any(), anyString())).thenReturn(r);
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> service.recommend(USER, 13L, 30, true, null));
        assertEquals("NOT_CURRENT_STEP", e.getDetails().get("reason"));
    }

    @Test
    void timeOverflow_isRejected() throws Exception {
        roadmap();
        ObjectNode r = real(om, "roadmap60", ROADMAP_IDS);
        when(client.recommend(any(), anyString())).thenReturn(r);
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> service.recommend(USER, 13L, 30, true, null));
        assertEquals("TIME_OVERFLOW", e.getDetails().get("reason"));
    }

    @Test
    @SuppressWarnings("unchecked")
    void pastDatedRecoverySession_dropsOnlyThePlan_withWarning() throws Exception {
        roadmap();
        ObjectNode r = real(om, "roadmap30", ROADMAP_IDS);
        ((ObjectNode) r.get("recoveryPlan").get("sessions").get(1)).put("date", "2026-10-20");
        when(client.recommend(any(), anyString())).thenReturn(r);
        Map<String, Object> out = service.recommend(USER, 13L, 30, true, null);
        assertTrue(((JsonNode) out.get("result")).get("recoveryPlan").isNull());
        assertEquals(List.of(), out.get("changes"));
        assertEquals("RECOVERY_PLAN_REJECTED", ((List<Map<String, Object>>) out.get("warnings")).get(0).get("code"));
        assertEquals(13, ((JsonNode) out.get("result")).path("recommendation").path("itemId").asInt(), "추천 자체는 유지");
    }

    @Test
    void ruleBasedSource_isAcceptedTheSameWay() throws Exception {
        roadmap();
        ObjectNode r = real(om, "roadmap30", ROADMAP_IDS);
        r.put("source", "RULE_BASED");
        ((ObjectNode) r.get("recommendation")).remove("checkQuestions");
        when(client.recommend(any(), anyString())).thenReturn(r);
        Map<String, Object> out = service.recommend(USER, 13L, 30, false, null);
        assertEquals("RULE_BASED", ((JsonNode) out.get("result")).path("source").asText());
    }

    @Test
    void currentStepCompleted_passesThrough_withSuggestedStep_andNoChanges() throws Exception {
        roadmap();
        ObjectNode r = om.createObjectNode();
        r.put("contractVersion", "adaptive-planner.v1").put("mode", "ROADMAP_COACH").put("status", "CURRENT_STEP_COMPLETED")
                .put("statusReason", "CURRENT_STEP_ALREADY_COMPLETED").put("message", "이미 완료한 단계입니다.");
        r.putNull("recommendation");
        r.putArray("alternatives");
        r.putNull("recoveryPlan");
        when(client.recommend(any(), anyString())).thenReturn(r);
        Map<String, Object> out = service.recommend(USER, 11L, 30, true, null);
        assertEquals(11L, out.get("currentStepId"));
        assertEquals(13L, out.get("suggestedStepId"));
        assertEquals(List.of(), out.get("changes"));
    }

    @Test
    void invalidMinutes_rejectedBeforeCallingAi() {
        roadmap();
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> service.recommend(USER, 13L, 45, true, null));
        assertEquals("ADAPTIVE_INVALID_MINUTES", e.getCode());
        verify(client, never()).recommend(any(), anyString());
    }

    @Test
    void otherUsersPlanner_neverReachesAi() {
        f.userPlanner(40, AdaptiveFixtures.OTHER, "남의 계획", TODAY, "높음", null);
        assertThrows(SecurityException.class, () -> service.recommend(USER, 40L, 30, true, null));
        verify(client, never()).recommend(any(), anyString());
    }
}
