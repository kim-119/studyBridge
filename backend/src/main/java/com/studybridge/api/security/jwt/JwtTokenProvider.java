package com.studybridge.api.security.jwt;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ClaimsBuilder;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.UUID;

@Component
public class JwtTokenProvider {

    public static final String SESSION_ID_CLAIM = "sid";

    @Value("${jwt.secret}")
    private String secretKeyString;

    @Value("${jwt.expiration-ms}")
    private long tokenValidityInMilliseconds;

    private SecretKey key;
    private final UserDetailsService userDetailsService;

    public JwtTokenProvider(UserDetailsService userDetailsService) {
        this.userDetailsService = userDetailsService;
    }

    // 서명키는 환경변수 JWT_SECRET 으로만 주입한다(application.yml 기본값 없음).
    // 없거나 HS256 최소 길이(32바이트)보다 짧으면 기동을 실패시킨다 — 약한/공개 키로 뜨는 것보다 안전하다.
    @PostConstruct
    protected void init() {
        if (secretKeyString == null || secretKeyString.isBlank()) {
            throw new IllegalStateException("JWT_SECRET 이 설정되지 않았습니다. 운영 비밀 파일로 주입해야 합니다.");
        }
        byte[] secretBytes = secretKeyString.getBytes(StandardCharsets.UTF_8);
        if (secretBytes.length < 32) {
            throw new IllegalStateException("JWT_SECRET 은 HS256 요구사항상 32바이트 이상이어야 합니다.");
        }
        this.key = Keys.hmacShaKeyFor(secretBytes);
    }

    // JWT 토큰 생성
    public String createToken(Long userId, String email) {
        return createToken(userId, email, null);
    }

    // sessionId(sid) 는 체험 계정 토큰에만 넣는다(일반 사용자 토큰은 기존과 동일한 claim).
    public String createToken(Long userId, String email, String sessionId) {
        ClaimsBuilder builder = Jwts.claims()
                .subject(email)
                .add("userId", userId);
        if (sessionId != null) {
            builder.add(SESSION_ID_CLAIM, sessionId);
        }
        Claims claims = builder.build();

        Date now = new Date();
        Date validity = new Date(now.getTime() + tokenValidityInMilliseconds);

        return Jwts.builder()
                .claims(claims)
                .issuedAt(now)
                .expiration(validity)
                .signWith(key, Jwts.SIG.HS256)
                .compact();
    }

    // JWT 리프레시 토큰 생성
    public String createRefreshToken(Long userId, String email) {
        Claims claims = Jwts.claims()
                .subject(email)
                .add("userId", userId)
                .build();

        Date now = new Date();
        Date validity = new Date(now.getTime() + 604800000L); // 7일 (7 * 24 * 60 * 60 * 1000)

        return Jwts.builder()
                .claims(claims)
                .issuedAt(now)
                .expiration(validity)
                .signWith(key, Jwts.SIG.HS256)
                .compact();
    }

    // 체험 계정 리프레시 토큰: sid 를 담고, 만료는 세션 절대 만료 시각(리프레시로 연장되지 않음).
    public String createRefreshToken(Long userId, String email, String sessionId, Date expiresAt) {
        Claims claims = Jwts.claims()
                .subject(email)
                .add("userId", userId)
                .add(SESSION_ID_CLAIM, sessionId)
                .build();

        return Jwts.builder()
                .claims(claims)
                .id(UUID.randomUUID().toString())
                .issuedAt(new Date())
                .expiration(expiresAt)
                .signWith(key, Jwts.SIG.HS256)
                .compact();
    }

    /** 서명·만료를 검증한 토큰의 식별 claim. sessionId 는 체험 계정 토큰에만 있다(그 외 null). */
    public record TokenClaims(String email, Long userId, String sessionId, Date expiresAt) {}

    public TokenClaims getTokenClaims(String token) {
        Claims claims = getClaims(token);
        Object uid = claims.get("userId");
        return new TokenClaims(claims.getSubject(),
                uid instanceof Number n ? n.longValue() : null,
                claims.get(SESSION_ID_CLAIM, String.class),
                claims.getExpiration());
    }

    // 토큰으로부터 인증 정보 추출
    public Authentication getAuthentication(String token) {
        String email = getClaims(token).getSubject();
        UserDetails userDetails = userDetailsService.loadUserByUsername(email);
        return new UsernamePasswordAuthenticationToken(userDetails, "", userDetails.getAuthorities());
    }

    // 토큰 유효성 검증
    public boolean validateToken(String token) {
        try {
            return getClaims(token).getExpiration().after(new Date());
        } catch (Exception e) {
            return false;
        }
    }

    private Claims getClaims(String token) {
        return Jwts.parser()
                .verifyWith(key)
                .build()
                .parseSignedClaims(token)
                .getPayload();
    }
}
