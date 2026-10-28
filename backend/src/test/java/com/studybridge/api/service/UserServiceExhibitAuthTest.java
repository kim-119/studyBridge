package com.studybridge.api.service;

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
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.spy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.studybridge.api.dto.UserDTO;
import com.studybridge.api.entity.RefreshToken;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.RefreshTokenRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.security.exhibit.ExhibitAccountProperties;
import com.studybridge.api.security.exhibit.ExhibitSessionException;
import com.studybridge.api.security.exhibit.ExhibitSessionService;
import com.studybridge.api.security.jwt.JwtTokenProvider;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.LocalDateTime;
import java.util.Base64;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

/**
 * 체험 계정(test1~test4) 인증 경로와 일반 사용자 회귀.
 *  · 체험 계정: 별칭 로그인, sid 토큰, Redis 슬롯(admit/rotate/release), DB refresh_tokens 미사용, 비밀번호 변경 차단.
 *  · 일반 사용자: 기존 DB refresh_tokens 경로 그대로(sid 없음, Redis 미사용).
 */
class UserServiceExhibitAuthTest {

    private static final String EXHIBIT_EMAIL = "test1@studybridge.co.kr";

    private UserRepository userRepository;
    private RefreshTokenRepository refreshTokenRepository;
    private PasswordEncoder encoder;
    private JwtTokenProvider jwt;
    private StringRedisTemplate redis;
    private ExhibitSessionService exhibit;
    private UserService service;

    private User exhibitUser;
    private User normalUser;

    @BeforeEach
    void setUp() {
        userRepository = mock(UserRepository.class);
        refreshTokenRepository = mock(RefreshTokenRepository.class);
        encoder = new BCryptPasswordEncoder(4);
        jwt = new JwtTokenProvider(mock(UserDetailsService.class));
        byte[] secret = new byte[48];
        new SecureRandom().nextBytes(secret);
        ReflectionTestUtils.setField(jwt, "secretKeyString", Base64.getEncoder().encodeToString(secret));
        ReflectionTestUtils.setField(jwt, "tokenValidityInMilliseconds", 1_800_000L);
        ReflectionTestUtils.invokeMethod(jwt, "init");
        redis = mock(StringRedisTemplate.class);
        exhibit = spy(new ExhibitSessionService(redis, new ExhibitAccountProperties(), Clock.systemUTC()));
        doNothing().when(exhibit).admit(anyLong(), anyString(), anyLong(), anyString());
        doNothing().when(exhibit).rotate(anyLong(), anyString(), anyString(), anyString());
        doNothing().when(exhibit).release(anyLong(), anyString());
        service = new UserService(userRepository, encoder, jwt, refreshTokenRepository, mock(S3Service.class), exhibit);

        exhibitUser = User.builder().id(101L).email(EXHIBIT_EMAIL).password(encoder.encode("1234"))
                .displayName("test1").role("USER").status("ACTIVE").isSubscribed(false).build();
        normalUser = User.builder().id(47L).email("test1@test.com").password(encoder.encode("password1!"))
                .displayName("일반").role("USER").status("ACTIVE").isSubscribed(false).build();
        when(userRepository.findByEmail(EXHIBIT_EMAIL)).thenReturn(Optional.of(exhibitUser));
        when(userRepository.findByEmail("test1@test.com")).thenReturn(Optional.of(normalUser));
        when(userRepository.findByEmail("nobody@test.com")).thenReturn(Optional.empty());
    }

    private static UserDTO.LoginRequest login(String id, String pw) {
        UserDTO.LoginRequest r = new UserDTO.LoginRequest();
        r.setEmail(id);
        r.setPassword(pw);
        return r;
    }

    @Test
    void exhibitAliasLogin_opensDeviceSlot_withSidTokens_andNoDbRefreshRow() {
        UserDTO.Response res = service.login(login("test1", "1234"));

        assertEquals(101L, res.getId());
        assertEquals(EXHIBIT_EMAIL, res.getEmail());
        assertTrue(res.getExhibitAccount());
        JwtTokenProvider.TokenClaims access = jwt.getTokenClaims(res.getAccessToken());
        JwtTokenProvider.TokenClaims refresh = jwt.getTokenClaims(res.getRefreshToken());
        assertNotNull(access.sessionId());
        assertEquals(access.sessionId(), refresh.sessionId(), "access/refresh 가 같은 기기 슬롯");
        assertEquals(101L, access.userId());
        verify(exhibit).admit(eq(101L), eq(access.sessionId()), anyLong(), eq(res.getRefreshToken()));
        verifyNoInteractions(refreshTokenRepository);
    }

    @Test
    void exhibitLogin_acceptsEmailFormAndCaseVariants() {
        assertEquals(101L, service.login(login("TEST1@studybridge.co.kr ", "1234")).getId());
        assertEquals(101L, service.login(login(" Test1", "1234")).getId());
    }

    @Test
    void twoExhibitLogins_getDifferentSessions() {
        String a = jwt.getTokenClaims(service.login(login("test1", "1234")).getAccessToken()).sessionId();
        String b = jwt.getTokenClaims(service.login(login("test1", "1234")).getAccessToken()).sessionId();
        assertNotEquals(a, b, "기기마다 독립 세션 id");
    }

    @Test
    void exhibitWrongPassword_doesNotConsumeSlot() {
        assertThrows(IllegalArgumentException.class, () -> service.login(login("test1", "0000")));
        verify(exhibit, never()).admit(anyLong(), anyString(), anyLong(), anyString());
    }

    @Test
    void exhibitThirdLogin_rejectedWith409() {
        doThrow(new ExhibitSessionException(HttpStatus.CONFLICT, "EXHIBIT_SESSION_LIMIT", "limit"))
                .when(exhibit).admit(anyLong(), anyString(), anyLong(), anyString());
        ExhibitSessionException e = assertThrows(ExhibitSessionException.class, () -> service.login(login("test1", "1234")));
        assertEquals(HttpStatus.CONFLICT, e.getStatus());
        verifyNoInteractions(refreshTokenRepository);
    }

    @Test
    void bannedExhibitAccount_cannotLogin() {
        exhibitUser.setStatus("BANNED");
        exhibitUser.setSuspensionReason("전시 종료");
        assertThrows(IllegalArgumentException.class, () -> service.login(login("test1", "1234")));
        verify(exhibit, never()).admit(anyLong(), anyString(), anyLong(), anyString());
    }

    @Test
    void normalUserLogin_unchanged_dbRefreshRow_noSid_noRedis() {
        when(refreshTokenRepository.findByEmail("test1@test.com")).thenReturn(Optional.empty());

        UserDTO.Response res = service.login(login("test1@test.com", "password1!"));

        assertEquals(47L, res.getId());
        assertFalse(res.getExhibitAccount());
        assertNull(jwt.getTokenClaims(res.getAccessToken()).sessionId(), "일반 사용자 토큰 claim 은 기존과 동일(sid 없음)");
        assertNull(jwt.getTokenClaims(res.getRefreshToken()).sessionId());
        verify(refreshTokenRepository).save(any(RefreshToken.class));
        verify(exhibit, never()).admit(anyLong(), anyString(), anyLong(), anyString());
        verifyNoInteractions(redis);
    }

    @Test
    void normalUserBareIdIsNotAliased() {
        when(userRepository.findByEmail("test5")).thenReturn(Optional.empty());
        assertThrows(IllegalArgumentException.class, () -> service.login(login("test5", "1234")),
                "목록에 없는 별칭은 일반 조회(미가입)로 처리");
    }

    @Test
    void exhibitRefresh_rotatesInSameSlot_keepsAbsoluteExpiry() {
        UserDTO.Response first = service.login(login("test1", "1234"));
        JwtTokenProvider.TokenClaims before = jwt.getTokenClaims(first.getRefreshToken());

        UserDTO.Response next = service.refreshToken(first.getRefreshToken());

        JwtTokenProvider.TokenClaims after = jwt.getTokenClaims(next.getRefreshToken());
        assertEquals(before.sessionId(), after.sessionId());
        assertEquals(before.expiresAt(), after.expiresAt(), "리프레시는 절대 만료를 연장하지 않는다");
        assertNotEquals(first.getRefreshToken(), next.getRefreshToken());
        assertEquals(before.sessionId(), jwt.getTokenClaims(next.getAccessToken()).sessionId());
        verify(exhibit).rotate(101L, before.sessionId(), first.getRefreshToken(), next.getRefreshToken());
        verifyNoInteractions(refreshTokenRepository);
    }

    @Test
    void exhibitRefresh_rejectedAfterBan_andSlotReleased() {
        UserDTO.Response first = service.login(login("test1", "1234"));
        String sid = jwt.getTokenClaims(first.getRefreshToken()).sessionId();
        exhibitUser.setStatus("BANNED");

        assertThrows(IllegalArgumentException.class, () -> service.refreshToken(first.getRefreshToken()));
        verify(exhibit).release(101L, sid);
        verify(exhibit, never()).rotate(anyLong(), anyString(), anyString(), anyString());
    }

    @Test
    void normalUserRefresh_usesDbPath() {
        String refresh = jwt.createRefreshToken(47L, "test1@test.com");
        RefreshToken row = RefreshToken.builder().id(1L).email("test1@test.com").token(refresh)
                .expiryDate(LocalDateTime.now().plusDays(7)).build();
        when(refreshTokenRepository.findByToken(refresh)).thenReturn(Optional.of(row));

        UserDTO.Response res = service.refreshToken(refresh);

        assertEquals(47L, res.getId());
        assertNull(jwt.getTokenClaims(res.getAccessToken()).sessionId());
        verify(refreshTokenRepository).save(row);
        verify(exhibit, never()).rotate(anyLong(), anyString(), anyString(), anyString());
    }

    @Test
    void logoutWithSession_releasesOnlyThatSlot_normalLogoutDeletesDbRow() {
        service.logout(EXHIBIT_EMAIL, "sid-a");
        verify(exhibit).release(101L, "sid-a");
        verify(refreshTokenRepository, never()).deleteByEmail(anyString());

        service.logout("test1@test.com", null);
        verify(refreshTokenRepository).deleteByEmail("test1@test.com");
    }

    @Test
    void exhibitPasswordChange_blocked() {
        UserDTO.ChangePasswordRequest r = new UserDTO.ChangePasswordRequest();
        r.setEmail(EXHIBIT_EMAIL);
        r.setCurrentPassword("1234");
        r.setNewPassword("changed123!");
        r.setNewPasswordConfirm("changed123!");
        String before = exhibitUser.getPassword();

        IllegalArgumentException e = assertThrows(IllegalArgumentException.class, () -> service.changePassword(r));
        assertTrue(e.getMessage().contains("체험 계정"));
        assertEquals(before, exhibitUser.getPassword());
    }

    @Test
    void createUser_hashesPassword_withDefaultUserRole() {
        when(userRepository.save(any(User.class))).thenAnswer(inv -> inv.getArgument(0));
        User created = service.createUser("test2@studybridge.co.kr", "1234", "test2", null);
        assertTrue(encoder.matches("1234", created.getPassword()));
        assertNotEquals("1234", created.getPassword());
        assertEquals("USER", created.getRole());
        assertEquals("ACTIVE", created.getStatus());
    }
}
