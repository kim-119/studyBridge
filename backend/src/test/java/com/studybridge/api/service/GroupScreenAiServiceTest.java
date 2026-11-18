package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.ScreenAiDTO.AnalyzeRequest;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.ScreenAiException;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.service.VisionUpstreamClient.VisionCall;
import com.studybridge.api.service.VisionUpstreamClient.VisionResult;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import reactor.core.publisher.Mono;

/**
 * 화면공유 AI 분석 권한·동의·요청 제한·취소. OpenVidu·ai07 은 Mock(실제 호출은 운영 E2E 에서 검증).
 * 방: 사용자 1(공유자 A, con_A/con_SA), 사용자 2(공유자 B, con_B/con_SB), 사용자 3(시청자, con_C).
 */
class GroupScreenAiServiceTest {

    private static final long GROUP = 25L;
    private static final String SID = "group_study_25";
    private static final long NOW = GroupVideoCallServiceTest.CLOCK.millis();

    private final ObjectMapper om = new ObjectMapper();
    private OpenViduService openVidu;
    private GroupStudyMemberRepository members;
    private UserRepository users;
    private ScreenAiConsentStore consent;
    private AiRequestGuard guard;
    private VisionUpstreamClient upstream;
    private GroupScreenAiService service;
    private final List<Map<String, Object>> connections = new ArrayList<>();
    private String jpeg;

    @BeforeEach
    void setUp() throws Exception {
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
        for (long id = 1; id <= 3; id++) {
            User u = new User();
            u.setDisplayName("사용자" + id);
            when(users.findById(id)).thenReturn(Optional.of(u));
        }
        GroupVideoCallService video = GroupVideoCallServiceTest.newService(openVidu, members, om, 2500, 1500);
        service = new GroupScreenAiService(video, openVidu, members, users, om, consent, guard, upstream,
                GroupVideoCallServiceTest.CLOCK, true, 1000, 1024 * 1024, 1280, 32, 6, 30);
        jpeg = ScreenAiImageValidatorTest.jpegB64(1280, 720);

        connections.add(primary("con_A", 1L));
        connections.add(primary("con_B", 2L));
        connections.add(primary("con_C", 3L));
        connections.add(screen("con_SA", 1L, "con_A", "str_SA_SCREEN"));
        connections.add(screen("con_SB", 2L, "con_B", "str_SB_SCREEN"));
    }

    private String sd(long userId, String kind, String owner) {
        return VideoConnectionMetadata.toServerData(om, GROUP, userId, VideoConnectionMetadata.Kind.valueOf(kind), owner, null, "WEB", NOW - 5_000);
    }

    private Map<String, Object> conn(String id, String serverData, List<Map<String, Object>> publishers, long activeAt) {
        Map<String, Object> c = new HashMap<>();
        c.put("connectionId", id);
        c.put("status", "active");
        c.put("serverData", serverData);
        c.put("clientData", "{\"userId\":999}");
        c.put("createdAt", activeAt - 500);
        c.put("activeAt", activeAt);
        c.put("publishers", publishers);
        return c;
    }

    private Map<String, Object> primary(String id, long userId) {
        return conn(id, sd(userId, "PRIMARY", null), List.of(publisher("str_" + id + "_CAMERA", "CAMERA")), NOW - 60_000);
    }

    private Map<String, Object> screen(String id, long userId, String owner, String streamId) {
        return conn(id, sd(userId, "SCREEN", owner), List.of(publisher(streamId, "SCREEN")), NOW - 30_000 + userId);
    }

    private static Map<String, Object> publisher(String streamId, String typeOfVideo) {
        return Map.of("streamId", streamId, "mediaOptions", Map.of("typeOfVideo", typeOfVideo, "hasVideo", true));
    }

    private AnalyzeRequest req(String connectionId, String streamId) {
        return new AnalyzeRequest(connectionId, streamId, "  이 Python 오류의 원인을 분석해 줘.  ", jpeg, "image/jpeg", "cr_1234567890");
    }

    private void upstreamAnswers(String answer) {
        when(upstream.analyze(any())).thenAnswer(inv -> Mono.just(new VisionResult(((VisionCall) inv.getArgument(0)).requestId(),
                answer, "qwen3-vl:4b-instruct", 1500L, 0L, 1400L)));
    }

    // ── 정상 경로 · 화면 구분 ──

    @Test
    void viewerAsksAboutConsentedShare_sharerAndAskerComeFromServer_notClient() {
        when(consent.isAllowed(GROUP, "con_SB", 2L)).thenReturn(true);
        upstreamAnswers("화면에 보이는 내용: ZeroDivisionError\n분석: 0으로 나눴습니다.");

        Map<String, Object> res = service.analyze(3L, GROUP, req("con_SB", "str_SB_SCREEN")).block();

        ArgumentCaptor<VisionCall> call = ArgumentCaptor.forClass(VisionCall.class);
        verify(upstream).analyze(call.capture());
        assertEquals(2L, call.getValue().sharerUserId());   // serverData(공유자 B)
        assertEquals(3L, call.getValue().askerUserId());    // JWT 사용자
        assertEquals(GROUP, call.getValue().groupId());
        assertEquals("str_SB_SCREEN", call.getValue().streamId());
        assertEquals("이 Python 오류의 원인을 분석해 줘.", call.getValue().question()); // 앞뒤 공백 제거
        assertEquals(jpeg, call.getValue().imageBase64());
        assertTrue(call.getValue().requestId().matches("^[0-9a-f-]{36}$"));
        assertFalse(call.getValue().toString().contains("Python"));

        assertEquals("화면에 보이는 내용: ZeroDivisionError\n분석: 0으로 나눴습니다.", res.get("answer"));
        assertEquals("con_SB", res.get("connectionId"));
        assertEquals("cr_1234567890", res.get("clientRequestId"));
        @SuppressWarnings("unchecked") Map<String, Object> sharer = (Map<String, Object>) res.get("sharer");
        assertEquals(2L, sharer.get("userId"));
        assertEquals("사용자2", sharer.get("name"));
        assertEquals(false, sharer.get("isMine"));
        verify(guard).release(any());
    }

    @Test
    void twoSharesAreDistinguishedByConnection() {
        when(consent.isAllowed(eq(GROUP), anyString(), anyLong())).thenReturn(true);
        upstreamAnswers("ok");

        service.analyze(3L, GROUP, req("con_SA", "str_SA_SCREEN")).block();
        service.analyze(3L, GROUP, req("con_SB", "str_SB_SCREEN")).block();

        ArgumentCaptor<VisionCall> calls = ArgumentCaptor.forClass(VisionCall.class);
        verify(upstream, times(2)).analyze(calls.capture());
        assertEquals(1L, calls.getAllValues().get(0).sharerUserId());
        assertEquals("str_SA_SCREEN", calls.getAllValues().get(0).streamId());
        assertEquals(2L, calls.getAllValues().get(1).sharerUserId());
        assertEquals("str_SB_SCREEN", calls.getAllValues().get(1).streamId());
        assertNotEquals(calls.getAllValues().get(0).requestId(), calls.getAllValues().get(1).requestId());
    }

    @Test
    void sharerMayAnalyzeOwnScreen_withoutSeparateConsent() {
        upstreamAnswers("내 화면");
        Map<String, Object> res = service.analyze(1L, GROUP, req("con_SA", "str_SA_SCREEN")).block();
        assertEquals("내 화면", res.get("answer"));
        verify(consent, never()).isAllowed(anyLong(), anyString(), anyLong());
    }

    // ── 권한 · 동의 ──

    @Test
    void nonMember_isRejected_beforeAnyLookup() {
        when(members.existsByGroupStudyIdAndUserIdAndStatus(GROUP, 9L, GroupStudyMemberStatus.JOINED)).thenReturn(false);
        ScreenAiException ex = assertThrows(ScreenAiException.class, () -> service.analyze(9L, GROUP, req("con_SB", "str_SB_SCREEN")));
        assertEquals("NOT_GROUP_MEMBER", ex.getCode());
        assertEquals(403, ex.getStatus().value());
        verify(openVidu, never()).listConnections(anyString(), anyBoolean());
        verify(upstream, never()).analyze(any());
    }

    @Test
    void missingConsent_isRejected_andLockReleased() {
        when(consent.isAllowed(GROUP, "con_SB", 2L)).thenReturn(false);
        ScreenAiException ex = assertThrows(ScreenAiException.class, () -> service.analyze(3L, GROUP, req("con_SB", "str_SB_SCREEN")));
        assertEquals("SHARER_CONSENT_REQUIRED", ex.getCode());
        assertEquals(403, ex.getStatus().value());
        verify(upstream, never()).analyze(any());
        verify(guard).release(any());
    }

    @Test
    void askerMustBeConnectedToTheRoomVideo() {
        connections.removeIf(c -> "con_C".equals(c.get("connectionId")));
        when(consent.isAllowed(GROUP, "con_SB", 2L)).thenReturn(true);
        ScreenAiException ex = assertThrows(ScreenAiException.class, () -> service.analyze(3L, GROUP, req("con_SB", "str_SB_SCREEN")));
        assertEquals("VIEWER_NOT_CONNECTED", ex.getCode());
        verify(upstream, never()).analyze(any());
    }

    @Test
    void endedShare_orphanShare_primaryConnection_andStaleStream_areRejected() {
        when(consent.isAllowed(eq(GROUP), anyString(), anyLong())).thenReturn(true);
        assertEquals("SCREEN_NOT_FOUND", assertThrows(ScreenAiException.class,
                () -> service.analyze(3L, GROUP, req("con_SX", "str_SX_SCREEN"))).getCode());
        // PRIMARY(카메라) Connection 은 화면이 아니다
        assertEquals("SCREEN_NOT_FOUND", assertThrows(ScreenAiException.class,
                () -> service.analyze(3L, GROUP, req("con_B", "str_con_B_CAMERA"))).getCode());
        // 공유를 다시 시작해 streamId 가 바뀜
        assertEquals("SCREEN_STREAM_MISMATCH", assertThrows(ScreenAiException.class,
                () -> service.analyze(3L, GROUP, req("con_SB", "str_OLD_SCREEN"))).getCode());
        // 소유 PRIMARY 가 사라진 orphan
        connections.removeIf(c -> "con_B".equals(c.get("connectionId")));
        assertEquals("SCREEN_NOT_FOUND", assertThrows(ScreenAiException.class,
                () -> service.analyze(3L, GROUP, req("con_SB", "str_SB_SCREEN"))).getCode());
        verify(upstream, never()).analyze(any());
    }

    @Test
    void screenOwnedByAnotherUsersPrimary_isNotTrusted() {
        // serverData.userId=2 인데 ownerConnectionId 가 사용자 1의 PRIMARY → 귀속 위조로 보고 제외
        connections.add(screen("con_SZ", 2L, "con_A", "str_SZ_SCREEN"));
        when(consent.isAllowed(eq(GROUP), anyString(), anyLong())).thenReturn(true);
        assertEquals("SCREEN_NOT_FOUND", assertThrows(ScreenAiException.class,
                () -> service.analyze(3L, GROUP, req("con_SZ", "str_SZ_SCREEN"))).getCode());
    }

    @Test
    void sharerWhoLeftTheGroup_isRejected() {
        when(members.existsByGroupStudyIdAndUserIdAndStatus(GROUP, 2L, GroupStudyMemberStatus.JOINED)).thenReturn(false);
        when(consent.isAllowed(GROUP, "con_SB", 2L)).thenReturn(true);
        assertEquals("SCREEN_NOT_FOUND", assertThrows(ScreenAiException.class,
                () -> service.analyze(3L, GROUP, req("con_SB", "str_SB_SCREEN"))).getCode());
    }

    // ── 입력 검증 ──

    @Test
    void questionAndIdsAreValidated_beforeLocking() {
        assertEquals("SCREEN_AI_QUESTION_INVALID", assertThrows(ScreenAiException.class, () -> service.analyze(3L, GROUP,
                new AnalyzeRequest("con_SB", "str_SB_SCREEN", "   ", jpeg, "image/jpeg", null))).getCode());
        assertEquals("SCREEN_AI_QUESTION_INVALID", assertThrows(ScreenAiException.class, () -> service.analyze(3L, GROUP,
                new AnalyzeRequest("con_SB", "str_SB_SCREEN", "가".repeat(1001), jpeg, "image/jpeg", null))).getCode());
        assertEquals("INVALID_REQUEST", assertThrows(ScreenAiException.class, () -> service.analyze(3L, GROUP,
                new AnalyzeRequest("con_S B", "str_SB_SCREEN", "q", jpeg, "image/jpeg", null))).getCode());
        assertEquals("INVALID_REQUEST", assertThrows(ScreenAiException.class, () -> service.analyze(3L, GROUP,
                new AnalyzeRequest("con_SB", null, "q", jpeg, "image/jpeg", null))).getCode());
        assertEquals("SCREEN_AI_IMAGE_INVALID", assertThrows(ScreenAiException.class, () -> service.analyze(3L, GROUP,
                new AnalyzeRequest("con_SB", "str_SB_SCREEN", "q", jpeg, "image/png", null))).getCode());
        verify(guard, never()).tryLock(anyString(), any());
    }

    @Test
    void requestToString_neverContainsQuestionOrImage() {
        String s = req("con_SB", "str_SB_SCREEN").toString();
        assertFalse(s.contains("Python"));
        assertFalse(s.contains(jpeg.substring(0, 24)));
    }

    // ── 요청 제한 ──

    @Test
    void secondConcurrentRequestOfSameUser_isRejected() {
        when(guard.tryLock(anyString(), any())).thenAnswer(inv -> new AiRequestGuard.Lock(inv.getArgument(0), "t", false));
        ScreenAiException ex = assertThrows(ScreenAiException.class, () -> service.analyze(3L, GROUP, req("con_SB", "str_SB_SCREEN")));
        assertEquals("SCREEN_AI_IN_PROGRESS", ex.getCode());
        assertEquals(429, ex.getStatus().value());
        assertTrue(ex.isRetryable());
        verify(guard, never()).release(any());
    }

    @Test
    void perUserRateLimit_rejectsWithRetryAfter_andReleasesLock() {
        when(guard.allow(eq(AiRequestGuard.rateKey("screen-ai", 3L)), eq(6), any())).thenReturn(false);
        ScreenAiException ex = assertThrows(ScreenAiException.class, () -> service.analyze(3L, GROUP, req("con_SB", "str_SB_SCREEN")));
        assertEquals("SCREEN_AI_RATE_LIMITED", ex.getCode());
        assertEquals(60, ex.getRetryAfterSeconds());
        verify(guard).release(any());
        verify(upstream, never()).analyze(any());
    }

    @Test
    void upstreamFailure_isPropagated_andLockReleased() {
        when(consent.isAllowed(GROUP, "con_SB", 2L)).thenReturn(true);
        when(upstream.analyze(any())).thenReturn(Mono.error(VisionUpstreamClient.mapUpstreamError(429, "VISION_QUEUE_FULL", true, 7, null)));
        ScreenAiException ex = assertThrows(ScreenAiException.class, () -> service.analyze(3L, GROUP, req("con_SB", "str_SB_SCREEN")).block());
        assertEquals("SCREEN_AI_BUSY", ex.getCode());
        assertEquals(7, ex.getRetryAfterSeconds());
        verify(guard).release(any());
    }

    // ── 취소 ──

    @Test
    void cancel_stopsTheUpstreamSubscription() {
        when(consent.isAllowed(GROUP, "con_SB", 2L)).thenReturn(true);
        AtomicBoolean upstreamCancelled = new AtomicBoolean(false);
        when(upstream.analyze(any())).thenReturn(Mono.<VisionResult>never().doOnCancel(() -> upstreamCancelled.set(true)));
        AtomicReference<Throwable> error = new AtomicReference<>();

        service.analyze(3L, GROUP, req("con_SB", "str_SB_SCREEN")).subscribe(x -> {}, error::set);
        Map<String, Object> res = service.cancel(3L, GROUP, "cr_1234567890");

        assertEquals(true, res.get("cancelled"));
        assertTrue(upstreamCancelled.get());
        assertEquals("SCREEN_AI_CANCELLED", ((ScreenAiException) error.get()).getCode());
        verify(guard).release(any());
        // 다른 사용자는 남의 요청을 취소할 수 없고, 두 번째 취소는 멱등
        assertEquals(false, service.cancel(2L, GROUP, "cr_1234567890").get("cancelled"));
        assertEquals(false, service.cancel(3L, GROUP, "cr_1234567890").get("cancelled"));
    }

    // ── 목록 · 동의 변경 ──

    @Test
    void listShares_reportsSharerConsentAndOwnership() {
        when(consent.isAllowed(GROUP, "con_SA", 1L)).thenReturn(false);
        when(consent.isAllowed(GROUP, "con_SB", 2L)).thenReturn(true);
        Map<String, Object> res = service.listShares(1L, GROUP);
        @SuppressWarnings("unchecked") List<Map<String, Object>> shares = (List<Map<String, Object>>) res.get("shares");
        assertEquals(2, shares.size());
        assertEquals("con_SA", shares.get(0).get("connectionId"));
        assertEquals("str_SA_SCREEN", shares.get(0).get("streamId"));
        assertEquals("사용자1", shares.get(0).get("sharerName"));
        assertEquals(true, shares.get(0).get("isMine"));
        assertEquals(true, shares.get(0).get("analyzable")); // 본인 화면
        assertEquals(false, shares.get(0).get("aiConsent"));
        assertEquals(false, shares.get(1).get("isMine"));
        assertEquals(true, shares.get(1).get("analyzable"));
        assertEquals(true, res.get("viewerConnected"));
        assertEquals(true, res.get("enabled"));
    }

    @Test
    void consentCanOnlyBeChangedByTheSharer() {
        when(openVidu.getConnection(SID, "con_SB")).thenReturn(Optional.of(screen("con_SB", 2L, "con_B", "str_SB_SCREEN")));
        when(openVidu.getConnection(SID, "con_C")).thenReturn(Optional.of(primary("con_C", 3L)));

        assertEquals("NOT_SHARE_OWNER", assertThrows(ScreenAiException.class, () -> service.setConsent(3L, GROUP, "con_SB", true)).getCode());
        assertEquals("SCREEN_NOT_FOUND", assertThrows(ScreenAiException.class, () -> service.setConsent(3L, GROUP, "con_C", true)).getCode());
        verify(consent, never()).set(anyLong(), anyString(), anyLong(), anyBoolean());

        Map<String, Object> res = service.setConsent(2L, GROUP, "con_SB", true);
        assertEquals(true, res.get("aiConsent"));
        verify(consent).set(GROUP, "con_SB", 2L, true);
    }

    @Test
    void disabledFeature_rejectsBeforeAnything() {
        GroupScreenAiService off = new GroupScreenAiService(GroupVideoCallServiceTest.newService(openVidu, members, om, 2500, 1500),
                openVidu, members, users, om, consent, guard, upstream, GroupVideoCallServiceTest.CLOCK, false, 1000, 1024 * 1024, 1280, 32, 6, 30);
        assertEquals("SCREEN_AI_DISABLED", assertThrows(ScreenAiException.class, () -> off.analyze(3L, GROUP, req("con_SB", "str_SB_SCREEN"))).getCode());
    }
}
