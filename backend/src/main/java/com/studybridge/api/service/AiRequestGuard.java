package com.studybridge.api.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.List;
import java.util.UUID;

/**
 * AI 호출 앞단의 Redis 가드 — 사용자별 키로만 동작한다(키에 항상 userId 포함, 다른 사용자와 공유 없음).
 *
 * <ul>
 *   <li>{@link #tryLock}: 같은 사용자·같은 대상의 동시 재생성/추천 생성을 1건으로 제한(SET NX PX). 해제는 토큰 일치 시에만(Lua).</li>
 *   <li>{@link #allow}: 고정 창 요청 제한(INCR + 첫 요청에만 EXPIRE).</li>
 * </ul>
 * Redis 장애 시 fail-open(허용)한다 — 가드 장애로 기능 자체를 막지 않는다. 중복 저장 방지는 DB 제약/조건부 UPDATE 가 최종 방어선이다.
 */
@Slf4j
@Component
public class AiRequestGuard {

    static final String PREFIX = "studybridge:ai-guard:";

    private static final DefaultRedisScript<Long> RELEASE_IF_OWNER = new DefaultRedisScript<>(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end", Long.class);

    private final StringRedisTemplate redis;

    public AiRequestGuard(StringRedisTemplate redis) {
        this.redis = redis;
    }

    /** 잠금 핸들. {@link #acquired()} 가 false 면 이미 진행 중인 요청이 있다. */
    public record Lock(String key, String token, boolean acquired) {}

    public static String lockKey(String feature, Long userId, Object target) {
        return PREFIX + "lock:" + feature + ":u" + userId + ":" + target;
    }

    public static String rateKey(String feature, Long userId) {
        return PREFIX + "rate:" + feature + ":u" + userId;
    }

    public Lock tryLock(String key, Duration ttl) {
        String token = UUID.randomUUID().toString();
        try {
            Boolean ok = redis.opsForValue().setIfAbsent(key, token, ttl);
            return new Lock(key, token, Boolean.TRUE.equals(ok));
        } catch (Exception e) {
            log.warn("[AI-GUARD] redis lock unavailable key={} → fail-open ({})", key, e.getClass().getSimpleName());
            return new Lock(key, null, true);
        }
    }

    public void release(Lock lock) {
        if (lock == null || !lock.acquired() || lock.token() == null) return;
        try {
            redis.execute(RELEASE_IF_OWNER, List.of(lock.key()), lock.token());
        } catch (Exception e) {
            log.warn("[AI-GUARD] redis release failed key={} ({}) — TTL 만료로 해제됨", lock.key(), e.getClass().getSimpleName());
        }
    }

    /** window 안에서 limit 회까지 허용. Redis 장애 시 허용. */
    public boolean allow(String key, int limit, Duration window) {
        try {
            Long n = redis.opsForValue().increment(key);
            if (n != null && n == 1L) {
                redis.expire(key, window);
            }
            return n == null || n <= limit;
        } catch (Exception e) {
            log.warn("[AI-GUARD] redis rate-limit unavailable key={} → fail-open ({})", key, e.getClass().getSimpleName());
            return true;
        }
    }
}
