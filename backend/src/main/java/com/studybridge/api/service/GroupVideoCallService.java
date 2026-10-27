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

import java.time.Clock;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * 그룹스터디 화상통화 Connection 발급/조회.
 *
 * <p>모델: Group Member(DB JOINED) ≠ Active User(OpenVidu 에 실제 접속한 고유 userId) ≠ Connection(기기·탭마다 1개 PRIMARY).
 * 참여 인원은 active PRIMARY Connection 의 고유 userId 수다. 신원은 {@link VideoConnectionMetadata}(serverData) 로만 판단한다.</p>
 *
 * <p>화면공유는 방마다 동시에 {@code openvidu.screen-share.max-per-group}(기본 2)명까지다. 참여 인원(카메라·마이크) 제한과는 별개다.
 * 슬롯 판정은 {@link ScreenSharePolicy}, 동시 요청 직렬화는 {@link ScreenShareAdmissionLock} 이 맡는다.</p>
 */
@Service
@Slf4j
public class GroupVideoCallService {

    private final OpenViduService openVidu;
    private final GroupStudyMemberRepository memberRepository;
    private final ObjectMapper objectMapper;
    private final String sessionPrefix;
    private final int viewerMaxDownloadKbps;
    private final int screenMaxUploadKbps;
    private final int screenMinUploadKbps;
    private final ScreenShareAdmissionLock admissionLock;
    private final Clock clock;
    private final int maxScreenSharesPerGroup;
    private final long screenPendingTtlMs;

    public GroupVideoCallService(OpenViduService openVidu,
                                 GroupStudyMemberRepository memberRepository,
                                 ObjectMapper objectMapper,
                                 ScreenShareAdmissionLock admissionLock,
                                 Clock clock,
                                 @Value("${openvidu.session-prefix:group_study_}") String sessionPrefix,
                                 @Value("${openvidu.bandwidth.viewer-max-download-kbps:2500}") int viewerMaxDownloadKbps,
                                 @Value("${openvidu.bandwidth.screen-max-upload-kbps:2500}") int screenMaxUploadKbps,
                                 @Value("${openvidu.bandwidth.screen-min-upload-kbps:1500}") int screenMinUploadKbps,
                                 @Value("${openvidu.screen-share.max-per-group:2}") int maxScreenSharesPerGroup,
                                 @Value("${openvidu.screen-share.pending-ttl-ms:30000}") long screenPendingTtlMs) {
        this.openVidu = openVidu;
        this.memberRepository = memberRepository;
        this.objectMapper = objectMapper;
        this.admissionLock = admissionLock;
        this.clock = clock;
        this.maxScreenSharesPerGroup = Math.max(1, maxScreenSharesPerGroup);
        this.screenPendingTtlMs = Math.max(1000, screenPendingTtlMs);
        this.sessionPrefix = sessionPrefix;
        this.viewerMaxDownloadKbps = viewerMaxDownloadKbps;
        this.screenMaxUploadKbps = screenMaxUploadKbps;
        // 하한이 상한보다 크면 KMS 가 상한을 넘는 REMB 를 보낸다(설정 실수) → 상한으로 맞춘다.
        this.screenMinUploadKbps = screenMaxUploadKbps > 0 ? Math.min(screenMinUploadKbps, screenMaxUploadKbps) : screenMinUploadKbps;
    }

    public String sessionIdFor(long groupId) {
        return sessionPrefix + groupId;
    }

    /** 이 서비스가 관리하는 세션이면 groupId, 아니면 null(다른 접두어의 세션은 건드리지 않는다). */
    public Long groupIdOf(String sessionId) {
        if (sessionId == null || !sessionId.startsWith(sessionPrefix)) return null;
        try {
            long id = Long.parseLong(sessionId.substring(sessionPrefix.length()));
            return id > 0 ? id : null;
        } catch (NumberFormatException e) {
            return null;
        }
    }

    public int maxScreenSharesPerGroup() {
        return maxScreenSharesPerGroup;
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
        ConnectionGrant grant = openVidu.createConnection(sessionId, serverData, "PUBLISHER", primaryKurentoOptions());
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

    /*
     * kurentoOptions 의 Recv/Send 는 Kurento WebRtcEndpoint(서버) 기준이고, 그 Connection 이 소유한 endpoint 에 적용된다
     * (openvidu-server 2.30 MediaEndpoint: owner 토큰의 값으로 setMax/MinVideoRecv/SendBandwidth). 송출 endpoint 는
     * 송출자 소유, 구독 endpoint 는 시청자 소유다. 따라서
     *   · videoMaxRecvBandwidth = 이 Connection 이 "올리는" 영상 상한(송출 endpoint)
     *   · videoMaxSendBandwidth = 이 Connection 이 "받는" 영상 상한(구독 endpoint)
     * 전역 기본은 둘 다 1000/300kbps. 카메라 송출(PRIMARY 의 Recv)은 전역값 그대로 둔다.
     */

    /** 시청자(PRIMARY)가 받는 영상 상한. 카메라는 송출 측 전역 1000 에 묶여 변화가 없고, 화면공유만 이 상한까지 받을 수 있다. */
    private Map<String, Object> primaryKurentoOptions() {
        if (viewerMaxDownloadKbps <= 0) return null;
        Map<String, Object> o = new HashMap<>();
        o.put("videoMaxSendBandwidth", viewerMaxDownloadKbps);
        return o;
    }

    /**
     * 화면공유(SCREEN) 송출 상한/하한. 하한(videoMinRecvBandwidth)은 KMS 가 공유자에게 보내는 REMB 의 바닥이다.
     * KMS 7 kmsremb: REMB = max(하한, min(KMS 수신 추정, 시청자들 REMB)) 이고, 시청자 Chrome 의 REMB 는 처음 5초 동안 받은 양으로
     * 초기화된 뒤 "받은 양의 1.5배"까지만 오른다. 정적인 문서 화면은 받는 양이 수십 kbps 라 REMB 가 하한에 붙고, 새 시청자가
     * 들어올 때마다 다시 하한으로 떨어진다. 하한 300 에서는 공유자 Chrome 의 목표가 150~370kbps 에 묶여 1080p 글자가
     * 뭉개졌다(E2E 1080p 문서: 슬라이드 QP 84~105/127, 텍스트 PSNR 25~31dB → 하한 1500: 목표 1.2~2.5Mbps, QP 15~47, 37~41dB).
     * 하한은 KMS 의 요청 바닥일 뿐이라, 공유자 업링크가 모자라면 Chrome 의 손실 기반 대역 추정이 그 아래로 내려간다
     * (E2E 업링크 1Mbps 제한: REMB 1500 유지, 실제 목표 95~904kbps).
     */
    private Map<String, Object> screenKurentoOptions() {
        Map<String, Object> o = new HashMap<>();
        if (screenMaxUploadKbps > 0) o.put("videoMaxRecvBandwidth", screenMaxUploadKbps);
        if (screenMinUploadKbps > 0) o.put("videoMinRecvBandwidth", screenMinUploadKbps);
        return o.isEmpty() ? null : o;
    }

    /**
     * 화면공유(SCREEN) 전용 Connection 토큰. OpenVidu 2.x 는 Connection 당 Publisher 1개라 카메라·마이크(PRIMARY)를 유지한 채
     * 화면을 보내려면 별도 Connection 이 필요하다. serverData.ownerConnectionId 로 같은 사용자에게 귀속돼 인원에 더해지지 않는다.
     *
     * <p>검증: JOINED 멤버 → primaryConnectionId 가 이 세션의 active Connection 이고 serverData(userId=나, kind=PRIMARY).
     * 그다음 방 단위 임계구역({@link ScreenShareAdmissionLock}) 안에서 OpenVidu 의 실제 SCREEN Connection(pending 포함)을 다시 읽어
     * 사용자당 1개 · 방당 {@code maxScreenSharesPerGroup} 개를 판정하고, 통과할 때만 Connection 을 만든다(조회-판정-생성 원자화).
     * 발급된 토큰은 접속 전까지 pending 으로 슬롯을 예약하고, pendingTtl 안에 접속하지 않으면 예약으로 보지 않는다.</p>
     *
     * <p>정리: 만료된 예약과 소유 PRIMARY 가 사라진(orphan) 화면공유는 누구 것이든 승인 전에 닫는다. 같은 탭(같은 PRIMARY)의 이전 예약은
     * 재시도로 보고 닫고, 같은 사용자의 다른 탭·기기 예약은 진행 중으로 보고 거절한다(그 기기의 시작을 끊지 않는다).</p>
     */
    public Map<String, Object> issueScreenToken(long userId, long groupId, String primaryConnectionId,
                                                String clientInstanceId, String deviceType) {
        requireJoinedMember(userId, groupId);
        if (!VideoConnectionMetadata.isValidConnectionId(primaryConnectionId)) {
            throw new VideoCallException(HttpStatus.BAD_REQUEST, "INVALID_CONNECTION_ID", "primaryConnectionId 형식이 올바르지 않습니다.");
        }
        String sessionId = sessionIdFor(groupId);
        return admissionLock.runExclusive(groupId, () -> {
            Map<String, Object> primary = openVidu.getConnection(sessionId, primaryConnectionId)
                    .filter(c -> "active".equals(c.get("status")))
                    .orElseThrow(() -> new VideoCallException(HttpStatus.CONFLICT, "PRIMARY_NOT_ACTIVE",
                            "화상 연결이 활성화된 뒤에 화면을 공유할 수 있습니다."));
            VideoConnectionMetadata owner = VideoConnectionMetadata.fromRest(objectMapper, primary.get("serverData"), primary.get("clientData"));
            if (!owner.serverVerified() || owner.kind() != Kind.PRIMARY || owner.userId() == null || owner.userId() != userId) {
                log.warn("[VIDEO] screen token owner mismatch userId={} groupId={} primary={} ownerUserId={} kind={} verified={}",
                        userId, groupId, primaryConnectionId, owner.userId(), owner.kind(), owner.serverVerified());
                throw new VideoCallException(HttpStatus.FORBIDDEN, "CONNECTION_OWNER_MISMATCH", "본인의 화상 연결에만 화면공유를 연결할 수 있습니다.");
            }

            ScreenSharePolicy.Snapshot snap = ScreenSharePolicy.inspect(objectMapper,
                    openVidu.listConnections(sessionId, true), clock.millis(), screenPendingTtlMs);
            int occupiedByOthers = 0;
            for (ScreenSharePolicy.ScreenSlot slot : snap.screens()) {
                boolean mine = slot.userId() != null && slot.userId() == userId;
                if (!slot.occupying()) {
                    closeStaleScreen(sessionId, groupId, slot); // 만료된 예약·orphan 은 누구 것이든 슬롯을 돌려준다
                } else if (!mine) {
                    occupiedByOthers++;
                } else if (slot.state() == ScreenSharePolicy.SlotState.ACTIVE) {
                    Map<String, Object> details = new LinkedHashMap<>();
                    details.put("connectionId", slot.connectionId());
                    details.put("ownerConnectionId", slot.ownerConnectionId());
                    throw new VideoCallException(HttpStatus.CONFLICT, "SCREEN_ALREADY_ACTIVE",
                            primaryConnectionId.equals(slot.ownerConnectionId())
                                    ? "이미 화면을 공유하고 있습니다."
                                    : "다른 기기에서 화면을 공유하고 있습니다. 그 기기에서 공유를 끝낸 뒤 다시 시도해주세요.",
                            details);
                } else if (primaryConnectionId.equals(slot.ownerConnectionId())) {
                    // 같은 탭의 이전 시작 시도가 접속 전에 끝났다(클라이언트는 탭당 한 번만 시작한다) → 재시도로 보고 예약을 넘겨받는다.
                    openVidu.deleteConnection(sessionId, slot.connectionId());
                    log.info("[VIDEO] previous pending screen token replaced userId={} groupId={} connectionId={}", userId, groupId, slot.connectionId());
                } else {
                    throw new VideoCallException(HttpStatus.CONFLICT, "SCREEN_START_IN_PROGRESS",
                            "다른 기기(탭)에서 화면공유를 시작하고 있습니다. 잠시 후 다시 시도해주세요.");
                }
            }
            if (occupiedByOthers >= maxScreenSharesPerGroup) {
                log.info("[VIDEO] screen share limit reached userId={} groupId={} occupied={} limit={}",
                        userId, groupId, occupiedByOthers, maxScreenSharesPerGroup);
                Map<String, Object> details = new LinkedHashMap<>();
                details.put("limit", maxScreenSharesPerGroup);
                details.put("activeCount", occupiedByOthers);
                throw new VideoCallException(HttpStatus.CONFLICT, "SCREEN_SHARE_LIMIT_REACHED",
                        screenLimitMessage(), details);
            }

            String instanceId = VideoConnectionMetadata.sanitizeInstanceId(clientInstanceId);
            String device = VideoConnectionMetadata.sanitizeDeviceType(deviceType);
            String serverData = VideoConnectionMetadata.toServerData(objectMapper, groupId, userId, Kind.SCREEN,
                    primaryConnectionId, instanceId, device, clock.millis());
            ConnectionGrant grant = openVidu.createConnection(sessionId, serverData, "PUBLISHER", screenKurentoOptions());
            log.info("[VIDEO] screen token issued userId={} groupId={} connectionId={} owner={} slot={}/{} maxSendKbps={} minSendKbps={}",
                    userId, groupId, grant.connectionId(), primaryConnectionId, occupiedByOthers + 1, maxScreenSharesPerGroup,
                    screenMaxUploadKbps, screenMinUploadKbps);

            Map<String, Object> body = new LinkedHashMap<>();
            body.put("token", grant.token());
            body.put("connectionId", grant.connectionId());
            body.put("sessionId", sessionId);
            body.put("kind", Kind.SCREEN.name());
            body.put("ownerConnectionId", primaryConnectionId);
            body.put("maxSendKbps", screenMaxUploadKbps);
            body.put("screenShareLimit", maxScreenSharesPerGroup);
            body.put("contractVersion", VideoConnectionMetadata.VERSION);
            return body;
        });
    }

    private String screenLimitMessage() {
        return "현재 화면공유 가능 인원(최대 " + maxScreenSharesPerGroup + "명)이 모두 사용 중입니다.";
    }

    private void closeStaleScreen(String sessionId, long groupId, ScreenSharePolicy.ScreenSlot slot) {
        boolean closed = openVidu.deleteConnection(sessionId, slot.connectionId());
        log.info("[VIDEO] stale screen slot released groupId={} userId={} connectionId={} state={} owner={} closed={}",
                groupId, slot.userId(), slot.connectionId(), slot.state(), slot.ownerConnectionId(), closed);
    }

    /** 정리할 것이 있는 세션인지(전체 세션 목록으로 먼저 거른 뒤 해당 방만 잠금을 잡는다). */
    public boolean needsScreenEnforcement(List<Map<String, Object>> connections) {
        ScreenSharePolicy.Snapshot snap = ScreenSharePolicy.inspect(objectMapper, connections, clock.millis(), screenPendingTtlMs);
        return !snap.stale().isEmpty() || !snap.overLimit(maxScreenSharesPerGroup).isEmpty() || !snap.screenStreamsOnPrimary().isEmpty();
    }

    /** 주기 정리 결과(로그·테스트용). */
    public record ScreenEnforcement(int staleClosed, int overLimitClosed, int bypassUnpublished) {
        public boolean changed() {
            return staleClosed + overLimitClosed + bypassUnpublished > 0;
        }
    }

    /**
     * 승인 경로 밖에서 생긴 상태를 OpenVidu 쪽에서 바로잡는다({@link ScreenSharePolicyEnforcer} 가 주기적으로 호출).
     * <ul>
     *   <li>만료된 예약·orphan 화면공유 → Connection 종료(유령 슬롯 반환)</li>
     *   <li>한도 초과 점유(배포 이전 발급분·다중 인스턴스 이상) → 늦게 들어온 것부터 Connection 종료</li>
     *   <li>PRIMARY(카메라·마이크) Connection 의 SCREEN 타입 스트림(승인 우회 게시) → 그 스트림만 강제 게시 해제</li>
     * </ul>
     * 승인과 같은 방 잠금을 기다리지 않고 시도하며, 처리 중인 승인이 있으면 이번 주기는 건너뛴다(empty).
     */
    public Optional<ScreenEnforcement> enforceScreenSharePolicy(String sessionId) {
        Long groupId = groupIdOf(sessionId);
        if (groupId == null) return Optional.of(new ScreenEnforcement(0, 0, 0));
        return admissionLock.tryRun(groupId, () -> {
            // 잠금 안에서 다시 읽는다(전체 세션 목록을 읽은 뒤 잠금을 얻기 전까지 승인이 끝났을 수 있다).
            ScreenSharePolicy.Snapshot snap = ScreenSharePolicy.inspect(objectMapper,
                    openVidu.listConnections(sessionId, true), clock.millis(), screenPendingTtlMs);
            int stale = 0;
            for (ScreenSharePolicy.ScreenSlot slot : snap.stale()) {
                closeStaleScreen(sessionId, groupId, slot);
                stale++;
            }
            int over = 0;
            for (ScreenSharePolicy.ScreenSlot slot : snap.overLimit(maxScreenSharesPerGroup)) {
                boolean closed = openVidu.deleteConnection(sessionId, slot.connectionId());
                log.warn("[VIDEO] screen share over limit closed groupId={} userId={} connectionId={} state={} limit={} closed={}",
                        groupId, slot.userId(), slot.connectionId(), slot.state(), maxScreenSharesPerGroup, closed);
                over++;
            }
            int bypass = 0;
            for (ScreenSharePolicy.ScreenStreamOnPrimary s : snap.screenStreamsOnPrimary()) {
                boolean done = openVidu.forceUnpublish(sessionId, s.streamId());
                log.warn("[VIDEO] SCREEN stream on PRIMARY connection unpublished (bypassed admission) groupId={} userId={} connectionId={} streamId={} done={}",
                        groupId, s.userId(), s.connectionId(), s.streamId(), done);
                bypass++;
            }
            return new ScreenEnforcement(stale, over, bypass);
        });
    }

    /**
     * 내 화면공유 Connection 을 서버에서 종료한다(클라이언트 disconnect 가 유실됐을 때의 안전망, Android 공유 중지 버튼 등).
     * 이미 없으면 멱등하게 stopped=false. 다른 사람 것이거나 SCREEN 이 아니면 403.
     */
    public Map<String, Object> stopScreenShare(long userId, long groupId, String screenConnectionId) {
        requireJoinedMember(userId, groupId);
        if (!VideoConnectionMetadata.isValidConnectionId(screenConnectionId)) {
            throw new VideoCallException(HttpStatus.BAD_REQUEST, "INVALID_CONNECTION_ID", "connectionId 형식이 올바르지 않습니다.");
        }
        String sessionId = sessionIdFor(groupId);
        Optional<Map<String, Object>> found = openVidu.getConnection(sessionId, screenConnectionId);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("connectionId", screenConnectionId);
        if (found.isEmpty()) {
            body.put("stopped", false);
            body.put("reason", "NOT_FOUND");
            return body;
        }
        VideoConnectionMetadata m = VideoConnectionMetadata.fromRest(objectMapper, found.get().get("serverData"), found.get().get("clientData"));
        if (!m.serverVerified() || m.kind() != Kind.SCREEN || m.userId() == null || m.userId() != userId) {
            throw new VideoCallException(HttpStatus.FORBIDDEN, "CONNECTION_OWNER_MISMATCH", "본인의 화면공유만 종료할 수 있습니다.");
        }
        boolean stopped = openVidu.deleteConnection(sessionId, screenConnectionId);
        log.info("[VIDEO] screen share stopped via API userId={} groupId={} connectionId={} stopped={}", userId, groupId, screenConnectionId, stopped);
        body.put("stopped", stopped);
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
        Set<String> sharingIds = new LinkedHashSet<>();
        for (ScreenSharePolicy.ScreenSlot slot : ScreenSharePolicy.inspect(objectMapper, raw, clock.millis(), screenPendingTtlMs).occupying()) {
            sharingIds.add(slot.connectionId());
        }

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

            if (meta.kind() == Kind.SCREEN) {
                if (sharingIds.contains(String.valueOf(c.get("connectionId")))) screenCount++; // orphan 은 세지 않는다
            }
            else if (meta.userId() != null) activeUserIds.add(meta.userId());
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("sessionId", sessionId);
        body.put("contractVersion", VideoConnectionMetadata.VERSION);
        body.put("activeUserCount", activeUserIds.size());
        body.put("activeUserIds", new ArrayList<>(activeUserIds));
        body.put("screenShareCount", screenCount);
        body.put("screenShareLimit", maxScreenSharesPerGroup);
        body.put("connections", connections);
        body.put("fetchedAt", System.currentTimeMillis());
        return body;
    }
}
