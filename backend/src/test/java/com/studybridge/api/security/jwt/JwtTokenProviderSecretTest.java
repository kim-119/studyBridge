package com.studybridge.api.security.jwt;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;

import java.security.SecureRandom;
import java.util.Base64;
import org.junit.jupiter.api.Test;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.test.util.ReflectionTestUtils;

// 서명키 주입 가드: 기본값 폴백이 없어졌으므로 키 누락·약한 키는 기동 실패, 다른 키로 서명된 토큰은 거부.
class JwtTokenProviderSecretTest {

    private static String randomSecret() {
        byte[] bytes = new byte[48];
        new SecureRandom().nextBytes(bytes);
        return Base64.getEncoder().encodeToString(bytes);
    }

    private static JwtTokenProvider provider(String secret) {
        JwtTokenProvider provider = new JwtTokenProvider(mock(UserDetailsService.class));
        ReflectionTestUtils.setField(provider, "secretKeyString", secret);
        ReflectionTestUtils.setField(provider, "tokenValidityInMilliseconds", 60_000L);
        return provider;
    }

    @Test
    void missingSecretFailsStartup() {
        assertThrows(IllegalStateException.class, () -> provider(null).init());
        assertThrows(IllegalStateException.class, () -> provider("   ").init());
    }

    @Test
    void shortSecretFailsStartup() {
        assertThrows(IllegalStateException.class, () -> provider("too-short-secret").init());
    }

    @Test
    void tokenSignedWithAnotherKeyIsRejected() {
        JwtTokenProvider oldKeyProvider = provider(randomSecret());
        JwtTokenProvider newKeyProvider = provider(randomSecret());
        assertDoesNotThrow(oldKeyProvider::init);
        assertDoesNotThrow(newKeyProvider::init);

        String oldAccess = oldKeyProvider.createToken(1L, "user@studybridge.test");
        String oldRefresh = oldKeyProvider.createRefreshToken(1L, "user@studybridge.test");

        assertTrue(oldKeyProvider.validateToken(oldAccess));
        assertFalse(newKeyProvider.validateToken(oldAccess));
        assertFalse(newKeyProvider.validateToken(oldRefresh));
        assertTrue(newKeyProvider.validateToken(newKeyProvider.createToken(1L, "user@studybridge.test")));
    }
}
