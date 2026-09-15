package com.studybridge.api.service;

import com.studybridge.api.config.PasswordResetProperties;
import com.studybridge.api.dto.PasswordResetDTO;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.PasswordResetException;
import com.studybridge.api.exception.PasswordResetException.Reason;
import com.studybridge.api.repository.RefreshTokenRepository;
import com.studybridge.api.repository.UserRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.transaction.support.SimpleTransactionStatus;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.transaction.support.TransactionTemplate;

import java.util.Collection;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * PasswordResetService 단위 테스트.
 *  - 실제 Redis 없이 StringRedisTemplate/ValueOperations 를 method-name 디스패처 mock 으로 대체하고,
 *    key -> value + 만료시각(가짜 시계) 인메모리 Map 으로 SET EX / GET / INCR / EXPIRE / TTL / DEL 의미를 재현한다.
 *  - 메일 발송/DB 는 mock. BCrypt 는 실제 인코더로 동일 비밀번호 검사와 저장 해시를 검증한다.
 */
class PasswordResetServiceTest {

    private static final String EMAIL = "reset-user@example.com";

    private final Map<String, String> values = new HashMap<>();
    private final Map<String, Long> expiresAt = new HashMap<>();
    private long now = 1_000L; // 가짜 시계(초)
    private int scriptCalls = 0;

    private StringRedisTemplate redis;
    private UserRepository userRepository;
    private RefreshTokenRepository refreshTokenRepository;
    private PasswordResetMailService mailService;
    private PasswordResetProperties props;
    private PasswordEncoder encoder;
    private PasswordResetService service;
    private User user;

    private void purgeExpired() {
        expiresAt.entrySet().removeIf(e -> {
            if (e.getValue() <= now) { values.remove(e.getKey()); return true; }
            return false;
        });
    }

    @SuppressWarnings("unchecked")
    @BeforeEach
    void setUp() {
        values.clear();
        expiresAt.clear();
        now = 1_000L;
        scriptCalls = 0;

        ValueOperations<String, String> ops = mock(ValueOperations.class, inv -> {
            purgeExpired();
            String m = inv.getMethod().getName();
            Object[] a = inv.getArguments();
            switch (m) {
                case "set": {
                    values.put((String) a[0], (String) a[1]);
                    if (a.length >= 4) {
                        expiresAt.put((String) a[0], now + TimeUnit.SECONDS.convert((Long) a[2], (TimeUnit) a[3]));
                    } else {
                        expiresAt.remove((String) a[0]);
                    }
                    return null;
                }
                case "get": return values.get((String) a[0]);
                case "setIfAbsent": { // SET NX EX
                    if (values.containsKey((String) a[0])) return false;
                    values.put((String) a[0], (String) a[1]);
                    expiresAt.put((String) a[0], now + TimeUnit.SECONDS.convert((Long) a[2], (TimeUnit) a[3]));
                    return true;
                }
                case "increment": {
                    long n = Long.parseLong(values.getOrDefault((String) a[0], "0")) + 1;
                    values.put((String) a[0], String.valueOf(n));
                    return n;
                }
                default: throw new UnsupportedOperationException(m);
            }
        });

        redis = mock(StringRedisTemplate.class, inv -> {
            purgeExpired();
            String m = inv.getMethod().getName();
            Object[] a = inv.getArguments();
            switch (m) {
                case "opsForValue": return ops;
                case "execute": { // PROMOTE_CODE_SCRIPT: code SET EX / attempts DEL / cooldown SET EX / sending DEL
                    if (!(a[0] instanceof org.springframework.data.redis.core.script.RedisScript)) throw new UnsupportedOperationException("execute");
                    List<String> keys = (List<String>) a[1];
                    Object[] argv = java.util.Arrays.copyOfRange(a, 2, a.length); // Mockito 는 varargs 를 펼쳐 전달한다
                    scriptCalls++;
                    values.put(keys.get(0), (String) argv[0]); expiresAt.put(keys.get(0), now + Long.parseLong((String) argv[1]));
                    values.remove(keys.get(1)); expiresAt.remove(keys.get(1));
                    values.put(keys.get(2), "1"); expiresAt.put(keys.get(2), now + Long.parseLong((String) argv[2]));
                    values.remove(keys.get(3)); expiresAt.remove(keys.get(3));
                    return 1L;
                }
                case "getExpire": {
                    Long exp = expiresAt.get((String) a[0]);
                    if (!values.containsKey((String) a[0])) return -2L;
                    return exp == null ? -1L : Math.max(0, exp - now);
                }
                case "hasKey": return values.containsKey((String) a[0]);
                case "expire": {
                    if (!values.containsKey((String) a[0])) return false;
                    expiresAt.put((String) a[0], now + TimeUnit.SECONDS.convert((Long) a[1], (TimeUnit) a[2]));
                    return true;
                }
                case "delete": {
                    if (a[0] instanceof Collection) {
                        long c = 0;
                        for (Object k : (Collection<?>) a[0]) { if (values.remove(k) != null) c++; expiresAt.remove(k); }
                        return c;
                    }
                    boolean r = values.remove(a[0]) != null;
                    expiresAt.remove(a[0]);
                    return r;
                }
                default: throw new UnsupportedOperationException(m);
            }
        });

        userRepository = mock(UserRepository.class);
        refreshTokenRepository = mock(RefreshTokenRepository.class);
        mailService = mock(PasswordResetMailService.class);
        encoder = new BCryptPasswordEncoder(4);
        props = new PasswordResetProperties();

        user = User.builder().id(77L).email(EMAIL).password(encoder.encode("OldPass1!")).displayName("tester").build();
        when(userRepository.findByEmail(EMAIL)).thenReturn(Optional.of(user));
        when(userRepository.findByEmail("nobody@example.com")).thenReturn(Optional.empty());

        TransactionTemplate tx = mock(TransactionTemplate.class);
        when(tx.execute(any())).thenAnswer(inv -> ((TransactionCallback<?>) inv.getArgument(0)).doInTransaction(new SimpleTransactionStatus()));
        org.mockito.Mockito.doAnswer(inv -> {
            ((java.util.function.Consumer<org.springframework.transaction.TransactionStatus>) inv.getArgument(0)).accept(new SimpleTransactionStatus());
            return null;
        }).when(tx).executeWithoutResult(any());

        service = new PasswordResetService(redis, userRepository, refreshTokenRepository, encoder, mailService, props, tx);
    }

    private String storedCode() { return values.get("password-reset:code:" + EMAIL); }

    private PasswordResetException expect(Reason reason, Runnable r) {
        PasswordResetException ex = assertThrows(PasswordResetException.class, r::run);
        assertEquals(reason, ex.getReason());
        return ex;
    }

    // ── 발송 ──

    @Test
    void sendCode_storesSixDigitCodeWithTtl_andSendsMail() {
        PasswordResetDTO.Response res = service.sendCode(EMAIL, "1.2.3.4");
        String code = storedCode();
        assertNotNull(code);
        assertTrue(code.matches("\\d{6}"));
        assertEquals(300L, redis.getExpire("password-reset:code:" + EMAIL, TimeUnit.SECONDS));
        assertEquals(60L, redis.getExpire("password-reset:cooldown:" + EMAIL, TimeUnit.SECONDS));
        assertEquals(300L, res.getExpiresInSeconds());
        ArgumentCaptor<String> sent = ArgumentCaptor.forClass(String.class);
        verify(mailService).sendVerificationCode(eq(EMAIL), sent.capture(), eq(300L));
        assertEquals(code, sent.getValue());
    }

    @Test
    void sendCode_unknownEmail_returnsSameMessage_withoutMail_butSetsCooldown() {
        PasswordResetDTO.Response known = service.sendCode(EMAIL, "1.1.1.1");
        PasswordResetDTO.Response unknown = service.sendCode("nobody@example.com", "1.1.1.1");
        assertEquals(known.getMessage(), unknown.getMessage());
        verify(mailService, times(1)).sendVerificationCode(anyString(), anyString(), anyLong());
        assertNull(values.get("password-reset:code:nobody@example.com"));
        assertTrue(values.containsKey("password-reset:cooldown:nobody@example.com"));
        expect(Reason.RESEND_COOLDOWN, () -> service.sendCode("nobody@example.com", "1.1.1.1"));
    }

    @Test
    void sendCode_withinCooldown_isRejected_andNotResentUntilCooldownEnds() {
        service.sendCode(EMAIL, "1.1.1.1");
        PasswordResetException ex = expect(Reason.RESEND_COOLDOWN, () -> service.sendCode(EMAIL, "1.1.1.1"));
        assertEquals(HttpStatus.TOO_MANY_REQUESTS, ex.getStatus());
        assertEquals(60L, ex.getRetryAfterSeconds());
        verify(mailService, times(1)).sendVerificationCode(anyString(), anyString(), anyLong());
        now += 61;
        service.sendCode(EMAIL, "1.1.1.1");
        verify(mailService, times(2)).sendVerificationCode(anyString(), anyString(), anyLong());
    }

    @Test
    void sendCode_latestCodeWins_previousAttemptsReset() {
        service.sendCode(EMAIL, "1.1.1.1");
        String first = storedCode();
        values.put("password-reset:attempts:" + EMAIL, "3");
        now += 61;
        service.sendCode(EMAIL, "1.1.1.1");
        String second = storedCode();
        assertNotNull(second);
        assertNull(values.get("password-reset:attempts:" + EMAIL));
        if (!first.equals(second)) {
            expect(Reason.CODE_MISMATCH, () -> service.verifyCode(EMAIL, first));
        }
        service.verifyCode(EMAIL, second);
        assertTrue(values.containsKey("password-reset:verified:" + EMAIL));
    }

    @Test
    void sendCode_mailFailure_leavesRedisUntouched_andPropagates503() {
        doThrow(new PasswordResetException(HttpStatus.SERVICE_UNAVAILABLE, Reason.MAIL_SEND_FAILED, "smtp down"))
                .when(mailService).sendVerificationCode(anyString(), anyString(), anyLong());
        expect(Reason.MAIL_SEND_FAILED, () -> service.sendCode(EMAIL, "1.1.1.1"));
        assertNull(storedCode(), "발송되지 않은 코드는 저장되지 않는다");
        assertFalse(values.containsKey("password-reset:cooldown:" + EMAIL), "발송 실패는 cooldown 을 걸지 않는다");
        assertFalse(values.containsKey("password-reset:sending:" + EMAIL), "발송 잠금 해제");
        assertEquals(0, scriptCalls);
    }

    @Test
    void sendCode_ipLimit_blocksAfterMax() {
        props.setIpMaxRequests(2);
        service.sendCode("nobody@example.com", "9.9.9.9");
        now += 61;
        service.sendCode("nobody@example.com", "9.9.9.9");
        now += 61;
        PasswordResetException ex = expect(Reason.TOO_MANY_REQUESTS, () -> service.sendCode("nobody@example.com", "9.9.9.9"));
        assertEquals(HttpStatus.TOO_MANY_REQUESTS, ex.getStatus());
        assertNotNull(ex.getRetryAfterSeconds());
    }

    @Test
    void redisOutage_becomes503_notStacktrace() {
        StringRedisTemplate broken = mock(StringRedisTemplate.class, inv -> { throw new DataAccessResourceFailureException("conn refused"); });
        PasswordResetService s = new PasswordResetService(broken, userRepository, refreshTokenRepository, encoder, mailService, props, mock(TransactionTemplate.class));
        PasswordResetException ex = expect(Reason.STORE_UNAVAILABLE, () -> s.sendCode(EMAIL, "1.1.1.1"));
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, ex.getStatus());
        verify(mailService, never()).sendVerificationCode(anyString(), anyString(), anyLong());
    }

    // ── 검증 ──

    @Test
    void verifyCode_wrongCode_countsAttempts_andInvalidatesAfterMax() {
        service.sendCode(EMAIL, "1.1.1.1");
        String code = storedCode();
        String wrong = code.equals("000000") ? "000001" : "000000";
        for (int i = 1; i < 5; i++) {
            PasswordResetException ex = expect(Reason.CODE_MISMATCH, () -> service.verifyCode(EMAIL, wrong));
            assertEquals(HttpStatus.BAD_REQUEST, ex.getStatus());
        }
        expect(Reason.CODE_ATTEMPTS_EXCEEDED, () -> service.verifyCode(EMAIL, wrong));
        assertNull(storedCode(), "상한 초과 시 코드 무효화");
        expect(Reason.CODE_EXPIRED, () -> service.verifyCode(EMAIL, code));
    }

    @Test
    void verifyCode_expired_isGone() {
        service.sendCode(EMAIL, "1.1.1.1");
        String code = storedCode();
        now += 301;
        PasswordResetException ex = expect(Reason.CODE_EXPIRED, () -> service.verifyCode(EMAIL, code));
        assertEquals(HttpStatus.GONE, ex.getStatus());
    }

    @Test
    void verifyCode_success_isOneTime_andCreatesVerifiedWithTtl() {
        service.sendCode(EMAIL, "1.1.1.1");
        String code = storedCode();
        PasswordResetDTO.Response res = service.verifyCode(EMAIL, code);
        assertEquals(600L, res.getResetWindowSeconds());
        assertNull(storedCode());
        assertEquals(600L, redis.getExpire("password-reset:verified:" + EMAIL, TimeUnit.SECONDS));
        expect(Reason.CODE_EXPIRED, () -> service.verifyCode(EMAIL, code));
    }

    @Test
    void verifyCode_emailCaseInsensitiveKey() {
        service.sendCode(EMAIL, "1.1.1.1");
        String code = storedCode();
        service.verifyCode(EMAIL.toUpperCase(), code);
        assertTrue(values.containsKey("password-reset:verified:" + EMAIL));
    }

    // ── 재설정 ──

    @Test
    void reset_withoutVerification_isForbidden_andDbUntouched() {
        String before = user.getPassword();
        PasswordResetException ex = expect(Reason.NOT_VERIFIED, () -> service.reset(EMAIL, "NewPass1!", "NewPass1!"));
        assertEquals(HttpStatus.FORBIDDEN, ex.getStatus());
        assertEquals(before, user.getPassword());
        verify(userRepository, never()).save(any());
    }

    @Test
    void reset_afterVerifiedTtlElapsed_isForbidden() {
        service.sendCode(EMAIL, "1.1.1.1");
        service.verifyCode(EMAIL, storedCode());
        now += 601;
        expect(Reason.NOT_VERIFIED, () -> service.reset(EMAIL, "NewPass1!", "NewPass1!"));
    }

    @Test
    void reset_policyAndConfirmAndSameAsOld() {
        service.sendCode(EMAIL, "1.1.1.1");
        service.verifyCode(EMAIL, storedCode());
        expect(Reason.PASSWORD_CONFIRM_MISMATCH, () -> service.reset(EMAIL, "NewPass1!", "Other1!!"));
        expect(Reason.PASSWORD_POLICY, () -> service.reset(EMAIL, "onlyletters", null));
        expect(Reason.PASSWORD_POLICY, () -> service.reset(EMAIL, "Short1!", null));
        expect(Reason.PASSWORD_POLICY, () -> service.reset(EMAIL, "New Pass1!", null));
        expect(Reason.PASSWORD_SAME_AS_OLD, () -> service.reset(EMAIL, "OldPass1!", "OldPass1!"));
        // 위 실패들은 verified 상태를 소모하지 않는다.
        assertTrue(values.containsKey("password-reset:verified:" + EMAIL));
    }

    @Test
    void reset_success_updatesBcrypt_revokesRefresh_clearsAllKeys_andIsOneTime() {
        service.sendCode(EMAIL, "1.1.1.1");
        service.verifyCode(EMAIL, storedCode());
        String oldHash = user.getPassword();

        PasswordResetDTO.Response res = service.reset(EMAIL, "NewPass1!", "NewPass1!");
        assertNotNull(res.getMessage());
        assertNotEquals(oldHash, user.getPassword());
        assertTrue(user.getPassword().startsWith("$2a$"));
        assertTrue(encoder.matches("NewPass1!", user.getPassword()));
        assertFalse(encoder.matches("OldPass1!", user.getPassword()));
        verify(userRepository).save(user);
        verify(refreshTokenRepository).deleteByEmail(EMAIL);
        assertTrue(values.keySet().stream().noneMatch(k -> k.startsWith("password-reset:") && k.endsWith(EMAIL)),
                "password-reset:* 키 전체 삭제");

        // 이미 사용한 인증으로 재시도 → 403
        expect(Reason.NOT_VERIFIED, () -> service.reset(EMAIL, "Another1!", "Another1!"));
    }

    @Test
    void reset_dbFailure_keepsVerifiedState() {
        service.sendCode(EMAIL, "1.1.1.1");
        service.verifyCode(EMAIL, storedCode());
        AtomicBoolean thrown = new AtomicBoolean(false);
        when(userRepository.save(any())).thenThrow(new DataAccessResourceFailureException("db down"));
        try {
            service.reset(EMAIL, "NewPass1!", "NewPass1!");
        } catch (DataAccessResourceFailureException e) {
            thrown.set(true);
        }
        assertTrue(thrown.get());
        assertTrue(values.containsKey("password-reset:verified:" + EMAIL), "DB 실패 시 인증 상태는 유지되어 재시도 가능");
    }

    // ── 발송/재전송 정합성 (mail code == authoritative Redis code) ──

    /** 메일로 실제 전달된 코드를 순서대로 기록하는 스파이. */
    private List<String> captureSentCodes() {
        List<String> sent = new ArrayList<>();
        org.mockito.Mockito.doAnswer(inv -> { sent.add(inv.getArgument(1)); return null; })
                .when(mailService).sendVerificationCode(anyString(), anyString(), anyLong());
        return sent;
    }

    @Test // TEST 1
    void initialSend_redisCodeEqualsMailedCode() {
        List<String> sent = captureSentCodes();
        service.sendCode(EMAIL, "1.1.1.1");
        assertEquals(1, sent.size());
        assertEquals(sent.get(0), storedCode());
        assertEquals(1, scriptCalls, "원자 스크립트 1회");
        assertFalse(values.containsKey("password-reset:sending:" + EMAIL), "성공 후 잠금 해제");
    }

    @Test // TEST 2 + TEST 4 + TEST 5
    void resendMailFailure_keepsExistingCode_attempts_andTtl() {
        List<String> sent = captureSentCodes();
        service.sendCode(EMAIL, "1.1.1.1");
        String a = storedCode();
        // A 로 1회 오입력 → attempts=1
        expect(Reason.CODE_MISMATCH, () -> service.verifyCode(EMAIL, a.equals("000000") ? "000001" : "000000"));
        assertEquals("1", values.get("password-reset:attempts:" + EMAIL));
        now += 100; // cooldown(60) 지남, code TTL 200 남음
        doThrow(new PasswordResetException(HttpStatus.SERVICE_UNAVAILABLE, Reason.MAIL_SEND_FAILED, "smtp down"))
                .when(mailService).sendVerificationCode(anyString(), anyString(), anyLong());
        expect(Reason.MAIL_SEND_FAILED, () -> service.sendCode(EMAIL, "1.1.1.1"));
        assertEquals(a, storedCode(), "SMTP 실패 시 기존 A 유지");
        assertEquals("1", values.get("password-reset:attempts:" + EMAIL), "attempts 가 초기화되지 않는다");
        assertEquals(200L, redis.getExpire("password-reset:code:" + EMAIL, TimeUnit.SECONDS), "기존 TTL 보존");
        assertEquals(1, sent.size(), "실패한 발송은 사용자에게 전달된 코드 목록에 없다");
        // 사용자가 가진 A 는 여전히 유효
        service.verifyCode(EMAIL, a);
        assertTrue(values.containsKey("password-reset:verified:" + EMAIL));
    }

    @Test // TEST 3 + TEST 6
    void resendSuccess_replacesCode_resetsAttempts_ttlAndCooldown() {
        List<String> sent = captureSentCodes();
        service.sendCode(EMAIL, "1.1.1.1");
        String a = storedCode();
        expect(Reason.CODE_MISMATCH, () -> service.verifyCode(EMAIL, a.equals("000000") ? "000001" : "000000"));
        now += 100;
        service.sendCode(EMAIL, "1.1.1.1");
        String b = storedCode();
        assertEquals(2, sent.size());
        assertEquals(sent.get(1), b, "Redis 최종 코드 == 마지막으로 실제 발송된 코드");
        assertNull(values.get("password-reset:attempts:" + EMAIL), "attempts reset");
        assertEquals(300L, redis.getExpire("password-reset:code:" + EMAIL, TimeUnit.SECONDS));
        assertEquals(60L, redis.getExpire("password-reset:cooldown:" + EMAIL, TimeUnit.SECONDS));
        if (!a.equals(b)) {
            expect(Reason.CODE_MISMATCH, () -> service.verifyCode(EMAIL, a));
        }
        service.verifyCode(EMAIL, b);
        assertTrue(values.containsKey("password-reset:verified:" + EMAIL));
    }

    @Test // TEST 10: 동시/중복 재전송 — 첫 발송이 진행 중이면 두 번째는 잠금으로 거부되고 최종 코드는 실제 발송 코드
    void concurrentResend_secondIsRejectedByLock_finalCodeMatchesMailed() {
        List<String> sent = new ArrayList<>();
        List<PasswordResetException> nested = new ArrayList<>();
        org.mockito.Mockito.doAnswer(inv -> {
            sent.add(inv.getArgument(1));
            if (sent.size() == 1) {
                // 첫 SMTP 전송 도중 같은 이메일로 두 번째 요청이 들어온 상황
                try { service.sendCode(EMAIL, "2.2.2.2"); } catch (PasswordResetException e) { nested.add(e); }
            }
            return null;
        }).when(mailService).sendVerificationCode(anyString(), anyString(), anyLong());

        service.sendCode(EMAIL, "1.1.1.1");
        assertEquals(1, sent.size(), "두 번째 요청은 메일을 보내지 않는다");
        assertEquals(1, nested.size());
        assertEquals(Reason.RESEND_COOLDOWN, nested.get(0).getReason());
        assertEquals(HttpStatus.TOO_MANY_REQUESTS, nested.get(0).getStatus());
        assertEquals(sent.get(0), storedCode(), "authoritative 코드 == 실제 발송 코드");
        assertFalse(values.containsKey("password-reset:sending:" + EMAIL));
    }

    @Test
    void sendingLock_isSelfExpiring() {
        values.put("password-reset:sending:" + EMAIL, "1");
        expiresAt.put("password-reset:sending:" + EMAIL, now + 12);
        PasswordResetException ex = expect(Reason.RESEND_COOLDOWN, () -> service.sendCode(EMAIL, "1.1.1.1"));
        assertEquals(12L, ex.getRetryAfterSeconds());
        verify(mailService, never()).sendVerificationCode(anyString(), anyString(), anyLong());
        now += 13;
        service.sendCode(EMAIL, "1.1.1.1");
        assertNotNull(storedCode());
    }

    @Test
    void redisFailureAfterMailSent_returns503_andKeepsPreviousCode() {
        List<String> sent = captureSentCodes();
        service.sendCode(EMAIL, "1.1.1.1");
        String a = storedCode();
        now += 100;
        // 스크립트(원자 교체) 단계에서만 Redis 장애
        StringRedisTemplate flaky = mock(StringRedisTemplate.class, inv -> {
            if (inv.getMethod().getName().equals("execute")) throw new DataAccessResourceFailureException("redis down");
            return inv.getMethod().invoke(redis, inv.getArguments());
        });
        PasswordResetService s2 = new PasswordResetService(flaky, userRepository, refreshTokenRepository, encoder, mailService, props, mock(TransactionTemplate.class));
        PasswordResetException ex = expect(Reason.STORE_UNAVAILABLE, () -> s2.sendCode(EMAIL, "1.1.1.1"));
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, ex.getStatus());
        assertEquals(2, sent.size(), "메일은 나갔다(불일치 창) — 503 으로 재요청 유도");
        assertEquals(a, storedCode(), "기존 A 는 손대지 않는다");
        assertFalse(values.containsKey("password-reset:sending:" + EMAIL), "잠금 해제");
    }

    // ── 값 경로: 요청 문자열 → DTO(String) → 서비스 비교 (leading zero 보존) ──

    @Test // TEST 1: 사용자가 입력한 "952372" 그대로 전달되면 성공
    void verifyCode_literal952372_succeeds() {
        values.put("password-reset:code:" + EMAIL, "952372");
        expiresAt.put("password-reset:code:" + EMAIL, now + 300);
        service.verifyCode(EMAIL, "952372");
        assertTrue(values.containsKey("password-reset:verified:" + EMAIL));
    }

    @Test // TEST 2: leading zero 코드 "098867" 문자열 그대로 성공(숫자 변환 없음)
    void verifyCode_leadingZero098867_succeeds() {
        values.put("password-reset:code:" + EMAIL, "098867");
        expiresAt.put("password-reset:code:" + EMAIL, now + 300);
        service.verifyCode(EMAIL, "098867");
        assertTrue(values.containsKey("password-reset:verified:" + EMAIL));
        // 숫자로 취급됐다면 통과했을 "98867" 은 실패해야 한다
        values.put("password-reset:code:" + EMAIL, "098867");
        expect(Reason.CODE_MISMATCH, () -> service.verifyCode(EMAIL, "98867"));
    }

    @Test // TEST 3: 요청 본문 JSON → DTO 바인딩은 String 이며 leading zero 와 6자리 형식이 보존된다
    void dto_jsonBinding_keepsStringAndLeadingZero() throws Exception {
        com.fasterxml.jackson.databind.ObjectMapper om = new com.fasterxml.jackson.databind.ObjectMapper();
        com.studybridge.api.dto.PasswordResetDTO.VerifyCodeRequest r =
                om.readValue("{\"email\":\"" + EMAIL + "\",\"code\":\"098867\"}", com.studybridge.api.dto.PasswordResetDTO.VerifyCodeRequest.class);
        assertEquals("098867", r.getCode());
        assertEquals(String.class, r.getCode().getClass());
        jakarta.validation.Validator validator = jakarta.validation.Validation.buildDefaultValidatorFactory().getValidator();
        assertTrue(validator.validate(r).isEmpty(), "6자리 숫자 문자열은 @Pattern 통과");
        // 공백/구분자가 섞인 값은 서버 @Pattern 에서 차단된다(프론트 onChange 가 \D 제거 + 6자리 절단으로 정규화)
        com.studybridge.api.dto.PasswordResetDTO.VerifyCodeRequest bad =
                om.readValue("{\"email\":\"" + EMAIL + "\",\"code\":\"0 9 8 8 6 7\"}", com.studybridge.api.dto.PasswordResetDTO.VerifyCodeRequest.class);
        assertFalse(validator.validate(bad).isEmpty());
        assertEquals("098867", "0 9 8 8 6 7".replaceAll("\\D", "").substring(0, 6), "프론트 정규화 규칙과 동일한 결과");
    }

    @Test // 입력 앞뒤 공백은 서버가 trim 하고, 그 외 변형(개행/전각 숫자)은 불일치
    void verifyCode_trimsOnlyOuterWhitespace() {
        values.put("password-reset:code:" + EMAIL, "952372");
        expiresAt.put("password-reset:code:" + EMAIL, now + 300);
        expect(Reason.CODE_MISMATCH, () -> service.verifyCode(EMAIL, "９５２３７２"));
        expect(Reason.CODE_MISMATCH, () -> service.verifyCode(EMAIL, "95237"));
        service.verifyCode(EMAIL, " 952372 ");
        assertTrue(values.containsKey("password-reset:verified:" + EMAIL));
    }

    // ── 메일 본문 ──

    @Test
    void mailBody_containsCodeAndRequiredSentences_noExternalResources() {
        String text = PasswordResetMailService.buildPlainText("483921", 5, "who@example.com");
        String html = PasswordResetMailService.buildHtml("483921", 5, "who@example.com");
        assertTrue(text.contains("[ 483921 ]"));
        assertTrue(text.contains("요청 계정: who@example.com"), "어느 계정용 번호인지 본문에 명시");
        assertTrue(html.contains("요청 계정: who@example.com"));
        assertTrue(text.contains("5분 동안 유효"));
        assertTrue(text.contains("본인이 요청하지 않은 경우"));
        assertTrue(html.contains("483921"));
        assertFalse(html.contains("<img"));
        assertFalse(html.contains("http://"));
        assertFalse(html.contains("https://"));
        assertEquals("[StudyBridge] 비밀번호 찾기 인증번호 안내", PasswordResetMailService.SUBJECT);
        assertEquals("r***@example.com", PasswordResetMailService.mask(EMAIL));
    }
}
