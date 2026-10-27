package com.studybridge.api.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Clock;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 화면공유자의 "AI 화면 분석 허용" 동의. 키 = 그룹 + 화면공유 Connection id → 공유를 새로 시작하면(새 Connection) 다시 동의해야 한다.
 *
 * <p>기본값은 미동의(opt-in). 값은 동의한 공유자 userId 라서, 다른 사람 Connection 에 남은 값이 재사용되지 않는다.
 * AiRequestGuard(fail-open)와 달리 동의는 fail-closed 여야 하므로 Redis 와 JVM 맵에 함께 쓰고, Redis 장애 시 JVM 값만 본다
 * (운영 Spring 은 단일 인스턴스). 철회는 JVM 에 기록(tombstone)으로 남겨 Redis 삭제가 실패해도 다시 허용으로 읽히지 않는다.
 * TTL 은 공유 하나가 이어질 수 있는 최대 시간 — 공유가 끝나면 Connection 이 사라져 어차피 쓰이지 않는다.</p>
 */
@Slf4j
@Component
public class ScreenAiConsentStore {

    static final String PREFIX = "studybridge:screen-ai:consent:";

    private record Local(long sharerUserId, boolean allowed, long expiresAt) {}

    private final StringRedisTemplate redis;
    private final Clock clock;
    private final Duration ttl;
    private final Map<String, Local> local = new ConcurrentHashMap<>();

    public ScreenAiConsentStore(StringRedisTemplate redis, Clock clock,
                                @Value("${ai.vision.consent-ttl-hours:12}") long ttlHours) {
        this.redis = redis;
        this.clock = clock;
        this.ttl = Duration.ofHours(Math.max(1, ttlHours));
    }

    static String key(long groupId, String connectionId) {
        return PREFIX + "g" + groupId + ":" + connectionId;
    }

    public void set(long groupId, String connectionId, long sharerUserId, boolean allowed) {
        String k = key(groupId, connectionId);
        local.put(k, new Local(sharerUserId, allowed, clock.millis() + ttl.toMillis()));
        try {
            if (allowed) redis.opsForValue().set(k, String.valueOf(sharerUserId), ttl);
            else redis.delete(k);
        } catch (Exception e) {
            log.warn("[SCREEN-AI] consent redis write failed groupId={} connectionId={} → JVM 값만 사용 ({})",
                    groupId, connectionId, e.getClass().getSimpleName());
        }
        pruneExpired();
    }

    public boolean isAllowed(long groupId, String connectionId, long sharerUserId) {
        String k = key(groupId, connectionId);
        Local l = local.get(k);
        boolean fresh = l != null && l.expiresAt() > clock.millis();
        if (fresh && !l.allowed()) return false; // 이 인스턴스에서 철회됨(Redis 삭제 실패 대비)
        try {
            String v = redis.opsForValue().get(k);
            return v != null && v.equals(String.valueOf(sharerUserId));
        } catch (Exception e) {
            boolean ok = fresh && l.allowed() && l.sharerUserId() == sharerUserId;
            log.warn("[SCREEN-AI] consent redis read failed groupId={} connectionId={} → JVM 값 사용 allowed={} ({})",
                    groupId, connectionId, ok, e.getClass().getSimpleName());
            return ok;
        }
    }

    private void pruneExpired() {
        if (local.size() < 256) return;
        long now = clock.millis();
        local.entrySet().removeIf(en -> en.getValue().expiresAt() <= now);
    }
}
