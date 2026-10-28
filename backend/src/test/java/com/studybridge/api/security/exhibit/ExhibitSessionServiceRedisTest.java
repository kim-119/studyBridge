package com.studybridge.api.security.exhibit;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
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
import org.springframework.data.redis.connection.lettuce.LettuceClientConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;

/**
 * 체험 계정 세션 슬롯 Lua(실제 Redis 필요). 일회용 Redis 로만 실행한다(운영 Redis 금지):
 * {@code docker run --rm -d -p 16391:6379 redis:7-alpine} 후 SB_TEST_REDIS_PORT=16391. 환경변수가 없으면(CI 등) 건너뛴다.
 */
@EnabledIfEnvironmentVariable(named = "SB_TEST_REDIS_PORT", matches = "\\d+")
class ExhibitSessionServiceRedisTest {

    private static final String TEST1 = "test1@studybridge.co.kr";
    private static final long U1 = 900_001L;
    private static final long U2 = 900_002L;

    /** 테스트가 시각을 앞당길 수 있는 Clock. */
    static final class MutableClock extends Clock {
        private Instant now = Instant.parse("2026-10-29T01:00:00Z");

        void advance(Duration d) {
            now = now.plus(d);
        }

        @Override
        public ZoneId getZone() {
            return ZoneId.of("Asia/Seoul");
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return now;
        }
    }

    private LettuceConnectionFactory factory;
    private StringRedisTemplate redis;
    private MutableClock clock;
    private ExhibitAccountProperties props;
    private ExhibitSessionService service;

    @BeforeEach
    void setUp() {
        factory = new LettuceConnectionFactory("127.0.0.1", Integer.parseInt(System.getenv("SB_TEST_REDIS_PORT")));
        factory.afterPropertiesSet();
        redis = new StringRedisTemplate(factory);
        redis.afterPropertiesSet();
        clock = new MutableClock();
        props = new ExhibitAccountProperties();
        service = new ExhibitSessionService(redis, props, clock);
        cleanup();
    }

    @AfterEach
    void tearDown() {
        cleanup();
        factory.destroy();
    }

    private void cleanup() {
        for (long u = 900_001L; u <= 900_004L; u++) redis.delete(ExhibitSessionService.key(u));
    }

    private String open(long userId, String refresh) {
        String sid = service.newSessionId();
        service.admit(userId, sid, service.sessionExpiresAt(), refresh);
        return sid;
    }

    @Test
    void twoDevicesAdmitted_thirdRejected_firstTwoKeepWorking() {
        String a = open(U1, "refresh-a");
        String b = open(U1, "refresh-b");

        ExhibitSessionException e = assertThrows(ExhibitSessionException.class, () -> open(U1, "refresh-c"));
        assertEquals(HttpStatus.CONFLICT, e.getStatus());
        assertEquals("EXHIBIT_SESSION_LIMIT", e.getCode());

        assertTrue(service.allowsAccess(TEST1, U1, a), "기존 기기 A 유지");
        assertTrue(service.allowsAccess(TEST1, U1, b), "기존 기기 B 유지");
        assertEquals(2, service.activeSessionCount(U1));
        assertEquals(2L, redis.opsForHash().size(ExhibitSessionService.key(U1)), "거절된 세 번째는 슬롯을 남기지 않는다");
    }

    @Test
    void logoutReleasesOnlyThatDevice_andFreesTheSlot() {
        String a = open(U1, "refresh-a");
        String b = open(U1, "refresh-b");

        service.release(U1, a);

        assertFalse(service.allowsAccess(TEST1, U1, a), "로그아웃한 기기 A 의 토큰은 거절");
        assertTrue(service.allowsAccess(TEST1, U1, b), "다른 기기 B 는 유지");
        String c = assertDoesNotThrow(() -> open(U1, "refresh-c"), "반환된 슬롯으로 새 기기 로그인");
        assertTrue(service.allowsAccess(TEST1, U1, c));
    }

    @Test
    void idleSlotIsReleased_andReloginSucceeds() {
        String a = open(U1, "refresh-a");
        String b = open(U1, "refresh-b");

        clock.advance(Duration.ofMinutes(20));
        assertTrue(service.allowsAccess(TEST1, U1, b), "B 는 계속 사용 중(lastSeen 갱신)");
        clock.advance(Duration.ofMinutes(11)); // A 는 31분 무요청, B 는 11분

        assertFalse(service.allowsAccess(TEST1, U1, a), "유휴 30분 초과(비정상 종료) → 슬롯 반환");
        assertTrue(service.allowsAccess(TEST1, U1, b));
        String c = assertDoesNotThrow(() -> open(U1, "refresh-c"), "만료된 슬롯 자리로 재접속");
        assertTrue(service.allowsAccess(TEST1, U1, c));
        assertEquals(2, service.activeSessionCount(U1));
    }

    @Test
    void idleSlotsArePurgedAtLogin_evenWithoutTouch() {
        open(U1, "refresh-a");
        open(U1, "refresh-b");
        clock.advance(Duration.ofMinutes(31));

        assertDoesNotThrow(() -> open(U1, "refresh-c"));
        assertDoesNotThrow(() -> open(U1, "refresh-d"));
        assertEquals(2L, redis.opsForHash().size(ExhibitSessionService.key(U1)), "유휴 슬롯은 로그인 Lua 가 정리");
    }

    @Test
    void absoluteLifetimeEndsSession_evenIfActive() {
        String a = open(U1, "refresh-a");
        long ttl = redis.getExpire(ExhibitSessionService.key(U1), TimeUnit.MILLISECONDS);
        assertTrue(ttl > Duration.ofHours(11).toMillis() && ttl <= Duration.ofHours(12).toMillis(), "키 TTL = 절대 수명");
        for (int i = 0; i < 12 * 4; i++) { // 12시간 동안 15분마다 사용
            clock.advance(Duration.ofMinutes(15));
            if (i < 12 * 4 - 1) assertTrue(service.allowsAccess(TEST1, U1, a));
        }
        assertFalse(service.allowsAccess(TEST1, U1, a), "절대 수명(12h) 후 재로그인 필요");
    }

    @Test
    void refreshRotatesWithinSlot_andRejectsReusedToken() {
        String a = open(U1, "refresh-a1");
        service.rotate(U1, a, "refresh-a1", "refresh-a2");

        IllegalArgumentException reused = assertThrows(IllegalArgumentException.class,
                () -> service.rotate(U1, a, "refresh-a1", "refresh-a3"));
        assertTrue(reused.getMessage().contains("이미 사용된"));
        assertDoesNotThrow(() -> service.rotate(U1, a, "refresh-a2", "refresh-a3"));
        assertTrue(service.allowsAccess(TEST1, U1, a), "회전 후에도 같은 슬롯");
        assertEquals(1, service.activeSessionCount(U1), "리프레시는 슬롯을 늘리지 않는다");

        service.release(U1, a);
        assertThrows(IllegalArgumentException.class, () -> service.rotate(U1, a, "refresh-a3", "refresh-a4"),
                "로그아웃한 기기의 리프레시 토큰은 거절");
    }

    @Test
    void concurrentLogins_admitExactlyTheLimit() throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(16);
        CountDownLatch go = new CountDownLatch(1);
        AtomicInteger admitted = new AtomicInteger();
        AtomicInteger rejected = new AtomicInteger();
        List<Future<?>> fs = new ArrayList<>();
        for (int i = 0; i < 20; i++) {
            int n = i;
            fs.add(pool.submit(() -> {
                go.await();
                try {
                    open(U1, "refresh-" + n);
                    admitted.incrementAndGet();
                } catch (ExhibitSessionException e) {
                    rejected.incrementAndGet();
                }
                return null;
            }));
        }
        go.countDown();
        for (Future<?> f : fs) f.get(20, TimeUnit.SECONDS);
        pool.shutdownNow();

        assertEquals(2, admitted.get(), "동시 로그인 20건 중 정확히 2건만 승인(원자적)");
        assertEquals(18, rejected.get());
        assertEquals(2L, redis.opsForHash().size(ExhibitSessionService.key(U1)));
    }

    @Test
    void fourAccountsTimesTwo_eightSessionsIndependent() {
        List<String[]> sessions = new ArrayList<>();
        for (long u = 900_001L; u <= 900_004L; u++) {
            sessions.add(new String[] {String.valueOf(u), open(u, "r1-" + u)});
            sessions.add(new String[] {String.valueOf(u), open(u, "r2-" + u)});
            long user = u;
            assertThrows(ExhibitSessionException.class, () -> open(user, "r3-" + user));
        }
        assertEquals(8, sessions.size());
        for (String[] s : sessions) {
            assertTrue(service.allowsAccess(TEST1, Long.parseLong(s[0]), s[1]));
        }
        service.release(U2, sessions.get(2)[1]);
        assertEquals(1, service.activeSessionCount(U2));
        assertEquals(2, service.activeSessionCount(U1), "다른 계정 슬롯은 영향 없음");
    }

    @Test
    void nonExhibitAccount_isNeverChecked() {
        assertTrue(service.allowsAccess("someone@example.com", 42L, null));
        assertTrue(service.allowsAccess("test1@test.com", 47L, null), "기존 일반 계정 test1@test.com 은 체험 계정이 아니다");
        assertFalse(service.allowsAccess(TEST1, U1, null), "체험 계정 토큰에 sid 가 없으면 거절");
        assertFalse(service.allowsAccess(TEST1, U1, "unknown-sid"));
    }

    @Test
    void redisDown_loginFailsClosed_requestsFailOpen() {
        LettuceConnectionFactory dead = new LettuceConnectionFactory(new RedisStandaloneConfiguration("127.0.0.1", 6399),
                LettuceClientConfiguration.builder().commandTimeout(Duration.ofMillis(500)).build());
        dead.afterPropertiesSet();
        try {
            StringRedisTemplate deadRedis = new StringRedisTemplate(dead);
            deadRedis.afterPropertiesSet();
            ExhibitSessionService down = new ExhibitSessionService(deadRedis, props, clock);

            ExhibitSessionException e = assertThrows(ExhibitSessionException.class,
                    () -> down.admit(U1, down.newSessionId(), down.sessionExpiresAt(), "r"));
            assertEquals(HttpStatus.SERVICE_UNAVAILABLE, e.getStatus(), "한도를 확인할 수 없으면 새 세션을 열지 않는다");
            assertTrue(down.allowsAccess(TEST1, U1, "sid"), "이미 발급된 서명 토큰은 Redis 장애 동안 허용");
            assertDoesNotThrow(() -> down.release(U1, "sid"));
        } finally {
            dead.destroy();
        }
    }
}
