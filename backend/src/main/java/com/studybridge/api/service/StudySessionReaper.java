package com.studybridge.api.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 비정상 종료 fallback: heartbeat 가 끊긴 공부 세션을 마지막 heartbeat 시각으로 종료하고,
 * heartbeat 미지원 좀비 세션(24h+)을 CANCELLED 로 정리한다. 세션마다 별도 트랜잭션(REQUIRES_NEW)이라 한 건 실패가 나머지를 막지 않는다.
 * 서버 재시작 후에도 DB 의 lastHeartbeatAt 만으로 복구되므로 인메모리 상태가 없다.
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class StudySessionReaper {

    private final TimerService timerService;

    @Scheduled(fixedDelayString = "${studybridge.study-session.reaper-delay-ms:60000}", initialDelayString = "${studybridge.study-session.reaper-initial-delay-ms:30000}")
    public void reap() {
        int expired = 0;
        int cancelled = 0;
        try {
            List<Long> timedOut = timerService.findHeartbeatTimedOutIds();
            for (Long id : timedOut) {
                try {
                    if (timerService.expireTimedOut(id)) expired++;
                } catch (RuntimeException e) {
                    log.warn("Failed to expire timed-out session {}: {}", id, e.getMessage());
                }
            }
            List<Long> stale = timerService.findStaleWithoutHeartbeatIds();
            for (Long id : stale) {
                try {
                    if (timerService.cancelStaleWithoutHeartbeat(id)) cancelled++;
                } catch (RuntimeException e) {
                    log.warn("Failed to cancel stale session {}: {}", id, e.getMessage());
                }
            }
        } catch (RuntimeException e) {
            log.warn("Study session reaper pass failed: {}", e.getMessage());
        }
        if (expired > 0 || cancelled > 0) {
            log.info("Study session reaper: expired={}, cancelledStale={}", expired, cancelled);
        }
    }
}
