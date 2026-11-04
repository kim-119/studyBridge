package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.quality.AiQualityGateSettings;
import com.studybridge.api.dto.ScreenAiDTO.AnalyzeRequest;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.ScreenAiException;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.service.VisionUpstreamClient.VisionCall;
import com.studybridge.api.service.VisionUpstreamClient.VisionResult;
import com.studybridge.api.service.support.ChatGateStubServer;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import reactor.core.publisher.Mono;

/**
 * 화면공유 AI 분석(POST /api/groups/{id}/screen-ai/analyze) 품질 게이트(Phase D, VISION_CAPTION / vision_text):
 *  근거 없이 평가 요청(ai07 은 판독 근거를 돌려주지 않는다) → 79 거절 후 80 승인만 응답, 근거 부재(VISION_NO_OBSERVATION_EVIDENCE) 거절은
 *  재생성 없이 SCREEN_AI_QUALITY_REJECTED, 평가기 503 은 SCREEN_AI_QUALITY_UNAVAILABLE, VISION_ANSWER_DISABLED 는 SCREEN_AI_DISABLED 유지,
 *  게이트 OFF 회귀 없음. 동의·권한 흐름은 그대로(본인 화면 분석으로 검증). 답변은 어디에도 저장하지 않는다(응답만).
 */
class GroupScreenAiQualityGateTest {

    private static final long GROUP = 25L;
    private static final String SID = "group_study_25";
    private static final long NOW = GroupVideoCallServiceTest.CLOCK.millis();

    private final ObjectMapper om = new ObjectMapper();
    private OpenViduService openVidu;
    private GroupStudyMemberRepository members;
    private AiRequestGuard guard;
    private VisionUpstreamClient upstream;
    private ScreenAiConsentStore consent;
    private UserRepository users;
    private final List<Map<String, Object>> connections = new ArrayList<>();
    private final AtomicInteger vlmCalls = new AtomicInteger();
    private String jpeg;
    private ChatGateStubServer stub;

    @BeforeEach
    void setUp() throws Exception {
        stub = new ChatGateStubServer();
        openVidu = mock(OpenViduService.class);
        members = mock(GroupStudyMemberRepository.class);
        users = mock(UserRepository.class);
        consent = mock(ScreenAiConsentStore.class);
        guard = mock(AiRequestGuard.class);
        upstream = mock(VisionUpstreamClient.class);
        when(members.existsByGroupStudyIdAndUserIdAndStatus(eq(GROUP), anyLong(), eq(GroupStudyMemberStatus.JOINED))).thenReturn(true);
        when(guard.tryLock(anyString(), any())).thenAnswer(inv -> new AiRequestGuard.Lock(inv.getArgument(0), "t", true));
        when(guard.allow(anyString(), anyInt(), any())).thenReturn(true);
        when(upstream.timeout()).thenReturn(Duration.ofSeconds(260));
        when(upstream.configured()).thenReturn(true);
        when(openVidu.listConnections(SID, false)).thenReturn(connections);
        User u = new User();
        u.setDisplayName("사용자1");
        when(users.findById(1L)).thenReturn(Optional.of(u));
        jpeg = ScreenAiImageValidatorTest.jpegB64(640, 360);
        connections.add(conn("con_A", sd(1L, "PRIMARY", null), "str_A_CAMERA", "CAMERA", NOW - 60_000));
        connections.add(conn("con_SA", sd(1L, "SCREEN", "con_A"), "str_SA_SCREEN", "SCREEN", NOW - 30_000));
        // VLM 대역: 호출마다 다른 초안(같은 초안 반복 = 재생성 중단 규칙과 섞이지 않게)
        when(upstream.analyze(any())).thenAnswer(inv -> Mono.just(new VisionResult(((VisionCall) inv.getArgument(0)).requestId(),
                "CANARYV 초안 " + vlmCalls.incrementAndGet() + ": 화면에 ZeroDivisionError 가 보입니다.", "qwen3-vl:4b-instruct",
                1500L, 0L, 1400L)));
    }

    @AfterEach
    void down() {
        stub.close();
    }

    private String sd(long userId, String kind, String owner) {
        return VideoConnectionMetadata.toServerData(om, GROUP, userId, VideoConnectionMetadata.Kind.valueOf(kind), owner, null, "WEB", NOW - 5_000);
    }

    private static Map<String, Object> conn(String id, String serverData, String streamId, String type, long activeAt) {
        Map<String, Object> c = new HashMap<>();
        c.put("connectionId", id);
        c.put("status", "active");
        c.put("serverData", serverData);
        c.put("clientData", "{\"userId\":999}");
        c.put("activeAt", activeAt);
        c.put("publishers", List.of(Map.of("streamId", streamId, "mediaOptions", Map.of("typeOfVideo", type, "hasVideo", true))));
        return c;
    }

    private GroupScreenAiService service(boolean gateOn) {
        return service(gateOn, GroupVideoCallServiceTest.CLOCK);
    }

    private GroupScreenAiService service(boolean gateOn, java.time.Clock clock) {
        GroupVideoCallService video = GroupVideoCallServiceTest.newService(openVidu, members, om, 2500, 1500);
        GroupScreenAiService s = new GroupScreenAiService(video, openVidu, members, users, om, consent, guard, upstream,
                clock, true, 1000, 1024 * 1024, 1280, 32, 6, 30);
        AiQualityGateSettings settings = AiQualityGateSettings.forTest(gateOn);
        s.setQualityGate(new com.studybridge.api.ai.quality.AiResponseQualityGate(settings, stub.evaluatorClient(settings)));
        s.setQualityEvaluator(stub.evaluatorClient(settings));
        return s;
    }

    private AnalyzeRequest req() {
        return new AnalyzeRequest("con_SA", "str_SA_SCREEN", "이 오류가 왜 나?", jpeg, "image/jpeg", "cr_1234567890");
    }

    @com.studybridge.api.ai.quality.GateEvidence({"POST /api/groups/{id}/screen-ai/analyze"})
    @Test
    void rejected79ThenApproved80ReturnsOnlyApprovedAnswer() {
        stub.policy = (n, in) -> n == 1 ? ChatGateStubServer.out(79, "REJECTED", false) : ChatGateStubServer.out(80, "APPROVED", false);
        Map<String, Object> res = service(true).analyze(1L, GROUP, req()).block();
        assertTrue(String.valueOf(res.get("answer")).contains("초안 2"), "재생성된 두 번째 초안만 응답");
        assertEquals("APPROVED", res.get("qualityStatus"));
        assertEquals(Boolean.TRUE, res.get("verified"));
        ArgumentCaptor<VisionCall> calls = ArgumentCaptor.forClass(VisionCall.class);
        verify(upstream, times(2)).analyze(calls.capture());
        assertTrue(calls.getAllValues().get(1).requestId().endsWith("-r1"), "재생성은 새 requestId");
        JsonNode ev = stub.evaluations.get(0);
        assertEquals("VISION_CAPTION", ev.get("taskType").asText());
        assertEquals("vision_text", ev.get("outputKind").asText());
        assertEquals(0, ev.get("groundingEvidence").size(), "ai07 이 판독 근거를 주지 않으므로 근거 없이 보낸다");
        assertTrue(ChatGateStubServer.proposedText(ev).contains("초안 1"));
        assertEquals("이 오류가 왜 나?", ev.get("originalRequest").asText());
        verify(guard, org.mockito.Mockito.timeout(3000)).release(any()); // 이벤트 루프 밖(전용 스케줄러)에서 해제
    }

    @com.studybridge.api.ai.quality.GateEvidence({"POST /api/groups/{id}/screen-ai/analyze"})
    @Test
    void noObservationEvidenceRejectionFailsExplicitlyWithoutRegeneration() {
        stub.policy = (n, in) -> ChatGateStubServer.out(60, "REJECTED", true); // HARD VISION_NO_OBSERVATION_EVIDENCE
        ScreenAiException ex = assertThrows(ScreenAiException.class, () -> service(true).analyze(1L, GROUP, req()).block());
        assertEquals("SCREEN_AI_QUALITY_REJECTED", ex.getCode());
        assertEquals(422, ex.getStatus().value());
        assertTrue(ex.isRetryable());
        assertEquals("AI_QUALITY_REJECTED", ex.getDetails().get("errorCode"));
        assertFalse(ex.getMessage().contains("CANARYV") || ex.getDetails().toString().contains("CANARYV"), "오류에 답변 본문 없음");
        assertEquals(1, vlmCalls.get(), "근거 부재 거절은 재생성으로 해결되지 않는다(GPU 낭비 방지)");
        verify(guard, org.mockito.Mockito.timeout(3000)).release(any()); // 이벤트 루프 밖(전용 스케줄러)에서 해제
    }

    @Test
    void threeOrdinaryRejectionsRegenerateTwiceThenFail() {
        stub.policy = (n, in) -> ChatGateStubServer.out(70, "REJECTED", false);
        ScreenAiException ex = assertThrows(ScreenAiException.class, () -> service(true).analyze(1L, GROUP, req()).block());
        assertEquals("SCREEN_AI_QUALITY_REJECTED", ex.getCode());
        assertEquals(3, vlmCalls.get(), "최초 1 + 재생성 2");
    }

    @Test
    void regenerationStopsWhenNextAttemptWouldExceedSingleCallBudget() {
        // 시계를 호출마다 150초씩 진행 → 첫 시도 후 '평균 150초+' 라 한 번 더 하면 260초 상한을 넘는다 → 재생성하지 않는다.
        java.util.concurrent.atomic.AtomicLong t = new java.util.concurrent.atomic.AtomicLong(1_000_000L);
        java.time.Clock ticking = new java.time.Clock() {
            @Override public java.time.ZoneId getZone() { return java.time.ZoneOffset.UTC; }
            @Override public java.time.Clock withZone(java.time.ZoneId zone) { return this; }
            @Override public java.time.Instant instant() { return java.time.Instant.ofEpochMilli(millis()); }
            @Override public long millis() { return t.addAndGet(150_000L); }
        };
        stub.policy = (n, in) -> ChatGateStubServer.out(70, "REJECTED", false);
        ScreenAiException ex = assertThrows(ScreenAiException.class, () -> service(true, ticking).analyze(1L, GROUP, req()).block());
        assertEquals("SCREEN_AI_QUALITY_REJECTED", ex.getCode());
        assertEquals(1, vlmCalls.get(), "시간 예산 초과 예상 시 재생성 안 함(클라이언트 대기 상한 보호)");
    }

    @Test
    void evaluatorDownIsUnavailableAndNotRegenerated() {
        stub.policy = (n, in) -> null;
        ScreenAiException ex = assertThrows(ScreenAiException.class, () -> service(true).analyze(1L, GROUP, req()).block());
        assertEquals("SCREEN_AI_QUALITY_UNAVAILABLE", ex.getCode());
        assertEquals(503, ex.getStatus().value());
        assertTrue(ex.isRetryable());
        assertEquals(1, vlmCalls.get());
    }

    @Test
    void answerDisabledByAi07StaysScreenAiDisabledAndIsNotEvaluated() {
        org.mockito.Mockito.doReturn(Mono.error(VisionUpstreamClient.mapUpstreamError(503, "VISION_ANSWER_DISABLED", false, null, null)))
                .when(upstream).analyze(any());
        ScreenAiException ex = assertThrows(ScreenAiException.class, () -> service(true).analyze(1L, GROUP, req()).block());
        assertEquals("SCREEN_AI_DISABLED", ex.getCode());
        assertEquals(503, ex.getStatus().value());
        assertEquals(0, stub.evaluations.size());
    }

    @Test
    void gateOnLockCoversRegenerations_gateOffKeepsLegacyTtlAndBody() {
        stub.policy = (n, in) -> ChatGateStubServer.out(90, "APPROVED", false);
        service(true).analyze(1L, GROUP, req()).block();
        Map<String, Object> off = service(false).analyze(1L, GROUP, req()).block();
        ArgumentCaptor<Duration> ttl = ArgumentCaptor.forClass(Duration.class);
        verify(guard, times(2)).tryLock(anyString(), ttl.capture());
        assertTrue(ttl.getAllValues().get(0).compareTo(Duration.ofSeconds(3 * 260)) > 0, "게이트 ON: 재생성 2회까지 잠금 유지");
        assertEquals(Duration.ofSeconds(290), ttl.getAllValues().get(1), "게이트 OFF: 기존 TTL");
        assertEquals(1, stub.evaluations.size(), "게이트 OFF 는 평가기 호출 0");
        assertNull(off.get("qualityStatus"));
        assertFalse(off.containsKey("verified"));
        assertTrue(String.valueOf(off.get("answer")).contains("CANARYV"));
    }
}
