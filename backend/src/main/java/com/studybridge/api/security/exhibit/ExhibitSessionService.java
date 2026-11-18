package com.studybridge.api.security.exhibit;

import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/**
 * 체험 계정의 기기별 세션 슬롯(계정당 최대 {@code exhibit.max-sessions-per-account}).
 *
 * <p>Redis HASH {@code studybridge:exhibit:sessions:u{userId}} — field = 세션 id(sid, 토큰의 "sid" claim),
 * value = {@code lastSeenMs:expiresAtMs:sha256(refreshToken)}. 판정·갱신은 전부 Lua 한 번으로 처리해 원자적이다
 * (동시에 여러 로그인이 와도 한도를 넘겨 승인하지 않는다).</p>
 *
 * <ul>
 *   <li>로그인: 유휴/만료 슬롯을 먼저 정리한 뒤 남은 슬롯 수가 한도 미만일 때만 새 슬롯을 연다. 한도면 거절하고 기존 세션은 그대로 둔다.</li>
 *   <li>요청마다(JwtAuthenticationFilter): 슬롯이 살아 있으면 lastSeen 을 전진, 없거나 유휴 초과면 거절(401 → 재로그인).</li>
 *   <li>리프레시: 같은 슬롯 안에서 리프레시 토큰을 회전(이전 토큰 재사용은 거절). 절대 만료는 연장하지 않는다.</li>
 *   <li>로그아웃: 그 기기 슬롯만 반환한다(같은 계정의 다른 기기는 유지).</li>
 * </ul>
 * 일반 사용자는 이 클래스를 거치지 않는다(DB refresh_tokens 경로 그대로).
 */
@Slf4j
@Service
public class ExhibitSessionService {

    static final String KEY_PREFIX = "studybridge:exhibit:sessions:u";
    /** 같은 슬롯의 lastSeen 쓰기 최소 간격(요청마다 HSET 하지 않는다). 유휴 기준(분 단위) 대비 무시할 수준. */
    static final long TOUCH_WRITE_INTERVAL_MS = 10_000L;

    private static final DefaultRedisScript<List> ADMIT = new DefaultRedisScript<>("""
            local now = tonumber(ARGV[1])
            local idle = tonumber(ARGV[2])
            local max = tonumber(ARGV[3])
            local live = 0
            local all = redis.call('HGETALL', KEYS[1])
            for i = 1, #all, 2 do
              local last, exp = string.match(all[i + 1], '^(%d+):(%d+):')
              if last == nil or tonumber(last) + idle <= now or tonumber(exp) <= now then
                redis.call('HDEL', KEYS[1], all[i])
              else
                live = live + 1
              end
            end
            if live >= max then
              return {0, live}
            end
            redis.call('HSET', KEYS[1], ARGV[4], ARGV[1] .. ':' .. ARGV[5] .. ':' .. ARGV[6])
            local ttl = tonumber(ARGV[5]) - now
            if redis.call('PTTL', KEYS[1]) < ttl then
              redis.call('PEXPIRE', KEYS[1], ttl)
            end
            return {1, live + 1}
            """, List.class);

    private static final DefaultRedisScript<Long> TOUCH = new DefaultRedisScript<>("""
            local v = redis.call('HGET', KEYS[1], ARGV[3])
            if not v then return 0 end
            local last, exp, h = string.match(v, '^(%d+):(%d+):(.*)$')
            local now = tonumber(ARGV[1])
            if last == nil or tonumber(last) + tonumber(ARGV[2]) <= now or tonumber(exp) <= now then
              redis.call('HDEL', KEYS[1], ARGV[3])
              return 0
            end
            if now - tonumber(last) >= tonumber(ARGV[4]) then
              redis.call('HSET', KEYS[1], ARGV[3], ARGV[1] .. ':' .. exp .. ':' .. h)
            end
            return 1
            """, Long.class);

    private static final DefaultRedisScript<Long> ROTATE = new DefaultRedisScript<>("""
            local v = redis.call('HGET', KEYS[1], ARGV[3])
            if not v then return 0 end
            local last, exp, h = string.match(v, '^(%d+):(%d+):(.*)$')
            local now = tonumber(ARGV[1])
            if last == nil or tonumber(last) + tonumber(ARGV[2]) <= now or tonumber(exp) <= now then
              redis.call('HDEL', KEYS[1], ARGV[3])
              return 0
            end
            if h ~= ARGV[4] then return -1 end
            redis.call('HSET', KEYS[1], ARGV[3], ARGV[1] .. ':' .. exp .. ':' .. ARGV[5])
            return 1
            """, Long.class);

    /** request attribute: 이 요청의 체험 세션 id(로그아웃이 그 기기 슬롯만 반환하는 데 쓴다). */
    public static final String SESSION_ID_ATTRIBUTE = "studybridge.exhibit.sessionId";

    private final StringRedisTemplate redis;
    private final ExhibitAccountProperties props;
    private final Clock clock;

    public ExhibitSessionService(StringRedisTemplate redis, ExhibitAccountProperties props, Clock clock) {
        this.redis = redis;
        this.props = props;
        this.clock = clock;
    }

    public boolean isExhibitEmail(String email) {
        return props.isExhibitEmail(email);
    }

    /** 로그인 입력이 체험 계정(별칭·email)이면 그 email. 일반 사용자 입력이면 empty. */
    public Optional<String> resolveLoginId(String input) {
        return props.resolveLoginId(input);
    }

    public String newSessionId() {
        return UUID.randomUUID().toString().replace("-", "");
    }

    /** 지금 로그인하면 세션이 끝나는 시각(epoch ms). 리프레시 토큰 만료도 이 값이다. */
    public long sessionExpiresAt() {
        return clock.millis() + props.getSessionMaxHours() * 3_600_000L;
    }

    private long idleMs() {
        return props.getSessionIdleMinutes() * 60_000L;
    }

    static String key(long userId) {
        return KEY_PREFIX + userId;
    }

    static String hash(String token) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(token.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    /**
     * 새 슬롯을 연다. 한도면 409 EXHIBIT_SESSION_LIMIT(기존 세션 유지), Redis 장애면 503 — 한도를 확인할 수 없으면 열지 않는다.
     */
    public void admit(long userId, String sessionId, long expiresAtMs, String refreshToken) {
        int max = Math.max(1, props.getMaxSessionsPerAccount());
        List<?> result;
        try {
            result = redis.execute(ADMIT, List.of(key(userId)), String.valueOf(clock.millis()), String.valueOf(idleMs()),
                    String.valueOf(max), sessionId, String.valueOf(expiresAtMs), hash(refreshToken));
        } catch (Exception e) {
            log.warn("[EXHIBIT] session admit failed (redis) userId={} ({})", userId, e.getClass().getSimpleName());
            throw new ExhibitSessionException(HttpStatus.SERVICE_UNAVAILABLE, "EXHIBIT_SESSION_UNAVAILABLE",
                    "체험 계정 로그인을 잠시 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.");
        }
        long admitted = result == null || result.isEmpty() ? 0 : ((Number) result.get(0)).longValue();
        long active = result == null || result.size() < 2 ? -1 : ((Number) result.get(1)).longValue();
        if (admitted != 1) {
            log.info("[EXHIBIT] session limit reached userId={} active={} limit={}", userId, active, max);
            throw new ExhibitSessionException(HttpStatus.CONFLICT, "EXHIBIT_SESSION_LIMIT",
                    "이 체험 계정은 이미 " + max + "대의 기기에서 사용 중입니다. 다른 체험 계정(test1~test4)을 이용하거나, 사용 중인 기기에서 로그아웃한 뒤 다시 시도해 주세요.");
        }
        log.info("[EXHIBIT] session opened userId={} active={}/{}", userId, active, max);
    }

    /**
     * 요청 허용 여부. 체험 계정이 아니면 항상 true(Redis 를 부르지 않는다).
     * 체험 계정은 sid 가 있고 슬롯이 살아 있어야 한다. Redis 장애 시에는 이미 발급된 서명 토큰을 믿고 허용한다(fail-open).
     */
    public boolean allowsAccess(String email, Long userId, String sessionId) {
        if (!props.isExhibitEmail(email)) return true;
        if (userId == null || sessionId == null || sessionId.isBlank()) return false;
        try {
            Long ok = redis.execute(TOUCH, List.of(key(userId)), String.valueOf(clock.millis()), String.valueOf(idleMs()),
                    sessionId, String.valueOf(TOUCH_WRITE_INTERVAL_MS));
            return ok != null && ok == 1L;
        } catch (Exception e) {
            log.warn("[EXHIBIT] session touch failed (redis) userId={} → fail-open ({})", userId, e.getClass().getSimpleName());
            return true;
        }
    }

    /** 같은 슬롯에서 리프레시 토큰을 회전한다. 슬롯이 없거나 만료면 / 이전 토큰이면 IllegalArgumentException(→ 401). */
    public void rotate(long userId, String sessionId, String oldRefreshToken, String newRefreshToken) {
        Long r;
        try {
            r = redis.execute(ROTATE, List.of(key(userId)), String.valueOf(clock.millis()), String.valueOf(idleMs()),
                    sessionId, hash(oldRefreshToken), hash(newRefreshToken));
        } catch (Exception e) {
            log.warn("[EXHIBIT] session rotate failed (redis) userId={} ({})", userId, e.getClass().getSimpleName());
            throw new ExhibitSessionException(HttpStatus.SERVICE_UNAVAILABLE, "EXHIBIT_SESSION_UNAVAILABLE",
                    "체험 계정 세션을 잠시 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.");
        }
        if (r == null || r == 0L) {
            throw new IllegalArgumentException("체험 계정 세션이 만료되었습니다. 다시 로그인해 주세요.");
        }
        if (r == -1L) {
            throw new IllegalArgumentException("이미 사용된 리프레시 토큰입니다. 다시 로그인해 주세요.");
        }
    }

    /** 이 기기 슬롯만 반환(로그아웃). 실패해도 유휴 만료로 반환된다. */
    public void release(long userId, String sessionId) {
        if (sessionId == null || sessionId.isBlank()) return;
        try {
            Long n = redis.opsForHash().delete(key(userId), sessionId);
            log.info("[EXHIBIT] session released userId={} removed={}", userId, n);
        } catch (Exception e) {
            log.warn("[EXHIBIT] session release failed (redis) userId={} → 유휴 만료로 반환됨 ({})", userId, e.getClass().getSimpleName());
        }
    }

    /** 살아 있는 슬롯 수(조회 전용, 정리하지 않는다). */
    public int activeSessionCount(long userId) {
        long now = clock.millis();
        long idle = idleMs();
        Map<Object, Object> all = redis.opsForHash().entries(key(userId));
        int live = 0;
        for (Object v : all.values()) {
            String[] parts = String.valueOf(v).split(":", 3);
            if (parts.length < 3) continue;
            try {
                if (Long.parseLong(parts[0]) + idle > now && Long.parseLong(parts[1]) > now) live++;
            } catch (NumberFormatException ignored) {
                // 손상된 값은 다음 로그인에서 정리된다
            }
        }
        return live;
    }
}
