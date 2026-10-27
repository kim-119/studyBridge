package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.exception.VideoCallException;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.service.OpenViduService.ConnectionGrant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Supplier;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/**
 * 방별 화면공유 최대 2명: 승인(원자적 조회-판정-생성), 예약(pending) TTL, orphan 반환, 동일 사용자 중복, 동시 요청 경쟁, 주기 정리.
 * OpenVidu 는 Mock(실제 연결은 E2E 에서 별도 검증).
 */
class ScreenShareLimitTest {

    private static final long GROUP = 25L;
    private static final String SID = "group_study_25";
    private static final long NOW = GroupVideoCallServiceTest.CLOCK.millis();

    private final ObjectMapper om = new ObjectMapper();
    private OpenViduService openVidu;
    private GroupStudyMemberRepository members;
    private GroupVideoCallService service;

    @BeforeEach
    void setUp() {
        openVidu = mock(OpenViduService.class);
        members = mock(GroupStudyMemberRepository.class);
        when(members.existsByGroupStudyIdAndUserIdAndStatus(eq(GROUP), anyLong(), eq(GroupStudyMemberStatus.JOINED))).thenReturn(true);
        service = GroupVideoCallServiceTest.newService(openVidu, members, om, 2500, 1500);
    }

    private String sd(long userId, String kind, String owner) {
        return VideoConnectionMetadata.toServerData(om, GROUP, userId, VideoConnectionMetadata.Kind.valueOf(kind), owner, null, "WEB", NOW - 5_000);
    }

    private Map<String, Object> conn(String id, String status, String serverData, long createdAt, List<Map<String, Object>> publishers) {
        Map<String, Object> c = new HashMap<>();
        c.put("connectionId", id);
        c.put("status", status);
        c.put("serverData", serverData);
        c.put("clientData", "{}");
        c.put("createdAt", createdAt);
        c.put("activeAt", "active".equals(status) ? createdAt + 500 : null);
        c.put("publishers", publishers);
        return c;
    }

    private Map<String, Object> primary(String id, long userId) {
        return conn(id, "active", sd(userId, "PRIMARY", null), NOW - 60_000, List.of());
    }

    private Map<String, Object> screen(String id, String status, long userId, String owner, long createdAt) {
        return conn(id, status, sd(userId, "SCREEN", owner), createdAt, List.of());
    }

    private void myPrimaryActive(String id, long userId) {
        when(openVidu.getConnection(SID, id)).thenReturn(Optional.of(primary(id, userId)));
    }

    // ── 승인 정책 ──

    @Test
    void thirdSharer_isRejectedWithLimitCode_andNothingIsCreated() {
        myPrimaryActive("con_C", 3L);
        when(openVidu.listConnections(SID, true)).thenReturn(List.of(
                primary("con_A", 1L), primary("con_B", 2L), primary("con_C", 3L),
                screen("con_SA", "active", 1L, "con_A", NOW - 20_000),
                screen("con_SB", "active", 2L, "con_B", NOW - 10_000)));

        VideoCallException ex = assertThrows(VideoCallException.class, () -> service.issueScreenToken(3L, GROUP, "con_C", null, null));

        assertEquals("SCREEN_SHARE_LIMIT_REACHED", ex.getCode());
        assertEquals(409, ex.getStatus().value());
        assertEquals("현재 화면공유 가능 인원(최대 2명)이 모두 사용 중입니다.", ex.getMessage());
        assertEquals(2, ex.getDetails().get("limit"));
        assertEquals(2, ex.getDetails().get("activeCount"));
        verify(openVidu, never()).createConnection(anyString(), anyString(), any(), any());
        verify(openVidu, never()).deleteConnection(anyString(), anyString());
    }

    @Test
    void zeroOrOneSharer_allowsStart_andResponseCarriesLimit() {
        myPrimaryActive("con_B", 2L);
        when(openVidu.listConnections(SID, true)).thenReturn(List.of(
                primary("con_A", 1L), primary("con_B", 2L),
                screen("con_SA", "active", 1L, "con_A", NOW - 20_000)));
        when(openVidu.createConnection(eq(SID), anyString(), eq("PUBLISHER"), any())).thenReturn(new ConnectionGrant("con_SB", "tok"));

        Map<String, Object> res = service.issueScreenToken(2L, GROUP, "con_B", null, null);

        assertEquals("con_SB", res.get("connectionId"));
        assertEquals(2, res.get("screenShareLimit"));
    }

    @Test
    void freshPendingReservation_ofAnotherUser_countsTowardTheLimit() {
        myPrimaryActive("con_C", 3L);
        when(openVidu.listConnections(SID, true)).thenReturn(List.of(
                primary("con_A", 1L), primary("con_B", 2L), primary("con_C", 3L),
                screen("con_SA", "active", 1L, "con_A", NOW - 20_000),
                screen("con_SB", "pending", 2L, "con_B", NOW - 2_000))); // B 가 막 승인받고 접속 중

        assertEquals("SCREEN_SHARE_LIMIT_REACHED",
                assertThrows(VideoCallException.class, () -> service.issueScreenToken(3L, GROUP, "con_C", null, null)).getCode());
        verify(openVidu, never()).deleteConnection(SID, "con_SB");
    }

    @Test
    void expiredReservation_andOrphanScreens_releaseTheirSlots() {
        myPrimaryActive("con_C", 3L);
        when(openVidu.listConnections(SID, true)).thenReturn(List.of(
                primary("con_A", 1L), primary("con_B", 2L), primary("con_C", 3L),
                screen("con_SA", "active", 1L, "con_A", NOW - 20_000),
                screen("con_SB_EXPIRED", "pending", 2L, "con_B", NOW - 31_000),          // TTL(30s) 지나도록 접속 안 함
                screen("con_SD_ORPHAN", "active", 4L, "con_D_GONE", NOW - 90_000)));     // 공유자 PRIMARY 퇴장(브라우저 강제 종료 등)
        when(openVidu.createConnection(eq(SID), anyString(), any(), any())).thenReturn(new ConnectionGrant("con_SC", "tok"));

        assertEquals("con_SC", service.issueScreenToken(3L, GROUP, "con_C", null, null).get("connectionId"));
        verify(openVidu).deleteConnection(SID, "con_SB_EXPIRED");
        verify(openVidu).deleteConnection(SID, "con_SD_ORPHAN");
        verify(openVidu, never()).deleteConnection(SID, "con_SA");
    }

    @Test
    void sameTabRetry_replacesItsOwnPendingReservation_insteadOfHoldingTwoSlots() {
        myPrimaryActive("con_A", 1L);
        when(openVidu.listConnections(SID, true)).thenReturn(List.of(
                primary("con_A", 1L), primary("con_B", 2L),
                screen("con_SB", "active", 2L, "con_B", NOW - 20_000),
                screen("con_SA_OLD", "pending", 1L, "con_A", NOW - 3_000)));
        when(openVidu.createConnection(eq(SID), anyString(), any(), any())).thenReturn(new ConnectionGrant("con_SA_NEW", "tok"));

        assertEquals("con_SA_NEW", service.issueScreenToken(1L, GROUP, "con_A", null, null).get("connectionId"));
        verify(openVidu).deleteConnection(SID, "con_SA_OLD");
    }

    @Test
    void sameUser_otherDeviceStarting_isNotInterrupted() {
        myPrimaryActive("con_APC", 1L);
        when(openVidu.listConnections(SID, true)).thenReturn(List.of(
                primary("con_APC", 1L), primary("con_ALAPTOP", 1L),
                screen("con_SALAPTOP", "pending", 1L, "con_ALAPTOP", NOW - 3_000)));

        VideoCallException ex = assertThrows(VideoCallException.class, () -> service.issueScreenToken(1L, GROUP, "con_APC", null, null));
        assertEquals("SCREEN_START_IN_PROGRESS", ex.getCode());
        assertEquals(409, ex.getStatus().value());
        verify(openVidu, never()).deleteConnection(anyString(), anyString());
        verify(openVidu, never()).createConnection(anyString(), anyString(), any(), any());
    }

    @Test
    void listConnections_reportsOccupiedScreensOnly_andTheLimit() {
        when(openVidu.listConnections(SID, false)).thenReturn(List.of(
                primary("con_A", 1L), primary("con_B", 2L),
                screen("con_SA", "active", 1L, "con_A", NOW - 20_000),
                screen("con_SX", "active", 9L, "con_GONE", NOW - 20_000)));

        Map<String, Object> res = service.listActiveConnections(1L, GROUP);

        assertEquals(1, res.get("screenShareCount"));
        assertEquals(2, res.get("screenShareLimit"));
    }

    // ── 동시성: 서로 다른 사용자의 동시 시작 요청 ──

    /** OpenVidu 를 흉내 내는 상태 저장소. 조회·생성 사이에 지연을 둬 잠금이 없으면 경쟁이 반드시 드러나게 한다. */
    private static final class FakeOpenVidu {
        final List<Map<String, Object>> connections = Collections.synchronizedList(new ArrayList<>());
        final AtomicInteger seq = new AtomicInteger();

        List<Map<String, Object>> snapshot() {
            synchronized (connections) {
                return new ArrayList<>(connections);
            }
        }

        void sleep() {
            try {
                Thread.sleep(15);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
    }

    private FakeOpenVidu wireFake(int users) {
        FakeOpenVidu fake = new FakeOpenVidu();
        for (long u = 1; u <= users; u++) {
            Map<String, Object> p = primary("con_P" + u, u);
            fake.connections.add(p);
            when(openVidu.getConnection(SID, "con_P" + u)).thenReturn(Optional.of(p));
        }
        when(openVidu.listConnections(eq(SID), eq(true))).thenAnswer(inv -> {
            List<Map<String, Object>> snap = fake.snapshot();
            fake.sleep();
            return snap;
        });
        when(openVidu.createConnection(eq(SID), anyString(), eq("PUBLISHER"), any())).thenAnswer(inv -> {
            fake.sleep();
            String id = "con_S" + fake.seq.incrementAndGet();
            Map<String, Object> c = new HashMap<>();
            c.put("connectionId", id);
            c.put("status", "pending");
            c.put("serverData", inv.getArgument(1));
            c.put("createdAt", NOW);
            c.put("publishers", List.of());
            fake.connections.add(c);
            return new ConnectionGrant(id, "tok_" + id);
        });
        return fake;
    }

    private Map<String, Integer> raceStart(GroupVideoCallService svc, int users) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(users);
        CountDownLatch go = new CountDownLatch(1);
        List<Future<String>> results = new ArrayList<>();
        for (long u = 1; u <= users; u++) {
            final long userId = u;
            results.add(pool.submit(() -> {
                go.await();
                try {
                    svc.issueScreenToken(userId, GROUP, "con_P" + userId, null, null);
                    return "GRANTED";
                } catch (VideoCallException e) {
                    return e.getCode();
                }
            }));
        }
        go.countDown();
        Map<String, Integer> tally = new ConcurrentHashMap<>();
        for (Future<String> f : results) tally.merge(f.get(10, TimeUnit.SECONDS), 1, Integer::sum);
        pool.shutdownNow();
        return tally;
    }

    @Test
    void concurrentStartsFromTenUsers_grantExactlyTwo() throws Exception {
        FakeOpenVidu fake = wireFake(10);

        Map<String, Integer> tally = raceStart(service, 10);

        assertEquals(2, tally.getOrDefault("GRANTED", 0), tally.toString());
        assertEquals(8, tally.getOrDefault("SCREEN_SHARE_LIMIT_REACHED", 0), tally.toString());
        assertEquals(2, fake.snapshot().stream()
                .filter(c -> String.valueOf(c.get("connectionId")).startsWith("con_S")).count());
    }

    @Test
    void withoutTheAdmissionLock_theSameRaceOverAdmits_controlExperiment() throws Exception {
        // 대조군: 잠금을 빼면(조회-판정-생성이 겹치면) 같은 조건에서 2명을 넘는다 → 위 테스트가 잠금 덕분에 통과함을 보인다.
        ScreenShareAdmissionLock noLock = new ScreenShareAdmissionLock(mock(AiRequestGuard.class), 0, 1000) {
            @Override
            public <T> T runExclusive(long groupId, Supplier<T> body) {
                return body.get();
            }
        };
        GroupVideoCallService unlocked = new GroupVideoCallService(openVidu, members, om, noLock, GroupVideoCallServiceTest.CLOCK,
                "group_study_", 2500, 2500, 1500, 2, 30_000);
        wireFake(10);

        Map<String, Integer> tally = raceStart(unlocked, 10);

        assertTrue(tally.getOrDefault("GRANTED", 0) > 2, tally.toString());
    }

    @Test
    void sameUserDoubleClick_concurrently_neverHoldsTwoSlots() throws Exception {
        FakeOpenVidu fake = wireFake(1);
        ExecutorService pool = Executors.newFixedThreadPool(4);
        CountDownLatch go = new CountDownLatch(1);
        List<Future<?>> fs = new ArrayList<>();
        for (int i = 0; i < 4; i++) {
            fs.add(pool.submit(() -> {
                go.await();
                try {
                    service.issueScreenToken(1L, GROUP, "con_P1", null, null);
                } catch (VideoCallException ignored) {
                    // 같은 탭 재시도는 이전 예약을 넘겨받는다
                }
                return null;
            }));
        }
        when(openVidu.deleteConnection(eq(SID), anyString())).thenAnswer(inv -> {
            String id = inv.getArgument(1);
            return fake.connections.removeIf(c -> id.equals(c.get("connectionId")));
        });
        go.countDown();
        for (Future<?> f : fs) f.get(10, TimeUnit.SECONDS);
        pool.shutdownNow();

        long screens = fake.snapshot().stream().filter(c -> String.valueOf(c.get("connectionId")).startsWith("con_S")).count();
        assertEquals(1, screens);
    }

    // ── 주기 정리(사후 강제) ──

    @Test
    void enforcer_closesStaleAndOverLimit_andUnpublishesScreenOnPrimary() {
        Map<String, Object> pubScreen = Map.of("streamId", "str_BYPASS", "mediaOptions", Map.of("typeOfVideo", "SCREEN"));
        Map<String, Object> pubCam = Map.of("streamId", "str_CAM", "mediaOptions", Map.of("typeOfVideo", "CAMERA"));
        Map<String, Object> pubCustom = Map.of("streamId", "str_CUSTOM", "mediaOptions", Map.of("typeOfVideo", "CUSTOM"));
        List<Map<String, Object>> conns = List.of(
                primary("con_A", 1L), primary("con_B", 2L), primary("con_C", 3L),
                conn("con_D", "active", sd(4L, "PRIMARY", null), NOW - 60_000, List.of(pubScreen)),   // 승인 우회: PRIMARY 로 SCREEN 게시
                conn("con_E", "active", sd(5L, "PRIMARY", null), NOW - 60_000, List.of(pubCam)),
                conn("con_F", "active", sd(6L, "PRIMARY", null), NOW - 60_000, List.of(pubCustom)),   // 카메라 handoff(CUSTOM)는 건드리지 않음
                screen("con_SA", "active", 1L, "con_A", NOW - 30_000),
                screen("con_SB", "active", 2L, "con_B", NOW - 20_000),
                screen("con_SC", "active", 3L, "con_C", NOW - 10_000),                // 한도 초과(가장 늦게 시작)
                screen("con_SX", "pending", 7L, "con_X_GONE", NOW - 1_000));          // orphan
        when(openVidu.listConnections(SID, true)).thenReturn(conns);
        when(openVidu.deleteConnection(eq(SID), anyString())).thenReturn(true);
        when(openVidu.forceUnpublish(eq(SID), anyString())).thenReturn(true);

        assertTrue(service.needsScreenEnforcement(conns));
        GroupVideoCallService.ScreenEnforcement r = service.enforceScreenSharePolicy(SID).orElseThrow();

        assertEquals(1, r.staleClosed());
        assertEquals(1, r.overLimitClosed());
        assertEquals(1, r.bypassUnpublished());
        verify(openVidu).deleteConnection(SID, "con_SX");
        verify(openVidu).deleteConnection(SID, "con_SC");
        verify(openVidu, never()).deleteConnection(SID, "con_SA");
        verify(openVidu, never()).deleteConnection(SID, "con_SB");
        verify(openVidu).forceUnpublish(SID, "str_BYPASS");
        verify(openVidu, never()).forceUnpublish(SID, "str_CAM");
        verify(openVidu, never()).forceUnpublish(SID, "str_CUSTOM");
        verify(openVidu, never()).deleteConnection(SID, "con_D"); // 카메라·마이크 Connection 자체는 유지
    }

    @Test
    void enforcer_leavesHealthyRoomsAndForeignSessionsAlone() {
        List<Map<String, Object>> healthy = List.of(primary("con_A", 1L), primary("con_B", 2L),
                screen("con_SA", "active", 1L, "con_A", NOW - 30_000),
                screen("con_SB", "pending", 2L, "con_B", NOW - 2_000));
        assertFalse(service.needsScreenEnforcement(healthy));
        assertEquals(0, service.enforceScreenSharePolicy("sbe2e_group_25").orElseThrow().staleClosed());
        assertEquals(null, service.groupIdOf("sbe2e_group_25"));
        assertEquals(null, service.groupIdOf("group_study_abc"));
        assertEquals(25L, service.groupIdOf("group_study_25"));
        verify(openVidu, never()).listConnections(eq("sbe2e_group_25"), anyBoolean());
    }

    @Test
    void enforcerJob_skipsSessionsThatNeedNothing_andSurvivesOpenViduErrors() {
        ScreenSharePolicyEnforcer job = new ScreenSharePolicyEnforcer(openVidu, service, true);
        when(openVidu.listSessionConnections()).thenThrow(new RuntimeException("down"));
        job.enforce(); // 예외 전파 없음

        Map<String, List<Map<String, Object>>> sessions = new HashMap<>();
        sessions.put(SID, List.of(primary("con_A", 1L), screen("con_SA", "active", 1L, "con_A", NOW - 30_000)));
        sessions.put("other_prefix_9", List.of(screen("con_Z", "pending", 1L, "con_GONE", 0L)));
        doReturn(sessions).when(openVidu).listSessionConnections();
        job.enforce();
        verify(openVidu, never()).listConnections(anyString(), anyBoolean());
        verify(openVidu, never()).deleteConnection(anyString(), anyString());

        new ScreenSharePolicyEnforcer(openVidu, service, false).enforce();
    }
}
