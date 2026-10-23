package com.studybridge.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * 그룹스터디 OpenVidu Connection 식별 계약(v1). 웹·Android 공통.
 *
 * <p>Spring 이 토큰을 발급할 때 OpenVidu Connection 의 serverData 에 아래 JSON 을 넣는다. OpenVidu 는 다른 참가자에게
 * {@code connection.data = clientData + "%/%" + serverData} 로 전달하므로, 클라이언트는 신원(userId/kind/owner)을
 * 반드시 serverData 쪽에서 읽어야 한다(clientData 는 클라이언트가 임의로 넣는 표시용 값).</p>
 *
 * <pre>
 * {"v":1,"app":"studybridge","groupId":25,"userId":8,"kind":"PRIMARY"|"SCREEN",
 *  "ownerConnectionId":null|"con_…","instanceId":"…"|null,"deviceType":"WEB"|"ANDROID"|"IOS"|"UNKNOWN","issuedAt":1792…}
 * </pre>
 * <ul>
 *   <li>서버 검증 값: v, app, groupId, userId, kind, ownerConnectionId(SCREEN 은 발급 시 소유자 PRIMARY 를 검증), issuedAt</li>
 *   <li>클라이언트 주장 값(표시/중복 판단용, 권한 판단 금지): instanceId, deviceType</li>
 * </ul>
 */
public record VideoConnectionMetadata(
        int version,
        Long groupId,
        Long userId,
        Kind kind,
        String ownerConnectionId,
        String instanceId,
        String deviceType,
        Long issuedAt,
        boolean serverVerified) {

    public enum Kind { PRIMARY, SCREEN }

    public static final int VERSION = 1;
    public static final String APP = "studybridge";
    /** OpenVidu 가 clientData 와 serverData 를 이어 붙일 때 쓰는 구분자. */
    public static final String METADATA_SEPARATOR = "%/%";

    private static final Pattern INSTANCE_ID = Pattern.compile("^[A-Za-z0-9_-]{8,64}$");
    private static final Pattern CONNECTION_ID = Pattern.compile("^con_[A-Za-z0-9]{1,64}$");
    private static final Set<String> DEVICE_TYPES = Set.of("WEB", "ANDROID", "IOS");

    public static boolean isValidConnectionId(String connectionId) {
        return connectionId != null && CONNECTION_ID.matcher(connectionId).matches();
    }

    /** 클라이언트가 보낸 탭/기기 인스턴스 id. 형식이 틀리면 버린다(요청 자체는 실패시키지 않는다 — 하위 호환). */
    public static String sanitizeInstanceId(String raw) {
        return raw != null && INSTANCE_ID.matcher(raw).matches() ? raw : null;
    }

    public static String sanitizeDeviceType(String raw) {
        if (raw == null || raw.isBlank()) return "UNKNOWN";
        String upper = raw.trim().toUpperCase(Locale.ROOT);
        return DEVICE_TYPES.contains(upper) ? upper : "UNKNOWN";
    }

    public static String toServerData(ObjectMapper om, long groupId, long userId, Kind kind, String ownerConnectionId,
                                      String instanceId, String deviceType, long issuedAt) {
        ObjectNode n = om.createObjectNode();
        n.put("v", VERSION);
        n.put("app", APP);
        n.put("groupId", groupId);
        n.put("userId", userId);
        n.put("kind", kind.name());
        if (ownerConnectionId != null) n.put("ownerConnectionId", ownerConnectionId); else n.putNull("ownerConnectionId");
        if (instanceId != null) n.put("instanceId", instanceId); else n.putNull("instanceId");
        n.put("deviceType", deviceType);
        n.put("issuedAt", issuedAt);
        return n.toString();
    }

    /**
     * OpenVidu REST Connection 의 serverData(우선)와 clientData(레거시 폴백)로 식별 정보를 만든다.
     * serverData 가 이 계약이 아니면 레거시 Connection(배포 이전 발급분)으로 보고 clientData 의 userId 를 비검증 값으로 쓴다.
     */
    public static VideoConnectionMetadata fromRest(ObjectMapper om, Object serverData, Object clientData) {
        JsonNode server = parseObject(om, serverData);
        if (server != null && APP.equals(server.path("app").asText(null)) && server.hasNonNull("userId")) {
            Kind kind = "SCREEN".equals(server.path("kind").asText()) ? Kind.SCREEN : Kind.PRIMARY;
            return new VideoConnectionMetadata(
                    server.path("v").asInt(VERSION),
                    server.hasNonNull("groupId") ? server.get("groupId").asLong() : null,
                    server.get("userId").asLong(),
                    kind,
                    textOrNull(server, "ownerConnectionId"),
                    textOrNull(server, "instanceId"),
                    textOrNull(server, "deviceType"),
                    server.hasNonNull("issuedAt") ? server.get("issuedAt").asLong() : null,
                    true);
        }
        JsonNode client = parseObject(om, clientData);
        Long legacyUserId = null;
        if (client != null && client.hasNonNull("userId")) {
            JsonNode u = client.get("userId");
            legacyUserId = u.canConvertToLong() ? u.asLong() : parseLongOrNull(u.asText());
        }
        return new VideoConnectionMetadata(0, null, legacyUserId, Kind.PRIMARY, null, null, null, null, false);
    }

    private static JsonNode parseObject(ObjectMapper om, Object raw) {
        if (!(raw instanceof String s) || s.isBlank()) return null;
        try {
            JsonNode n = om.readTree(s);
            return n != null && n.isObject() ? n : null;
        } catch (Exception e) {
            return null;
        }
    }

    private static String textOrNull(JsonNode n, String field) {
        JsonNode v = n.get(field);
        return v == null || v.isNull() ? null : v.asText();
    }

    private static Long parseLongOrNull(String s) {
        try {
            return s == null ? null : Long.parseLong(s.trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
