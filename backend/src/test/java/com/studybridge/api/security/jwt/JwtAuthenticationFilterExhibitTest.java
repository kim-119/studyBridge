package com.studybridge.api.security.jwt;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.spy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.studybridge.api.entity.User;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.security.exhibit.ExhibitAccountProperties;
import com.studybridge.api.security.exhibit.ExhibitSessionService;
import java.security.SecureRandom;
import java.time.Clock;
import java.util.Base64;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.test.util.ReflectionTestUtils;

/** 요청 인증 게이트: 일반 사용자 토큰은 Redis 를 거치지 않고 그대로, 체험 계정 토큰은 살아 있는 기기 슬롯이 있어야 인증된다. */
class JwtAuthenticationFilterExhibitTest {

    private static final String EXHIBIT_EMAIL = "test1@studybridge.co.kr";

    private JwtTokenProvider jwt;
    private StringRedisTemplate redis;
    private ExhibitSessionService exhibit;
    private JwtAuthenticationFilter filter;

    @BeforeEach
    void setUp() {
        UserDetailsService uds = mock(UserDetailsService.class);
        when(uds.loadUserByUsername(EXHIBIT_EMAIL)).thenReturn(new CustomUserDetails(
                User.builder().id(101L).email(EXHIBIT_EMAIL).password("x").displayName("test1").role("USER").build()));
        when(uds.loadUserByUsername("user@example.com")).thenReturn(new CustomUserDetails(
                User.builder().id(7L).email("user@example.com").password("x").displayName("일반").role("USER").build()));
        jwt = new JwtTokenProvider(uds);
        byte[] secret = new byte[48];
        new SecureRandom().nextBytes(secret);
        ReflectionTestUtils.setField(jwt, "secretKeyString", Base64.getEncoder().encodeToString(secret));
        ReflectionTestUtils.setField(jwt, "tokenValidityInMilliseconds", 60_000L);
        jwt.init();
        redis = mock(StringRedisTemplate.class);
        exhibit = spy(new ExhibitSessionService(redis, new ExhibitAccountProperties(), Clock.systemUTC()));
        filter = new JwtAuthenticationFilter(jwt, exhibit);
        SecurityContextHolder.clearContext();
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
    }

    private MockHttpServletRequest run(String token) throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/api/users/profile");
        req.addHeader("Authorization", "Bearer " + token);
        filter.doFilter(req, new MockHttpServletResponse(), new MockFilterChain());
        return req;
    }

    @Test
    void normalUserToken_authenticatedWithoutRedis() throws Exception {
        MockHttpServletRequest req = run(jwt.createToken(7L, "user@example.com"));

        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        assertNotNull(auth);
        assertEquals("user@example.com", auth.getName());
        assertNull(req.getAttribute(ExhibitSessionService.SESSION_ID_ATTRIBUTE));
        verifyNoInteractions(redis);
    }

    @Test
    void exhibitToken_withLiveSlot_authenticated_andSessionIdExposed() throws Exception {
        doReturn(true).when(exhibit).allowsAccess(EXHIBIT_EMAIL, 101L, "sid-a");

        MockHttpServletRequest req = run(jwt.createToken(101L, EXHIBIT_EMAIL, "sid-a"));

        assertNotNull(SecurityContextHolder.getContext().getAuthentication());
        assertEquals("sid-a", req.getAttribute(ExhibitSessionService.SESSION_ID_ATTRIBUTE));
    }

    @Test
    void exhibitToken_releasedSlot_notAuthenticated() throws Exception {
        doReturn(false).when(exhibit).allowsAccess(EXHIBIT_EMAIL, 101L, "sid-gone");

        MockHttpServletRequest req = run(jwt.createToken(101L, EXHIBIT_EMAIL, "sid-gone"));

        assertNull(SecurityContextHolder.getContext().getAuthentication(), "로그아웃·유휴 만료된 기기 → 401");
        assertNull(req.getAttribute(ExhibitSessionService.SESSION_ID_ATTRIBUTE));
    }

    @Test
    void exhibitToken_withoutSid_rejectedWithoutRedis() throws Exception {
        run(jwt.createToken(101L, EXHIBIT_EMAIL));

        assertNull(SecurityContextHolder.getContext().getAuthentication(), "체험 계정은 기기 슬롯 없는 토큰으로 인증할 수 없다");
        verifyNoInteractions(redis);
    }

    @Test
    void invalidToken_neverReachesSessionCheck() throws Exception {
        run("not-a-jwt");
        assertNull(SecurityContextHolder.getContext().getAuthentication());
        verify(exhibit, never()).allowsAccess(any(), any(), any());
    }
}
