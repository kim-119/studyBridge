package com.studybridge.api.service;

import com.studybridge.api.config.PasswordResetProperties;
import com.studybridge.api.dto.PasswordResetDTO;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.PasswordResetException;
import com.studybridge.api.exception.PasswordResetException.Reason;
import com.studybridge.api.repository.RefreshTokenRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.concurrent.TimeUnit;
import java.util.function.Supplier;
import java.util.regex.Pattern;

/**
 * 비밀번호 찾기(이메일 인증번호) 핵심 흐름. 임시 상태는 전부 Redis(TTL) 에만 둔다.
 *
 * <pre>
 *  send-code   : 이메일 → (IP/재전송 제한) → 사용자 존재 확인 → 발송 잠금(SET NX) → 6자리 SecureRandom 코드 → SMTP 발송
 *                → 성공 시에만 Lua 원자 교체(code TTL 5분 덮어쓰기 + attempts 초기화 + cooldown 60초 + 잠금 해제).
 *                SMTP 실패 시 기존 유효 코드 보존. 미가입 이메일은 메일 없이 동일한 200 (계정 존재 여부 비노출).
 *  verify-code : code 키 조회(없음=만료) → 상수시간 비교 → 실패 시 attempts 증가(상한 초과=코드 무효화)
 *                → 성공 시 code/attempts 삭제 + verified 키(TTL 10분).
 *  reset       : verified 키 필수 → 비밀번호 정책/확인/기존 동일 검사 → BCrypt → users.password UPDATE
 *                → 리프레시 토큰 폐기 → password-reset:* 키 전체 삭제(일회성).
 * </pre>
 *
 * Redis 키:
 *  password-reset:code:{email}, password-reset:verified:{email}, password-reset:attempts:{email},
 *  password-reset:cooldown:{email}, password-reset:sending:{email}(발송 잠금), password-reset:ip:{ip}
 *
 * 인증번호·비밀번호는 절대 로그에 남기지 않는다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PasswordResetService {

    static final String KEY_PREFIX = "password-reset:";
    static final String KEY_CODE = KEY_PREFIX + "code:";
    static final String KEY_VERIFIED = KEY_PREFIX + "verified:";
    static final String KEY_ATTEMPTS = KEY_PREFIX + "attempts:";
    static final String KEY_COOLDOWN = KEY_PREFIX + "cooldown:";
    static final String KEY_IP = KEY_PREFIX + "ip:";
    /** 이메일 단위 발송 진행 중 잠금(SET NX EX). 동시 재전송 역전 방지. */
    static final String KEY_SENDING = KEY_PREFIX + "sending:";
    /** SMTP connect(5s)+read(10s)+write(10s) 타임아웃 합보다 길게 잡아 잠금이 먼저 풀리지 않게 한다. */
    static final long SENDING_LOCK_SECONDS = 30;

    /**
     * SMTP 성공 후 authoritative 상태 원자 교체:
     *  KEYS[1]=code SET EX ARGV[2], KEYS[2]=attempts DEL, KEYS[3]=cooldown SET EX ARGV[3], KEYS[4]=sending 잠금 DEL.
     */
    static final RedisScript<Long> PROMOTE_CODE_SCRIPT = new DefaultRedisScript<>(
            "redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2]) "
                    + "redis.call('DEL', KEYS[2]) "
                    + "redis.call('SET', KEYS[3], '1', 'EX', ARGV[3]) "
                    + "redis.call('DEL', KEYS[4]) "
                    + "return 1", Long.class);

    /** 회원가입 화면과 동일 정책: 8~16자, 영문+숫자+특수문자 각 1개 이상, 공백 불가. */
    static final Pattern PASSWORD_POLICY =
            Pattern.compile("^(?=.*[A-Za-z])(?=.*\\d)(?=.*[^A-Za-z0-9\\s])[^\\s]{8,16}$");

    private static final String GENERIC_SEND_MESSAGE =
            "입력하신 이메일이 가입된 계정이라면 인증번호를 발송했습니다. 메일함을 확인해 주세요.";

    private final StringRedisTemplate redisTemplate;
    private final UserRepository userRepository;
    private final RefreshTokenRepository refreshTokenRepository;
    private final PasswordEncoder passwordEncoder;
    private final PasswordResetMailService mailService;
    private final PasswordResetProperties properties;
    private final TransactionTemplate transactionTemplate;
    private final SecureRandom secureRandom = new SecureRandom();

    // ─────────────────────────────── A. 인증번호 발송 ───────────────────────────────

    /**
     * 불변조건: "사용자가 실제로 받은 최신 인증번호" == "Redis 가 검증하는 인증번호".
     *  - 외부 side effect(SMTP) 가 성공한 뒤에만 Redis 를 바꾼다. SMTP 실패 시 기존 유효 코드/attempts/TTL 은 그대로 남는다.
     *  - 성공 시 code SET / attempts DEL / cooldown SET / 잠금 DEL 을 Lua 스크립트 하나로 원자 교체한다(부분 반영 없음).
     *  - 이메일 단위 발송 잠금(SET NX EX)으로 동시 재전송을 1건만 통과시켜 "메일 A 뒤에 메일 B, Redis 는 A" 같은 역전이 생기지 않는다.
     *  - 남는 창: SMTP 성공 후 Redis 장애. 이때는 503(STORE_UNAVAILABLE) 로 재요청을 유도하고 ERROR 로 불일치 위험을 기록한다.
     *    (잠금/cooldown 이 없어도 잠금 TTL 만료 후 재요청 가능, 기존 코드는 손대지 않음.)
     */
    public PasswordResetDTO.Response sendCode(String rawEmail, String clientIp) {
        String email = normalize(rawEmail);
        String key = keyOf(email);

        enforceIpLimit(clientIp);

        Long cooldown = redis(() -> redisTemplate.getExpire(KEY_COOLDOWN + key, TimeUnit.SECONDS));
        if (cooldown != null && cooldown > 0) {
            throw new PasswordResetException(HttpStatus.TOO_MANY_REQUESTS, Reason.RESEND_COOLDOWN,
                    "인증번호를 다시 요청하려면 " + cooldown + "초 후에 시도해 주세요.", cooldown);
        }

        Optional<User> user = userRepository.findByEmail(email);
        if (user.isEmpty()) {
            // 계정 존재 여부를 응답으로 드러내지 않는다. 메일/코드 없이 cooldown 만 동일하게 적용한다.
            redis(() -> {
                redisTemplate.opsForValue().set(KEY_COOLDOWN + key, "1",
                        properties.getResendCooldownSeconds(), TimeUnit.SECONDS);
                return null;
            });
            log.info("[password-reset] 미가입 이메일 발송 요청 무시 to={}", PasswordResetMailService.mask(email));
            return PasswordResetDTO.Response.builder()
                    .message(GENERIC_SEND_MESSAGE)
                    .expiresInSeconds(properties.getCodeTtlSeconds())
                    .resendAfterSeconds(properties.getResendCooldownSeconds())
                    .build();
        }

        // 발송 잠금: 같은 이메일의 동시 발송은 1건만. 잠금 TTL 은 SMTP connect+read+write 타임아웃 합보다 길다.
        String sendingKey = KEY_SENDING + key;
        Boolean locked = redis(() -> redisTemplate.opsForValue().setIfAbsent(sendingKey, "1",
                SENDING_LOCK_SECONDS, TimeUnit.SECONDS));
        if (!Boolean.TRUE.equals(locked)) {
            Long lockTtl = redis(() -> redisTemplate.getExpire(sendingKey, TimeUnit.SECONDS));
            long retry = lockTtl == null || lockTtl <= 0 ? SENDING_LOCK_SECONDS : lockTtl;
            throw new PasswordResetException(HttpStatus.TOO_MANY_REQUESTS, Reason.RESEND_COOLDOWN,
                    "인증메일을 발송하는 중입니다. " + retry + "초 후에 다시 시도해 주세요.", retry);
        }

        String code = generateCode();
        try {
            // 1) 외부 side effect 먼저. 실패하면 Redis 는 아무것도 바뀌지 않는다(기존 코드·attempts·TTL 보존).
            mailService.sendVerificationCode(user.get().getEmail(), code, properties.getCodeTtlSeconds());
        } catch (RuntimeException e) {
            releaseSendingLock(sendingKey, email);
            throw e;
        }

        // 2) SMTP 성공 확인 후에만 authoritative 코드 교체(원자).
        try {
            redisTemplate.execute(PROMOTE_CODE_SCRIPT,
                    List.of(KEY_CODE + key, KEY_ATTEMPTS + key, KEY_COOLDOWN + key, sendingKey),
                    code, String.valueOf(properties.getCodeTtlSeconds()), String.valueOf(properties.getResendCooldownSeconds()));
        } catch (DataAccessException e) {
            // 메일은 나갔는데 저장 실패 → 수신한 인증번호가 검증되지 않는 불일치 창. 재요청을 유도하고 명확히 기록한다.
            log.error("[password-reset] 메일 발송 후 Redis 저장 실패 — 수신 인증번호와 서버 상태 불일치 위험, 재요청 필요 to={} cause={}",
                    PasswordResetMailService.mask(email), e.getClass().getSimpleName());
            releaseSendingLock(sendingKey, email);
            throw new PasswordResetException(HttpStatus.SERVICE_UNAVAILABLE, Reason.STORE_UNAVAILABLE,
                    "인증번호 저장에 실패했습니다. 인증번호를 다시 요청해 주세요.");
        }
        log.info("[password-reset] 인증번호 발급 to={} ttl={}s", PasswordResetMailService.mask(email), properties.getCodeTtlSeconds());

        return PasswordResetDTO.Response.builder()
                .message(GENERIC_SEND_MESSAGE)
                .expiresInSeconds(properties.getCodeTtlSeconds())
                .resendAfterSeconds(properties.getResendCooldownSeconds())
                .build();
    }

    private void releaseSendingLock(String sendingKey, String email) {
        try {
            redisTemplate.delete(sendingKey);
        } catch (DataAccessException ignored) {
            log.warn("[password-reset] 발송 잠금 해제 실패(TTL {}s 후 자동 해제) to={}", SENDING_LOCK_SECONDS,
                    PasswordResetMailService.mask(email));
        }
    }

    // ─────────────────────────────── B. 인증번호 검증 ───────────────────────────────

    public PasswordResetDTO.Response verifyCode(String rawEmail, String inputCode) {
        String email = normalize(rawEmail);
        String key = keyOf(email);
        String code = inputCode == null ? "" : inputCode.trim();

        String stored = redis(() -> redisTemplate.opsForValue().get(KEY_CODE + key));
        if (stored == null) {
            throw new PasswordResetException(HttpStatus.GONE, Reason.CODE_EXPIRED,
                    "인증번호가 만료되었거나 발급되지 않았습니다. 인증번호를 다시 요청해 주세요.");
        }

        if (!constantTimeEquals(stored, code)) {
            long attempts = redis(() -> {
                Long n = redisTemplate.opsForValue().increment(KEY_ATTEMPTS + key);
                if (n != null && n == 1L) {
                    redisTemplate.expire(KEY_ATTEMPTS + key, properties.getCodeTtlSeconds(), TimeUnit.SECONDS);
                }
                return n == null ? 1L : n;
            });
            int max = properties.getMaxVerifyAttempts();
            if (attempts >= max) {
                redis(() -> redisTemplate.delete(List.of(KEY_CODE + key, KEY_ATTEMPTS + key)));
                log.warn("[password-reset] 인증 시도 초과로 코드 무효화 to={} attempts={}", PasswordResetMailService.mask(email), attempts);
                throw new PasswordResetException(HttpStatus.TOO_MANY_REQUESTS, Reason.CODE_ATTEMPTS_EXCEEDED,
                        "인증 시도 횟수를 초과하여 인증번호가 무효화되었습니다. 인증번호를 다시 요청해 주세요.");
            }
            long remaining = max - attempts;
            throw new PasswordResetException(HttpStatus.BAD_REQUEST, Reason.CODE_MISMATCH,
                    "인증번호가 올바르지 않습니다. (남은 시도 " + remaining + "회)");
        }

        // 일회성: 성공 즉시 코드 폐기 → 같은 코드 재사용 불가.
        redis(() -> {
            redisTemplate.delete(List.of(KEY_CODE + key, KEY_ATTEMPTS + key));
            redisTemplate.opsForValue().set(KEY_VERIFIED + key, Instant.now().toString(),
                    properties.getVerifiedTtlSeconds(), TimeUnit.SECONDS);
            return null;
        });
        log.info("[password-reset] 인증 성공 to={} resetWindow={}s", PasswordResetMailService.mask(email), properties.getVerifiedTtlSeconds());

        return PasswordResetDTO.Response.builder()
                .message("인증이 완료되었습니다. 새 비밀번호를 설정해 주세요.")
                .resetWindowSeconds(properties.getVerifiedTtlSeconds())
                .build();
    }

    // ─────────────────────────────── C. 새 비밀번호 설정 ───────────────────────────────

    public PasswordResetDTO.Response reset(String rawEmail, String newPassword, String newPasswordConfirm) {
        String email = normalize(rawEmail);
        String key = keyOf(email);

        if (newPasswordConfirm != null && !newPasswordConfirm.equals(newPassword)) {
            throw new PasswordResetException(HttpStatus.BAD_REQUEST, Reason.PASSWORD_CONFIRM_MISMATCH,
                    "새 비밀번호 확인이 일치하지 않습니다.");
        }
        if (newPassword == null || !PASSWORD_POLICY.matcher(newPassword).matches()) {
            throw new PasswordResetException(HttpStatus.BAD_REQUEST, Reason.PASSWORD_POLICY,
                    "비밀번호는 8~16자이며 영문, 숫자, 특수문자를 모두 포함해야 합니다.");
        }

        // 권한 판단은 서버(Redis verified 키)만 신뢰한다. 프론트 상태와 무관.
        Boolean verified = redis(() -> redisTemplate.hasKey(KEY_VERIFIED + key));
        if (!Boolean.TRUE.equals(verified)) {
            throw new PasswordResetException(HttpStatus.FORBIDDEN, Reason.NOT_VERIFIED,
                    "이메일 인증이 완료되지 않았거나 인증 유효시간이 지났습니다. 인증을 다시 진행해 주세요.");
        }

        User user = userRepository.findByEmail(email)
                .orElseThrow(() -> new PasswordResetException(HttpStatus.BAD_REQUEST, Reason.USER_NOT_FOUND,
                        "사용자를 찾을 수 없습니다."));

        if (passwordEncoder.matches(newPassword, user.getPassword())) {
            throw new PasswordResetException(HttpStatus.BAD_REQUEST, Reason.PASSWORD_SAME_AS_OLD,
                    "기존 비밀번호와 다른 비밀번호를 사용해 주세요.");
        }

        String encoded = passwordEncoder.encode(newPassword);
        transactionTemplate.executeWithoutResult(status -> {
            user.setPassword(encoded);
            userRepository.save(user);
            // 비밀번호가 바뀌었으므로 기존 세션(리프레시 토큰)은 폐기한다.
            refreshTokenRepository.deleteByEmail(user.getEmail());
        });

        // DB 반영 후 일회성 인증 상태 및 관련 키 전체 삭제. Redis 장애 시에도 변경 자체는 완료된 상태다.
        try {
            redisTemplate.delete(List.of(KEY_VERIFIED + key, KEY_CODE + key, KEY_ATTEMPTS + key, KEY_COOLDOWN + key));
        } catch (DataAccessException e) {
            log.warn("[password-reset] 비밀번호 변경 후 Redis 키 정리 실패(TTL 로 만료됨) to={}: {}",
                    PasswordResetMailService.mask(email), e.getClass().getSimpleName());
        }
        log.info("[password-reset] 비밀번호 변경 완료 userId={} to={}", user.getId(), PasswordResetMailService.mask(email));

        return PasswordResetDTO.Response.builder()
                .message("비밀번호가 변경되었습니다. 새 비밀번호로 로그인해 주세요.")
                .build();
    }

    // ─────────────────────────────── 내부 ───────────────────────────────

    private void enforceIpLimit(String clientIp) {
        if (clientIp == null || clientIp.isBlank() || properties.getIpMaxRequests() <= 0) return;
        String ipKey = KEY_IP + clientIp.trim();
        Long count = redis(() -> {
            Long n = redisTemplate.opsForValue().increment(ipKey);
            if (n != null && n == 1L) {
                redisTemplate.expire(ipKey, properties.getIpWindowSeconds(), TimeUnit.SECONDS);
            }
            return n;
        });
        if (count != null && count > properties.getIpMaxRequests()) {
            Long ttl = redis(() -> redisTemplate.getExpire(ipKey, TimeUnit.SECONDS));
            long retry = ttl == null || ttl <= 0 ? properties.getIpWindowSeconds() : ttl;
            log.warn("[password-reset] IP 요청 상한 초과 ip={} count={}", clientIp, count);
            throw new PasswordResetException(HttpStatus.TOO_MANY_REQUESTS, Reason.TOO_MANY_REQUESTS,
                    "요청이 너무 많습니다. " + retry + "초 후에 다시 시도해 주세요.", retry);
        }
    }

    String generateCode() {
        return String.format("%06d", secureRandom.nextInt(1_000_000));
    }

    static String normalize(String email) {
        if (email == null) {
            throw new PasswordResetException(HttpStatus.BAD_REQUEST, Reason.INVALID_EMAIL, "이메일을 입력해주세요.");
        }
        String trimmed = email.trim();
        if (trimmed.isEmpty()) {
            throw new PasswordResetException(HttpStatus.BAD_REQUEST, Reason.INVALID_EMAIL, "이메일을 입력해주세요.");
        }
        return trimmed;
    }

    /** Redis 키는 대소문자 무관하게 같은 계정으로 묶는다. */
    static String keyOf(String email) {
        return email.toLowerCase(Locale.ROOT);
    }

    private static boolean constantTimeEquals(String a, String b) {
        return MessageDigest.isEqual(a.getBytes(StandardCharsets.UTF_8), b.getBytes(StandardCharsets.UTF_8));
    }

    /** Redis 장애를 503 으로 변환한다(스택트레이스 노출 금지). */
    private <T> T redis(Supplier<T> op) {
        try {
            return op.get();
        } catch (DataAccessException e) {
            log.error("[password-reset] Redis 접근 실패: {}", e.getClass().getSimpleName());
            throw new PasswordResetException(HttpStatus.SERVICE_UNAVAILABLE, Reason.STORE_UNAVAILABLE,
                    "인증 서비스를 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.");
        }
    }
}
