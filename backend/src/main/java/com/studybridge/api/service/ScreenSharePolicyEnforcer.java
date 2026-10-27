package com.studybridge.api.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

/**
 * 화면공유 한도의 서버측 사후 강제. 승인(SCREEN 토큰 발급)은 {@link GroupVideoCallService#issueScreenToken} 이 막지만,
 * OpenVidu 클라이언트는 받은 Connection 으로 직접 게시하므로 다음 상태는 승인만으로 막을 수 없다:
 * 접속하지 않고 남은 예약 토큰, 소유자가 사라진 화면공유, PRIMARY(카메라·마이크) Connection 으로 SCREEN 타입 스트림을 올리는 수정된 클라이언트.
 * 주기마다 OpenVidu 세션 목록을 한 번 읽고, 손볼 것이 있는 방만 승인과 같은 방 잠금 안에서 바로잡는다.
 *
 * <p>OpenVidu 서버 설정(webhook 등)은 바꾸지 않는다 — REST 조회와 Connection/스트림 종료만 쓴다.</p>
 */
@Slf4j
@Component
public class ScreenSharePolicyEnforcer {

    private final OpenViduService openVidu;
    private final GroupVideoCallService videoCallService;
    private final boolean enabled;

    public ScreenSharePolicyEnforcer(OpenViduService openVidu,
                                     GroupVideoCallService videoCallService,
                                     @Value("${openvidu.screen-share.enforcer-enabled:true}") boolean enabled) {
        this.openVidu = openVidu;
        this.videoCallService = videoCallService;
        this.enabled = enabled;
    }

    @Scheduled(fixedDelayString = "${openvidu.screen-share.enforcer-delay-ms:15000}",
            initialDelayString = "${openvidu.screen-share.enforcer-initial-delay-ms:30000}")
    public void enforce() {
        if (!enabled) return;
        Map<String, List<Map<String, Object>>> sessions;
        try {
            sessions = openVidu.listSessionConnections();
        } catch (Exception e) {
            log.warn("[VIDEO] screen share enforcer skipped (OpenVidu unavailable): {}", e.toString());
            return;
        }
        for (Map.Entry<String, List<Map<String, Object>>> e : sessions.entrySet()) {
            String sessionId = e.getKey();
            if (videoCallService.groupIdOf(sessionId) == null) continue; // 다른 접두어(격리 E2E 등) 세션은 건드리지 않는다
            try {
                if (!videoCallService.needsScreenEnforcement(e.getValue())) continue;
                videoCallService.enforceScreenSharePolicy(sessionId).ifPresentOrElse(
                        r -> {
                            if (r.changed()) log.info("[VIDEO] screen share enforced sessionId={} stale={} overLimit={} bypass={}",
                                    sessionId, r.staleClosed(), r.overLimitClosed(), r.bypassUnpublished());
                        },
                        () -> log.debug("[VIDEO] screen share enforcer deferred (admission in progress) sessionId={}", sessionId));
            } catch (Exception ex) {
                log.warn("[VIDEO] screen share enforcer failed sessionId={}: {}", sessionId, ex.toString());
            }
        }
    }
}
