package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * Redis 분산 잠금 경로(실제 Redis 필요): JVM 잠금을 따로 가진 두 인스턴스(= Spring 2대)가 같은 방 승인을 동시에 수행해도 겹치지 않는다.
 * 일회용 Redis 로만 실행한다(운영 Redis 금지): {@code docker run --rm -d -p 16379:6379 redis:7-alpine} 후 SB_TEST_REDIS_PORT=16379.
 * 환경변수가 없으면(CI 등) 건너뛴다.
 */
@EnabledIfEnvironmentVariable(named = "SB_TEST_REDIS_PORT", matches = "\\d+")
class ScreenShareAdmissionLockRedisTest {

    private LettuceConnectionFactory factory;
    private StringRedisTemplate redis;

    @BeforeEach
    void setUp() {
        factory = new LettuceConnectionFactory("127.0.0.1", Integer.parseInt(System.getenv("SB_TEST_REDIS_PORT")));
        factory.afterPropertiesSet();
        redis = new StringRedisTemplate(factory);
        redis.afterPropertiesSet();
        redis.delete(ScreenShareAdmissionLock.key(25L));
    }

    @AfterEach
    void tearDown() {
        redis.delete(ScreenShareAdmissionLock.key(25L));
        factory.destroy();
    }

    @Test
    void twoInstances_neverRunTheSameRoomsAdmissionConcurrently() throws Exception {
        ScreenShareAdmissionLock instanceA = new ScreenShareAdmissionLock(new AiRequestGuard(redis), 5000, 60000);
        ScreenShareAdmissionLock instanceB = new ScreenShareAdmissionLock(new AiRequestGuard(redis), 5000, 60000);
        AtomicInteger inside = new AtomicInteger();
        AtomicInteger maxInside = new AtomicInteger();
        AtomicInteger runs = new AtomicInteger();
        ExecutorService pool = Executors.newFixedThreadPool(8);
        CountDownLatch go = new CountDownLatch(1);
        List<Future<?>> fs = new ArrayList<>();
        for (int i = 0; i < 8; i++) {
            ScreenShareAdmissionLock lock = i % 2 == 0 ? instanceA : instanceB;
            fs.add(pool.submit(() -> {
                go.await();
                return lock.runExclusive(25L, () -> {
                    maxInside.accumulateAndGet(inside.incrementAndGet(), Math::max);
                    try {
                        Thread.sleep(40);
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                    }
                    inside.decrementAndGet();
                    return runs.incrementAndGet();
                });
            }));
        }
        go.countDown();
        for (Future<?> f : fs) f.get(20, TimeUnit.SECONDS);
        pool.shutdownNow();

        assertEquals(8, runs.get());
        assertEquals(1, maxInside.get());
        assertFalse(Boolean.TRUE.equals(redis.hasKey(ScreenShareAdmissionLock.key(25L)))); // 끝나면 해제(토큰 일치 Lua)
    }

    @Test
    void lockHeldByAnotherInstance_tryRunSkips_andTtlBoundsAStuckHolder() {
        redis.opsForValue().set(ScreenShareAdmissionLock.key(25L), "other-instance", java.time.Duration.ofMillis(1500));
        ScreenShareAdmissionLock lock = new ScreenShareAdmissionLock(new AiRequestGuard(redis), 3000, 60000);

        assertTrue(lock.tryRun(25L, () -> "x").isEmpty());          // 정리 작업은 기다리지 않고 건너뜀
        assertEquals("ok", lock.runExclusive(25L, () -> "ok"));     // 승인은 TTL 만료까지 기다렸다가 진행
    }
}
