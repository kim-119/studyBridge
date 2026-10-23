package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.exception.VideoCallException;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.service.OpenViduService.ConnectionGrant;
import com.studybridge.api.service.VideoConnectionMetadata.Kind;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 그룹스터디 화상통화 Connection 발급/조회.
 *
 * <p>모델: Group Member(DB JOINED) ≠ Active User(OpenVidu 에 실제 접속한 고유 userId) ≠ Connection(기기·탭마다 1개 PRIMARY).
 * 참여 인원은 active PRIMARY Connection 의 고유 userId 수다. 신원은 {@link VideoConnectionMetadata}(serverData) 로만 판단한다.</p>
 */
@Service
@Slf4j
public class GroupVideoCallService {

    private final OpenViduService openVidu;
    private final GroupStudyMemberRepository memberRepository;
    private final ObjectMapper objectMapper;
    private final String sessionPrefix;

    public GroupVideoCallService(OpenViduService openVidu,
                                 GroupStudyMemberRepository memberRepository,
                                 ObjectMapper objectMapper,
                                 @Value("${openvidu.session-prefix:group_study_}") String sessionPrefix) {
        this.openVidu = openVidu;
        this.memberRepository = memberRepository;
        this.objectMapper = objectMapper;
        this.sessionPrefix = sessionPrefix;
    }

    public String sessionIdFor(long groupId) {
        return sessionPrefix + groupId;
    }

    private void requireJoinedMember(long userId, long groupId) {
        if (!memberRepository.existsByGroupStudyIdAndUserIdAndStatus(groupId, userId, GroupStudyMemberStatus.JOINED)) {
            log.warn("[VIDEO] access denied (not a JOINED member) userId={} groupId={}", userId, groupId);
            throw new VideoCallException(HttpStatus.FORBIDDEN, "NOT_GROUP_MEMBER", "그룹스터디 참여 멤버만 화상통화에 접속할 수 있습니다.");
        }
    }

    /** 기본(PRIMARY: 음성·카메라) Connection 토큰. 기존 응답 필드 token 은 그대로 유지한다. */
    public Map<String, Object> issuePrimaryToken(long userId, long groupId, String clientInstanceId, String deviceType) {
        requireJoinedMember(userId, groupId);
        String sessionId = sessionIdFor(groupId);
        openVidu.createSession(sessionId);

        String instanceId = VideoConnectionMetadata.sanitizeInstanceId(clientInstanceId);
        String device = VideoConnectionMetadata.sanitizeDeviceType(deviceType);
        String serverData = VideoConnectionMetadata.toServerData(objectMapper, groupId, userId, Kind.PRIMARY,
                null, instanceId, device, System.currentTimeMillis());
        ConnectionGrant grant = openVidu.createConnection(sessionId, serverData, "PUBLISHER", null);
        log.info("[VIDEO] primary token issued userId={} groupId={} connectionId={} device={} instance={}",
                userId, groupId, grant.connectionId(), device, instanceId == null ? "-" : "set");

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("token", grant.token());
        body.put("connectionId", grant.connectionId());
        body.put("sessionId", sessionId);
        body.put("kind", Kind.PRIMARY.name());
        body.put("contractVersion", VideoConnectionMetadata.VERSION);
        return body;
    }

    /**
     * 서버(OpenVidu)가 알고 있는 active Connection 목록 = 실시간 접속의 Source of Truth.
     * 클라이언트는 이 목록에 없는 원격 Connection(새로고침 직후 join 응답에 섞여 들어온 ghost 등)을 정리한다.
     * 토큰·IP·위치·플랫폼 문자열은 내보내지 않는다.
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> listActiveConnections(long userId, long groupId) {
        requireJoinedMember(userId, groupId);
        String sessionId = sessionIdFor(groupId);
        List<Map<String, Object>> raw = openVidu.listConnections(sessionId, false);

        List<Map<String, Object>> connections = new ArrayList<>();
        Set<Long> activeUserIds = new LinkedHashSet<>();
        int screenCount = 0;
        for (Map<String, Object> c : raw) {
            if (!"active".equals(c.get("status"))) continue;
            VideoConnectionMetadata meta = VideoConnectionMetadata.fromRest(objectMapper, c.get("serverData"), c.get("clientData"));

            List<Map<String, Object>> streams = new ArrayList<>();
            if (c.get("publishers") instanceof List<?> pubs) {
                for (Object p : pubs) {
                    if (!(p instanceof Map<?, ?> pub)) continue;
                    Map<String, Object> media = pub.get("mediaOptions") instanceof Map<?, ?> m ? (Map<String, Object>) m : Map.of();
                    Map<String, Object> s = new LinkedHashMap<>();
                    s.put("streamId", pub.get("streamId"));
                    s.put("typeOfVideo", media.get("typeOfVideo"));
                    s.put("hasAudio", media.get("hasAudio"));
                    s.put("hasVideo", media.get("hasVideo"));
                    streams.add(s);
                }
            }

            Map<String, Object> item = new LinkedHashMap<>();
            item.put("connectionId", c.get("connectionId"));
            item.put("userId", meta.userId());
            item.put("verified", meta.serverVerified());
            item.put("kind", meta.kind().name());
            item.put("ownerConnectionId", meta.ownerConnectionId());
            item.put("deviceType", meta.deviceType());
            item.put("createdAt", c.get("createdAt"));
            item.put("activeAt", c.get("activeAt"));
            item.put("streams", streams);
            connections.add(item);

            if (meta.kind() == Kind.SCREEN) screenCount++;
            else if (meta.userId() != null) activeUserIds.add(meta.userId());
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("sessionId", sessionId);
        body.put("contractVersion", VideoConnectionMetadata.VERSION);
        body.put("activeUserCount", activeUserIds.size());
        body.put("activeUserIds", new ArrayList<>(activeUserIds));
        body.put("screenShareCount", screenCount);
        body.put("connections", connections);
        body.put("fetchedAt", System.currentTimeMillis());
        return body;
    }
}
