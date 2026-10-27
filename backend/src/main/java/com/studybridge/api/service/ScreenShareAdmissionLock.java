package com.studybridge.api.service;

import com.studybridge.api.exception.VideoCallException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.ReentrantLock;
import java.util.function.Supplier;

/**
 * 방(그룹) 단위 화면공유 승인 임계구역. "조회 → 판정 → SCREEN Connection 생성" 을 한 번에 한 요청만 수행하게 해
 * 서로 다른 사용자의 동시 시작 요청에서도 한도를 넘지 않게 한다.
 *
 * <ol>
 *   <li>JVM 잠금(그룹별 ReentrantLock, 대기 상한) — 단일 Spring 인스턴스(현재 운영)에서는 이것만으로 정확하다.</li>
 *   <li>Redis 분산 잠금(기존 {@link AiRequestGuard} 의 SET NX PX + 토큰 일치 시에만 해제하는 Lua 재사용) — Spring 을 여러 대로
 *       늘려도 같은 방의 승인이 겹치지 않게 한다. Redis 장애 시 AiRequestGuard 는 fail-open 이므로 JVM 잠금만으로 진행한다.</li>
 * </ol>
 */
@Slf4j
@Component
public class ScreenShareAdmissionLock {

    static final String KEY_PREFIX = "studybridge:video:screen-admission:g";
    private static final long RETRY_SLEEP_MS = 50;

    private final AiRequestGuard redisGuard;
    private final Duration waitTimeout;
    private final Duration redisLockTtl;
    private final Map<Long, ReentrantLock> localLocks = new ConcurrentHashMap<>();

    public ScreenShareAdmissionLock(AiRequestGuard redisGuard,
                                    @Value("${openvidu.screen-share.admission-wait-ms:5000}") long waitMs,
                                    @Value("${openvidu.screen-share.admission-lock-ttl-ms:60000}") long lockTtlMs) {
        this.redisGuard = redisGuard;
        this.waitTimeout = Duration.ofMillis(Math.max(0, waitMs));
        this.redisLockTtl = Duration.ofMillis(Math.max(1000, lockTtlMs));
    }

    static String key(long groupId) {
        return KEY_PREFIX + groupId;
    }

    /** 잠금을 얻을 때까지(최대 waitTimeout) 기다렸다가 실행한다. 못 얻으면 503 SCREEN_ADMISSION_BUSY. */
    public <T> T runExclusive(long groupId, Supplier<T> body) {
        return run(groupId, waitTimeout, body).orElseThrow(() -> new VideoCallException(HttpStatus.SERVICE_UNAVAILABLE,
                "SCREEN_ADMISSION_BUSY", "화면공유 요청이 몰려 처리하지 못했습니다. 잠시 후 다시 시도해주세요."));
    }

    /** 기다리지 않고 시도한다(주기 정리 작업용). 다른 요청이 처리 중이면 empty. */
    public <T> Optional<T> tryRun(long groupId, Supplier<T> body) {
        return run(groupId, Duration.ZERO, body);
    }

    private <T> Optional<T> run(long groupId, Duration wait, Supplier<T> body) {
        long deadline = System.nanoTime() + wait.toNanos();
        ReentrantLock local = localLocks.computeIfAbsent(groupId, k -> new ReentrantLock(true));
        try {
            if (!local.tryLock(wait.toNanos(), TimeUnit.NANOSECONDS)) return Optional.empty();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return Optional.empty();
        }
        try {
            AiRequestGuard.Lock remote = redisGuard.tryLock(key(groupId), redisLockTtl);
            while (!remote.acquired()) {
                if (System.nanoTime() >= deadline) {
                    log.warn("[VIDEO] screen admission busy (redis lock held elsewhere) groupId={}", groupId);
                    return Optional.empty();
                }
                try {
                    Thread.sleep(RETRY_SLEEP_MS);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    return Optional.empty();
                }
                remote = redisGuard.tryLock(key(groupId), redisLockTtl);
            }
            try {
                return Optional.ofNullable(body.get());
            } finally {
                redisGuard.release(remote);
            }
        } finally {
            local.unlock();
        }
    }
}
