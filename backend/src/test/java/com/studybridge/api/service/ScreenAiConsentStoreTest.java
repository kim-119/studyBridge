package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.RedisConnectionFailureException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

/** 공유자 동의는 opt-in·fail-closed: Redis 장애에도 철회가 허용으로 되살아나지 않는다. */
class ScreenAiConsentStoreTest {

    private StringRedisTemplate redis;
    private ValueOperations<String, String> ops;
    private final Map<String, String> data = new HashMap<>();
    private boolean redisDown;
    private ScreenAiConsentStore store;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        redis = mock(StringRedisTemplate.class);
        ops = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(ops);
        when(ops.get(anyString())).thenAnswer(inv -> {
            if (redisDown) throw new RedisConnectionFailureException("down");
            return data.get(inv.<String>getArgument(0));
        });
        org.mockito.Mockito.doAnswer(inv -> {
            if (redisDown) throw new RedisConnectionFailureException("down");
            data.put(inv.getArgument(0), inv.getArgument(1));
            return null;
        }).when(ops).set(anyString(), anyString(), any(java.time.Duration.class));
        when(redis.delete(anyString())).thenAnswer(inv -> {
            if (redisDown) throw new RedisConnectionFailureException("down");
            return data.remove(inv.<String>getArgument(0)) != null;
        });
        store = new ScreenAiConsentStore(redis, GroupVideoCallServiceTest.CLOCK, 12);
    }

    @Test
    void defaultIsNotAllowed_andConsentIsBoundToTheSharer() {
        assertFalse(store.isAllowed(25L, "con_SA", 1L));
        store.set(25L, "con_SA", 1L, true);
        assertTrue(store.isAllowed(25L, "con_SA", 1L));
        assertFalse(store.isAllowed(25L, "con_SA", 2L)); // 다른 사람의 공유로 재사용되지 않음
        assertFalse(store.isAllowed(26L, "con_SA", 1L)); // 다른 그룹
    }

    @Test
    void revokeWhileRedisIsDown_staysRevokedAfterRecovery() {
        store.set(25L, "con_SA", 1L, true);
        redisDown = true;
        store.set(25L, "con_SA", 1L, false); // Redis 삭제 실패
        assertFalse(store.isAllowed(25L, "con_SA", 1L));
        redisDown = false;                    // Redis 에는 아직 허용 값이 남아 있다
        assertTrue(data.containsKey(ScreenAiConsentStore.key(25L, "con_SA")));
        assertFalse(store.isAllowed(25L, "con_SA", 1L));
    }

    @Test
    void redisDown_usesThisInstancesConsent() {
        store.set(25L, "con_SA", 1L, true);
        redisDown = true;
        assertTrue(store.isAllowed(25L, "con_SA", 1L));
        assertFalse(store.isAllowed(25L, "con_SB", 2L));
    }
}
