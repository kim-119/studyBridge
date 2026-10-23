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
import java.util.HashMap;
import java.util.List;
import java.util.Map;
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

    @BeforeEach
    void setUp() {
        openVidu = mock(OpenViduService.class);
        members = mock(GroupStudyMemberRepository.class);
        when(members.existsByGroupStudyIdAndUserIdAndStatus(GROUP, USER, GroupStudyMemberStatus.JOINED)).thenReturn(true);
        service = new GroupVideoCallService(openVidu, members, om, "group_study_");
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
