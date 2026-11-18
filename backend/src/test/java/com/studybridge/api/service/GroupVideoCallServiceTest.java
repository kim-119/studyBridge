package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.exception.VideoCallException;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.service.OpenViduService.ConnectionGrant;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

/**
 * Ghost Connection 수정의 서버 계약: PRIMARY 토큰의 serverData 에 서버 검증 userId/kind 가 실리고,
 * 실시간 접속 목록은 OpenVidu active Connection 만, 참여 인원은 PRIMARY 고유 userId 로 센다.
 */
class GroupVideoCallServiceTest {

    private static final long USER = 8L;
    private static final long GROUP = 25L;
    private static final String SID = "group_study_25";

    private final ObjectMapper om = new ObjectMapper();
    private OpenViduService openVidu;
    private GroupStudyMemberRepository members;
    private GroupVideoCallService service;
    static final Clock CLOCK = Clock.fixed(Instant.ofEpochMilli(1_000_000L), ZoneOffset.UTC);

    /** Redis 잠금은 항상 획득(단위 테스트는 JVM 잠금 경로만 검증, Redis 경로는 ScreenShareAdmissionLockRedisTest). */
    static ScreenShareAdmissionLock jvmOnlyLock() {
        AiRequestGuard guard = mock(AiRequestGuard.class);
        when(guard.tryLock(anyString(), any())).thenAnswer(inv -> new AiRequestGuard.Lock(inv.getArgument(0), "t", true));
        return new ScreenShareAdmissionLock(guard, 5000, 60000);
    }

    static GroupVideoCallService newService(OpenViduService openVidu, GroupStudyMemberRepository members, ObjectMapper om,
                                            int screenMax, int screenMin) {
        return new GroupVideoCallService(openVidu, members, om, jvmOnlyLock(), CLOCK, "group_study_", 2500, screenMax, screenMin, 2, 30_000);
    }

    @BeforeEach
    void setUp() {
        openVidu = mock(OpenViduService.class);
        members = mock(GroupStudyMemberRepository.class);
        when(members.existsByGroupStudyIdAndUserIdAndStatus(GROUP, USER, GroupStudyMemberStatus.JOINED)).thenReturn(true);
        service = newService(openVidu, members, om, 2500, 1500);
    }

    private static Map<String, Object> conn(String id, String status, String serverData, String clientData) {
        Map<String, Object> c = new HashMap<>();
        c.put("connectionId", id);
        c.put("status", status);
        c.put("serverData", serverData);
        c.put("clientData", clientData);
        c.put("createdAt", 1L);
        c.put("activeAt", 2L);
        c.put("publishers", List.of());
        c.put("token", "wss://secret-token-must-not-leak");
        c.put("ip", "203.0.113.9");
        return c;
    }

    private String serverData(long userId, String kind, String owner) {
        return VideoConnectionMetadata.toServerData(om, GROUP, userId,
                VideoConnectionMetadata.Kind.valueOf(kind), owner, "tab-abcdef12", "WEB", 100L);
    }

    @Test
    void primaryToken_putsServerVerifiedIdentityInServerData_andKeepsLegacyTokenField() throws Exception {
        when(openVidu.createConnection(eq(SID), anyString(), eq("PUBLISHER"), any()))
                .thenReturn(new ConnectionGrant("con_AAAA1111", "wss://studybridge.co.kr:4443?sessionId=group_study_25&token=tok_x"));

        Map<String, Object> res = service.issuePrimaryToken(USER, GROUP, "tab-abcdef12", "web");

        assertEquals("wss://studybridge.co.kr:4443?sessionId=group_study_25&token=tok_x", res.get("token"));
        assertEquals("con_AAAA1111", res.get("connectionId"));
        assertEquals("PRIMARY", res.get("kind"));
        assertEquals(SID, res.get("sessionId"));
        verify(openVidu).createSession(SID);

        ArgumentCaptor<String> data = ArgumentCaptor.forClass(String.class);
        verify(openVidu).createConnection(eq(SID), data.capture(), eq("PUBLISHER"), any());
        JsonNode sd = om.readTree(data.getValue());
        assertEquals(1, sd.get("v").asInt());
        assertEquals("studybridge", sd.get("app").asText());
        assertEquals(USER, sd.get("userId").asLong());
        assertEquals(GROUP, sd.get("groupId").asLong());
        assertEquals("PRIMARY", sd.get("kind").asText());
        assertTrue(sd.get("ownerConnectionId").isNull());
        assertEquals("tab-abcdef12", sd.get("instanceId").asText());
        assertEquals("WEB", sd.get("deviceType").asText());
    }

    @Test
    void primaryToken_withoutBody_isBackwardCompatible_andDropsMalformedClientHints() throws Exception {
        when(openVidu.createConnection(eq(SID), anyString(), any(), any())).thenReturn(new ConnectionGrant("con_B", "tok"));
        service.issuePrimaryToken(USER, GROUP, null, null);
        service.issuePrimaryToken(USER, GROUP, "<script>x</script>", "toaster");

        ArgumentCaptor<String> data = ArgumentCaptor.forClass(String.class);
        verify(openVidu, org.mockito.Mockito.times(2)).createConnection(eq(SID), data.capture(), any(), any());
        for (String raw : data.getAllValues()) {
            JsonNode sd = om.readTree(raw);
            assertTrue(sd.get("instanceId").isNull());
            assertEquals("UNKNOWN", sd.get("deviceType").asText());
            assertEquals(USER, sd.get("userId").asLong()); // 신원은 항상 JWT principal
        }
    }

    @Test
    void nonMember_isRejected403_beforeTouchingOpenVidu() {
        VideoCallException ex = assertThrows(VideoCallException.class, () -> service.issuePrimaryToken(99L, GROUP, null, null));
        assertEquals(403, ex.getStatus().value());
        assertEquals("NOT_GROUP_MEMBER", ex.getCode());
        verify(openVidu, never()).createSession(anyString());
        assertThrows(VideoCallException.class, () -> service.listActiveConnections(99L, GROUP));
        verify(openVidu, never()).listConnections(anyString(), org.mockito.ArgumentMatchers.anyBoolean());
    }

    @Test
    void connections_countsUniquePrimaryUsers_notScreens_notMembers_andHidesSecrets() {
        when(openVidu.listConnections(SID, false)).thenReturn(List.of(
                conn("con_PC", "active", serverData(USER, "PRIMARY", null), "{\"userId\":8,\"clientData\":\"김도형\"}"),
                conn("con_ANDROID", "active", serverData(USER, "PRIMARY", null), "{\"userId\":8}"),          // 같은 사람 다른 기기
                conn("con_SCREEN", "active", serverData(USER, "SCREEN", "con_PC"), "{\"userId\":8}"),        // 화면공유
                conn("con_OTHER", "active", serverData(55L, "PRIMARY", null), "{\"userId\":55}"),
                conn("con_LEGACY", "active", "", "{\"userId\":\"77\",\"clientData\":\"구버전\"}"),            // 배포 전 발급분
                conn("con_PENDING", "pending", serverData(56L, "PRIMARY", null), "")));

        Map<String, Object> res = service.listActiveConnections(USER, GROUP);

        assertEquals(3, res.get("activeUserCount")); // 8, 55, 77 — 화면공유·두 번째 기기는 인원에 더하지 않는다
        assertEquals(List.of(8L, 55L, 77L), res.get("activeUserIds"));
        assertEquals(1, res.get("screenShareCount"));
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> list = (List<Map<String, Object>>) res.get("connections");
        assertEquals(5, list.size()); // pending 제외
        Map<String, Object> screen = list.stream().filter(m -> "con_SCREEN".equals(m.get("connectionId"))).findFirst().orElseThrow();
        assertEquals("SCREEN", screen.get("kind"));
        assertEquals("con_PC", screen.get("ownerConnectionId"));
        assertEquals(true, screen.get("verified"));
        Map<String, Object> legacy = list.stream().filter(m -> "con_LEGACY".equals(m.get("connectionId"))).findFirst().orElseThrow();
        assertEquals(77L, legacy.get("userId"));
        assertEquals(false, legacy.get("verified"));
        assertEquals("PRIMARY", legacy.get("kind"));
        for (Map<String, Object> m : list) {
            assertFalse(m.containsKey("token"));
            assertFalse(m.containsKey("ip"));
        }
    }

    // ── 화면공유(SCREEN) 계약 ──

    private void primaryActive(String id, String serverData) {
        when(openVidu.getConnection(SID, id)).thenReturn(Optional.of(conn(id, "active", serverData, "{}")));
    }

    @Test
    void primaryToken_raisesOnlyViewerDownloadCap_cameraUploadStaysGlobal() {
        when(openVidu.createConnection(eq(SID), anyString(), any(), any())).thenReturn(new ConnectionGrant("con_P", "tok"));
        service.issuePrimaryToken(USER, GROUP, null, null);
        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, Object>> ko = ArgumentCaptor.forClass(Map.class);
        verify(openVidu).createConnection(eq(SID), anyString(), eq("PUBLISHER"), ko.capture());
        // Kurento 기준 Send = 이 Connection 이 받는 방향(구독 endpoint). Recv(카메라 송출)는 건드리지 않는다.
        assertEquals(2500, ko.getValue().get("videoMaxSendBandwidth"));
        assertFalse(ko.getValue().containsKey("videoMaxRecvBandwidth"));
    }

    @Test
    void screenToken_ownedByVerifiedPrimary_isSeparateConnectionAttributedToSameUser() throws Exception {
        primaryActive("con_PC", serverData(USER, "PRIMARY", null));
        when(openVidu.listConnections(SID, true)).thenReturn(List.of(conn("con_PC", "active", serverData(USER, "PRIMARY", null), "{}")));
        when(openVidu.createConnection(eq(SID), anyString(), eq("PUBLISHER"), any())).thenReturn(new ConnectionGrant("con_SCR", "tok_screen"));

        Map<String, Object> res = service.issueScreenToken(USER, GROUP, "con_PC", "tab-abcdef12", "WEB");

        assertEquals("tok_screen", res.get("token"));
        assertEquals("SCREEN", res.get("kind"));
        assertEquals("con_PC", res.get("ownerConnectionId"));
        ArgumentCaptor<String> data = ArgumentCaptor.forClass(String.class);
        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, Object>> ko = ArgumentCaptor.forClass(Map.class);
        verify(openVidu).createConnection(eq(SID), data.capture(), eq("PUBLISHER"), ko.capture());
        JsonNode sd = om.readTree(data.getValue());
        assertEquals("SCREEN", sd.get("kind").asText());
        assertEquals(USER, sd.get("userId").asLong());
        assertEquals("con_PC", sd.get("ownerConnectionId").asText());
        // Kurento 기준 Recv = 화면공유 송출 endpoint 가 받는(=공유자가 올리는) 방향. 하한 = KMS 가 공유자에게 보내는 REMB 바닥
        assertEquals(2500, ko.getValue().get("videoMaxRecvBandwidth"));
        assertEquals(1500, ko.getValue().get("videoMinRecvBandwidth"));
        assertFalse(ko.getValue().containsKey("videoMaxSendBandwidth"));
    }

    @Test
    void screenToken_minUploadAboveMax_isClampedToMax() {
        service = newService(openVidu, members, om, 1200, 3000);
        primaryActive("con_PC", serverData(USER, "PRIMARY", null));
        when(openVidu.listConnections(SID, true)).thenReturn(List.of(conn("con_PC", "active", serverData(USER, "PRIMARY", null), "{}")));
        when(openVidu.createConnection(eq(SID), anyString(), eq("PUBLISHER"), any())).thenReturn(new ConnectionGrant("con_SCR", "tok_screen"));

        service.issueScreenToken(USER, GROUP, "con_PC", null, null);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, Object>> ko = ArgumentCaptor.forClass(Map.class);
        verify(openVidu).createConnection(eq(SID), anyString(), eq("PUBLISHER"), ko.capture());
        assertEquals(1200, ko.getValue().get("videoMaxRecvBandwidth"));
        assertEquals(1200, ko.getValue().get("videoMinRecvBandwidth"));
    }

    @Test
    void screenToken_rejectsSomeoneElsesOrLegacyOrInactivePrimary() {
        primaryActive("con_OTHER", serverData(55L, "PRIMARY", null));
        VideoCallException other = assertThrows(VideoCallException.class, () -> service.issueScreenToken(USER, GROUP, "con_OTHER", null, null));
        assertEquals("CONNECTION_OWNER_MISMATCH", other.getCode());
        assertEquals(403, other.getStatus().value());

        primaryActive("con_LEGACY", "");
        when(openVidu.getConnection(SID, "con_LEGACY")).thenReturn(Optional.of(conn("con_LEGACY", "active", "", "{\"userId\":8}")));
        assertEquals("CONNECTION_OWNER_MISMATCH",
                assertThrows(VideoCallException.class, () -> service.issueScreenToken(USER, GROUP, "con_LEGACY", null, null)).getCode());

        primaryActive("con_SCRN", serverData(USER, "SCREEN", "con_PC"));
        assertEquals("CONNECTION_OWNER_MISMATCH",
                assertThrows(VideoCallException.class, () -> service.issueScreenToken(USER, GROUP, "con_SCRN", null, null)).getCode());

        when(openVidu.getConnection(SID, "con_GONE")).thenReturn(Optional.empty());
        VideoCallException gone = assertThrows(VideoCallException.class, () -> service.issueScreenToken(USER, GROUP, "con_GONE", null, null));
        assertEquals("PRIMARY_NOT_ACTIVE", gone.getCode());
        assertEquals(409, gone.getStatus().value());

        when(openVidu.getConnection(SID, "con_PEND")).thenReturn(Optional.of(conn("con_PEND", "pending", serverData(USER, "PRIMARY", null), "")));
        assertEquals("PRIMARY_NOT_ACTIVE",
                assertThrows(VideoCallException.class, () -> service.issueScreenToken(USER, GROUP, "con_PEND", null, null)).getCode());

        assertEquals("INVALID_CONNECTION_ID",
                assertThrows(VideoCallException.class, () -> service.issueScreenToken(USER, GROUP, "../../x", null, null)).getCode());
        verify(openVidu, never()).createConnection(anyString(), anyString(), any(), any());
    }

    @Test
    void screenToken_oneActivePerUser_conflictCarriesExistingConnection() {
        primaryActive("con_PC", serverData(USER, "PRIMARY", null));
        when(openVidu.listConnections(SID, true)).thenReturn(List.of(
                conn("con_PC", "active", serverData(USER, "PRIMARY", null), "{}"),
                conn("con_ANDROID", "active", serverData(USER, "PRIMARY", null), "{}"),
                conn("con_SCR_ANDROID", "active", serverData(USER, "SCREEN", "con_ANDROID"), "{}")));
        VideoCallException ex = assertThrows(VideoCallException.class, () -> service.issueScreenToken(USER, GROUP, "con_PC", null, null));
        assertEquals("SCREEN_ALREADY_ACTIVE", ex.getCode());
        assertEquals(409, ex.getStatus().value());
        assertEquals("con_SCR_ANDROID", ex.getDetails().get("connectionId"));
        verify(openVidu, never()).deleteConnection(anyString(), anyString());
    }

    @Test
    void screenToken_revokesUnusedPendingAndClosesOrphanScreens_thenIssues() {
        primaryActive("con_PC2", serverData(USER, "PRIMARY", null));
        when(openVidu.listConnections(SID, true)).thenReturn(List.of(
                conn("con_PC2", "active", serverData(USER, "PRIMARY", null), "{}"),
                conn("con_SCR_PENDING", "pending", serverData(USER, "SCREEN", "con_PC2"), ""),
                conn("con_SCR_ORPHAN", "active", serverData(USER, "SCREEN", "con_PC_BEFORE_REFRESH"), "{}"),
                conn("con_X", "active", serverData(55L, "PRIMARY", null), "{}"),
                conn("con_SCR_OTHER_USER", "active", serverData(55L, "SCREEN", "con_X"), "{}")));
        when(openVidu.createConnection(eq(SID), anyString(), any(), any())).thenReturn(new ConnectionGrant("con_SCR_NEW", "tok"));

        assertEquals("con_SCR_NEW", service.issueScreenToken(USER, GROUP, "con_PC2", null, null).get("connectionId"));
        verify(openVidu).deleteConnection(SID, "con_SCR_PENDING");
        verify(openVidu).deleteConnection(SID, "con_SCR_ORPHAN");
        verify(openVidu, never()).deleteConnection(SID, "con_SCR_OTHER_USER"); // 살아 있는 다른 사람 화면공유는 건드리지 않는다
    }

    @Test
    void stopScreen_onlyOwnScreen_idempotent() {
        when(openVidu.getConnection(SID, "con_MINE")).thenReturn(Optional.of(conn("con_MINE", "active", serverData(USER, "SCREEN", "con_PC"), "{}")));
        when(openVidu.deleteConnection(SID, "con_MINE")).thenReturn(true);
        assertEquals(true, service.stopScreenShare(USER, GROUP, "con_MINE").get("stopped"));

        when(openVidu.getConnection(SID, "con_THEIRS")).thenReturn(Optional.of(conn("con_THEIRS", "active", serverData(55L, "SCREEN", "con_X"), "{}")));
        assertEquals("CONNECTION_OWNER_MISMATCH", assertThrows(VideoCallException.class, () -> service.stopScreenShare(USER, GROUP, "con_THEIRS")).getCode());

        when(openVidu.getConnection(SID, "con_MYPRIMARY")).thenReturn(Optional.of(conn("con_MYPRIMARY", "active", serverData(USER, "PRIMARY", null), "{}")));
        assertEquals("CONNECTION_OWNER_MISMATCH", assertThrows(VideoCallException.class, () -> service.stopScreenShare(USER, GROUP, "con_MYPRIMARY")).getCode());

        when(openVidu.getConnection(SID, "con_GONE")).thenReturn(Optional.empty());
        Map<String, Object> gone = service.stopScreenShare(USER, GROUP, "con_GONE");
        assertEquals(false, gone.get("stopped"));
        verify(openVidu, never()).deleteConnection(SID, "con_THEIRS");
        verify(openVidu, never()).deleteConnection(SID, "con_MYPRIMARY");
    }

    @Test
    void metadata_rejectsForeignServerDataShape_andParsesLegacyClientData() {
        VideoConnectionMetadata spoof = VideoConnectionMetadata.fromRest(om, "{\"userId\":1,\"kind\":\"SCREEN\"}", "{\"userId\":2}");
        assertFalse(spoof.serverVerified()); // app 표식 없는 serverData 는 계약 아님 → 레거시 경로
        assertEquals(2L, spoof.userId());
        assertEquals(VideoConnectionMetadata.Kind.PRIMARY, spoof.kind());
        VideoConnectionMetadata none = VideoConnectionMetadata.fromRest(om, null, "not-json");
        assertNull(none.userId());
        assertTrue(VideoConnectionMetadata.isValidConnectionId("con_XtwcedOqop"));
        assertFalse(VideoConnectionMetadata.isValidConnectionId("con_../../sessions"));
    }
}
